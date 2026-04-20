"""Tests for gpx_poi_enricher.overpass module.

Covers: build_overpass_query, extract_candidates, element_latlon.
No real HTTP calls are made; Overpass responses are provided as mock dicts.
"""

from __future__ import annotations

import pytest

from gpx_poi_enricher.overpass import (
    build_overpass_query,
    element_latlon,
    extract_candidates,
)
from gpx_poi_enricher.profiles import SearchProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    profile_id: str = "camping",
    description: str = "Campingplatz",
    tags: tuple = ({"key": "tourism", "value": "camp_site"},),
    terms: dict | None = None,
    max_km: float = 10.0,
    sample_km: float = 5.0,
    batch_size: int = 4,
    retries: int = 2,
) -> SearchProfile:
    """Build a minimal SearchProfile for overpass tests."""
    if terms is None:
        terms = {"DE": ["Campingplatz"], "EN": ["campsite"]}
    return SearchProfile(
        id=profile_id,
        description=description,
        symbol="Campground",
        tags=tuple(tags),
        terms=terms,
        max_km=max_km,
        sample_km=sample_km,
        batch_size=batch_size,
        retries=retries,
    )


def _make_node(
    node_id: int = 1,
    lat: float = 48.0,
    lon: float = 11.0,
    tags: dict | None = None,
) -> dict:
    """Build an Overpass-style node element dict."""
    return {
        "type": "node",
        "id": node_id,
        "lat": lat,
        "lon": lon,
        "tags": tags or {"name": "Test Camp", "tourism": "camp_site"},
    }


def _make_way(
    way_id: int = 2,
    center_lat: float = 48.1,
    center_lon: float = 11.1,
    tags: dict | None = None,
) -> dict:
    """Build an Overpass-style way element dict (with center, no direct lat/lon)."""
    return {
        "type": "way",
        "id": way_id,
        "center": {"lat": center_lat, "lon": center_lon},
        "tags": tags or {"name": "Camp Way", "tourism": "caravan_site"},
    }


# ---------------------------------------------------------------------------
# element_latlon
# ---------------------------------------------------------------------------


def test_element_latlon_node_format():
    """element_latlon must extract lat/lon directly for node elements."""
    el = {"type": "node", "id": 1, "lat": 48.5, "lon": 11.5}
    lat, lon = element_latlon(el)
    assert lat == pytest.approx(48.5)
    assert lon == pytest.approx(11.5)


def test_element_latlon_way_center_format():
    """element_latlon must extract lat/lon from the center dict for way elements."""
    el = {"type": "way", "id": 2, "center": {"lat": 47.0, "lon": 8.0}}
    lat, lon = element_latlon(el)
    assert lat == pytest.approx(47.0)
    assert lon == pytest.approx(8.0)


def test_element_latlon_missing_coords_returns_none():
    """element_latlon must return (None, None) when neither direct nor center coords exist."""
    el = {"type": "way", "id": 3}
    lat, lon = element_latlon(el)
    assert lat is None
    assert lon is None


def test_element_latlon_empty_center_returns_none():
    """element_latlon must return (None, None) when center dict exists but has no lat/lon."""
    el = {"type": "way", "id": 4, "center": {}}
    lat, lon = element_latlon(el)
    assert lat is None
    assert lon is None


def test_element_latlon_direct_lat_lon_takes_priority():
    """element_latlon must prefer top-level lat/lon over center when both exist."""
    el = {"type": "node", "id": 5, "lat": 48.0, "lon": 11.0, "center": {"lat": 99.0, "lon": 99.0}}
    lat, lon = element_latlon(el)
    assert lat == pytest.approx(48.0)
    assert lon == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# build_overpass_query
# ---------------------------------------------------------------------------


