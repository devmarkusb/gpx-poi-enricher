from __future__ import annotations

from unittest.mock import patch

import requests
import responses as resp_lib

from gpx_poi_enricher.maps_to_gpx_cli import NOMINATIM_SEARCH_URL, _build_geocode_queries, _geocode


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
