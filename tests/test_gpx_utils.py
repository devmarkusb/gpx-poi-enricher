"""Tests for gpx_poi_enricher.gpx_utils module.

Covers: haversine_km, sample_track_by_distance, min_distance_to_track_km,
parse_gpx_trackpoints, remove_tracks_and_routes, add_waypoints_to_gpx.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from gpx_poi_enricher.gpx_utils import (
    GPX_NS,
    add_waypoints_to_gpx,
    haversine_km,
    min_distance_to_track_km,
    parse_gpx_trackpoints,
    remove_tracks_and_routes,
    sample_track_by_distance,
)

# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lat1, lon1, lat2, lon2, expected_km, tolerance_km",
    [
        # Same point: distance must be exactly 0.
        (48.1351, 11.5820, 48.1351, 11.5820, 0.0, 0.001),
        # Munich (48.1351, 11.582) to Zurich (47.3769, 8.5417): actual ~242 km.
        (48.1351, 11.5820, 47.3769, 8.5417, 242.0, 5.0),
        # Zurich (47.3769, 8.5417) to Lyon (45.764, 4.8357): actual ~335 km.
        (47.3769, 8.5417, 45.7640, 4.8357, 335.0, 8.0),
        # Lyon (45.764, 4.8357) to Marseille (43.2965, 5.3811): actual ~278 km.
        (45.7640, 4.8357, 43.2965, 5.3811, 278.0, 8.0),
        # Marseille (43.2965, 5.3811) to Barcelona (41.3851, 2.1734): actual ~339 km.
        (43.2965, 5.3811, 41.3851, 2.1734, 339.0, 10.0),
        # North Pole to South Pole: must be half the Earth's circumference ~20015 km.
        (90.0, 0.0, -90.0, 0.0, 20015.0, 5.0),
    ],
)
def test_haversine_km_known_distances(lat1, lon1, lat2, lon2, expected_km, tolerance_km):
    """haversine_km should return distances close to known reference values."""
    result = haversine_km(lat1, lon1, lat2, lon2)
    assert abs(result - expected_km) <= tolerance_km, (
        f"haversine_km({lat1}, {lon1}, {lat2}, {lon2}) = {result:.2f} km, "
        f"expected ~{expected_km} km (tolerance ±{tolerance_km} km)"
    )


def test_haversine_km_symmetry():
    """haversine_km must be symmetric: distance A→B equals distance B→A."""
    d_ab = haversine_km(48.1351, 11.5820, 41.3851, 2.1734)
    d_ba = haversine_km(41.3851, 2.1734, 48.1351, 11.5820)
    assert abs(d_ab - d_ba) < 1e-9


def test_haversine_km_non_negative():
    """haversine_km must never return a negative distance."""
    assert haversine_km(0.0, 0.0, 1.0, 1.0) >= 0.0
    assert haversine_km(-10.0, -20.0, 10.0, 20.0) >= 0.0


# ---------------------------------------------------------------------------
# sample_track_by_distance
# ---------------------------------------------------------------------------


def test_sample_track_by_distance_empty():
    """sample_track_by_distance on an empty list must return an empty list."""
    assert sample_track_by_distance([], spacing_km=50.0) == []


def test_sample_track_by_distance_single_point():
    """A single-point track is returned unchanged."""
    pts = [(48.0, 11.0)]
    result = sample_track_by_distance(pts, spacing_km=50.0)
    assert result == pts


def test_sample_track_by_distance_first_and_last_always_included(sample_track_points):
    """The first and last original points must always appear in the result."""
    result = sample_track_by_distance(sample_track_points, spacing_km=1000.0)
    assert result[0] == sample_track_points[0]
    assert result[-1] == sample_track_points[-1]


def test_sample_track_by_distance_spacing_respected(sample_track_points):
    """Consecutive sampled points must be separated by at least spacing_km
    (except when the last point is forced in regardless of distance)."""
    spacing_km = 100.0
    result = sample_track_by_distance(sample_track_points, spacing_km=spacing_km)
    # Every consecutive pair except the very last forced inclusion must exceed spacing_km.
    for i in range(len(result) - 2):
        d = haversine_km(result[i][0], result[i][1], result[i + 1][0], result[i + 1][1])
        assert d >= spacing_km - 1e-6, (
            f"Points {result[i]} and {result[i + 1]} are only {d:.2f} km apart "
            f"(spacing_km={spacing_km})"
        )


def test_sample_track_by_distance_very_small_spacing_includes_all(sample_track_points):
    """With a tiny spacing the result should include at least as many points as the input."""
    result = sample_track_by_distance(sample_track_points, spacing_km=0.001)
    assert len(result) >= len(sample_track_points)


def test_sample_track_by_distance_large_spacing_returns_two(sample_track_points):
    """With spacing larger than the total route length, only first and last are returned."""
    result = sample_track_by_distance(sample_track_points, spacing_km=99999.0)
    assert result[0] == sample_track_points[0]
    assert result[-1] == sample_track_points[-1]
    assert len(result) == 2


# ---------------------------------------------------------------------------
# min_distance_to_track_km
# ---------------------------------------------------------------------------


def test_min_distance_to_track_km_exact_point(sample_track_points):
    """A point that is exactly on the track must have distance ~0."""
    on_track = sample_track_points[2]
    d = min_distance_to_track_km(on_track[0], on_track[1], sample_track_points)
    assert d < 1e-6


def test_min_distance_to_track_km_nearby_point(sample_track_points):
    """A point very close to the track must have a small distance."""
    near_munich = (48.14, 11.59)  # ~0.7 km north-east of Munich waypoint
    d = min_distance_to_track_km(near_munich[0], near_munich[1], sample_track_points)
    assert d < 5.0, f"Expected close point to be < 5 km from track, got {d:.2f} km"


def test_min_distance_to_track_km_far_point(sample_track_points):
    """A point far from the track (e.g. Tokyo) must report a large distance."""
    tokyo = (35.6762, 139.6503)
    d = min_distance_to_track_km(tokyo[0], tokyo[1], sample_track_points)
    assert d > 5000.0, f"Expected Tokyo to be > 5000 km from route, got {d:.2f} km"


def test_min_distance_to_track_km_single_point_track():
    """With a single-point track the result equals the distance to that point."""
    track = [(48.0, 11.0)]
    pt = (48.1, 11.1)
    d = min_distance_to_track_km(pt[0], pt[1], track)
    expected = haversine_km(pt[0], pt[1], track[0][0], track[0][1])
    assert abs(d - expected) < 1e-6


# ---------------------------------------------------------------------------
# parse_gpx_trackpoints
# ---------------------------------------------------------------------------


def test_parse_gpx_trackpoints_returns_correct_count(sample_gpx_path):
    """parse_gpx_trackpoints should find exactly 5 track points in the fixture."""
    _tree, _root, pts = parse_gpx_trackpoints(sample_gpx_path)
    assert len(pts) == 5


def test_parse_gpx_trackpoints_first_and_last(sample_gpx_path, sample_track_points):
    """parse_gpx_trackpoints should return the expected first and last coordinates."""
    _tree, _root, pts = parse_gpx_trackpoints(sample_gpx_path)
    assert pytest.approx(pts[0][0], abs=1e-4) == sample_track_points[0][0]
    assert pytest.approx(pts[0][1], abs=1e-4) == sample_track_points[0][1]
    assert pytest.approx(pts[-1][0], abs=1e-4) == sample_track_points[-1][0]
    assert pytest.approx(pts[-1][1], abs=1e-4) == sample_track_points[-1][1]


def test_parse_gpx_trackpoints_returns_tree_and_root(sample_gpx_path):
    """parse_gpx_trackpoints should return a valid ElementTree and root element."""
    tree, root, pts = parse_gpx_trackpoints(sample_gpx_path)
    assert isinstance(tree, ET.ElementTree)
    assert isinstance(root, ET.Element)
    assert root.tag == f"{{{GPX_NS}}}gpx"


def test_parse_gpx_trackpoints_raises_for_missing_file():
    """parse_gpx_trackpoints should propagate an error for a non-existent file."""
    with pytest.raises((FileNotFoundError, OSError)):
        parse_gpx_trackpoints("/nonexistent/path/to/file.gpx")


def test_parse_gpx_trackpoints_raises_for_no_trackpoints(tmp_path):
    """parse_gpx_trackpoints should raise ValueError when no trkpt elements exist."""
    empty_gpx = tmp_path / "empty.gpx"
    empty_gpx.write_text(
        '<?xml version="1.0"?>'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">'
        "</gpx>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="No track points found"):
        parse_gpx_trackpoints(str(empty_gpx))


# ---------------------------------------------------------------------------
# remove_tracks_and_routes
# ---------------------------------------------------------------------------


def _make_gpx_root(include_trk: bool = True, include_rte: bool = True) -> ET.Element:
    """Helper: build a minimal GPX root element with optional trk/rte children."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    if include_trk:
        ET.SubElement(root, f"{{{GPX_NS}}}trk")
    if include_rte:
        ET.SubElement(root, f"{{{GPX_NS}}}rte")
    ET.SubElement(root, f"{{{GPX_NS}}}wpt", lat="48.0", lon="11.0")
    return root


