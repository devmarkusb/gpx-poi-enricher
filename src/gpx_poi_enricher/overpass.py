"""Overpass API client: query building, execution, and result extraction."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import requests

from .gpx_utils import min_distance_to_track_km

if TYPE_CHECKING:
    from .profiles import SearchProfile

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

USER_AGENT = "gpx-poi-enricher/0.1 (https://github.com/devmarkusb/gpx-poi-enricher)"


def _tag_condition(tag: dict[str, Any]) -> str:
    key = tag["key"]
    value = tag["value"]
    condition = f'["{key}"]' if value == "*" else f'["{key}"="{value}"]'
    extra = tag.get("and")
    if extra:
        for item in extra if isinstance(extra, list) else [extra]:
            ek, ev = item["key"], item["value"]
            condition += f'["{ek}"]' if ev == "*" else f'["{ek}"="{ev}"]'
    return condition


def _collect_tag_lines(
    points: list[tuple[float, float]],
    radius_m: int,
    profile: SearchProfile,
) -> list[str]:
    lines: list[str] = []
    for lat, lon in points:
        selectors = [
            f"node(around:{radius_m},{lat},{lon})",
            f"way(around:{radius_m},{lat},{lon})",
            f"relation(around:{radius_m},{lat},{lon})",
        ]
        for sel in selectors:
            for tag in profile.tags:
                lines.append(f"{sel}{_tag_condition(tag)};")
    return lines


def _collect_term_lines(
    points: list[tuple[float, float]],
    radius_m: int,
    profile: SearchProfile,
    country_code: str,
) -> list[str]:
    terms = profile.terms_for_country(country_code)
    if not terms:
        return []
    regex = "|".join(re.escape(t) for t in terms)
    lines: list[str] = []
    for lat, lon in points:
        selectors = [
            f"node(around:{radius_m},{lat},{lon})",
            f"way(around:{radius_m},{lat},{lon})",
            f"relation(around:{radius_m},{lat},{lon})",
        ]
        for sel in selectors:
            lines.append(f'{sel}["name"~"{regex}", i];')
            lines.append(f'{sel}["description"~"{regex}", i];')
            lines.append(f'{sel}["operator"~"{regex}", i];')
    return lines


def _collect_tag_and_term_lines(
    points: list[tuple[float, float]],
    radius_m: int,
    profile: SearchProfile,
    country_code: str,
) -> list[str]:
    """Tag filters AND (name OR description OR operator) regex — one statement per branch."""
    terms = profile.terms_for_country(country_code)
    if not terms:
        return []
    regex = "|".join(re.escape(t) for t in terms)
    lines: list[str] = []
    for lat, lon in points:
        selectors = [
            f"node(around:{radius_m},{lat},{lon})",
            f"way(around:{radius_m},{lat},{lon})",
            f"relation(around:{radius_m},{lat},{lon})",
        ]
        for sel in selectors:
            for tag in profile.tags:
                cond = _tag_condition(tag)
                lines.append(f'{sel}{cond}["name"~"{regex}", i];')
                lines.append(f'{sel}{cond}["description"~"{regex}", i];')
                lines.append(f'{sel}{cond}["operator"~"{regex}", i];')
    return lines


def _wrap_overpass(lines: list[str]) -> str:
    return "[out:json][timeout:180];\n(\n" + "\n".join(lines) + "\n);\nout center tags;\n"


def build_overpass_queries(
    points: list[tuple[float, float]],
    max_km: float,
    profile: SearchProfile,
    country_code: str,
) -> list[str]:
    """Build one or two Overpass QL scripts for *profile*.

    When both OSM tag filters and search terms apply:

    - If ``profile.must_match_terms`` is true, emit a **single** script that
      **AND**-combines tag predicates with name/description/operator regex
      branches (each branch is tag predicates plus one text field).
    - Otherwise emit **two** scripts (tag selectors, then term regex
      selectors); the enricher merges element lists so results are tag hits
      **or** text hits.

    Returns:
        One or two query strings, or raises if nothing could be built.
    """
    radius_m = int(max_km * 1000)
    tag_lines = _collect_tag_lines(points, radius_m, profile)
    term_lines = _collect_term_lines(points, radius_m, profile, country_code)

    if tag_lines and term_lines and profile.must_match_terms:
        combined = _collect_tag_and_term_lines(points, radius_m, profile, country_code)
        if not combined:
            raise ValueError(
                f"No Overpass query could be built for profile '{profile.id}' "
                f"(tags + terms produced no lines for country '{country_code}')."
            )
        return [_wrap_overpass(combined)]

    queries: list[str] = []
    if tag_lines:
        queries.append(_wrap_overpass(tag_lines))
    if term_lines:
        queries.append(_wrap_overpass(term_lines))

    if not queries:
        raise ValueError(
            f"No Overpass query could be built for profile '{profile.id}' "
            f"(no tag filters and no terms for country '{country_code}'). "
            "Add non-empty 'terms' in the profile YAML, or OSM tag filters."
        )

    return queries


def build_overpass_query(
    points: list[tuple[float, float]],
    max_km: float,
    profile: SearchProfile,
    country_code: str,
) -> str:
    """Build a single Overpass QL script (tags-only, terms-only, or AND-combined).

    Raises:
        ValueError: If the profile needs two separate Overpass requests
            (tags and terms both apply and ``must_match_terms`` is false).
    """
    queries = build_overpass_queries(points, max_km, profile, country_code)
    if len(queries) != 1:
        raise ValueError(
            f"Profile '{profile.id}' uses tags and terms without must_match_terms; "
            f"use build_overpass_queries() for {len(queries)} Overpass request(s)."
        )
    return queries[0]


def query_overpass(
    session: requests.Session,
    query: str,
    max_retries: int = 2,
    urls: list[str] | None = None,
    verbose: bool = False,
    progress: dict | None = None,
) -> dict[str, Any]:
    """Execute an Overpass QL query against the public API mirrors.

    Tries each URL in *urls* up to *max_retries* times with exponential
    back-off. Raises the last encountered exception if all attempts fail.
    """
    endpoints = urls or OVERPASS_URLS
    headers = {"User-Agent": USER_AGENT}
    last_error: Exception | None = None

    for base_url in endpoints:
        for attempt in range(max_retries):
            if progress is not None:
                progress.update(
                    {"endpoint": base_url, "attempt": attempt + 1, "max_retries": max_retries}
                )
            try:
                r = session.post(base_url, data={"data": query}, headers=headers, timeout=240)
                content_type = r.headers.get("content-type", "")

                if r.ok and "json" in content_type.lower():
                    try:
                        return r.json()
                    except json.JSONDecodeError as exc:
                        last_error = exc
                        wait_s = min(60, 5 * (2**attempt))
                        print(
                            f"Invalid JSON from {base_url} (attempt {attempt + 1}/{max_retries}): {exc}",
                            file=sys.stderr,
                        )
                        time.sleep(wait_s)
                        continue

                body = r.text[:4000]
                busy = (
                    r.status_code in (429, 500, 502, 504)
                    or "too busy" in body.lower()
                    or "timeout" in body.lower()
                )
                if busy:
                    wait_s = min(60, 5 * (2**attempt))
                    last_error = RuntimeError(
                        f"Overpass busy at {base_url} (attempt {attempt + 1}/{max_retries})"
                    )
                    print(
                        f"Overpass busy at {base_url} (attempt {attempt + 1}/{max_retries}), "
                        f"waiting {wait_s}s...",
                        file=sys.stderr,
                    )
                    if verbose:
                        print(body[:1000], file=sys.stderr)
                    time.sleep(wait_s)
                    continue

                if verbose:
                    print(r.text[:1000], file=sys.stderr)
                r.raise_for_status()
                last_error = RuntimeError(
                    f"Unexpected response from {base_url} (status {r.status_code})"
                )
                time.sleep(min(60, 5 * (2**attempt)))

            except requests.RequestException as exc:
                last_error = exc
                wait_s = min(60, 5 * (2**attempt))
                print(
                    f"Request failed at {base_url} (attempt {attempt + 1}/{max_retries}): {exc}",
                    file=sys.stderr,
                )
                time.sleep(wait_s)

    if last_error:
        raise last_error
    raise RuntimeError("All Overpass endpoints failed with no error recorded")


def element_latlon(el: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract (lat, lon) from an Overpass element (node, way center, or relation center)."""
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return center["lat"], center["lon"]
    return None, None


