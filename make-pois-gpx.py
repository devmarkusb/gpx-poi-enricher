#!/usr/bin/env python3
"""
Add configurable POI waypoints near a GPX track.

Examples:
  python add-pois-to-gpx.py split.gpx camping.gpx --profile camping
  python add-pois-to-gpx.py split.gpx playgrounds.gpx --profile playground
  python add-pois-to-gpx.py split.gpx zoos.gpx --profile zoo --max-km 15

Notes:
- Output GPX contains only the found POI waypoints (<wpt>), not the input track (keeps files small).
- The route is sampled, then representative route points are reverse-geocoded to segment the route
  by country (DE / FR / ES / others) so localized text terms apply per segment.
- Queries are sent to Overpass in small batches with retries and endpoint fallback.
- Search is tag-first. Profiles with a non-empty ``terms`` map also union name/description/operator
  regex matches for that segment; profiles with no ``terms`` are tag-only.
- Profile-specific defaults are applied unless explicitly overridden on the command line.
"""

import argparse
import json
import math
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict

import requests


GPX_NS = "http://www.topografix.com/GPX/1/1"
NS = {"gpx": GPX_NS}
ET.register_namespace("", GPX_NS)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "gpx-poi-enricher/3.0 (personal route planning)"

SEARCH_PROFILES = {
    "camping": {
        "description": "Campingplatz",
        "tags": [
            {"key": "tourism", "value": "camp_site"},
            {"key": "tourism", "value": "caravan_site"},
        ],
        "terms": {
            "DE": ["Campingplatz", "Wohnmobilstellplatz"],
            "FR": ["camping", "aire de camping-car"],
            "ES": ["camping", "área de autocaravanas"],
            "EN": ["camping", "motorhome stopover", "caravan site"],
        },
        "symbol": "Campground",
    },
    "playground": {
        "description": "Spielplatz",
        "tags": [
            {"key": "leisure", "value": "playground"},
        ],
        "symbol": "Playground",
    },
    "outdoor_pool": {
        "description": "Freibad, Erlebnisbad, Thermalbad",
        "tags": [
            {"key": "leisure", "value": "swimming_pool"},
            {"key": "leisure", "value": "water_park"},
            {"key": "amenity", "value": "public_bath"},
        ],
        "terms": {
            "DE": ["Freibad", "Erlebnisbad", "Thermalbad", "Therme"],
            "FR": ["piscine", "parc aquatique", "thermes", "bains thermaux"],
            "ES": ["piscina", "parque acuático", "balneario", "termas"],
            "EN": ["outdoor pool", "water park", "thermal bath"],
        },
        "symbol": "Swimming Area",
    },
    "beach": {
        "description": "Badesee, Strand",
        "tags": [
            {"key": "natural", "value": "beach"},
            {"key": "leisure", "value": "bathing_place"},
        ],
        "terms": {
            "DE": ["Badesee", "Badestrand", "Strand", "Badestelle"],
            "FR": ["plage", "lac de baignade", "baignade"],
            "ES": ["playa", "zona de baño", "lago para bañarse"],
            "EN": ["beach", "swimming lake", "bathing place"],
        },
        "symbol": "Beach",
    },
    "theme_park": {
        "description": "Freizeitpark",
        "tags": [
            {"key": "tourism", "value": "theme_park"},
            {"key": "tourism", "value": "attraction"},
        ],
        "terms": {
            "DE": ["Freizeitpark", "Erlebnispark", "Themenpark"],
            "FR": ["parc d attractions", "parc a theme"],
            "ES": ["parque de atracciones", "parque temático"],
            "EN": ["theme park", "amusement park"],
        },
        "symbol": "Amusement Park",
    },
    "zoo": {
        "description": "Zoo, Streichelzoo",
        "tags": [
            {"key": "tourism", "value": "zoo"},
            {"key": "animal", "value": "petting_zoo"},
        ],
        "symbol": "Zoo",
    },
    "aquarium": {
        "description": "Aquarium",
        "tags": [
            {"key": "tourism", "value": "aquarium"},
        ],
        "symbol": "Aquarium",
    },
    "mcdonalds": {
        "description": "McDonalds",
        "tags": [
            {"key": "amenity", "value": "fast_food", "and": {"key": "brand", "value": "McDonald's"}},
            {"key": "brand:wikidata", "value": "Q38076"},
        ],
        "symbol": "Fast Food",
    },
    "restaurant": {
        "description": "Restaurant mit Kinderkarte",
        "tags": [
            {"key": "amenity", "value": "restaurant"},
        ],
        "terms": {
            "DE": ["Kinderkarte", "Familienrestaurant", "kinderfreundlich"],
            "FR": ["menu enfant", "restaurant familial", "adapté aux enfants"],
            "ES": ["menú infantil", "restaurante familiar", "apto para niños"],
            "EN": ["kids menu", "family restaurant", "child friendly restaurant"],
        },
        "symbol": "Restaurant",
    },
    "kids_activities": {
        "description": "Kinder Erlebnis aller Art",
        "tags": [
        ],
        "terms": {
            "DE": ["Kindererlebnis", "Erlebniswelt", "Familienpark", "Indoor Spielplatz"],
            "FR": ["parc de loisirs", "activité enfant", "parc familial", "aire de jeux couverte"],
            "ES": ["parque de ocio", "actividad infantil", "parque familiar", "parque infantil cubierto"],
            "EN": ["kids attraction", "family attraction", "indoor playground", "children activity"],
        },
        "symbol": "Scenic Area",
    },
    "attractions": {
        "description": "allgemein spektakuläre kindertaugliche Sehenswürdigkeit",
        "tags": [
            {"key": "tourism", "value": "attraction"},
            {"key": "tourism", "value": "viewpoint"},
            {"key": "tourism", "value": "museum"},
            {"key": "historic", "value": "*"},
        ],
        "terms": {
            "DE": ["Sehenswürdigkeit", "familienfreundlich", "Aussichtspunkt", "Erlebnis"],
            "FR": ["site touristique", "familial", "point de vue", "incontournable"],
            "ES": ["atracción turística", "familiar", "mirador", "imprescindible"],
            "EN": ["family attraction", "scenic viewpoint", "must see", "kid friendly attraction"],
        },
        "symbol": "Scenic Area",
    },
}

