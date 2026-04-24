"""Thin bridge between Kotlin and the gpx_poi_enricher Python package.

Called via Chaquopy's Java/Python interop. All file paths are absolute strings
(Kotlin resolves Android SAF URIs to temp-file paths before calling here).
"""

import json
import pathlib
import re
import sys
import threading

import requests

import gpx_poi_enricher.maps_to_gpx_cli as _maps_mod
from gpx_poi_enricher.enricher import enrich_gpx_file
from gpx_poi_enricher.maps_to_gpx_cli import (
    _expand_url,
    _resolve_waypoints,
    _route_osrm,
    _write_gpx,
    parse_waypoints_from_url,
)
from gpx_poi_enricher.profiles import load_all_profiles
from gpx_poi_enricher.split_cli import add_split_waypoints

# Use HTTPS for OSRM so Android cleartext-traffic policy is satisfied
_maps_mod.OSRM_BASE_URL = "https://router.project-osrm.org/route/v1"

_cancel_event = threading.Event()


class _LogStream:
    """Redirect stderr lines to a Kotlin LogCallback object."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, callback):
        self._cb = callback
        self._buf = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._cb.onLog(line.strip())

    def flush(self):
        if self._buf.strip():
            self._cb.onLog(self._buf.strip())
            self._buf = ""

    def fileno(self):
        raise OSError("not a real file")


def list_profiles(profiles_dir: str) -> str:
    profiles = load_all_profiles(pathlib.Path(profiles_dir))
    return json.dumps([{"id": p.id, "description": p.description} for p in profiles.values()])


def enrich(
    input_path: str,
    output_path: str,
    profile_id: str,
    profiles_dir: str,
    max_km,  # float or None (passed as Java Double/null)
    sample_km,
    log_callback,
) -> int:
    _cancel_event.clear()
    kwargs = {"cancel_event": _cancel_event}
    if max_km is not None:
        kwargs["max_km"] = float(max_km)
    if sample_km is not None:
        kwargs["sample_km"] = float(sample_km)

    old = sys.stderr
    sys.stderr = _LogStream(log_callback)
    try:
        pois = enrich_gpx_file(
            input_path,
            output_path,
            profile_id,
            profiles_dir=pathlib.Path(profiles_dir),
            **kwargs,
        )
        return len(pois)
    finally:
        sys.stderr = old


def cancel():
    _cancel_event.set()


def split(input_path: str, output_path: str, segments: int, log_callback) -> None:
    old = sys.stderr
    sys.stderr = _LogStream(log_callback)
    try:
        add_split_waypoints(input_path, output_path, int(segments))
    finally:
        sys.stderr = old


def maps_to_gpx(url: str, output_path: str, mode: str, track_name: str, log_callback) -> None:
    old = sys.stderr
    sys.stderr = _LogStream(log_callback)
    try:
        session = requests.Session()
        if "goo.gl" in url or "maps.app" in url:
            sys.stderr.write("Expanding short URL...\n")
            url = _expand_url(url, session)
        raw = parse_waypoints_from_url(url)
        sys.stderr.write(f"Found {len(raw)} waypoints.\n")
        waypoints = _resolve_waypoints(raw, session)
        sys.stderr.write(f"Routing via OSRM ({mode})...\n")
        track_points = _route_osrm(waypoints, mode, session)
        sys.stderr.write(f"  {len(track_points)} track points returned.\n")
        _write_gpx(track_points, waypoints, output_path, track_name)
    finally:
        sys.stderr = old


# ── Easy mode helpers ─────────────────────────────────────────────────────────


def _shorten_label(label: str) -> str:
    """Extract a short city-level name from a verbose address string."""
    parts = [p.strip() for p in label.split(",")]
    for part in parts:
        clean = re.sub(r"^\d[\d\s]*\s+", "", part).strip()
        if clean and not any(c.isdigit() for c in clean):
            return clean
    clean = re.sub(r"^\d[\d\s]*\s+", "", parts[0]).strip()
    return clean or parts[0]


def _safe_filename(label: str) -> str:
    """Sanitize a string for use as a filename component."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", label).strip(". ")


def easy_generate(
    url: str,
    profile_id: str,
    profiles_dir: str,
    output_dir: str,
    log_callback,
) -> str:
    """Combined Maps→GPX + POI enrichment pipeline for Easy mode.

    Returns a JSON string:
        {track_path, poi_path, start, finish, poi_count, track_reused}
    or {cancelled: true} if cancelled before completion.
    """
    _cancel_event.clear()
    old = sys.stderr
    sys.stderr = _LogStream(log_callback)
    try:
        session = requests.Session()

        # Step 1: Expand short URLs
        if "goo.gl" in url or "maps.app" in url:
            sys.stderr.write("Expanding short URL…\n")
            url = _expand_url(url, session)
            sys.stderr.write(f"  → {url}\n")

        # Step 2: Parse waypoints
        raw = parse_waypoints_from_url(url)
        if len(raw) < 2:
            raise ValueError("Need at least 2 waypoints (origin + destination).")
        sys.stderr.write(f"Found {len(raw)} waypoint(s) in URL.\n")

        # Step 3: Resolve / geocode
        sys.stderr.write("Resolving waypoints via Nominatim…\n")
        waypoints = _resolve_waypoints(raw, session)
        for lat, lon, label in waypoints:
            sys.stderr.write(f"  {label} → {lat:.5f}, {lon:.5f}\n")

        # Step 4: Derive filenames from shortened start/finish labels
        start_label = _shorten_label(waypoints[0][2])
        finish_label = _shorten_label(waypoints[-1][2])
        base_name = f"{_safe_filename(start_label)}-{_safe_filename(finish_label)}"
        out_dir = pathlib.Path(output_dir)
        track_path = str(out_dir / f"{base_name}.gpx")
        poi_path = str(out_dir / f"{base_name}-{profile_id}.gpx")
        track_name = f"{start_label} – {finish_label}"

        # Step 5: Create track GPX (reuse if already exists)
        track_reused = False
        if pathlib.Path(track_path).exists():
            sys.stderr.write(f"Track already exists, reusing: {track_path}\n")
            track_reused = True
        else:
            sys.stderr.write("Routing via OSRM (driving)…\n")
            track_points = _route_osrm(waypoints, "driving", session)
            sys.stderr.write(f"  {len(track_points)} track point(s) returned.\n")
            _write_gpx(track_points, waypoints, track_path, track_name)
            sys.stderr.write(f"Track saved: {track_path}\n")

        if _cancel_event.is_set():
            sys.stderr.write("Cancelled.\n")
            return json.dumps({"cancelled": True})

        # Step 6: Enrich with selected profile
        sys.stderr.write(f"Enriching with '{profile_id}' profile…\n")
        items = enrich_gpx_file(
            track_path,
            poi_path,
            profile_id,
            profiles_dir=pathlib.Path(profiles_dir),
            cancel_event=_cancel_event,
            progress_interval=5.0,
        )
        sys.stderr.write(f"POIs saved: {poi_path}  ({len(items)} POI(s))\n")

        return json.dumps(
            {
                "track_path": track_path,
                "poi_path": poi_path,
                "start": start_label,
                "finish": finish_label,
                "poi_count": len(items),
                "track_reused": track_reused,
            }
        )
    finally:
        sys.stderr.flush()
        sys.stderr = old
