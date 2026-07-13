"""Thin bridge between Kotlin and the gpx_poi_enricher Python package.

Called via Chaquopy's Java/Python interop. All file paths are absolute strings
(Kotlin resolves Android SAF URIs to temp-file paths before calling here).
"""

import json
import pathlib
import sys
import threading

import requests

from gpx_poi_enricher.enricher import EnrichInterrupted, enrich_gpx_file, enrich_tracks_to_poi_gpx
from gpx_poi_enricher.maps_to_gpx_cli import (
    _expand_url,
    _resolve_waypoints,
    _route_osrm,
    _write_gpx,
    _write_gpx_segments,
    apply_route_defaults,
    parse_waypoints_from_url,
    preview_route_names_from_url,
    route_names_from_waypoints,
    shorten_label,
)
from gpx_poi_enricher.poi_catalog import catalog_to_json, save_catalog_entry
from gpx_poi_enricher.profiles import (
    delete_user_profile,
    dump_profile_yaml,
    load_all_profiles_with_sources,
    load_profile,
    profile_from_json_text,
    profile_from_yaml_text,
    profile_to_mapping,
    save_profile,
    template_profile,
)
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

# Serialize stderr redirection: concurrent Chaquopy calls (e.g. easy_generate + enrich) can
# interleave at the GIL and corrupt sys.stderr if each does old=sys.stderr; sys.stderr=... .
_stderr_lock = threading.Lock()


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
    meta = load_all_profiles_with_sources(pathlib.Path(profiles_dir))
    rows = [
        {"id": pid, "description": prof.description, "source": src}
        for pid, (prof, src) in meta.items()
    ]
    rows.sort(key=lambda r: (r["source"] != "user", r["description"].lower()))
    return json.dumps(rows)


def get_profile_json(profiles_dir: str, profile_id: str) -> str:
    p = load_profile(profile_id.strip().lower(), pathlib.Path(profiles_dir))
    return json.dumps(profile_to_mapping(p), indent=2)


def save_profile_json(profiles_dir: str, json_payload: str) -> str:
    p = profile_from_json_text(json_payload)
    path = save_profile(p, pathlib.Path(profiles_dir))
    return str(path)


def save_profile_yaml(profiles_dir: str, yaml_payload: str) -> str:
    p = profile_from_yaml_text(yaml_payload)
    path = save_profile(p, pathlib.Path(profiles_dir))
    return str(path)


def export_profile_yaml(profiles_dir: str, profile_id: str) -> str:
    p = load_profile(profile_id.strip().lower(), pathlib.Path(profiles_dir))
    return dump_profile_yaml(p)


def get_profile_yaml(profiles_dir: str, profile_id: str) -> str:
    p = load_profile(profile_id.strip().lower(), pathlib.Path(profiles_dir))
    return dump_profile_yaml(p)


def new_profile_template_yaml() -> str:
    return dump_profile_yaml(template_profile())


def delete_profile(profiles_dir: str, profile_id: str) -> str:
    ok = delete_user_profile(profile_id.strip().lower(), pathlib.Path(profiles_dir))
    return json.dumps({"deleted": ok})


def list_catalog() -> str:
    return catalog_to_json()


def add_profile_from_catalog(profiles_dir: str, entry_id: str) -> str:
    profile = save_catalog_entry(entry_id.strip().lower(), pathlib.Path(profiles_dir))
    return json.dumps({"id": profile.id, "description": profile.description})


def enrich(
    input_path: str,
    output_path: str,
    profile_id: str,
    profiles_dir: str,
    max_km,  # float or None (passed as Java Double/null)
    sample_km,
    log_callback,
    resume: bool = False,
) -> str:
    _cancel_event.clear()
    kwargs = {"cancel_event": _cancel_event}
    if max_km is not None:
        kwargs["max_km"] = float(max_km)
    if sample_km is not None:
        kwargs["sample_km"] = float(sample_km)

    with _stderr_lock:
        old = sys.stderr
        sys.stderr = _LogStream(log_callback)
        try:
            pois = enrich_gpx_file(
                input_path,
                output_path,
                profile_id,
                profiles_dir=pathlib.Path(profiles_dir),
                checkpoint_each_batch=True,
                resume=bool(resume),
                **kwargs,
            )
            return json.dumps({"ok": True, "poi_count": len(pois)})
        except EnrichInterrupted as exc:
            return json.dumps(
                {
                    "interrupted": True,
                    "message": str(exc),
                    "input_path": input_path,
                    "output_path": output_path,
                    "profile_id": profile_id,
                }
            )
        finally:
            sys.stderr.flush()
            sys.stderr = old


