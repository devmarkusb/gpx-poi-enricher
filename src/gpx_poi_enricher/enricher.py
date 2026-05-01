"""Core enrichment engine: orchestrates geocoding + Overpass queries."""

from __future__ import annotations

import copy
import os
import pathlib
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import requests

from .geocoding import detect_country_segments
from .gpx_utils import (
    add_waypoints_to_gpx,
    parse_gpx_trackpoints,
    remove_tracks_and_routes,
    sample_track_by_distance,
)
from .overpass import build_overpass_queries, extract_candidates, query_overpass
from .profiles import SearchProfile, load_profile
from .progress import ProgressHeartbeat


def _sorted_poi_items(
    candidates: OrderedDict[tuple[float, float], dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(candidates.values(), key=lambda x: (x["distance_km"], x["name"].lower()))


def _write_waypoints_gpx_snapshot(
    root_template: ET.Element,
    items: list[dict[str, Any]],
    output_path: str | pathlib.Path,
    *,
    symbol: str,
    type_label: str,
) -> None:
    """Write a waypoints-only GPX to *output_path* (atomic replace when possible)."""
    root = copy.deepcopy(root_template)
    add_waypoints_to_gpx(root, items, symbol=symbol, type_label=type_label)
    remove_tracks_and_routes(root)
    tree = ET.ElementTree(root)
    outp = pathlib.Path(output_path)
    tmp = outp.with_name(outp.name + ".tmp")
    tree.write(str(tmp), encoding="utf-8", xml_declaration=True)
    os.replace(tmp, outp)


def _chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _dedupe_overpass_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep first occurrence per (type, id); preserves stable order."""
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for el in elements:
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out


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
    early_cancel_if_no_pois: bool | None = None,
    early_cancel_after_batches: int | None = None,
    on_batch_checkpoint: Callable[[list[dict[str, Any]]], None] | None = None,
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
        early_cancel_if_no_pois: If None (default), use the profile's ``early_cancel_if_no_pois``.
            If True/False, override the profile for this run.
        early_cancel_after_batches: If None, use the profile's threshold; otherwise override
            (only applies when early cancel is enabled).
        on_batch_checkpoint: If set, called after each Overpass batch with the current sorted
            POI list (same ordering as the return value) so callers can persist partial results.

    Returns:
        Sorted list of POI dicts (keys: lat, lon, name, kind, distance_km, tags).
    """
    _max_km = max_km if max_km is not None else profile.max_km
    _sample_km = sample_km if sample_km is not None else profile.sample_km
    _batch_size = batch_size if batch_size is not None else profile.batch_size
    _early_cancel = (
        profile.early_cancel_if_no_pois
        if early_cancel_if_no_pois is None
        else early_cancel_if_no_pois
    )
    _early_cancel_batches = (
        profile.early_cancel_after_batches
        if early_cancel_after_batches is None
        else early_cancel_after_batches
    )
    if _early_cancel and _early_cancel_batches < 1:
        raise ValueError("early_cancel_after_batches must be >= 1 when early cancel is enabled.")

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

    def _run_overpass_batches() -> None:
        nonlocal batch_num
        for cc, pts in country_segments.items():
            for batch in _chunked(pts, _batch_size):
                batch_num += 1
                progress_state.update(
                    {"phase": "overpass", "country": cc, "batch": (batch_num, total_batches)}
                )

                merged_elements: list[dict[str, Any]] = []
                for query in build_overpass_queries(batch, _max_km, profile, cc):
                    data = query_overpass(
                        session,
                        query,
                        max_retries=profile.retries,
                        verbose=verbose,
                        progress=progress_state,
                    )
                    merged_elements.extend(data.get("elements") or [])
                data = {"elements": _dedupe_overpass_elements(merged_elements)}
                for item in extract_candidates(data, track_points, _max_km, profile):
                    key = (round(item["lat"], 5), round(item["lon"], 5))
                    if key not in all_candidates:
                        all_candidates[key] = item

                progress_state["pois_found"] = len(all_candidates)

                if (
                    _early_cancel
                    and batch_num >= _early_cancel_batches
                    and len(all_candidates) == 0
                    and batch_num < total_batches
                ):
                    raise RuntimeError(
                        f"No POIs found after {batch_num} batches — cancelling early.\n"
                        f"Current search radius: max_km={_max_km}. "
                        f"Try increasing it (e.g. --max-km {int(_max_km * 2)}) "
                        f"or switching to a broader profile."
                    )

                if on_batch_checkpoint is not None:
                    on_batch_checkpoint(_sorted_poi_items(all_candidates))

                time.sleep(1.0)
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Operation cancelled by user.")

    if use_progress:
        with ProgressHeartbeat(progress_state, interval=progress_interval):
            _run_overpass_batches()
    else:
        _run_overpass_batches()

    return _sorted_poi_items(all_candidates)


def enrich_gpx_file(
    input_path: str | pathlib.Path,
    output_path: str | pathlib.Path,
    profile_id: str,
    profiles_dir: pathlib.Path | None = None,
    early_cancel_if_no_pois: bool | None = None,
    *,
    checkpoint_each_batch: bool = False,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """High-level convenience function: load GPX, enrich, write output GPX.

    Args:
        input_path: Path to the input GPX file (must contain a ``<trk>``).
        output_path: Path for the output GPX file (waypoints only).
        profile_id: Profile identifier (e.g. ``"camping"``).
        profiles_dir: Optional override for the profiles directory.
        early_cancel_if_no_pois: Passed to :func:`enrich_track`; None means use the profile.
        checkpoint_each_batch: If True, overwrite *output_path* after each Overpass batch with
            all POIs collected so far (same format as the final file), so interruptions retain data.
        **kwargs: Forwarded to :func:`enrich_track`.

    Returns:
        The list of POI dicts written as waypoints.
    """
    profile = load_profile(profile_id, profiles_dir)
    tree, root, track_points = parse_gpx_trackpoints(str(input_path))
    outp = pathlib.Path(output_path)
    if checkpoint_each_batch:
        outp.parent.mkdir(parents=True, exist_ok=True)

    def _checkpoint(items: list[dict[str, Any]]) -> None:
        _write_waypoints_gpx_snapshot(
            root,
            items,
            outp,
            symbol=profile.symbol,
            type_label=profile.description,
        )

    items = enrich_track(
        track_points,
        profile,
        early_cancel_if_no_pois=early_cancel_if_no_pois,
        on_batch_checkpoint=_checkpoint if checkpoint_each_batch else None,
        **kwargs,
    )

    print(f"\nAdding {len(items)} waypoints.", file=sys.stderr)
    add_waypoints_to_gpx(root, items, symbol=profile.symbol, type_label=profile.description)
    remove_tracks_and_routes(root)
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)
    print(f"Wrote: {output_path}", file=sys.stderr)

    return items