PROFILE_DEFAULTS = {
    "camping": {"max_km": 10.0, "sample_km": 5.0, "batch_size": 6},
    "playground": {"max_km": 3.0, "sample_km": 3.0, "batch_size": 4},
    "outdoor_pool": {"max_km": 10.0, "sample_km": 5.0, "batch_size": 4},
    "beach": {"max_km": 25.0, "sample_km": 12.0, "batch_size": 4},
    "theme_park": {"max_km": 10.0, "sample_km": 5.0, "batch_size": 3},
    "zoo": {"max_km": 12.0, "sample_km": 6.0, "batch_size": 3},
    "aquarium": {"max_km": 15.0, "sample_km": 7.0, "batch_size": 4},
    "mcdonalds": {"max_km": 5.0, "sample_km": 10.0, "batch_size": 10},
    "restaurant": {"max_km": 5.0, "sample_km": 10.0, "batch_size": 8},
    "kids_activities": {"max_km": 15.0, "sample_km": 7.0, "batch_size": 4},
    "attractions": {"max_km": 20.0, "sample_km": 10.0, "batch_size": 3},
}

DEFAULT_QUERY_BEHAVIOR = {"retries": 2}

PROFILE_QUERY_BEHAVIOR = {
    "camping": {"retries": 3},
    "restaurant": {"retries": 3},
    "kids_activities": {"retries": 3},
    "attractions": {"retries": 3},
}


def _short_http_host(url):
    if not url:
        return "—"
    s = url
    for p in ("https://", "http://"):
        if s.startswith(p):
            s = s[len(p) :]
            break
    return s.split("/")[0] if s else url


