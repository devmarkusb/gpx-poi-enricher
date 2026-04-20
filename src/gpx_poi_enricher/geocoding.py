"""Nominatim reverse-geocoding to detect the country of route segments."""

from __future__ import annotations

import sys
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

import requests

from .gpx_utils import haversine_km

if TYPE_CHECKING:
    pass

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "gpx-poi-enricher/0.1 (https://github.com/devmarkusb/gpx-poi-enricher)"


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
            except requests.RequestException as exc:
                print(f"Reverse geocoding failed for {pt}: {exc}", file=sys.stderr)

            last_rev = pt
            time.sleep(sleep_between_calls)

        if last_cc:
            country_points.setdefault(last_cc, []).append(pt)

    return country_points
