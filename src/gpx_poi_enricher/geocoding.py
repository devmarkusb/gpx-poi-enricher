"""Nominatim place lookup and reverse geocoding for points and route segments."""

from __future__ import annotations

import math
import sys
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

import requests

from .gpx_utils import haversine_km

if TYPE_CHECKING:
    pass

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "gpx-poi-enricher/0.1 (https://github.com/devmarkusb/gpx-poi-enricher)"

# Address keys most likely to name the place a coordinate belongs to, most local first.
_PLACE_NAME_KEYS = (
    "neighbourhood",
    "quarter",
    "suburb",
    "borough",
    "hamlet",
    "village",
    "town",
    "city_district",
    "city",
    "municipality",
    "locality",
    "park",
    "road",
    "county",
    "state",
    "country",
)


def geocode_place(name: str, session: requests.Session) -> tuple[float, float]:
    """Resolve a POI name or address to coordinates through Nominatim."""
    response = session.get(
        NOMINATIM_SEARCH_URL,
        params={"q": name, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json()
    # Leave room for a following country or place lookup in the enrichment pipeline.
    time.sleep(1.1)
    if results:
        try:
            lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
            if (
                math.isfinite(lat)
                and math.isfinite(lon)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                return lat, lon
        except (KeyError, TypeError, ValueError):
            pass
    raise ValueError("Could not find that place. Add its city or address, or enter LAT,LON.")


def reverse_country_code(
    lat: float,
    lon: float,
    session: requests.Session,
    user_agent: str = USER_AGENT,
) -> str:
    """Return the ISO 3166-1 alpha-2 country code (uppercased) for a coordinate.

    Returns an empty string if the lookup fails or the country is unknown.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 5,
        "addressdetails": 1,
    }
    headers = {"User-Agent": user_agent}
    r = session.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("address", {}).get("country_code", "").upper()


def reverse_place_name(
    lat: float,
    lon: float,
    session: requests.Session,
    user_agent: str = USER_AGENT,
    zoom: int = 14,
) -> str:
    """Return a human-readable name for a coordinate (``''`` when none is known).

    Prefers the matched object's own name, then the most local named address part
    (neighbourhood/town/…), then the display name. Raises on HTTP errors — callers
    that only want a nicer label should catch :class:`requests.RequestException`.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": zoom,
        "addressdetails": 1,
    }
    headers = {"User-Agent": user_agent}
    r = session.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    name = str(data.get("name") or "").strip()
    if name:
        return name
    address = data.get("address") or {}
    for key in _PLACE_NAME_KEYS:
        value = str(address.get(key, "")).strip()
        if value:
            return value
    return str(data.get("display_name") or "").strip()


def detect_country_segments(
    sampled_points: list[tuple[float, float]],
    session: requests.Session,
    min_spacing_km: float = 40.0,
    progress: dict | None = None,
    sleep_between_calls: float = 1.1,
) -> OrderedDict[str, list[tuple[float, float]]]:
    """Group sampled track points by country using Nominatim reverse geocoding.

    Only calls Nominatim when the last geocoded point is more than *min_spacing_km*
    away (honouring rate-limit best-practices). Points where the country cannot
    be determined are omitted.

    Returns an ``OrderedDict`` mapping country code → list of points in that country,
    preserving first-encounter order.
    """
    country_points: OrderedDict[str, list[tuple[float, float]]] = OrderedDict()
    last_rev: tuple[float, float] | None = None
    last_cc: str | None = None
    rev_calls = 0
    n = len(sampled_points)

    for i, pt in enumerate(sampled_points):
        if progress is not None:
            progress["nominatim_sample_idx"] = i
            progress["nominatim_samples_total"] = n

        need = (
            last_rev is None
            or haversine_km(last_rev[0], last_rev[1], pt[0], pt[1]) >= min_spacing_km
        )

        if need:
            rev_calls += 1
            if progress is not None:
                progress["nominatim_rev_calls"] = rev_calls

            try:
                cc = reverse_country_code(pt[0], pt[1], session)
                if cc:
                    last_cc = cc
            except requests.RequestException:
                print("Reverse geocoding failed.", file=sys.stderr)

            last_rev = pt
            time.sleep(sleep_between_calls)

        if last_cc:
            country_points.setdefault(last_cc, []).append(pt)

    return country_points
