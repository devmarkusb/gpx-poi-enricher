"""Extract detour geometry from multiple routed polylines.

Given a primary route (reference) and alternate routes, finds where alternates
leave the reference farther than a threshold. For output we collapse each
alternate into a single contiguous span (one GPX per alternate) instead of many
tiny fragments. Routes that match the primary or an earlier alternate (including
reverse) can be skipped as redundant.
"""

from __future__ import annotations

from gpx_poi_enricher.gpx_utils import haversine_km, min_distance_to_polyline_segments_km


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


def _far_ranges_merged(
    alternate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
    *,
    near_threshold_km: float,
    gap_merge_km: float,
) -> list[tuple[int, int]]:
    """Half-open index ranges on *alternate* where points are far from *reference*."""
    if len(alternate) < 2 or len(reference) < 2:
        return []

    # Segment distance (not vertex-only): avoids classifying opposite carriageway / reversed
    # OSRM geometry as a full-route \"detour\" when it still follows the same corridor.
    near_flags = [
        min_distance_to_polyline_segments_km(lat, lon, reference) < near_threshold_km
        for lat, lon in alternate
    ]

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

    return _merge_far_ranges(alternate, ranges, gap_merge_km)


def extract_detour_segments(
    alternate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
    *,
    near_threshold_km: float = 0.055,
    min_detour_km: float = 0.35,
    gap_merge_km: float = 0.12,
    min_points: int = 6,
) -> list[list[tuple[float, float]]]:
    """Return polyline chunks on *alternate* that deviate significantly from *reference*."""
    merged_ranges = _far_ranges_merged(
        alternate,
        reference,
        near_threshold_km=near_threshold_km,
        gap_merge_km=gap_merge_km,
    )
    out: list[list[tuple[float, float]]] = []
    for lo, hi in merged_ranges:
        chunk = alternate[lo:hi]
        if len(chunk) < min_points:
            continue
        if polyline_length_km(chunk) < min_detour_km:
            continue
        out.append(chunk)

    return out


def detour_span_for_alternate(
    alternate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
    *,
    near_threshold_km: float = 0.055,
    min_detour_km: float = 0.35,
    gap_merge_km: float = 0.12,
    min_points: int = 6,
) -> list[tuple[float, float]] | None:
    """Single contiguous slice of *alternate* covering all deviation from *reference*.

    Returns one polyline per alternate URL (indices ``min … max`` along that route)
    so callers emit one ``-detour-NN.gpx`` per alternate instead of many fragments.
    ``None`` if there is no substantial deviation.
    """
    merged_ranges = _far_ranges_merged(
        alternate,
        reference,
        near_threshold_km=near_threshold_km,
        gap_merge_km=gap_merge_km,
    )
    if not merged_ranges:
        return None

    total_far_km = sum(polyline_length_km(alternate[lo:hi]) for lo, hi in merged_ranges)
    if total_far_km < min_detour_km:
        return None

    lo_span = min(lo for lo, _ in merged_ranges)
    hi_span = max(hi for _, hi in merged_ranges)
    span = alternate[lo_span:hi_span]
    if len(span) < min_points:
        return None
    return span


def alternate_is_reverse_itinerary(
    primary_pts: list[tuple[float, float]],
    alt_pts: list[tuple[float, float]],
    *,
    endpoint_km: float = 3.0,
) -> bool:
    """True when the alternate is clearly the same trip as the primary but **B→A** not **A→B**.

    OSRM often returns a different polyline for the return direction (other carriageway, etc.),
    so geometry-vs-primary tests may still mark most points as \"far\". For detour output we
    treat this case as **not** a side detour: use the primary and ``-full-NN`` only.
    """
    if len(primary_pts) < 2 or len(alt_pts) < 2:
        return False
    a0, a1 = primary_pts[0], primary_pts[-1]
    b0, b1 = alt_pts[0], alt_pts[-1]
    same_order = (
        haversine_km(b0[0], b0[1], a0[0], a0[1]) <= endpoint_km
        and haversine_km(b1[0], b1[1], a1[0], a1[1]) <= endpoint_km
    )
    if same_order:
        return False
    reverse_order = (
        haversine_km(b0[0], b0[1], a1[0], a1[1]) <= endpoint_km
        and haversine_km(b1[0], b1[1], a0[0], a0[1]) <= endpoint_km
    )
    return reverse_order


def mean_min_distance_to_polyline(
    probe: list[tuple[float, float]],
    polyline: list[tuple[float, float]],
    *,
    stride: int = 25,
) -> float:
    """Mean min distance to *polyline* (segment-based) for sampled points on *probe*."""
    if len(probe) < 2 or len(polyline) < 2:
        return float("inf")
    step = max(1, stride)
    dists: list[float] = []
    for i in range(0, len(probe), step):
        lat, lon = probe[i]
        dists.append(min_distance_to_polyline_segments_km(lat, lon, polyline))
    return sum(dists) / len(dists)


def alternate_redundant_with_prior(
    alt_pts: list[tuple[float, float]],
    primary_pts: list[tuple[float, float]],
    prior_alt_pts: list[list[tuple[float, float]]],
    *,
    mean_dup_km: float = 0.08,
    stride: int = 25,
) -> bool:
    """True if *alt_pts* matches the primary or any earlier alternate (forward or reverse)."""
    if len(alt_pts) < 2:
        return True

    if mean_min_distance_to_polyline(alt_pts, primary_pts, stride=stride) <= mean_dup_km:
        return True

    alt_rev = list(reversed(alt_pts))
    if mean_min_distance_to_polyline(alt_rev, primary_pts, stride=stride) <= mean_dup_km:
        return True

    for prev in prior_alt_pts:
        if len(prev) < 2:
            continue
        if mean_min_distance_to_polyline(alt_pts, prev, stride=stride) <= mean_dup_km:
            return True
        if mean_min_distance_to_polyline(alt_rev, prev, stride=stride) <= mean_dup_km:
            return True

    return False
