"""Point URL contracts, including redirect validation, without live services."""

from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses

from gpx_poi_enricher.geocoding import NOMINATIM_SEARCH_URL
from gpx_poi_enricher.location import resolve_point_input


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0,0", (0, 0)),
        (" geo:-1.25, 2.5 ", (-1.25, 2.5)),
        ("https://www.google.com/maps?q=1.25%2C2.5", (1.25, 2.5)),
        ("https://maps.google.de/?ll=-1.25,2.5", (-1.25, 2.5)),
        ("https://www.google.com/maps/place/Test/@9,9,4z/data=!3d1.25!4d2.5", (1.25, 2.5)),
    ],
)
def test_resolve_supported_points(value, expected):
    assert resolve_point_input(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "91,0",
        "0,181",
        "https://example.invalid/?q=0,0",
        "http://maps.app.goo.gl/test",
        "https://user:password@maps.google.com/?q=0,0",
        "https://maps.google.com:8443/?q=0,0",
    ],
)
def test_reject_invalid_points_and_urls(value):
    with pytest.raises(ValueError):
        resolve_point_input(value)


@responses.activate
def test_short_link_closes_owned_session(monkeypatch):
    short = "https://maps.app.goo.gl/test"
    responses.get(short, status=302, headers={"Location": "https://www.google.com/maps?q=1,2"})
    session = requests.Session()
    session.close = Mock(wraps=session.close)
    monkeypatch.setattr("gpx_poi_enricher.location.requests.Session", lambda: session)
    assert resolve_point_input(short) == (1, 2)
    session.close.assert_called_once()


@responses.activate
def test_short_link_rejects_foreign_redirect_before_fetch():
    short = "https://maps.app.goo.gl/test"
    responses.get(short, status=302, headers={"Location": "https://example.invalid/?q=1,2"})
    with pytest.raises(ValueError):
        resolve_point_input(short)
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        "Aquarium Berlin",
        "https://www.google.com/maps/place/Aquarium+Berlin/",
        "https://www.google.com/maps/place/Aquarium%20Berlin/",
        "https://www.google.com/maps/search/?api=1&query=Aquarium+Berlin",
        "https://maps.google.de/?q=Aquarium%20Berlin",
        "www.google.com/maps/place/Aquarium+Berlin/",
    ],
)
@responses.activate
def test_resolve_named_poi_or_maps_link(value, monkeypatch):
    monkeypatch.setattr("gpx_poi_enricher.geocoding.time.sleep", lambda *_: None)
    responses.get(NOMINATIM_SEARCH_URL, json=[{"lat": "1.25", "lon": "2.5"}])

    assert resolve_point_input(value) == (1.25, 2.5)
    query = parse_qs(urlsplit(responses.calls[0].request.url).query)
    assert query["q"] == ["Aquarium Berlin"]
    assert responses.calls[0].request.headers["User-Agent"].startswith("gpx-poi-enricher/")


@responses.activate
def test_short_named_place_link_reuses_and_closes_owned_session(monkeypatch):
    monkeypatch.setattr("gpx_poi_enricher.geocoding.time.sleep", lambda *_: None)
    short = "https://maps.app.goo.gl/test"
    responses.get(
        short,
        status=302,
        headers={"Location": "https://www.google.com/maps/place/Aquarium+Berlin/"},
    )
    responses.get(NOMINATIM_SEARCH_URL, json=[{"lat": "1.25", "lon": "2.5"}])
    session = requests.Session()
    session.close = Mock(wraps=session.close)
    monkeypatch.setattr("gpx_poi_enricher.location.requests.Session", lambda: session)

    assert resolve_point_input(short) == (1.25, 2.5)
    session.close.assert_called_once()
    assert len(responses.calls) == 2


@pytest.mark.parametrize(
    "results", [[], [{}], [{"lat": "nan", "lon": "2"}], [{"lat": "91", "lon": "2"}]]
)
@responses.activate
def test_named_place_without_valid_match_reports_place_error(results, monkeypatch):
    monkeypatch.setattr("gpx_poi_enricher.geocoding.time.sleep", lambda *_: None)
    responses.get(NOMINATIM_SEARCH_URL, json=results)

    with pytest.raises(ValueError, match="Could not find that place"):
        resolve_point_input("Unknown POI")


@responses.activate
def test_empty_point_does_not_attempt_a_lookup():
    with pytest.raises(ValueError, match="Enter a place name"):
        resolve_point_input("   ")
    assert not responses.calls
