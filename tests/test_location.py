"""Point URL contracts, including redirect validation, without live services."""

from unittest.mock import Mock

import pytest
import requests
import responses

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
