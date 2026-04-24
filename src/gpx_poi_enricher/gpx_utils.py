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
        pts.append((float(trkpt.attrib["lat"]), float(trkpt.attrib["lon"])))

    if not pts:
        raise ValueError(f"No track points found in GPX file: {path}")

    return tree, root, pts


def sample_track_by_distance(
    points: list[tuple[float, float]],
    spacing_km: float,
) -> list[tuple[float, float]]:
    """Return a sub-sampled list of track points spaced at most *spacing_km* apart.

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
    """Return the approximate minimum distance in km from (lat, lon) to any track point.

    Uses a two-pass coarse/fine approach for performance on long tracks.
    """
    best_idx = 0
    best = float("inf")

    for i in range(0, len(track_points), coarse_step):
        d = haversine_km(lat, lon, track_points[i][0], track_points[i][1])
        if d < best:
            best = d
            best_idx = i

    start = max(0, best_idx - 5 * coarse_step)
    end = min(len(track_points), best_idx + 5 * coarse_step + 1)

    for i in range(start, end):
        d = haversine_km(lat, lon, track_points[i][0], track_points[i][1])
        if d < best:
            best = d

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
        ET.SubElement(wpt, f"{{{GPX_NS}}}type").text = type_label
        ET.SubElement(
            wpt, f"{{{GPX_NS}}}desc"
        ).text = f"approx {item['distance_km']:.1f} km from track"
        ET.SubElement(wpt, f"{{{GPX_NS}}}sym").text = symbol
        root.append(wpt)