class ProgressHeartbeat:
    """Print status every ``interval`` seconds while long operations run (stderr, flushed)."""

    def __init__(self, state, interval=5.0, stream=None):
        self.state = state
        self.interval = interval
        self.stream = stream if stream is not None else sys.stderr
        self._stop = threading.Event()
        self._thread = None

    def _format_line(self):
        s = self.state
        phase = s.get("phase", "?")
        pois = s.get("pois_found", 0)

        if phase == "nominatim":
            si = s.get("nominatim_sample_idx", 0)
            st = s.get("nominatim_samples_total", "?")
            rv = s.get("nominatim_rev_calls", 0)
            return (
                f"[progress] nominatim: sample {si + 1}/{st}, "
                f"reverse-geocode calls completed: {rv} | pois so far: {pois}"
            )

        if phase == "overpass":
            bcur, btot = s.get("batch", (0, 0))
            cc = s.get("country", "?")
            host = _short_http_host(s.get("endpoint"))
            att = s.get("attempt")
            mx = s.get("max_retries")
            att_s = f"{att}/{mx}" if att is not None and mx else "—"
            return (
                f"[progress] overpass: batch {bcur}/{btot} ({cc}) | "
                f"{host} attempt {att_s} | pois so far: {pois}"
            )

        return f"[progress] {phase} | pois so far: {pois}"

    def _run(self):
        while not self._stop.wait(self.interval):
            print(self._format_line(), file=self.stream, flush=True)

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 2.0)
        return False


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gpx_trackpoints(path):
    tree = ET.parse(path)
    root = tree.getroot()

    pts = []
    for trkpt in root.findall(".//gpx:trkpt", NS):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        pts.append((lat, lon))

    if not pts:
        raise ValueError("No track points found in GPX.")

    return tree, root, pts


def sample_track_by_distance(points, spacing_km):
    sampled = [points[0]]
    dist_since = 0.0

    for i in range(1, len(points)):
        a = points[i - 1]
        b = points[i]
        d = haversine_km(a[0], a[1], b[0], b[1])
        dist_since += d
        if dist_since >= spacing_km:
            sampled.append(b)
            dist_since = 0.0

    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    return sampled


def reverse_country_code(lat, lon, session):
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 5,
        "addressdetails": 1,
    }
    headers = {"User-Agent": USER_AGENT}
    r = session.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("address", {}).get("country_code", "").upper()


def detect_country_segments(sampled_points, session, min_spacing_for_reverse_km=40.0, progress=None):
    country_points = OrderedDict()
    last_rev = None
    last_cc = None
    n = len(sampled_points)
    rev_calls = 0

    for i, pt in enumerate(sampled_points):
        if progress is not None:
            progress["nominatim_sample_idx"] = i
            progress["nominatim_samples_total"] = n

        if last_rev is None:
            need = True
        else:
            need = haversine_km(last_rev[0], last_rev[1], pt[0], pt[1]) >= min_spacing_for_reverse_km

        if need:
            rev_calls += 1
            if progress is not None:
                progress["nominatim_rev_calls"] = rev_calls

            try:
                cc = reverse_country_code(pt[0], pt[1], session)
                if cc:
                    last_cc = cc
            except requests.RequestException as e:
                print(f"Reverse geocoding failed for {pt}: {e}", file=sys.stderr)

            last_rev = pt
            time.sleep(1.1)

        if last_cc:
            country_points.setdefault(last_cc, []).append(pt)

    return country_points


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def profile_description(profile_id):
    return SEARCH_PROFILES[profile_id]["description"]


def profile_terms_for_country(profile_id, country_code):
    profile = SEARCH_PROFILES[profile_id]
    terms = []
    tmap = profile.get("terms") or {}

    if country_code in tmap:
        terms.extend(tmap[country_code])

    terms.extend(tmap.get("EN", []))

    dedup = []
    seen = set()
    for term in terms:
        k = term.lower()
        if k not in seen:
            seen.add(k)
            dedup.append(term)

    return dedup


