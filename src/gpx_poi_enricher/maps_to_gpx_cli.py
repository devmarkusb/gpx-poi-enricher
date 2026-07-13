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
import functools
import math
import os
import pathlib
import re
import sys
import time
import unicodedata
from urllib.parse import parse_qs, unquote_plus, urlparse

import gpxpy
import gpxpy.gpx
import requests

try:
    from babel import Locale
except ImportError:  # pragma: no cover - optional dependency in some environments
    Locale = None

USER_AGENT = "gpx-poi-enricher/0.1 (https://github.com/devmarkusb/gpx-poi-enricher)"

OSRM_PROFILES = {"driving": "car", "cycling": "bike", "walking": "foot"}
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
# Public demo; may rate-limit or time out. Override with OSRM_BASE_URL or --osrm-base-url.
OSRM_DEFAULT_BASE = "https://router.project-osrm.org/route/v1"
# Kept as a module attribute so callers can monkey-patch (legacy Android bridge).
OSRM_BASE_URL = OSRM_DEFAULT_BASE

DEFAULT_TRACK_NAME = "Route"
DEFAULT_OUTPUT_STEM = "route"


def shorten_label(label: str) -> str:
    """Return a short city-level name from a potentially verbose address string."""
    parts = [p.strip() for p in label.split(",")]
    for part in parts:
        clean = re.sub(r"^\d[\d\s]*\s+", "", part).strip()
        if clean and not any(c.isdigit() for c in clean):
            return clean
    clean = re.sub(r"^\d[\d\s]*\s+", "", parts[0]).strip()
    return clean or parts[0]


def safe_filename_component(label: str) -> str:
    """Sanitize a string for use as a filename component."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", label).strip(". ")


def is_default_track_name(name: str | None) -> bool:
    text = (name or "").strip()
    return not text or text == DEFAULT_TRACK_NAME


def is_default_output_path(path: str) -> bool:
    if not (path or "").strip():
        return True
    return pathlib.Path(path).stem.casefold() == DEFAULT_OUTPUT_STEM


def route_names_from_waypoints(
    waypoints: list[tuple[float, float, str]],
) -> tuple[str, str, str, str]:
    """Return ``(start_label, finish_label, file_stem, track_name)``."""
    start_label = shorten_label(waypoints[0][2])
    finish_label = shorten_label(waypoints[-1][2])
    file_stem = f"{safe_filename_component(start_label)}-{safe_filename_component(finish_label)}"
    track_name = f"{start_label} – {finish_label}"
    return start_label, finish_label, file_stem, track_name


def apply_route_defaults(
    waypoints: list[tuple[float, float, str]],
    track_name: str,
    output_path: str,
) -> tuple[str, str]:
    """Use start/finish labels for track name and output stem when still at GUI defaults."""
    _, _, file_stem, auto_track = route_names_from_waypoints(waypoints)
    resolved_track = auto_track if is_default_track_name(track_name) else track_name.strip()
    out = pathlib.Path(output_path)
    if is_default_output_path(output_path):
        resolved_output = str(out.parent / f"{file_stem}.gpx")
    else:
        resolved_output = output_path
    return resolved_track, resolved_output


def preview_route_names_from_url(
    url: str,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Parse + geocode a Maps URL; return suggested track/filename labels (no routing)."""
    owns_session = session is None
    if owns_session:
        session = requests.Session()
    try:
        if "goo.gl" in url or "maps.app" in url:
            url = _expand_url(url, session)
        raw = parse_waypoints_from_url(url)
        if len(raw) < 2:
            raise ValueError("Need at least 2 waypoints (origin + destination).")
        waypoints = _resolve_waypoints(raw, session)
        start_label, finish_label, file_stem, track_name = route_names_from_waypoints(waypoints)
        return {
            "track_name": track_name,
            "output_basename": f"{file_stem}.gpx",
            "start": start_label,
            "finish": finish_label,
        }
    finally:
        if owns_session:
            session.close()


def _effective_osrm_base_url(explicit: str | None = None) -> str:
    if explicit is not None:
        return explicit.rstrip("/")
    env = os.environ.get("OSRM_BASE_URL")
    if env:
        return env.rstrip("/")
    return OSRM_BASE_URL.rstrip("/")


# Matches "lat,lon" like "48.8566,2.3522" or "-33.8688,151.2093"
_COORD_RE = re.compile(r"^-?\d+\.?\d*,-?\d+\.?\d*$")
_ADMIN_PREFIX_RE = re.compile(
    r"^(?:province|provinz|provincia|província|prov\.?|region|région|región|county|state)\s+(?:de\s+)?",
    re.IGNORECASE,
)
_FALLBACK_COUNTRY_ALIASES = {
    "allemagne": "Germany",
    "alemania": "Germany",
    "deutschland": "Germany",
    "espagne": "Spain",
    "espana": "Spain",
    "espanha": "Spain",
    "spanien": "Spain",
    "francia": "France",
    "france": "France",
    "frankreich": "France",
    "germany": "Germany",
    "italia": "Italy",
    "italien": "Italy",
    "nederland": "Netherlands",
    "niederlande": "Netherlands",
    "paesi bassi": "Netherlands",
    "paises bajos": "Netherlands",
    "pays bas": "Netherlands",
    "portogallo": "Portugal",
    "portugal": "Portugal",
    "spane": "Spain",
    "spain": "Spain",
}


