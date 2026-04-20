"""Tests for gpx_poi_enricher.geocoding module.

Covers: detect_country_segments (grouping by country, HTTP error handling,
min_spacing_km enforcement). All Nominatim HTTP calls are mocked with the
`responses` library – no real network access.
"""

from __future__ import annotations

from collections import OrderedDict
from unittest.mock import patch

import pytest
import requests
import responses as resp_lib

from gpx_poi_enricher.geocoding import (
    NOMINATIM_URL,
    detect_country_segments,
    reverse_country_code,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nominatim_json(country_code: str) -> dict:
    """Build a minimal Nominatim jsonv2 response for a given country code."""
    return {
        "place_id": 12345,
        "address": {
            "country_code": country_code,
            "country": "Test Country",
        },
    }


def _session() -> requests.Session:
    return requests.Session()


# ---------------------------------------------------------------------------
# reverse_country_code
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_reverse_country_code_returns_uppercased_code():
    """reverse_country_code must return the country code uppercased."""
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_URL,
        json=_nominatim_json("de"),
        status=200,
    )
    result = reverse_country_code(48.1351, 11.5820, _session())
    assert result == "DE"


@resp_lib.activate
def test_reverse_country_code_returns_correct_country():
    """reverse_country_code must return the country for the given coordinate."""
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_URL,
        json=_nominatim_json("es"),
        status=200,
    )
    result = reverse_country_code(41.3851, 2.1734, _session())
    assert result == "ES"


@resp_lib.activate
def test_reverse_country_code_missing_address_returns_empty_string():
    """reverse_country_code must return an empty string when address is absent."""
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_URL,
        json={"place_id": 0},
        status=200,
    )
    result = reverse_country_code(0.0, 0.0, _session())
    assert result == ""


@resp_lib.activate
def test_reverse_country_code_http_error_raises():
    """reverse_country_code must propagate HTTP errors (raise_for_status)."""
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_URL,
        status=503,
    )
    session = _session()
    with pytest.raises(requests.HTTPError):
        reverse_country_code(48.0, 11.0, session)


# ---------------------------------------------------------------------------
# detect_country_segments – basic grouping
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_detect_country_segments_single_country():
    """All points in a single country must be grouped under that country code."""
    # Provide one Nominatim response for the first (and only) lookup.
    resp_lib.add(
        resp_lib.GET,
        NOMINATIM_URL,
        json=_nominatim_json("de"),
        status=200,
    )
    pts = [(48.1351, 11.5820), (47.8, 11.0), (47.5, 10.5)]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)
    assert "DE" in result
    assert len(result["DE"]) == len(pts)


@resp_lib.activate
def test_detect_country_segments_two_countries():
    """Points in two different countries must be grouped into two separate entries."""
    # First point → Germany, second point triggers new lookup → Spain.
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("es"), status=200)

    # Use a very small min_spacing_km so every point triggers a lookup.
    pts = [
        (48.1351, 11.5820),  # Germany
        (41.3851, 2.1734),  # Spain (>40 km away)
    ]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)

    assert "DE" in result
    assert "ES" in result


@resp_lib.activate
def test_detect_country_segments_returns_ordered_dict():
    """detect_country_segments must return an OrderedDict."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    pts = [(48.1351, 11.5820)]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)
    assert isinstance(result, OrderedDict)


@resp_lib.activate
def test_detect_country_segments_preserves_insertion_order():
    """The order of country codes must reflect the order they were first encountered."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("fr"), status=200)
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("es"), status=200)

    pts = [
        (48.1351, 11.5820),  # DE
        (45.7640, 4.8357),  # FR (far enough away from DE)
        (41.3851, 2.1734),  # ES (far enough away from FR)
    ]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)

    keys = list(result.keys())
    assert keys.index("DE") < keys.index("FR") < keys.index("ES")


# ---------------------------------------------------------------------------
# detect_country_segments – HTTP error handling
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_detect_country_segments_skips_point_on_http_error():
    """detect_country_segments must skip a point (not raise) when Nominatim returns an error."""
    # First request fails; second succeeds.
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, status=500)
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("es"), status=200)

    pts = [
        (48.1351, 11.5820),  # HTTP error → skip
        (41.3851, 2.1734),  # OK → ES
    ]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        # Should not raise; Spain point should still be captured.
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)

    # ES should appear (the erroring point may or may not contribute).
    assert "ES" in result


@resp_lib.activate
def test_detect_country_segments_all_errors_returns_empty():
    """If every Nominatim call fails and no country is ever resolved,
    the result should be an empty OrderedDict (no points can be grouped)."""
    # All calls return 500.
    for _ in range(3):
        resp_lib.add(resp_lib.GET, NOMINATIM_URL, status=500)

    pts = [(48.0, 11.0), (47.0, 10.0), (46.0, 9.0)]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(pts, _session(), min_spacing_km=0.0, sleep_between_calls=0)

    # No successful geocoding → empty result (no country ever set as last_cc).
    assert len(result) == 0


# ---------------------------------------------------------------------------
# detect_country_segments – min_spacing_km
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_detect_country_segments_respects_min_spacing_km():
    """Nominatim should only be called again when the distance since the last
    geocoded point exceeds min_spacing_km. Close-together points must reuse
    the last known country code without making an additional HTTP call."""
    # Only one Nominatim call should occur for 3 very close points.
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)

    # All three points are < 1 km apart (Munich city scale).
    pts = [
        (48.1351, 11.5820),
        (48.1360, 11.5830),  # ~0.13 km from previous
        (48.1370, 11.5840),  # ~0.13 km from previous
    ]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(
            pts, _session(), min_spacing_km=50.0, sleep_between_calls=0
        )

    # Only 1 HTTP call was registered; if more calls were attempted, responses
    # would raise ConnectionError (passthrough disabled by @resp_lib.activate).
    assert "DE" in result
    assert len(result["DE"]) == 3  # all three points belong to DE


@resp_lib.activate
def test_detect_country_segments_large_spacing_triggers_new_lookup():
    """When points are far apart (exceeding min_spacing_km), a new lookup is triggered."""
    # Two separate calls expected for two widely-separated points.
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("es"), status=200)

    pts = [
        (48.1351, 11.5820),  # Munich – DE
        (41.3851, 2.1734),  # Barcelona – ES (~1600 km away)
    ]
    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        result = detect_country_segments(
            pts, _session(), min_spacing_km=40.0, sleep_between_calls=0
        )

    assert "DE" in result
    assert "ES" in result


# ---------------------------------------------------------------------------
# detect_country_segments – empty input
# ---------------------------------------------------------------------------


def test_detect_country_segments_empty_input():
    """detect_country_segments with an empty point list must return an empty OrderedDict."""
    result = detect_country_segments([], _session(), min_spacing_km=40.0, sleep_between_calls=0)
    assert result == OrderedDict()


# ---------------------------------------------------------------------------
# detect_country_segments – progress dict
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_detect_country_segments_updates_progress():
    """detect_country_segments must update the progress dict during iteration."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)

    pts = [(48.1351, 11.5820), (48.14, 11.59)]
    progress: dict = {}

    with patch("gpx_poi_enricher.geocoding.time.sleep"):
        detect_country_segments(
            pts, _session(), min_spacing_km=0.0, sleep_between_calls=0, progress=progress
        )

    assert "nominatim_samples_total" in progress
    assert progress["nominatim_samples_total"] == len(pts)