def test_build_overpass_query_contains_out_json():
    """build_overpass_query must produce a query starting with [out:json]."""
    profile = _make_profile()
    pts = [(48.1351, 11.5820)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    assert "[out:json]" in query


def test_build_overpass_query_includes_around_radius():
    """build_overpass_query must embed the radius in metres (max_km * 1000)."""
    profile = _make_profile()
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=5.0, profile=profile, country_code="DE")
    assert "around:5000" in query


def test_build_overpass_query_includes_tag_filter():
    """build_overpass_query must include the profile's OSM tag filter."""
    profile = _make_profile(tags=({"key": "tourism", "value": "camp_site"},))
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    assert '"tourism"="camp_site"' in query


def test_build_overpass_query_includes_terms_regex():
    """build_overpass_query must embed country-specific and EN terms as a regex."""
    profile = _make_profile(terms={"DE": ["Campingplatz"], "EN": ["campsite"]})
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    # Both DE and EN terms should appear in the query (escaped in regex).
    assert "Campingplatz" in query
    assert "campsite" in query


def test_build_overpass_query_multiple_element_types():
    """build_overpass_query must emit node/way/relation selectors."""
    profile = _make_profile()
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    assert "node(" in query
    assert "way(" in query
    assert "relation(" in query


def test_build_overpass_query_multiple_points():
    """build_overpass_query must generate selectors for every point in the batch."""
    profile = _make_profile()
    pts = [(48.0, 11.0), (47.0, 10.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    # Both coordinates should appear in the query string.
    assert "48.0" in query
    assert "47.0" in query


def test_build_overpass_query_wildcard_tag_value():
    """build_overpass_query with value='*' must emit a key-only filter [key]."""
    profile = _make_profile(tags=({"key": "tourism", "value": "*"},))
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    assert '["tourism"]' in query


def test_build_overpass_query_raises_for_empty_tags_and_no_terms():
    """build_overpass_query must raise ValueError when there are no tags and no terms."""
    profile = _make_profile(tags=(), terms={})
    pts = [(48.0, 11.0)]
    with pytest.raises(ValueError, match="No Overpass query could be built"):
        build_overpass_query(pts, max_km=10.0, profile=profile, country_code="ZZ")


def test_build_overpass_query_kids_activities_no_tags_unknown_country():
    """build_overpass_query for a profile with no tags and no matching country terms
    must raise ValueError when used with an unrecognised country code.

    This mirrors the 'kids_activities' profile which has no OSM tag filters and
    relies entirely on search terms. For an unknown country with no EN fallback either
    a ValueError should be raised.
    """
    profile = _make_profile(tags=(), terms={"DE": ["Kindererlebnis"]})
    pts = [(48.0, 11.0)]
    # Country ZZ has no terms and there are no tags – expect ValueError.
    with pytest.raises(ValueError):
        build_overpass_query(pts, max_km=15.0, profile=profile, country_code="ZZ")


def test_build_overpass_query_and_tag_extra_condition():
    """build_overpass_query must include extra conditions from the 'and' key in a tag."""
    profile = _make_profile(
        tags=({"key": "amenity", "value": "fuel", "and": {"key": "motorcar", "value": "yes"}},)
    )
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=5.0, profile=profile, country_code="EN")
    assert '"amenity"="fuel"' in query
    assert '"motorcar"="yes"' in query


def test_build_overpass_query_ends_with_out_center_tags():
    """build_overpass_query must end with 'out center tags;'."""
    profile = _make_profile()
    pts = [(48.0, 11.0)]
    query = build_overpass_query(pts, max_km=10.0, profile=profile, country_code="DE")
    assert query.strip().endswith("out center tags;")


# ---------------------------------------------------------------------------
# extract_candidates
# ---------------------------------------------------------------------------


def test_extract_candidates_filters_by_distance(sample_track_points):
    """extract_candidates must exclude elements that exceed max_km from the track."""
    profile = _make_profile()
    # A node in Tokyo is ~9000 km from the Munich-Barcelona track.
    tokyo_node = _make_node(node_id=99, lat=35.6762, lon=139.6503)
    data = {"elements": [tokyo_node]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert result == [], "Tokyo node should be filtered out as it is far from the track"


def test_extract_candidates_includes_nearby_elements(sample_track_points):
    """extract_candidates must include elements within max_km of the track."""
    profile = _make_profile()
    # A node very close to Munich (first track point).
    near_munich = _make_node(node_id=1, lat=48.14, lon=11.58)
    data = {"elements": [near_munich]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 1


def test_extract_candidates_result_has_required_keys(sample_track_points):
    """Each returned candidate dict must have lat, lon, name, kind, distance_km, tags."""
    profile = _make_profile()
    near_munich = _make_node(node_id=1, lat=48.14, lon=11.58)
    data = {"elements": [near_munich]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 1
    candidate = result[0]
    for key in ("lat", "lon", "name", "kind", "distance_km", "tags"):
        assert key in candidate, f"Missing key '{key}' in candidate dict"


def test_extract_candidates_deduplication(sample_track_points):
    """extract_candidates must not return duplicate coordinates (same lat/lon rounded to 5 dp)."""
    profile = _make_profile()
    # Two nodes with essentially the same coordinate.
    node_a = _make_node(node_id=1, lat=48.14000, lon=11.58000)
    node_b = _make_node(node_id=2, lat=48.14000, lon=11.58000)
    data = {"elements": [node_a, node_b]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 1, "Duplicate coordinates should be deduplicated"


def test_extract_candidates_handles_missing_lat_lon(sample_track_points):
    """extract_candidates must silently skip elements with no usable coordinates."""
    profile = _make_profile()
    bad_el = {"type": "way", "id": 99, "tags": {"name": "Broken"}}  # no lat/lon/center
    near_munich = _make_node(node_id=1, lat=48.14, lon=11.58)
    data = {"elements": [bad_el, near_munich]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 1  # only near_munich should be returned


def test_extract_candidates_empty_data(sample_track_points):
    """extract_candidates must return an empty list when elements is empty."""
    profile = _make_profile()
    result = extract_candidates({"elements": []}, sample_track_points, max_km=10.0, profile=profile)
    assert result == []


def test_extract_candidates_uses_way_center(sample_track_points):
    """extract_candidates must correctly handle way elements that use 'center' for coordinates."""
    profile = _make_profile()
    # Way whose center is near Munich.
    way = _make_way(way_id=10, center_lat=48.14, center_lon=11.58)
    data = {"elements": [way]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 1
    assert result[0]["lat"] == pytest.approx(48.14, abs=1e-5)


def test_extract_candidates_name_from_tags(sample_track_points):
    """extract_candidates must use the 'name' tag as the candidate's name when present."""
    profile = _make_profile()
    node = _make_node(
        node_id=1,
        lat=48.14,
        lon=11.58,
        tags={"name": "Campingpark München", "tourism": "camp_site"},
    )
    data = {"elements": [node]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert result[0]["name"] == "Campingpark München"


def test_extract_candidates_distance_km_is_non_negative(sample_track_points):
    """The distance_km field in all returned candidates must be non-negative."""
    profile = _make_profile()
    node = _make_node(node_id=1, lat=48.14, lon=11.58)
    data = {"elements": [node]}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert all(c["distance_km"] >= 0 for c in result)


def test_extract_candidates_multiple_nearby(sample_track_points):
    """extract_candidates must return multiple candidates when several are within range."""
    profile = _make_profile()
    nodes = [
        _make_node(
            node_id=i,
            lat=48.13 + i * 0.01,
            lon=11.58,
            tags={"name": f"Camp {i}", "tourism": "camp_site"},
        )
        for i in range(3)
    ]
    data = {"elements": nodes}
    result = extract_candidates(data, sample_track_points, max_km=10.0, profile=profile)
    assert len(result) == 3