def _normalize_lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only).strip().casefold()


@functools.lru_cache(maxsize=1)
def _country_aliases() -> dict[str, str]:
    aliases = dict(_FALLBACK_COUNTRY_ALIASES)
    if Locale is None:
        return aliases

    english_territories = Locale.parse("en").territories
    for locale_id in ("en", "de", "es", "ca", "fr", "it", "nl", "pt"):
        for territory_code, territory_name in Locale.parse(locale_id).territories.items():
            if len(territory_code) != 2 or not territory_code.isalpha():
                continue
            english_name = english_territories.get(territory_code)
            if english_name:
                aliases[_normalize_lookup_key(territory_name)] = english_name
    return aliases


def _normalize_country_name(value: str) -> str:
    return _country_aliases().get(_normalize_lookup_key(value), value)


def _is_known_country(value: str) -> bool:
    return _normalize_lookup_key(value) in _country_aliases()


def _looks_like_street_address(value: str) -> bool:
    return bool(re.search(r"\d", value))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def _extract_google_data_coords(url: str) -> list[tuple[float, float]]:
    """Return (lat, lon) pairs embedded in a Google Maps ``/data=`` block."""
    match = re.search(r"/data=([^?#]+)", url)
    if not match:
        return []
    data = match.group(1)
    coords: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()

    def _add(lat_s: str, lon_s: str) -> None:
        lat, lon = float(lat_s), float(lon_s)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            key = (lat, lon)
            if key not in seen:
                seen.add(key)
                coords.append(key)

    # Older / alternate encoding: !2m2!1d{lon}!2d{lat}
    for lon_s, lat_s in re.findall(r"!2m2!1d([\d.-]+)!2d([\d.-]+)", data):
        _add(lat_s, lon_s)
    # Common in maps.app.goo.gl expanded URLs: !8m2!3d{lat}!4d{lon}
    for lat_s, lon_s in re.findall(r"!8m2!3d([\d.-]+)!4d([\d.-]+)", data):
        _add(lat_s, lon_s)
    return coords


def _attach_google_data_coords(waypoints: list[dict], url: str) -> None:
    """Merge Google-resolved coordinates into parsed waypoints when counts match."""
    coords = _extract_google_data_coords(url)
    if len(coords) != len(waypoints):
        return
    for wpt, (lat, lon) in zip(waypoints, coords, strict=True):
        if "coord" not in wpt:
            wpt["coord"] = (lat, lon)


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


def _build_geocode_queries(name: str) -> list[str]:
    """Build a small set of fallback geocoding queries for localized place strings."""
    candidates: list[str] = [name]
    parts = [p.strip() for p in name.split(",") if p.strip()]
    if not parts:
        return candidates

    cleaned_parts = [_ADMIN_PREFIX_RE.sub("", p).strip() for p in parts]
    if cleaned_parts:
        cleaned_parts[-1] = _normalize_country_name(cleaned_parts[-1])
    cleaned = ", ".join(cleaned_parts)
    if cleaned and cleaned != name:
        candidates.append(cleaned)

    if len(cleaned_parts) >= 2:
        last_part = cleaned_parts[-1]
        if _is_known_country(last_part):
            no_country = ", ".join(cleaned_parts[:-1])
            if no_country:
                candidates.append(no_country)
            city_country = f"{cleaned_parts[0]}, {last_part}"
            candidates.append(city_country)
        if not _looks_like_street_address(cleaned_parts[0]):
            candidates.append(cleaned_parts[0])

    # Keep order stable while removing duplicates.
    seen: set[str] = set()
    deduped: list[str] = []
    for cand in candidates:
        if cand not in seen:
            seen.add(cand)
            deduped.append(cand)
    return deduped


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
        _attach_google_data_coords(waypoints, url)
        return waypoints

    # Old-style path: /maps/dir/Part1/Part2/...
    path = parsed.path
    marker = "/maps/dir/"
    if marker not in path:
        raise ValueError(
            f"URL does not look like a Google Maps directions link (no '{marker}'): {url!r}"
        )

    after = path[path.index(marker) + len(marker) :]
    parts = [unquote_plus(p) for p in after.split("/") if p]

    result: list[dict] = []
    for part in parts:
        if part.startswith("@") or part.startswith(
            "data="
        ):  # map anchor / metadata mark end of waypoints
            break
        if _is_coordinate(part):
            result.append({"coord": _parse_coord(part)})
        else:
            result.append({"name": part})
    _attach_google_data_coords(result, url)
    return result


