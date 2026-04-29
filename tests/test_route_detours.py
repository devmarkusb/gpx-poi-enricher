"""Tests for route_detours."""

from __future__ import annotations

from gpx_poi_enricher.route_detours import (
    alternate_is_reverse_itinerary,
    alternate_redundant_with_prior,
    detour_span_for_alternate,
    extract_detour_segments,
    polyline_length_km,
)


def _straight_line(lat0: float, lon0: float, n: int, step_km: float) -> list[tuple[float, float]]:
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


def test_detour_span_single_polyline_for_parallel_alternate():
    """One merged span per alternate (not one GPX per fragment)."""
    ref = _straight_line(48.0, 11.0, 60, 0.35)
    alt = [(lat, lon + 0.015) for lat, lon in ref]
    span = detour_span_for_alternate(
        alt,
        ref,
        near_threshold_km=0.05,
        min_detour_km=0.15,
        gap_merge_km=0.12,
        min_points=5,
    )
    assert span is not None
    assert len(span) >= 5


def test_redundant_reverse_matches_primary():
    primary = _straight_line(48.0, 11.0, 80, 0.4)
    reverse_dup = list(reversed(primary))
    assert alternate_redundant_with_prior(reverse_dup, primary, [], mean_dup_km=0.05, stride=10)


def test_redundant_detects_prior_alternate():
    a = _straight_line(48.0, 11.0, 40, 0.5)
    b = [(lat, lon + 0.0001) for lat, lon in a]
    assert alternate_redundant_with_prior(b, a, [a], mean_dup_km=0.02, stride=5)


def test_reverse_itinerary_endpoints_swap():
    primary = [(48.0, 11.0), (49.0, 11.5)]
    alt_rev = [(49.0, 11.5), (48.0, 11.0)]
    assert alternate_is_reverse_itinerary(primary, alt_rev, endpoint_km=5.0)


def test_same_direction_not_reverse_itinerary():
    primary = [(48.0, 11.0), (49.0, 11.5)]
    alt_fw = [(48.01, 11.01), (49.01, 11.51)]
    assert not alternate_is_reverse_itinerary(primary, alt_fw, endpoint_km=5.0)
