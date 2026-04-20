"""Integration-style tests for gpx_poi_enricher.enricher module.

Tests enrich_gpx_file and enrich_track using the sample GPX fixture.
All HTTP calls (Nominatim and Overpass) are mocked with the `responses`
library – no real network access is made.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest
import responses as resp_lib

from gpx_poi_enricher.enricher import enrich_gpx_file, enrich_track
from gpx_poi_enricher.geocoding import NOMINATIM_URL
from gpx_poi_enricher.gpx_utils import GPX_NS
from gpx_poi_enricher.overpass import OVERPASS_URLS
from gpx_poi_enricher.profiles import SearchProfile

OVERPASS_URL = OVERPASS_URLS[0]


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_profile(
    profile_id: str = "camping",
    tags: tuple = ({"key": "tourism", "value": "camp_site"},),
    terms: dict | None = None,
    max_km: float = 10.0,
    sample_km: float = 500.0,  # large so we get only a few sampled points in tests
    batch_size: int = 10,
    retries: int = 1,
) -> SearchProfile:
    """Build a minimal SearchProfile suitable for enricher tests."""
    if terms is None:
        terms = {"DE": ["Campingplatz"], "EN": ["campsite"]}
    return SearchProfile(
        id=profile_id,
        description="Campingplatz",
        symbol="Campground",
        tags=tuple(tags),
        terms=terms,
        max_km=max_km,
        sample_km=sample_km,
        batch_size=batch_size,
        retries=retries,
    )


def _nominatim_json(country_code: str) -> dict:
    return {"address": {"country_code": country_code}}


def _overpass_response_with_campsite(lat: float = 48.14, lon: float = 11.58) -> dict:
    """Return an Overpass API response containing one camp_site near Munich."""
    return {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": lat,
                "lon": lon,
                "tags": {"name": "Test Campsite", "tourism": "camp_site"},
            }
        ]
    }


def _overpass_empty_response() -> dict:
    return {"elements": []}


# ---------------------------------------------------------------------------
# enrich_track – unit-level tests (mocked HTTP)
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_enrich_track_returns_list(sample_track_points, profiles_dir):
    """enrich_track must return a list (possibly empty) of candidate dicts."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    profile = _make_profile()
    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        result = enrich_track(
            sample_track_points,
            profile,
            progress_interval=0,
        )

    assert isinstance(result, list)


@resp_lib.activate
def test_enrich_track_result_is_sorted_by_distance(sample_track_points):
    """enrich_track must return candidates sorted by distance_km ascending."""
    # Register Nominatim for each geocoding call (one per sampled point if spacing small).
    for cc in ["de", "de", "fr", "fr", "es"]:
        resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json(cc), status=200)

    # Overpass returns two nodes at different distances.
    overpass_response = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 48.14,
                "lon": 11.58,
                "tags": {"name": "Close Camp", "tourism": "camp_site"},
            },
            {
                "type": "node",
                "id": 2,
                "lat": 48.20,
                "lon": 11.60,
                "tags": {"name": "Far Camp", "tourism": "camp_site"},
            },
        ]
    }
    # Register enough Overpass responses for all batches.
    for _ in range(10):
        resp_lib.add(resp_lib.POST, OVERPASS_URL, json=overpass_response, status=200)

    profile = _make_profile(sample_km=100.0)
    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        result = enrich_track(
            sample_track_points,
            profile,
            progress_interval=0,
        )

    if len(result) >= 2:
        distances = [r["distance_km"] for r in result]
        assert distances == sorted(distances), "Results must be sorted by distance_km"


@resp_lib.activate
def test_enrich_track_result_dicts_have_required_keys(sample_track_points):
    """Each dict in the enrich_track result must have lat, lon, name, kind, distance_km, tags."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_response_with_campsite(), status=200)

    profile = _make_profile()
    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        result = enrich_track(
            sample_track_points,
            profile,
            progress_interval=0,
        )

    for candidate in result:
        for key in ("lat", "lon", "name", "kind", "distance_km", "tags"):
            assert key in candidate, f"Missing key '{key}' in candidate: {candidate}"


@resp_lib.activate
def test_enrich_track_respects_max_km(sample_track_points):
    """enrich_track must exclude candidates that exceed max_km from the track."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    # Return a node in Tokyo which is far from any track point.
    tokyo_response = {
        "elements": [
            {
                "type": "node",
                "id": 99,
                "lat": 35.6762,
                "lon": 139.6503,
                "tags": {"name": "Tokyo Camp", "tourism": "camp_site"},
            }
        ]
    }
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=tokyo_response, status=200)

    profile = _make_profile(max_km=10.0)
    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        result = enrich_track(
            sample_track_points,
            profile,
            progress_interval=0,
        )

    assert result == [], "No Tokyo-based candidates should survive the max_km filter"


