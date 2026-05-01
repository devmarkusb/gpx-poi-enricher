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

from gpx_poi_enricher.enricher import enrich_gpx_file
from gpx_poi_enricher.maps_to_gpx_cli import (
    _expand_url,
    _resolve_waypoints,
    _route_osrm,
    _write_gpx,
    _write_gpx_segments,
    parse_waypoints_from_url,
)
from gpx_poi_enricher.profiles import load_all_profiles
from gpx_poi_enricher.route_detours import (
    alternate_is_reverse_itinerary,
    alternate_redundant_with_prior,
    extract_detour_segments,
)
from gpx_poi_enricher.split_cli import (
    add_split_waypoints,
    is_detour_track_path,
    milestone_sidecar_path,
)

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
    primary_url: str,
    extras_multiline: str,
    profile_id: str,
    profiles_dir: str,
    output_dir: str,
    log_callback,
    split_segments: int = 0,
) -> str:
    """Combined Maps→GPX + POI enrichment pipeline for Easy mode (primary + optional alternates).

    *extras_multiline*: optional extra Google Maps URLs, one per line (same semantics as desktop
    Easy tab). Alternate routes yield ``-full-NN.gpx`` files; deviations vs primary yield
    ``-detour-NN.gpx``, each detour enriched for POIs like the primary track.

    *split_segments*: if >= 2, writes a waypoint-only companion ``{stem}-milestones.gpx`` next to
    each full-route track (primary and ``-full-NN`` alternates); detour fragments are skipped.
    Track GPX files are unchanged (0 = disabled).

    Returns a JSON string:
        {
          track_path, poi_path, start, finish, poi_count, track_reused,
          alternate_full_paths: [...],
          detour_results: [{"track_path", "poi_path", "poi_count"}, ...],
        }
    or ``{cancelled: true}`` if cancelled before completion.
    """
    _cancel_event.clear()
    old = sys.stderr
    sys.stderr = _LogStream(log_callback)
    try:
        extra_lines = [ln.strip() for ln in (extras_multiline or "").splitlines() if ln.strip()]
        urls = [primary_url.strip(), *extra_lines]
        session = requests.Session()

        routes: list[tuple[list[tuple[float, float, str]], list[tuple[float, float]]]] = []
        for idx, raw_url in enumerate(urls):
            if _cancel_event.is_set():
                sys.stderr.write("Cancelled.\n")
                return json.dumps({"cancelled": True})
            url = raw_url
            sys.stderr.write(f"Route {idx + 1}/{len(urls)}: parsing…\n")
            if "goo.gl" in url or "maps.app" in url:
                sys.stderr.write("Expanding short URL…\n")
                url = _expand_url(url, session)
                sys.stderr.write(f"  → {url}\n")

            raw = parse_waypoints_from_url(url)
            if len(raw) < 2:
                raise ValueError("Each URL needs at least 2 waypoints (origin + destination).")
            sys.stderr.write(f"Found {len(raw)} waypoint(s) in URL.\n")

            sys.stderr.write("Resolving waypoints via Nominatim…\n")
            waypoints = _resolve_waypoints(raw, session)
            for lat, lon, label in waypoints:
                sys.stderr.write(f"  {label} → {lat:.5f}, {lon:.5f}\n")

            sys.stderr.write("Routing via OSRM (driving)…\n")
            track_points = _route_osrm(waypoints, "driving", session)
            sys.stderr.write(f"  {len(track_points)} track point(s) returned.\n")
            routes.append((waypoints, track_points))

        primary_wp, primary_pts = routes[0]
        start_label = _shorten_label(primary_wp[0][2])
        finish_label = _shorten_label(primary_wp[-1][2])
        base_name = f"{_safe_filename(start_label)}-{_safe_filename(finish_label)}"
        out_dir = pathlib.Path(output_dir)
        track_path = str(out_dir / f"{base_name}.gpx")
        poi_path = str(out_dir / f"{base_name}-{profile_id}.gpx")
        track_name = f"{start_label} – {finish_label}"

        track_reused = False
        if pathlib.Path(track_path).exists():
            sys.stderr.write(f"Primary track already exists, reusing: {track_path}\n")
            track_reused = True
        else:
            _write_gpx(primary_pts, primary_wp, track_path, track_name)
            sys.stderr.write(f"Primary track saved: {track_path}\n")

        tracks_to_enrich: list[str] = [track_path]
        alternate_full_paths: list[str] = []

        if len(routes) > 1:
            for j, (wpts, pts) in enumerate(routes[1:], start=2):
                alt_path = out_dir / f"{base_name}-full-{j:02d}.gpx"
                alt_track = f"{_shorten_label(wpts[0][2])} – {_shorten_label(wpts[-1][2])}"
                alt_path_str = str(alt_path)
                alternate_full_paths.append(alt_path_str)
                if alt_path.exists():
                    sys.stderr.write(f"Alternate route GPX already exists, reusing: {alt_path}\n")
                else:
                    _write_gpx(pts, wpts, alt_path_str, alt_track)
                    sys.stderr.write(f"Alternate route GPX: {alt_path}\n")

            prior_alt_pts: list[list[tuple[float, float]]] = []
            for j, (_, alt_pts) in enumerate(routes[1:], start=2):
                if alternate_redundant_with_prior(alt_pts, primary_pts, prior_alt_pts):
                    sys.stderr.write(
                        f"Alternate {j}: skipping detour enrichment (same as primary "
                        "or earlier alternate, including reverse).\n"
                    )
                    prior_alt_pts.append(alt_pts)
                    continue
                if alternate_is_reverse_itinerary(primary_pts, alt_pts):
                    sys.stderr.write(
                        f"Alternate {j}: skipping detour enrichment (reverse itinerary "
                        "B→A vs primary A→B).\n"
                    )
                    prior_alt_pts.append(alt_pts)
                    continue
                prior_alt_pts.append(alt_pts)
                detour_segs = extract_detour_segments(alt_pts, primary_pts)
                if not detour_segs:
                    sys.stderr.write(
                        f"Alternate {j}: no detour track (on primary within threshold).\n"
                    )
                    continue
                det_path = out_dir / f"{base_name}-detour-{j:02d}.gpx"
                det_str = str(det_path)
                if det_path.exists():
                    sys.stderr.write(f"Detour GPX already exists, reusing: {det_path}\n")
                else:
                    _write_gpx_segments(detour_segs, [], det_str, f"Detour (alternate {j})")
                    n_pts = sum(len(s) for s in detour_segs)
                    sys.stderr.write(
                        f"Detour GPX: {det_path} ({len(detour_segs)} segments, {n_pts} points)\n"
                    )
                tracks_to_enrich.append(det_str)

        milestone_paths: list[str] = []
        ss = int(split_segments)
        if ss >= 2:
            for tpath in tracks_to_enrich:
                if is_detour_track_path(tpath):
                    continue
                mpath = milestone_sidecar_path(tpath)
                add_split_waypoints(tpath, mpath, ss)
                milestone_paths.append(mpath)
                sys.stderr.write(f"Wrote milestone-only GPX ({ss} wpt): {mpath}\n")

        if _cancel_event.is_set():
            sys.stderr.write("Cancelled.\n")
            return json.dumps({"cancelled": True})

        primary_stem = pathlib.Path(track_path).stem
        detour_results: list[dict] = []
        primary_poi_count = 0

        for tpath in tracks_to_enrich:
            if _cancel_event.is_set():
                sys.stderr.write("Cancelled.\n")
                return json.dumps({"cancelled": True})
            stem = pathlib.Path(tpath).stem
            outp = str(out_dir / f"{stem}-{profile_id}.gpx")
            sys.stderr.write(f"Enriching: {tpath} → {outp}\n")
            early_cancel = None if stem == primary_stem else False
            items = enrich_gpx_file(
                tpath,
                outp,
                profile_id,
                profiles_dir=pathlib.Path(profiles_dir),
                early_cancel_if_no_pois=early_cancel,
                cancel_event=_cancel_event,
                progress_interval=5.0,
            )
            n = len(items)
            sys.stderr.write(f"POIs saved: {outp}  ({n} POI(s))\n")
            if stem == primary_stem:
                primary_poi_count = n
            elif "-detour-" in stem:
                detour_results.append({"track_path": tpath, "poi_path": outp, "poi_count": n})

        return json.dumps(
            {
                "track_path": track_path,
                "poi_path": poi_path,
                "start": start_label,
                "finish": finish_label,
                "poi_count": primary_poi_count,
                "track_reused": track_reused,
                "alternate_full_paths": alternate_full_paths,
                "detour_results": detour_results,
                "milestone_paths": milestone_paths,
            }
        )
    finally:
        sys.stderr.flush()
        sys.stderr = old
