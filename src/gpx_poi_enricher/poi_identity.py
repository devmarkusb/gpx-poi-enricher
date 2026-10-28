"""Stable OSM identity shared by search results and GPX checkpoints."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

CandidateKey = tuple[str, int] | tuple[float, float]
OSM_URL_PREFIX = "https://www.openstreetmap.org/"
_OSM_URL = re.compile(re.escape(OSM_URL_PREFIX) + r"(node|way|relation)/([1-9][0-9]*)")


def osm_identity(element_type: Any, element_id: Any) -> tuple[str, int] | None:
    if element_type in ("node", "way", "relation") and type(element_id) is int and element_id > 0:
        return element_type, element_id
    return None


def osm_identity_from_url(url: str) -> tuple[str, int] | None:
    match = _OSM_URL.fullmatch(url)
    return (match[1], int(match[2])) if match else None


def candidate_key(candidate: Mapping[str, Any]) -> CandidateKey:
    """Use OSM type+ID, retaining coordinate fallback for anonymous callers."""
    return osm_identity(candidate.get("osm_type"), candidate.get("osm_id")) or (
        round(candidate["lat"], 5),
        round(candidate["lon"], 5),
    )