def test_remove_tracks_and_routes_removes_trk():
    """remove_tracks_and_routes must remove all <trk> elements."""
    root = _make_gpx_root(include_trk=True, include_rte=False)
    remove_tracks_and_routes(root)
    trks = root.findall(f"{{{GPX_NS}}}trk")
    assert trks == [], "Expected no <trk> elements after removal"


def test_remove_tracks_and_routes_removes_rte():
    """remove_tracks_and_routes must remove all <rte> elements."""
    root = _make_gpx_root(include_trk=False, include_rte=True)
    remove_tracks_and_routes(root)
    rtes = root.findall(f"{{{GPX_NS}}}rte")
    assert rtes == [], "Expected no <rte> elements after removal"


def test_remove_tracks_and_routes_preserves_wpt():
    """remove_tracks_and_routes must leave <wpt> elements intact."""
    root = _make_gpx_root(include_trk=True, include_rte=True)
    remove_tracks_and_routes(root)
    wpts = root.findall(f"{{{GPX_NS}}}wpt")
    assert len(wpts) == 1, "Expected 1 <wpt> element to survive"


def test_remove_tracks_and_routes_multiple_trk():
    """remove_tracks_and_routes must handle multiple track segments."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    for _ in range(3):
        ET.SubElement(root, f"{{{GPX_NS}}}trk")
    remove_tracks_and_routes(root)
    assert root.findall(f"{{{GPX_NS}}}trk") == []


def test_remove_tracks_and_routes_no_op_when_empty():
    """remove_tracks_and_routes must not raise when there is nothing to remove."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    remove_tracks_and_routes(root)  # should not raise