def cancel():
    _cancel_event.set()


def split(input_path: str, output_path: str, segments: int, log_callback) -> None:
    with _stderr_lock:
        old = sys.stderr
        sys.stderr = _LogStream(log_callback)
        try:
            add_split_waypoints(input_path, output_path, int(segments))
        finally:
            sys.stderr.flush()
            sys.stderr = old


def maps_to_gpx(url: str, output_path: str, mode: str, track_name: str, log_callback) -> str:
    with _stderr_lock:
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
            track_name, output_path = apply_route_defaults(waypoints, track_name, output_path)
            sys.stderr.write(f"Routing via OSRM ({mode})...\n")
            track_points = _route_osrm(waypoints, mode, session)
            sys.stderr.write(f"  {len(track_points)} track points returned.\n")
            _write_gpx(track_points, waypoints, output_path, track_name)
            _, _, file_stem, _ = route_names_from_waypoints(waypoints)
            return json.dumps(
                {
                    "track_name": track_name,
                    "output_basename": f"{file_stem}.gpx",
                }
            )
        finally:
            sys.stderr.flush()
            sys.stderr = old


def preview_route_names(url: str, log_callback) -> str:
    """Parse + geocode a Maps URL and return suggested track/filename labels (no routing)."""
    with _stderr_lock:
        old = sys.stderr
        sys.stderr = _LogStream(log_callback)
        try:
            return json.dumps(preview_route_names_from_url(url))
        finally:
            sys.stderr.flush()
            sys.stderr = old


