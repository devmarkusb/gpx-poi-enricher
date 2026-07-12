from __future__ import annotations

from unittest.mock import patch

import requests
import responses as resp_lib

from gpx_poi_enricher.maps_to_gpx_cli import (
    NOMINATIM_SEARCH_URL,
    _build_geocode_queries,
    _extract_google_data_coords,
    _geocode,
    _pick_best_geocode_result,
    parse_waypoints_from_url,
)


def _session() -> requests.Session:
    return requests.Session()


def test_build_geocode_queries_normalizes_localized_country_names():
    queries = _build_geocode_queries("Tarragona, Provinz Tarragona, Spanien")

    assert "Tarragona, Tarragona, Spain" in queries
    assert "Tarragona, Spain" in queries


@resp_lib.activate
def test_geocode_retries_with_normalized_country_query():
    resp_lib.add(resp_lib.GET, NOMINATIM_SEARCH_URL, json=[], status=200)
    resp_lib.add(resp_lib.GET, NOMINATIM_SEARCH_URL, json=[], status=200)
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_SEARCH_URL,
        json=[{"lat": "41.1189", "lon": "1.2445"}],
        status=200,
    )

    with patch("gpx_poi_enricher.maps_to_gpx_cli.time.sleep"):
        lat, lon = _geocode("Tarragona, Provinz Tarragona, Spanien", _session())

    assert (lat, lon) == (41.1189, 1.2445)
    queries = [call.request.params["q"] for call in resp_lib.calls]
    assert queries[:3] == [
        "Tarragona, Provinz Tarragona, Spanien",
        "Tarragona, Tarragona, Spain",
        "Tarragona, Tarragona",
    ]


def test_build_geocode_queries_keeps_full_street_address_without_country_suffix():
    queries = _build_geocode_queries("Neuer Weg 2C, 01239 Dresden-Prohlis")

    assert queries == ["Neuer Weg 2C, 01239 Dresden-Prohlis"]


def test_parse_waypoints_attaches_google_data_coordinates():
    url = (
        "https://www.google.com/maps/dir/Heilbronn/Neuer+Weg+2C,+01239+Dresden-Prohlis/"
        "@50.0960524,10.1708852,8z/data=!4m14!4m13!"
        "!1m5!1m1!1s0x47982897b04d51d1:0x41ffd3c8d099070!2m2!1d9.210879!2d49.1426929!"
        "!1m5!1m1!1s0x4709c6f5d49261fd:0x5531f089e13b5b03!2m2!1d13.7770421!2d50.9920183!3e0"
    )

    waypoints = parse_waypoints_from_url(url)

    assert waypoints == [
        {"name": "Heilbronn", "coord": (49.1426929, 9.210879)},
        {"name": "Neuer Weg 2C, 01239 Dresden-Prohlis", "coord": (50.9920183, 13.7770421)},
    ]


def test_extract_google_data_coords_ignores_invalid_values():
    url = "https://www.google.com/maps/dir/A/B/data=!2m2!1d200!2d100"

    assert _extract_google_data_coords(url) == []


def test_pick_best_geocode_result_prefers_waypoint_nearby():
    results = [
        {"lat": "54.6526955", "lon": "9.7726300"},
        {"lat": "50.9920310", "lon": "13.7770268"},
    ]
    near = (49.1426929, 9.210879)  # Heilbronn

    best = _pick_best_geocode_result(results, near=near)

    assert best == results[1]


@resp_lib.activate
def test_geocode_prefers_result_near_previous_waypoint():
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_SEARCH_URL,
        json=[
            {"lat": "54.6526955", "lon": "9.7726300"},
            {"lat": "50.9920310", "lon": "13.7770268"},
        ],
        status=200,
    )

    with patch("gpx_poi_enricher.maps_to_gpx_cli.time.sleep"):
        lat, lon = _geocode(
            "Neuer Weg 2C, 01239 Dresden-Prohlis",
            _session(),
            near=(49.1426929, 9.210879),
        )

    assert (lat, lon) == (50.992031, 13.7770268)
    assert resp_lib.calls[0].request.params["limit"] == "5"
