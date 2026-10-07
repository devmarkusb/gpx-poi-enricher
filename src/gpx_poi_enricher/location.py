"""Resolve a coordinate or Google Maps place link to a latitude/longitude pair."""

from __future__ import annotations

import math
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

_PAIR_RE = re.compile(r"^\s*(?:geo:)?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_PLACE_COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_VIEW_COORDS_RE = re.compile(r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)")
_GOOGLE_HOST_RE = re.compile(
    r"^(?:(?:www|maps)\.)?google\.(?:com|[a-z]{2,3}(?:\.[a-z]{2})?)$",
    re.IGNORECASE,
)
_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _coordinates(pair: str) -> tuple[float, float] | None:
    match = _PAIR_RE.fullmatch(pair)
    if not match:
        return None
    lat, lon = map(float, match.groups())
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def _validate_maps_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Google Maps URL.") from exc

    host = (parsed.hostname or "").lower()
    is_short_maps_link = host == "maps.app.goo.gl" or (
        host == "goo.gl" and parsed.path.startswith("/maps/")
    )
    is_google_maps_link = bool(_GOOGLE_HOST_RE.fullmatch(host))
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not (is_short_maps_link or is_google_maps_link)
    ):
        raise ValueError("Use an HTTPS Google Maps link or enter coordinates as LAT,LON.")
    return host, parsed.path


def _expand_short_link(url: str, session: requests.Session) -> str:
    current = url
    for _ in range(6):
        host, _ = _validate_maps_url(current)
        if host not in {"maps.app.goo.gl", "goo.gl"}:
            return current

        try:
            response = session.get(
                current,
                allow_redirects=False,
                stream=True,
                timeout=(5, 20),
            )
        except requests.RequestException as exc:
            raise ValueError(f"Could not open the Google Maps link: {exc}") from exc

        status_code = response.status_code
        destination = response.headers.get("Location")
        response.close()
        if status_code not in _REDIRECT_CODES:
            return current
        if not destination:
            raise ValueError("The Google Maps short link did not provide a destination.")
        current = urljoin(current, destination)
        _validate_maps_url(current)

    raise ValueError("The Google Maps short link redirected too many times.")


def _coordinates_from_maps_url(url: str) -> tuple[float, float] | None:
    decoded_url = unquote(url)
    place_match = _PLACE_COORDS_RE.search(decoded_url)
    if place_match:
        pair = ",".join(place_match.groups())
        coords = _coordinates(pair)
        if coords:
            return coords

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ("query", "q", "center", "ll"):
        for value in query.get(key, []):
            coords = _coordinates(value)
            if coords:
                return coords

    view_match = _VIEW_COORDS_RE.search(decoded_url)
    if view_match:
        coords = _coordinates(",".join(view_match.groups()))
        if coords:
            return coords
    return None


def resolve_point_input(
    value: str,
    *,
    session: requests.Session | None = None,
) -> tuple[float, float]:
    """Resolve ``LAT,LON`` or a Google Maps place URL to coordinates.

    For Maps place URLs, the place pin is preferred over the map viewport center.
    Short ``maps.app.goo.gl`` links are expanded through HTTPS redirects.
    """
    if _PAIR_RE.fullmatch(value):
        direct = _coordinates(value)
        if direct:
            return direct
        raise ValueError("Coordinates must be within latitude -90..90 and longitude -180..180.")

    candidate = value.strip()
    if "://" not in candidate and not candidate.lower().startswith("geo:"):
        candidate = f"https://{candidate}"
    host, _ = _validate_maps_url(candidate)
    if host in {"maps.app.goo.gl", "goo.gl"}:
        candidate = _expand_short_link(candidate, session or requests.Session())

    coords = _coordinates_from_maps_url(candidate)
    if coords:
        return coords
    raise ValueError(
        "Could not find coordinates in that Maps link. Enter LAT,LON or use a place link with a map pin."
    )