def build_query(points, max_km, profile_id, country_code):
    profile = SEARCH_PROFILES[profile_id]
    radius_m = int(max_km * 1000)
    lines = []

    for lat, lon in points:
        selectors = [
            f"node(around:{radius_m},{lat},{lon})",
            f"way(around:{radius_m},{lat},{lon})",
            f"relation(around:{radius_m},{lat},{lon})",
        ]

        for sel in selectors:
            for tag in profile["tags"]:
                key = tag["key"]
                value = tag["value"]
                condition = f'["{key}"]' if value == "*" else f'["{key}"="{value}"]'
                if "and" in tag:
                    for extra in (tag["and"] if isinstance(tag["and"], list) else [tag["and"]]):
                        ek, ev = extra["key"], extra["value"]
                        condition += f'["{ek}"]' if ev == "*" else f'["{ek}"="{ev}"]'
                lines.append(f'{sel}{condition};')

    terms = profile_terms_for_country(profile_id, country_code)
    regex = "|".join(re.escape(t) for t in terms)

    if regex:
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

    if not lines:
        raise ValueError(
            f"No Overpass query could be built for profile {profile_id!r} "
            f"({profile_description(profile_id)!r}; no tag filters and no terms for this segment). "
            f"Add non-empty 'terms' in the profile, or tag filters."
        )

    return "[out:json][timeout:180];\n(\n" + "\n".join(lines) + "\n);\nout center tags;\n"


def query_overpass(session, query, profile_id, verbose=False, progress=None):
    behavior = {**DEFAULT_QUERY_BEHAVIOR, **PROFILE_QUERY_BEHAVIOR.get(profile_id, {})}
    max_retries = behavior["retries"]

    headers = {"User-Agent": USER_AGENT}
    last_error = None
    urls = OVERPASS_URLS

    for base_url in urls:
        for attempt in range(max_retries):
            try:
                if progress is not None:
                    progress["endpoint"] = base_url
                    progress["attempt"] = attempt + 1
                    progress["max_retries"] = max_retries
                r = session.post(base_url, data={"data": query}, headers=headers, timeout=240)
                content_type = r.headers.get("content-type", "")
                if r.ok and "json" in content_type.lower():
                    try:
                        return r.json()
                    except json.JSONDecodeError as e:
                        last_error = e
                        body = r.text[:4000]
                        print(
                            f"Invalid JSON from Overpass at {base_url} "
                            f"(attempt {attempt + 1}/{max_retries}): {e}",
                            file=sys.stderr,
                        )
                        if verbose:
                            print(body[:1000], file=sys.stderr)
                        wait_s = min(60, 5 * (2 ** attempt))
                        time.sleep(wait_s)
                        continue

                body = r.text[:4000]
                busy = (
                        r.status_code in (429, 500, 502, 504)
                        or "too busy" in body.lower()
                        or "timeout" in body.lower()
                )

                if busy:
                    last_error = RuntimeError(
                        f"Overpass busy at {base_url} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    wait_s = min(60, 5 * (2 ** attempt))
                    print(
                        f"Overpass busy at {base_url} "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait_s}s...",
                        file=sys.stderr,
                    )
                    if verbose:
                        print(body[:1000], file=sys.stderr)
                    time.sleep(wait_s)
                    continue

                if verbose:
                    print(body, file=sys.stderr)
                r.raise_for_status()
                last_error = RuntimeError(
                    f"Unexpected response from {base_url} (status {r.status_code}, not JSON)"
                )
                wait_s = min(60, 5 * (2 ** attempt))
                time.sleep(wait_s)

            except requests.RequestException as e:
                last_error = e
                wait_s = min(60, 5 * (2 ** attempt))
                print(
                    f"Request failed at {base_url} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}",
                    file=sys.stderr,
                )
                time.sleep(wait_s)

    if last_error:
        raise last_error
    raise RuntimeError("All Overpass endpoints failed")


def element_latlon(el):
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return center["lat"], center["lon"]
    return None, None


def min_distance_to_track_km(lat, lon, track_points, coarse_step=30):
    best_idx = 0
    best = float("inf")

    for i in range(0, len(track_points), coarse_step):
        d = haversine_km(lat, lon, track_points[i][0], track_points[i][1])
        if d < best:
            best = d
            best_idx = i

    start = max(0, best_idx - 5 * coarse_step)
    end = min(len(track_points), best_idx + 5 * coarse_step + 1)

    for i in range(start, end):
        d = haversine_km(lat, lon, track_points[i][0], track_points[i][1])
        if d < best:
            best = d

    return best


