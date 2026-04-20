"""CLI: convert a Google Maps directions URL to a GPX file.

Handles:
  - Short URLs (maps.app.goo.gl/...) — followed via HTTP redirect
  - Path-style: https://www.google.com/maps/dir/Paris/Lyon/Marseille/
  - Query-style: https://www.google.com/maps/dir/?api=1&origin=...&destination=...
  - Coordinate waypoints (no geocoding needed) and place-name waypoints (Nominatim)
  - Routing via the public OSRM API (no API key required)
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import parse_qs, unquote_plus, urlparse

import gpxpy
import gpxpy.gpx
import requests

USER_AGENT = "gpx-poi-enricher/0.1 (https://github.com/devmarkusb/gpx-poi-enricher)"

OSRM_PROFILES = {"driving": "car", "cycling": "bike", "walking": "foot"}
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1"

# Matches "lat,lon" like "48.8566,2.3522" or "-33.8688,151.2093"
_COORD_RE = re.compile(r"^-?\d+\.?\d*,-?\d+\.?\d*$")


def _expand_url(url: str, session: requests.Session) -> str:
    """Follow redirects and return the final URL (used for short URLs)."""
    r = session.head(url, allow_redirects=True, timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.url


def _is_coordinate(s: str) -> bool:
    if not _COORD_RE.match(s):
        return False
    lat, lon = s.split(",")
    return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180


def _parse_coord(s: str) -> tuple[float, float]:
    lat, lon = s.split(",")
    return float(lat), float(lon)


def parse_waypoints_from_url(url: str) -> list[dict]:
    """Extract raw waypoints from a Google Maps directions URL.

    Returns a list of dicts, each either ``{'coord': (lat, lon)}`` or ``{'name': str}``.
    Raises ``ValueError`` if the URL cannot be parsed as a directions link.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    # New-style: ?api=1&origin=...&destination=...&waypoints=A|B
    if "origin" in qs or "destination" in qs:
        waypoints: list[dict] = []

        def _add(raw: str) -> None:
            raw = raw.strip().removeprefix("via:")
            if not raw:
                return
            if _is_coordinate(raw):
                waypoints.append({"coord": _parse_coord(raw)})
            else:
                waypoints.append({"name": raw})

        if "origin" in qs:
            _add(qs["origin"][0])
        if "waypoints" in qs:
            for part in qs["waypoints"][0].split("|"):
                _add(part)
        if "destination" in qs:
            _add(qs["destination"][0])
        return waypoints

    # Old-style path: /maps/dir/Part1/Part2/...
    path = parsed.path
    marker = "/maps/dir/"
    if marker not in path:
        raise ValueError(
            f"URL does not look like a Google Maps directions link (no '{marker}'): {url!r}"
        )

    after = path[path.index(marker) + len(marker):]
    parts = [unquote_plus(p) for p in after.split("/") if p]

    result: list[dict] = []
    for part in parts:
        if part.startswith("@"):  # map view anchor, e.g. @48.8566,2.3522,10z
            continue
        if _is_coordinate(part):
            result.append({"coord": _parse_coord(part)})
        else:
            result.append({"name": part})
    return result