# ---------------------------------------------------------------------------
# add_waypoints_to_gpx
# ---------------------------------------------------------------------------


def _make_poi_items(n: int = 2) -> list[dict]:
    return [
        {
            "lat": 48.0 + i * 0.1,
            "lon": 11.0 + i * 0.1,
            "name": f"Test POI {i}",
            "kind": "tourism=camp_site",
            "distance_km": float(i),
        }
        for i in range(n)
    ]


def test_add_waypoints_to_gpx_correct_count():
    """add_waypoints_to_gpx should append one <wpt> per item."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    items = _make_poi_items(3)
    add_waypoints_to_gpx(root, items, symbol="Campground", type_label="Campingplatz")
    wpts = root.findall(f"{{{GPX_NS}}}wpt")
    assert len(wpts) == 3


def test_add_waypoints_to_gpx_coordinates():
    """add_waypoints_to_gpx should set lat/lon attributes correctly."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    items = [
        {
            "lat": 48.123456,
            "lon": 11.654321,
            "name": "Camp A",
            "kind": "tourism=camp_site",
            "distance_km": 2.5,
        }
    ]
    add_waypoints_to_gpx(root, items, symbol="Campground", type_label="Campingplatz")
    wpt = root.find(f"{{{GPX_NS}}}wpt")
    assert wpt is not None
    assert float(wpt.attrib["lat"]) == pytest.approx(48.123456, abs=1e-5)
    assert float(wpt.attrib["lon"]) == pytest.approx(11.654321, abs=1e-5)


def test_add_waypoints_to_gpx_name_and_symbol():
    """add_waypoints_to_gpx should write name and symbol sub-elements."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    items = [
        {
            "lat": 48.0,
            "lon": 11.0,
            "name": "My Camp",
            "kind": "tourism=camp_site",
            "distance_km": 1.0,
        }
    ]
    add_waypoints_to_gpx(root, items, symbol="Campground", type_label="Campingplatz")
    wpt = root.find(f"{{{GPX_NS}}}wpt")
    name_el = wpt.find(f"{{{GPX_NS}}}name")
    sym_el = wpt.find(f"{{{GPX_NS}}}sym")
    type_el = wpt.find(f"{{{GPX_NS}}}type")
    assert name_el is not None and name_el.text == "My Camp"
    assert sym_el is not None and sym_el.text == "Campground"
    assert type_el is not None and type_el.text == "Campingplatz"


def test_add_waypoints_to_gpx_desc_contains_distance():
    """add_waypoints_to_gpx should include the distance in the <desc> element."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    items = [
        {
            "lat": 48.0,
            "lon": 11.0,
            "name": "Camp B",
            "kind": "tourism=camp_site",
            "distance_km": 7.35,
        }
    ]
    add_waypoints_to_gpx(root, items, symbol="Campground", type_label="Campingplatz")
    wpt = root.find(f"{{{GPX_NS}}}wpt")
    desc_el = wpt.find(f"{{{GPX_NS}}}desc")
    assert desc_el is not None
    assert "7.3" in desc_el.text  # formatted as one decimal place


def test_add_waypoints_to_gpx_empty_list_is_noop():
    """add_waypoints_to_gpx with an empty items list must not modify the root."""
    root = ET.Element(f"{{{GPX_NS}}}gpx")
    add_waypoints_to_gpx(root, [], symbol="Campground", type_label="Campingplatz")
    assert list(root) == []