def choose_name(tags, profile_id):
    desc = profile_description(profile_id)
    for key in ("name", "official_name", "short_name", "brand", "operator"):
        val = tags.get(key, "").strip()
        if val:
            return val

    for tag in SEARCH_PROFILES[profile_id]["tags"]:
        if tag["value"] != "*" and tags.get(tag["key"]) == tag["value"]:
            return f"{desc} ({tag['key']}={tag['value']})"

    return desc


def choose_kind(tags, profile_id):
    desc = profile_description(profile_id)
    matches = []

    for tag in SEARCH_PROFILES[profile_id]["tags"]:
        key = tag["key"]
        value = tag["value"]
        if value == "*":
            if key in tags:
                matches.append(f"{key}={tags[key]}")
        elif tags.get(key) == value:
            matches.append(f"{key}={value}")

    if matches:
        return f"{desc} [{', '.join(matches[:3])}]"
    return desc


def extract_candidates(data, track_points, max_km, profile_id):
    dedup = OrderedDict()

    for el in data.get("elements", []):
        lat, lon = element_latlon(el)
        if lat is None or lon is None:
            continue

        tags = el.get("tags", {})
        d = min_distance_to_track_km(lat, lon, track_points)

        if d > max_km:
            continue

        key = (round(lat, 5), round(lon, 5))
        if key in dedup:
            continue

        dedup[key] = {
            "lat": lat,
            "lon": lon,
            "name": choose_name(tags, profile_id),
            "kind": choose_kind(tags, profile_id),
            "distance_km": d,
            "tags": tags,
        }

    return list(dedup.values())


def remove_tracks_and_routes(root):
    """Drop <trk> and <rte> so the output file stays small (waypoints only)."""
    trk_tag = f"{{{GPX_NS}}}trk"
    rte_tag = f"{{{GPX_NS}}}rte"
    for child in list(root):
        if child.tag in (trk_tag, rte_tag):
            root.remove(child)


def add_waypoints_to_gpx(root, items, profile_id):
    symbol = SEARCH_PROFILES[profile_id].get("symbol", "Pin")
    pdesc = profile_description(profile_id)

    for item in items:
        wpt = ET.Element(f"{{{GPX_NS}}}wpt", lat=f"{item['lat']:.6f}", lon=f"{item['lon']:.6f}")

        name_el = ET.SubElement(wpt, f"{{{GPX_NS}}}name")
        name_el.text = item["name"]

        type_el = ET.SubElement(wpt, f"{{{GPX_NS}}}type")
        type_el.text = pdesc

        desc_el = ET.SubElement(wpt, f"{{{GPX_NS}}}desc")
        desc_el.text = f"{item['kind']}; approx {item['distance_km']:.1f} km from track"

        sym_el = ET.SubElement(wpt, f"{{{GPX_NS}}}sym")
        sym_el.text = symbol

        root.append(wpt)


def print_available_profiles():
    print("Available profiles (use id on the CLI):")
    for pid in SEARCH_PROFILES:
        pdata = SEARCH_PROFILES[pid]
        defaults = PROFILE_DEFAULTS.get(pid, {})
        print(
            f"  - {pid} — {pdata['description']}"
            f"  [max_km={defaults.get('max_km')}, "
            f"sample_km={defaults.get('sample_km')}, "
            f"batch_size={defaults.get('batch_size')}]"
        )