def _choose_name(tags: dict[str, str], profile: SearchProfile) -> str:
    for key in ("name", "official_name", "short_name", "brand", "operator"):
        val = tags.get(key, "").strip()
        if val:
            return val
    return profile.description


def _choose_kind(tags: dict[str, str], profile: SearchProfile) -> str:
    matches = []
    for tag in profile.tags:
        key, value = tag["key"], tag["value"]
        if value == "*":
            if key in tags:
                matches.append(f"{key}={tags[key]}")
        elif tags.get(key) == value:
            matches.append(f"{key}={value}")
    return f"{profile.description} [{', '.join(matches[:3])}]" if matches else profile.description


def extract_candidates(
    data: dict[str, Any],
    track_points: list[tuple[float, float]],
    max_km: float,
    profile: SearchProfile,
) -> list[dict[str, Any]]:
    """Filter Overpass results to POIs within *max_km* of the track, deduplicated.

    Returns a list of dicts with keys: lat, lon, name, kind, distance_km, tags.
    """
    dedup: OrderedDict[tuple[float, float], dict[str, Any]] = OrderedDict()

    for el in data.get("elements", []):
        lat, lon = element_latlon(el)
        if lat is None or lon is None:
            continue

        tags = el.get("tags", {})
        d = min_distance_to_track_km(lat, lon, track_points)
        if d > max_km:
            continue

        key = (round(lat, 5), round(lon, 5))
        if key not in dedup:
            dedup[key] = {
                "lat": lat,
                "lon": lon,
                "name": _choose_name(tags, profile),
                "kind": _choose_kind(tags, profile),
                "distance_km": d,
                "tags": tags,
            }

    return list(dedup.values())