def _geocode(name: str, session: requests.Session) -> tuple[float, float]:
    """Forward-geocode a place name via Nominatim. Returns (lat, lon)."""
    params = {"q": name, "format": "jsonv2", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    r = session.get(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Nominatim could not geocode: {name!r}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def _resolve_waypoints(
    raw: list[dict], session: requests.Session
) -> list[tuple[float, float, str]]:
    """Resolve each raw waypoint to (lat, lon, label), geocoding names as needed."""
    resolved: list[tuple[float, float, str]] = []
    for i, wpt in enumerate(raw):
        if "coord" in wpt:
            lat, lon = wpt["coord"]
            resolved.append((lat, lon, f"{lat:.6f},{lon:.6f}"))
        else:
            name = wpt["name"]
            print(f"  geocoding {name!r} ...", file=sys.stderr)
            lat, lon = _geocode(name, session)
            resolved.append((lat, lon, name))
            if i < len(raw) - 1:
                time.sleep(1.1)  # honour Nominatim 1 req/s policy
    return resolved


def _route_osrm(
    waypoints: list[tuple[float, float, str]],
    mode: str,
    session: requests.Session,
) -> list[tuple[float, float]]:
    """Route between resolved waypoints via OSRM. Returns list of (lat, lon)."""
    osrm_profile = OSRM_PROFILES.get(mode, "car")
    # OSRM expects lon,lat order (GeoJSON)
    coord_str = ";".join(f"{lon},{lat}" for lat, lon, _ in waypoints)
    url = f"{OSRM_BASE_URL}/{osrm_profile}/{coord_str}"
    params = {"overview": "full", "geometries": "geojson"}
    headers = {"User-Agent": USER_AGENT}
    r = session.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM returned an error: {data.get('message', data)}")
    # GeoJSON coordinates are [lon, lat] — convert to (lat, lon)
    return [(c[1], c[0]) for c in data["routes"][0]["geometry"]["coordinates"]]


def _write_gpx(
    track_points: list[tuple[float, float]],
    waypoints: list[tuple[float, float, str]],
    output_path: str,
    track_name: str,
) -> None:
    gpx = gpxpy.gpx.GPX()

    for lat, lon, name in waypoints:
        gpx.waypoints.append(gpxpy.gpx.GPXWaypoint(latitude=lat, longitude=lon, name=name))

    track = gpxpy.gpx.GPXTrack(name=track_name)
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)
    for lat, lon in track_points:
        segment.points.append(gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(gpx.to_xml())


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="maps-to-gpx",
        description=(
            "Convert a Google Maps directions URL to a GPX file.\n\n"
            "Examples:\n"
            '  maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Marseille/" route.gpx\n'
            '  maps-to-gpx "https://maps.app.goo.gl/ABC123" route.gpx --mode cycling\n'
            '  maps-to-gpx "https://www.google.com/maps/dir/?api=1&origin=Paris&'
            'destination=Barcelona&waypoints=Lyon" route.gpx --name "Spain trip"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("url", help="Google Maps directions URL (full or short maps.app.goo.gl link)")
    ap.add_argument("output_gpx", help="Output GPX file path")
    ap.add_argument(
        "--mode",
        choices=["driving", "cycling", "walking"],
        default="driving",
        help="Transport mode for routing (default: driving)",
    )
    ap.add_argument(
        "--name",
        default="Route",
        help="Track name written into the GPX file (default: Route)",
    )
    args = ap.parse_args()

    session = requests.Session()

    # 1. Expand short URLs
    url = args.url
    if "goo.gl" in url or "maps.app" in url:
        print("Expanding short URL...", file=sys.stderr)
        try:
            url = _expand_url(url, session)
        except requests.RequestException as exc:
            print(f"Error expanding URL: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"  -> {url}", file=sys.stderr)

    # 2. Parse waypoints from URL
    try:
        raw = parse_waypoints_from_url(url)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if len(raw) < 2:
        print("Error: need at least an origin and a destination (2 waypoints).", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(raw)} waypoint(s) in URL.", file=sys.stderr)

    # 3. Resolve / geocode
    print("Resolving waypoints...", file=sys.stderr)
    try:
        waypoints = _resolve_waypoints(raw, session)
    except (ValueError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    for lat, lon, label in waypoints:
        print(f"  {label:<40}  {lat:.5f}, {lon:.5f}", file=sys.stderr)

    # 4. Route
    print(f"Routing via OSRM ({args.mode})...", file=sys.stderr)
    try:
        track_points = _route_osrm(waypoints, args.mode, session)
    except (RuntimeError, requests.RequestException) as exc:
        print(f"Routing error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(track_points)} track point(s) returned.", file=sys.stderr)

    # 5. Write GPX
    _write_gpx(track_points, waypoints, args.output_gpx, args.name)
    print(f"Saved: {args.output_gpx}", file=sys.stderr)


if __name__ == "__main__":
    main()