def resolve_profile_params(profile_id, args):
    fallback = {"max_km": 10.0, "sample_km": 20.0, "batch_size": 4}
    defaults = {**fallback, **PROFILE_DEFAULTS.get(profile_id, {})}

    max_km = args.max_km if args.max_km is not None else defaults["max_km"]
    sample_km = args.sample_km if args.sample_km is not None else defaults["sample_km"]
    batch_size = args.batch_size if args.batch_size is not None else defaults["batch_size"]

    return max_km, sample_km, batch_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_gpx", nargs="?", help="Input GPX with track")
    ap.add_argument("output_gpx", nargs="?", help="Output GPX with added POI waypoints")
    ap.add_argument(
        "--profile",
        help="Profile id (see --list-profiles), e.g. camping or playground; case-insensitive",
    )

    ap.add_argument("--sample-km", type=float, default=None, help="Track sampling spacing in km")
    ap.add_argument("--max-km", type=float, default=None, help="Max distance from track in km")
    ap.add_argument("--country-sample-km", type=float, default=40.0, help="Reverse geocode spacing in km (default: 40)")
    ap.add_argument("--batch-size", type=int, default=None, help="Overpass query batch size")
    ap.add_argument("--list-profiles", action="store_true", help="List supported search profiles and exit")
    ap.add_argument("--verbose", action="store_true", help="Show verbose Overpass error bodies")
    ap.add_argument(
        "--progress-interval",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Print progress to stderr every SEC seconds during Nominatim/Overpass (default: 5; 0 disables)",
    )
    args = ap.parse_args()

    if args.list_profiles:
        print_available_profiles()
        return

    if not args.input_gpx or not args.output_gpx or not args.profile:
        ap.error("input_gpx, output_gpx and --profile are required unless --list-profiles is used")

    profile_id = args.profile.strip().lower()
    if profile_id not in SEARCH_PROFILES:
        print(f"Unknown profile: {args.profile}", file=sys.stderr)
        print_available_profiles()
        sys.exit(2)

    max_km, sample_km, batch_size = resolve_profile_params(profile_id, args)

    tree, root, track_points = parse_gpx_trackpoints(args.input_gpx)
    sampled = sample_track_by_distance(track_points, spacing_km=sample_km)
    session = requests.Session()

    print(f"Loaded {len(track_points)} track points.")
    print(f"Sampled to {len(sampled)} points at ~{sample_km} km spacing.")
    print(f"Profile: {profile_id} ({profile_description(profile_id)})")
    print(f"Using max_km={max_km}, sample_km={sample_km}, batch_size={batch_size}")

    progress_state = {
        "phase": "nominatim",
        "pois_found": 0,
        "endpoint": None,
        "attempt": None,
        "max_retries": None,
        "batch": (0, 0),
        "country": "",
    }

    hb_ctx = None
    if args.progress_interval and args.progress_interval > 0:
        hb_ctx = ProgressHeartbeat(progress_state, interval=args.progress_interval)

    if hb_ctx:
        with hb_ctx:
            country_segments = detect_country_segments(
                sampled,
                session,
                min_spacing_for_reverse_km=args.country_sample_km,
                progress=progress_state,
            )
    else:
        country_segments = detect_country_segments(
            sampled,
            session,
            min_spacing_for_reverse_km=args.country_sample_km,
            progress=None,
        )

    if not country_segments:
        country_segments = OrderedDict([("EN", sampled)])

    total_batches = sum(
        (len(pts) + batch_size - 1) // batch_size for pts in country_segments.values()
    )
    batch_num = 0

    all_candidates = OrderedDict()

    def run_overpass_batches():
        nonlocal batch_num
        for cc, pts in country_segments.items():
            for batch in chunked(pts, batch_size):
                batch_num += 1
                progress_state["phase"] = "overpass"
                progress_state["country"] = cc
                progress_state["batch"] = (batch_num, total_batches)

                query = build_query(batch, max_km, profile_id, cc)
                data = query_overpass(
                    session,
                    query,
                    profile_id,
                    verbose=args.verbose,
                    progress=progress_state,
                )
                candidates = extract_candidates(data, track_points, max_km, profile_id)

                for item in candidates:
                    key = (round(item["lat"], 5), round(item["lon"], 5))
                    if key not in all_candidates:
                        all_candidates[key] = item

                progress_state["pois_found"] = len(all_candidates)
                time.sleep(1.0)

    if hb_ctx:
        with ProgressHeartbeat(progress_state, interval=args.progress_interval):
            run_overpass_batches()
    else:
        run_overpass_batches()

    items = sorted(all_candidates.values(), key=lambda x: (x["distance_km"], x["name"].lower()))

    print(f"\nAdding {len(items)} waypoints.")
    add_waypoints_to_gpx(root, items, profile_id)
    remove_tracks_and_routes(root)
    tree.write(args.output_gpx, encoding="utf-8", xml_declaration=True)
    print(f"Wrote: {args.output_gpx}")


if __name__ == "__main__":
    main()