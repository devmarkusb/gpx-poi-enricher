"""GPX file reading and writing utilities."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

GPX_NS = "http://www.topografix.com/GPX/1/1"
_NS = {"gpx": GPX_NS}
ET.register_namespace("", GPX_NS)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two lat/lon points."""
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    a = max(0.0, min(1.0, a))
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gpx_trackpoints(
    path: str,
) -> tuple[ET.ElementTree, ET.Element, list[tuple[float, float]]]:
    """Parse a GPX file and return (tree, root, list-of-(lat, lon) track points).

    Raises ``ValueError`` if no track points are found.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    pts: list[tuple[float, float]] = []
    for trkpt in root.findall(".//gpx:trkpt", _NS):
        lat, lon = float(trkpt.attrib["lat"]), float(trkpt.attrib["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid GPX coordinates: latitude/longitude outside valid ranges.")
        pts.append((lat, lon))

    if not pts:
        raise ValueError(f"No track points found in GPX file: {path}")

    return tree, root, pts


def sample_track_by_distance(
    points: list[tuple[float, float]],
    spacing_km: float,
) -> list[tuple[float, float]]:
    """Keep the first vertex after each *spacing_km* of accumulated track distance.

    The first and last original points are always included.
    """
    if not points:
        return []

    sampled = [points[0]]
    dist_since = 0.0

    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        dist_since += haversine_km(a[0], a[1], b[0], b[1])
        if dist_since >= spacing_km:
            sampled.append(b)
            dist_since = 0.0

    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    return sampled


def min_distance_to_track_km(
    lat: float,
    lon: float,
    track_points: list[tuple[float, float]],
    coarse_step: int = 30,
) -> float:
    """Return the minimum distance in km from (lat, lon) to any track vertex.

    ``coarse_step`` is retained for caller compatibility. A local window around a
    coarse match is insufficient on looping tracks, so every vertex is considered.
    """
    best = float("inf")
    for point_lat, point_lon in track_points:
        # Meridional separation is a lower bound on great-circle distance.
        if abs(lat - point_lat) * (math.pi * 6371.0088 / 180) > best:
            continue
        d = haversine_km(lat, lon, point_lat, point_lon)
        if d < best:
            best = d
            if best == 0:
                break

    return best


def _point_to_segment_distance_planar_km(
    lat: float,
    lon: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Shortest distance from *lat*, *lon* to the segment *(lat1,lon1)-(lat2,lon2)*.

    Uses a local tangent-plane approximation (adequate for typical OSRM segment lengths).
    """
    lat0 = (lat1 + lat2 + lat) / 3.0
    cos_lat = math.cos(math.radians(lat0))
    km_lon = 111.320 * cos_lat
    km_lat = 111.132

    lon_offset = (lon - lon1 + 180) % 360 - 180
    lon_span = (lon2 - lon1 + 180) % 360 - 180
    px = lon_offset * km_lon
    py = (lat - lat1) * km_lat
    vx = lon_span * km_lon
    vy = (lat2 - lat1) * km_lat
    seg_len_sq = vx * vx + vy * vy
    if seg_len_sq < 1e-24:
        return haversine_km(lat, lon, lat1, lon1)

    t = max(0.0, min(1.0, (px * vx + py * vy) / seg_len_sq))
    proj_lat = lat1 + t * (lat2 - lat1)
    proj_lon = (lon1 + t * lon_span + 180) % 360 - 180
    return haversine_km(lat, lon, proj_lat, proj_lon)


def min_distance_to_polyline_segments_km(
    lat: float,
    lon: float,
    track_points: list[tuple[float, float]],
    *,
    coarse_step: int = 25,
    segment_window: int = 120,
) -> float:
    """Minimum great-circle distance from *(lat, lon)* to the polyline through *track_points*.

    Distance is measured to **segments** between consecutive vertices, not only to vertices.
    This avoids false \"far\" classifications when the query point lies beside a long straight
    (e.g. opposite carriageway) while vertices sit only on one side.

    Every segment is considered, with conservative latitude/longitude bounds to
    skip segments that cannot improve the result. Local windows can miss a remote
    part of a looping route. The tuning parameters remain for caller compatibility.
    """
    if not track_points:
        return float("inf")
    best = haversine_km(lat, lon, *track_points[0])
    max_lat = max(abs(lat), max(abs(pt[0]) for pt in track_points))
    # A spherical longitude-distance lower bound: sin(x) >= 2*x/pi for 0..pi/2.
    lon_bound_scale = (2 / math.pi) * 111.1950802335329 * math.cos(math.radians(max_lat))
    for (lat1, lon1), (lat2, lon2) in zip(track_points, track_points[1:]):
        if best == 0:
            break
        lat_gap = max(min(lat1, lat2) - lat, lat - max(lat1, lat2), 0.0)
        if lat_gap * 111.1950802335329 > best:
            continue
        span = (lon2 - lon1 + 180) % 360 - 180
        offset = (lon - lon1 + 180) % 360 - 180
        lo, hi = min(0.0, span), max(0.0, span)
        if offset < lo:
            lon_gap = min(lo - offset, offset + 360 - hi)
        elif offset > hi:
            lon_gap = min(offset - hi, lo + 360 - offset)
        else:
            lon_gap = 0.0
        if lon_gap * lon_bound_scale > best:
            continue
        best = min(best, _point_to_segment_distance_planar_km(lat, lon, lat1, lon1, lat2, lon2))
    return best


def remove_tracks_and_routes(root: ET.Element) -> None:
    """Remove all ``<trk>`` and ``<rte>`` elements from the GPX root in-place."""
    trk_tag = f"{{{GPX_NS}}}trk"
    rte_tag = f"{{{GPX_NS}}}rte"
    for child in list(root):
        if child.tag in (trk_tag, rte_tag):
            root.remove(child)


def add_waypoints_to_gpx(
    root: ET.Element,
    items: list[dict],
    symbol: str,
    type_label: str,
) -> None:
    """Append POI waypoints to a GPX root element.

    Args:
        root: The GPX ``<gpx>`` element to append ``<wpt>`` children to.
        items: List of dicts with keys ``lat``, ``lon``, ``name``, ``kind``, ``distance_km``.
        symbol: Garmin/GPX symbol name (e.g. ``"Campground"``).
        type_label: Human-readable type string written to ``<type>``.
    """
    for item in items:
        wpt = ET.Element(
            f"{{{GPX_NS}}}wpt",
            lat=f"{item['lat']:.6f}",
            lon=f"{item['lon']:.6f}",
        )
        ET.SubElement(wpt, f"{{{GPX_NS}}}name").text = item["name"]
        ET.SubElement(
            wpt, f"{{{GPX_NS}}}desc"
        ).text = f"approx {item['distance_km']:.1f} km from track"
        ET.SubElement(wpt, f"{{{GPX_NS}}}sym").text = symbol
        ET.SubElement(wpt, f"{{{GPX_NS}}}type").text = type_label
        # GPX requires waypoints before routes, tracks and root extensions.
        insert_at = next(
            (
                i
                for i, child in enumerate(root)
                if child.tag in {f"{{{GPX_NS}}}rte", f"{{{GPX_NS}}}trk", f"{{{GPX_NS}}}extensions"}
            ),
            len(root),
        )
        root.insert(insert_at, wpt)