# ── Easy mode helpers ─────────────────────────────────────────────────────────
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
          reused_paths: [...],
          alternate_full_paths: [...],
          detour_results: [{"track_path", "poi_path", "poi_count"}, ...],
        }
    or ``{cancelled: true}`` if cancelled before completion.
    """
    _cancel_event.clear()
    with _stderr_lock:
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
            start_label, finish_label, base_name, track_name = route_names_from_waypoints(
                primary_wp
            )
            out_dir = pathlib.Path(output_dir)
            track_path = str(out_dir / f"{base_name}.gpx")
            poi_path = str(out_dir / f"{base_name}-{profile_id}.gpx")

            track_reused = False
            reused_paths: list[str] = []
            if pathlib.Path(track_path).exists():
                sys.stderr.write(f"Primary track already exists, reusing: {track_path}\n")
                track_reused = True
                reused_paths.append(track_path)
            else:
                _write_gpx(primary_pts, primary_wp, track_path, track_name)
                sys.stderr.write(f"Primary track saved: {track_path}\n")

            tracks_to_enrich: list[str] = [track_path]
            alternate_full_paths: list[str] = []

            if len(routes) > 1:
                for j, (wpts, pts) in enumerate(routes[1:], start=2):
                    alt_path = out_dir / f"{base_name}-full-{j:02d}.gpx"
                    alt_track = f"{shorten_label(wpts[0][2])} – {shorten_label(wpts[-1][2])}"
                    alt_path_str = str(alt_path)
                    alternate_full_paths.append(alt_path_str)
                    if alt_path.exists():
                        sys.stderr.write(
                            f"Alternate route GPX already exists, reusing: {alt_path}\n"
                        )
                        reused_paths.append(alt_path_str)
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
                        reused_paths.append(det_str)
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

            try:
                poi_pairs = enrich_tracks_to_poi_gpx(
                    tracks_to_enrich,
                    profile_id,
                    out_dir,
                    profiles_dir=pathlib.Path(profiles_dir),
                    cancel_event=_cancel_event,
                    progress_interval=5.0,
                )
            except EnrichInterrupted as exc:
                return json.dumps(
                    {
                        "interrupted": True,
                        "message": str(exc),
                        "tracks_to_enrich": exc.tracks_to_enrich,
                        "track_index": exc.track_index,
                        "profile_id": profile_id,
                        "output_dir": str(out_dir),
                        "split_segments": ss,
                        "track_path": track_path,
                        "poi_path": poi_path,
                        "start": start_label,
                        "finish": finish_label,
                        "track_reused": track_reused,
                        "reused_paths": reused_paths,
                        "alternate_full_paths": alternate_full_paths,
                        "milestone_paths": milestone_paths,
                    }
                )

            poi_by_stem: dict[str, tuple[str, int]] = {}
            for poi_path_item, n in poi_pairs:
                stem = pathlib.Path(poi_path_item).stem
                if stem.endswith(f"-{profile_id}"):
                    stem = stem[: -len(f"-{profile_id}")]
                poi_by_stem[stem] = (poi_path_item, n)

            for tpath in tracks_to_enrich:
                stem = pathlib.Path(tpath).stem
                if stem not in poi_by_stem:
                    continue
                poi_path_item, n = poi_by_stem[stem]
                if stem == primary_stem:
                    primary_poi_count = n
                elif "-detour-" in stem:
                    detour_results.append(
                        {"track_path": tpath, "poi_path": poi_path_item, "poi_count": n}
                    )

            return json.dumps(
                {
                    "track_path": track_path,
                    "poi_path": poi_path,
                    "start": start_label,
                    "finish": finish_label,
                    "poi_count": primary_poi_count,
                    "track_reused": track_reused,
                    "reused_paths": reused_paths,
                    "alternate_full_paths": alternate_full_paths,
                    "detour_results": detour_results,
                    "milestone_paths": milestone_paths,
                }
            )
        finally:
            sys.stderr.flush()
            sys.stderr = old


def easy_resume_enrichment(
    profile_id: str,
    profiles_dir: str,
    output_dir: str,
    tracks_to_enrich_json: str,
    start_at: int,
    log_callback,
) -> str:
    """Continue POI enrichment after :class:`EnrichInterrupted` from :func:`easy_generate`."""
    _cancel_event.clear()
    tracks_to_enrich: list[str] = json.loads(tracks_to_enrich_json)
    out_dir = pathlib.Path(output_dir)
    with _stderr_lock:
        old = sys.stderr
        sys.stderr = _LogStream(log_callback)
        try:
            primary_stem = pathlib.Path(tracks_to_enrich[0]).stem
            track_path = tracks_to_enrich[0]
            poi_path = str(out_dir / f"{primary_stem}-{profile_id}.gpx")
            detour_results: list[dict] = []
            primary_poi_count = 0

            try:
                poi_pairs = enrich_tracks_to_poi_gpx(
                    tracks_to_enrich,
                    profile_id,
                    out_dir,
                    start_at=int(start_at),
                    profiles_dir=pathlib.Path(profiles_dir),
                    cancel_event=_cancel_event,
                    progress_interval=5.0,
                )
            except EnrichInterrupted as exc:
                return json.dumps(
                    {
                        "interrupted": True,
                        "message": str(exc),
                        "tracks_to_enrich": exc.tracks_to_enrich,
                        "track_index": exc.track_index,
                        "profile_id": profile_id,
                        "output_dir": str(out_dir),
                    }
                )

            poi_by_stem: dict[str, tuple[str, int]] = {}
            for poi_path_item, n in poi_pairs:
                stem = pathlib.Path(poi_path_item).stem
                if stem.endswith(f"-{profile_id}"):
                    stem = stem[: -len(f"-{profile_id}")]
                poi_by_stem[stem] = (poi_path_item, n)

            for tpath in tracks_to_enrich:
                stem = pathlib.Path(tpath).stem
                if stem not in poi_by_stem:
                    continue
                poi_path_item, n = poi_by_stem[stem]
                if stem == primary_stem:
                    primary_poi_count = n
                elif "-detour-" in stem:
                    detour_results.append(
                        {"track_path": tpath, "poi_path": poi_path_item, "poi_count": n}
                    )

            return json.dumps(
                {
                    "track_path": track_path,
                    "poi_path": poi_path,
                    "poi_count": primary_poi_count,
                    "detour_results": detour_results,
                }
            )
        finally:
            sys.stderr.flush()
            sys.stderr = old
