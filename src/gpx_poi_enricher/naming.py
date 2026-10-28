"""Label and filename helpers shared by route and point output naming.

Route mode names files after its start/finish labels; point mode names them after
the starting point's Nominatim place name, with a coordinate-based hash fallback.
"""

from __future__ import annotations

import hashlib
import re

import requests

from .geocoding import reverse_place_name

# Placeholder names OSM uses when no real name exists — useless as a filename.
_PLACEHOLDER_NAMES = frozenset({"unnamed", "unknown", "nameless", "n/a", "none", "-"})

# Upper bound for a single filename component (keeps paths readable everywhere).
_MAX_LABEL_LEN = 60


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


def _trim_label(text: str, limit: int = _MAX_LABEL_LEN) -> str:
    """Cut *text* to *limit* characters, preferring a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    if " " in cut:
        return cut.rsplit(" ", 1)[0]
    return cut


def clean_label(raw: str | None) -> str:
    """Reduce a raw name/address to a short, file-safe label (``''`` when unusable)."""
    text = shorten_label((raw or "").strip())
    text = text.strip(" \t-–—·,;:")
    if not text or text.casefold() in _PLACEHOLDER_NAMES:
        return ""
    if not any(ch.isalnum() for ch in text):
        return ""
    return _trim_label(text)


def point_output_stem(
    point: tuple[float, float],
    *,
    session: requests.Session | None = None,
) -> tuple[str, str]:
    """Filename stem for a point-mode POI GPX: ``(stem, source)``.

    Use one Nominatim reverse lookup at *point*, independent of search results.
    If no usable place name is available, hash the coordinates at seven decimal
    places so equivalent coordinate strings and Maps links share a fallback.
    """
    label = ""
    if session is not None:
        try:
            place = reverse_place_name(point[0], point[1], session)
        except requests.RequestException:
            place = ""
        label = clean_label(place)

    stem = safe_filename_component(label) if label else ""
    if stem:
        return stem, "place"
    coordinates = ",".join(f"{coordinate + 0.0:.7f}" for coordinate in point)
    return f"point-{hashlib.sha256(coordinates.encode()).hexdigest()[:8]}", "hash"