def _pick_best_geocode_result(
    results: list[dict],
    *,
    near: tuple[float, float] | None,
) -> dict:
    if not near or len(results) == 1:
        return results[0]
    near_lat, near_lon = near
    return min(
        results,
        key=lambda row: _haversine_km(near_lat, near_lon, float(row["lat"]), float(row["lon"])),
    )


def _geocode(
    name: str,
    session: requests.Session,
    *,
    near: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Forward-geocode a place name via Nominatim. Returns (lat, lon)."""
    headers = {"User-Agent": USER_AGENT}
    queries = _build_geocode_queries(name)
    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(1.1)  # honour Nominatim 1 req/s policy for retries
        params = {"q": query, "format": "jsonv2", "limit": 5 if near else 1}
        r = session.get(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        results = r.json()
        if results:
            best = _pick_best_geocode_result(results, near=near)
            return float(best["lat"]), float(best["lon"])

    raise ValueError(f"Nominatim could not geocode: {name!r}")


def _resolve_waypoints(
    raw: list[dict], session: requests.Session
) -> list[tuple[float, float, str]]:
    """Resolve each raw waypoint to (lat, lon, label), geocoding names as needed."""
    resolved: list[tuple[float, float, str]] = []
    for i, wpt in enumerate(raw):
        if "coord" in wpt:
            lat, lon = wpt["coord"]
            label = wpt.get("name", f"{lat:.6f},{lon:.6f}")
            resolved.append((lat, lon, label))
        else:
            name = wpt["name"]
            print(f"  geocoding {name!r} ...", file=sys.stderr)
            near = resolved[-1][:2] if resolved else None
            lat, lon = _geocode(name, session, near=near)
            resolved.append((lat, lon, name))
            if i < len(raw) - 1:
                time.sleep(1.1)  # honour Nominatim 1 req/s policy
    return resolved


def _route_osrm(
    waypoints: list[tuple[float, float, str]],
    mode: str,
    session: requests.Session,
    *,
    base_url: str | None = None,
) -> list[tuple[float, float]]:
    """Route between resolved waypoints via OSRM. Returns list of (lat, lon)."""
    osrm_profile = OSRM_PROFILES.get(mode, "car")
    # OSRM expects lon,lat order (GeoJSON)
    coord_str = ";".join(f"{lon},{lat}" for lat, lon, _ in waypoints)
    root = _effective_osrm_base_url(base_url)
    url = f"{root}/{osrm_profile}/{coord_str}"
    params = {"overview": "full", "geometries": "geojson"}
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            r = session.get(url, params=params, headers=headers, timeout=60)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok":
                raise RuntimeError(f"OSRM returned an error: {data.get('message', data)}")
            # GeoJSON coordinates are [lon, lat] — convert to (lat, lon)
            return [(c[1], c[0]) for c in data["routes"][0]["geometry"]["coordinates"]]
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(
                f"OSRM unreachable after retries ({root}): {exc}. "
                "The public demo server is often overloaded; set OSRM_BASE_URL to a "
                "self-hosted OSRM base (…/route/v1) or try again later."
            ) from exc


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


def _write_gpx_segments(
    track_segments: list[list[tuple[float, float]]],
    waypoints: list[tuple[float, float, str]],
    output_path: str,
    track_name: str,
) -> None:
    """Write one GPX track with multiple ``trkseg`` elements (disjoint geometry)."""
    gpx = gpxpy.gpx.GPX()

    for lat, lon, name in waypoints:
        gpx.waypoints.append(gpxpy.gpx.GPXWaypoint(latitude=lat, longitude=lon, name=name))

    track = gpxpy.gpx.GPXTrack(name=track_name)
    gpx.tracks.append(track)
    for seg_pts in track_segments:
        if not seg_pts:
            continue
        segment = gpxpy.gpx.GPXTrackSegment()
        track.segments.append(segment)
        for lat, lon in seg_pts:
            segment.points.append(gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon))

    if not track.segments:
        raise ValueError("track_segments produced no non-empty segments")

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
    ap.add_argument(
        "--osrm-base-url",
        default=None,
        metavar="URL",
        help=(
            "OSRM API root ending in /route/v1 (default: public demo; "
            "overrides OSRM_BASE_URL env if set)"
        ),
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
        track_points = _route_osrm(waypoints, args.mode, session, base_url=args.osrm_base_url)
    except (RuntimeError, requests.RequestException) as exc:
        print(f"Routing error: {exc}", file=sys.stderr)
        if isinstance(exc, requests.ConnectionError | requests.Timeout):
            print(
                "Hint: set OSRM_BASE_URL or pass --osrm-base-url to use your own OSRM server.",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"  {len(track_points)} track point(s) returned.", file=sys.stderr)

    # 5. Write GPX (auto-name from start/finish when still at CLI defaults)
    track_name, output_gpx = apply_route_defaults(waypoints, args.name, args.output_gpx)
    _write_gpx(track_points, waypoints, output_gpx, track_name)
    print(f"Saved: {output_gpx}", file=sys.stderr)


if __name__ == "__main__":
    main()
