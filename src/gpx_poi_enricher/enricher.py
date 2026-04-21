"""Core enrichment engine: orchestrates geocoding + Overpass queries."""

from __future__ import annotations

import pathlib
import sys
import threading
import time
from collections import OrderedDict
from typing import Any

import requests

from .geocoding import detect_country_segments
from .gpx_utils import (
    add_waypoints_to_gpx,
    parse_gpx_trackpoints,
    remove_tracks_and_routes,
    sample_track_by_distance,
)
from .overpass import build_overpass_query, extract_candidates, query_overpass
from .profiles import SearchProfile, load_profile
from .progress import ProgressHeartbeat


def _chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def enrich_track(
    track_points: list[tuple[float, float]],
    profile: SearchProfile,
    *,
    max_km: float | None = None,
    sample_km: float | None = None,
    batch_size: int | None = None,
    country_sample_km: float = 40.0,
    progress_interval: float = 5.0,
    verbose: bool = False,
    http_session: requests.Session | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Enrich a list of track points with nearby POIs from OpenStreetMap.

    Args:
        track_points: List of ``(lat, lon)`` tuples forming the route.
        profile: A :class:`~gpx_poi_enricher.profiles.SearchProfile` instance.
        max_km: Override profile's max search radius (km).
        sample_km: Override profile's track sampling interval (km).
        batch_size: Override profile's Overpass batch size.
        country_sample_km: Minimum distance (km) between Nominatim calls.
        progress_interval: Print progress to stderr every N seconds (0 = off).
        verbose: Print verbose Overpass error bodies to stderr.
        http_session: Optional pre-configured ``requests.Session``.

    Returns:
        Sorted list of POI dicts (keys: lat, lon, name, kind, distance_km, tags).
    """
    _max_km = max_km if max_km is not None else profile.max_km
    _sample_km = sample_km if sample_km is not None else profile.sample_km
    _batch_size = batch_size if batch_size is not None else profile.batch_size

    session = http_session or requests.Session()
    sampled = sample_track_by_distance(track_points, _sample_km)

    print(f"Loaded {len(track_points)} track points.", file=sys.stderr)
    print(f"Sampled to {len(sampled)} points at ~{_sample_km} km spacing.", file=sys.stderr)
    print(f"Profile: {profile.id} ({profile.description})", file=sys.stderr)
    print(
        f"Using max_km={_max_km}, sample_km={_sample_km}, batch_size={_batch_size}", file=sys.stderr
    )

    progress_state: dict[str, Any] = {
        "phase": "nominatim",
        "pois_found": 0,
        "endpoint": None,
        "attempt": None,
        "max_retries": None,
        "batch": (0, 0),
        "country": "",
    }

    use_progress = progress_interval > 0

    if use_progress:
        with ProgressHeartbeat(progress_state, interval=progress_interval):
            country_segments = detect_country_segments(
                sampled, session, min_spacing_km=country_sample_km, progress=progress_state
            )
    else:
        country_segments = detect_country_segments(
            sampled, session, min_spacing_km=country_sample_km
        )

    if not country_segments:
        country_segments = OrderedDict([("EN", sampled)])

    total_batches = sum(
        (len(pts) + _batch_size - 1) // _batch_size for pts in country_segments.values()
    )
    batch_num = 0
    all_candidates: OrderedDict[tuple[float, float], dict[str, Any]] = OrderedDict()

    _early_cancel_batches = 3

    def _run_overpass_batches() -> None:
        nonlocal batch_num
        for cc, pts in country_segments.items():
            for batch in _chunked(pts, _batch_size):
                batch_num += 1
                progress_state.update(
                    {"phase": "overpass", "country": cc, "batch": (batch_num, total_batches)}
                )

                query = build_overpass_query(batch, _max_km, profile, cc)
                data = query_overpass(
                    session,
                    query,
                    max_retries=profile.retries,
                    verbose=verbose,
                    progress=progress_state,
                )
                for item in extract_candidates(data, track_points, _max_km, profile):
                    key = (round(item["lat"], 5), round(item["lon"], 5))
                    if key not in all_candidates:
                        all_candidates[key] = item

                progress_state["pois_found"] = len(all_candidates)

                if (
                    batch_num >= _early_cancel_batches
                    and len(all_candidates) == 0
                    and batch_num < total_batches
                ):
                    raise RuntimeError(
                        f"No POIs found after {batch_num} batches — cancelling early.\n"
                        f"Current search radius: max_km={_max_km}. "
                        f"Try increasing it (e.g. --max-km {int(_max_km * 2)}) "
                        f"or switching to a broader profile."
                    )

                time.sleep(1.0)
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")

    if use_progress:
        with ProgressHeartbeat(progress_state, interval=progress_interval):
            _run_overpass_batches()
    else:
        _run_overpass_batches()

    return sorted(all_candidates.values(), key=lambda x: (x["distance_km"], x["name"].lower()))


def enrich_gpx_file(
    input_path: str | pathlib.Path,
    output_path: str | pathlib.Path,
    profile_id: str,
    profiles_dir: pathlib.Path | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """High-level convenience function: load GPX, enrich, write output GPX.

    Args:
        input_path: Path to the input GPX file (must contain a ``<trk>``).
        output_path: Path for the output GPX file (waypoints only).
        profile_id: Profile identifier (e.g. ``"camping"``).
        profiles_dir: Optional override for the profiles directory.
        **kwargs: Forwarded to :func:`enrich_track`.

    Returns:
        The list of POI dicts written as waypoints.
    """
    profile = load_profile(profile_id, profiles_dir)
    tree, root, track_points = parse_gpx_trackpoints(str(input_path))
    items = enrich_track(track_points, profile, **kwargs)

    print(f"\nAdding {len(items)} waypoints.", file=sys.stderr)
    add_waypoints_to_gpx(root, items, symbol=profile.symbol, type_label=profile.description)
    remove_tracks_and_routes(root)
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)
    print(f"Wrote: {output_path}", file=sys.stderr)

    return items
