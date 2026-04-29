"""Tests for route_detours: detour extraction."""

from __future__ import annotations

from gpx_poi_enricher.route_detours import (
    extract_detour_segments,
    polyline_length_km,
)


def _straight_line(lat0: float, lon0: float, n: int, step_km: float) -> list[tuple[float, float]]:
    """Rough north-going polyline (~step_km between points at mid-latitude)."""
    pts = []
    dlat = (step_km / 111.0) if n > 1 else 0.0
    for i in range(n):
        pts.append((lat0 + i * dlat, lon0))
    return pts


def test_polyline_length_zero_or_short():
    assert polyline_length_km([]) == 0.0
    assert polyline_length_km([(48.0, 11.0)]) == 0.0


def test_extract_detour_identical_to_reference():
    ref = _straight_line(48.0, 11.0, 40, 0.5)
    assert extract_detour_segments(ref, ref, near_threshold_km=0.05, min_detour_km=0.1) == []


def test_extract_detour_parallel_far_route_nonempty():
    """Alternate stays ~1 km east of reference — non-empty detour list."""
    ref = _straight_line(48.0, 11.0, 50, 0.4)
    alt = [(lat, lon + 0.015) for lat, lon in ref]
    segs = extract_detour_segments(
        alt,
        ref,
        near_threshold_km=0.05,
        min_detour_km=0.15,
        min_points=5,
    )
    assert len(segs) >= 1
    assert sum(polyline_length_km(s) for s in segs) > 5.0