@resp_lib.activate
def test_enrich_track_no_country_falls_back_to_en(sample_track_points):
    """If Nominatim returns empty string for every point, enrich_track must fall
    back to using 'EN' as the single country segment and still complete."""
    # Nominatim returns empty address so country_code is empty.
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"address": {}}, status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    profile = _make_profile()
    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        # Should not raise; should return an empty list when no POIs found.
        result = enrich_track(
            sample_track_points,
            profile,
            progress_interval=0,
        )

    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# enrich_gpx_file – integration tests
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_enrich_gpx_file_writes_output(sample_gpx_path, tmp_path, profiles_dir):
    """enrich_gpx_file must create an output GPX file at the specified path."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    assert output_path.exists(), "enrich_gpx_file must create the output file"


@resp_lib.activate
def test_enrich_gpx_file_output_is_valid_gpx(sample_gpx_path, tmp_path, profiles_dir):
    """enrich_gpx_file must produce a well-formed GPX XML file."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    # Should parse without error.
    tree = ET.parse(str(output_path))
    root = tree.getroot()
    assert root.tag == f"{{{GPX_NS}}}gpx"


@resp_lib.activate
def test_enrich_gpx_file_strips_tracks_from_output(sample_gpx_path, tmp_path, profiles_dir):
    """The output GPX file must not contain any <trk> or <rte> elements."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    tree = ET.parse(str(output_path))
    root = tree.getroot()
    assert root.findall(f"{{{GPX_NS}}}trk") == [], "Output must not contain <trk> elements"
    assert root.findall(f"{{{GPX_NS}}}rte") == [], "Output must not contain <rte> elements"


@resp_lib.activate
def test_enrich_gpx_file_contains_waypoints_when_pois_found(
    sample_gpx_path, tmp_path, profiles_dir
):
    """When Overpass returns a nearby POI, the output GPX must contain a <wpt> element."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    # Return a campsite very close to the first track point (Munich).
    resp_lib.add(
        resp_lib.POST,
        OVERPASS_URL,
        json=_overpass_response_with_campsite(lat=48.14, lon=11.58),
        status=200,
    )

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        count = enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    assert count >= 1, "At least one waypoint must be added for the nearby POI"
    tree = ET.parse(str(output_path))
    root = tree.getroot()
    wpts = root.findall(f"{{{GPX_NS}}}wpt")
    assert len(wpts) >= 1


@resp_lib.activate
def test_enrich_gpx_file_returns_waypoint_count(sample_gpx_path, tmp_path, profiles_dir):
    """enrich_gpx_file must return the integer count of waypoints written."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(resp_lib.POST, OVERPASS_URL, json=_overpass_empty_response(), status=200)

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        count = enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    assert isinstance(count, int)
    assert count >= 0


@resp_lib.activate
def test_enrich_gpx_file_waypoint_names_in_output(sample_gpx_path, tmp_path, profiles_dir):
    """Waypoint <name> elements in the output GPX must reflect the POI names returned
    by Overpass."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json=_nominatim_json("de"), status=200)
    resp_lib.add(
        resp_lib.POST,
        OVERPASS_URL,
        json={
            "elements": [
                {
                    "type": "node",
                    "id": 42,
                    "lat": 48.14,
                    "lon": 11.58,
                    "tags": {"name": "Campingpark Isartal", "tourism": "camp_site"},
                }
            ]
        },
        status=200,
    )

    output_path = tmp_path / "out.gpx"

    with (
        patch("gpx_poi_enricher.geocoding.time.sleep"),
        patch("gpx_poi_enricher.enricher.time.sleep"),
    ):
        count = enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )

    if count > 0:
        tree = ET.parse(str(output_path))
        root = tree.getroot()
        names = [
            el.text
            for wpt in root.findall(f"{{{GPX_NS}}}wpt")
            for el in wpt.findall(f"{{{GPX_NS}}}name")
        ]
        assert "Campingpark Isartal" in names


@resp_lib.activate
def test_enrich_gpx_file_unknown_profile_raises(sample_gpx_path, tmp_path, profiles_dir):
    """enrich_gpx_file must raise FileNotFoundError for an unknown profile_id."""
    output_path = tmp_path / "out.gpx"
    with pytest.raises(FileNotFoundError):
        enrich_gpx_file(
            sample_gpx_path,
            str(output_path),
            profile_id="nonexistent_profile_xyz",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )


@resp_lib.activate
def test_enrich_gpx_file_missing_input_raises(tmp_path, profiles_dir):
    """enrich_gpx_file must raise an error when the input GPX does not exist."""
    output_path = tmp_path / "out.gpx"
    with pytest.raises((FileNotFoundError, OSError)):
        enrich_gpx_file(
            str(tmp_path / "nonexistent.gpx"),
            str(output_path),
            profile_id="camping",
            profiles_dir=profiles_dir,
            progress_interval=0,
        )
