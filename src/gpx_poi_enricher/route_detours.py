"""Extract detour segments from multiple routed polylines.

Given a primary route (reference) and one or more alternate routes, finds
contiguous segments on alternates that stay farther than a threshold from the
reference polyline — these are treated as significant detours. Reverse or
parallel routes that largely coincide with the reference produce few or no
detour segments because distances remain below the threshold.
"""

from __future__ import annotations

from gpx_poi_enricher.gpx_utils import haversine_km, min_distance_to_track_km


def polyline_length_km(points: list[tuple[float, float]]) -> float:
    """Total path length along consecutive points (km)."""
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        total += haversine_km(a[0], a[1], b[0], b[1])
    return total


def _merge_far_ranges(
    points: list[tuple[float, float]],
    ranges: list[tuple[int, int]],
    gap_merge_km: float,
) -> list[tuple[int, int]]:
    """Merge half-open far ranges [lo, hi) separated by short near gaps along *points*."""
    if not ranges:
        return []
    merged: list[tuple[int, int]] = [ranges[0]]
    for lo, hi in ranges[1:]:
        prev_lo, prev_hi = merged[-1]
        gap_segment = points[prev_hi:lo]
        gap_len = polyline_length_km(gap_segment)
        if gap_len <= gap_merge_km:
            merged[-1] = (prev_lo, hi)
        else:
            merged.append((lo, hi))
    return merged


def extract_detour_segments(
    alternate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
    *,
    near_threshold_km: float = 0.045,
    min_detour_km: float = 0.18,
    gap_merge_km: float = 0.06,
    min_points: int = 4,
) -> list[list[tuple[float, float]]]:
    """Return polyline chunks on *alternate* that deviate significantly from *reference*.

    Points on *alternate* are classified as "near" when their distance to the
    *reference* polyline (vertex sampling via :func:`~gpx_utils.min_distance_to_track_km`)
    is below *near_threshold_km*. Contiguous runs of "far" points at least
    *min_detour_km* long become detour segments. Short near-gaps between two far
    runs are merged when the gap length is below *gap_merge_km*.
    """
    if len(alternate) < 2 or len(reference) < 2:
        return []

    near_flags = [
        min_distance_to_track_km(lat, lon, reference) < near_threshold_km for lat, lon in alternate
    ]

    # Half-open ranges [lo, hi) where far
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(near_flags)
    while i < n:
        if near_flags[i]:
            i += 1
            continue
        start = i
        while i < n and not near_flags[i]:
            i += 1
        ranges.append((start, i))

    if not ranges:
        return []

    merged_ranges = _merge_far_ranges(alternate, ranges, gap_merge_km)

    out: list[list[tuple[float, float]]] = []
    for lo, hi in merged_ranges:
        chunk = alternate[lo:hi]
        if len(chunk) < min_points:
            continue
        if polyline_length_km(chunk) < min_detour_km:
            continue
        out.append(chunk)

    return out
