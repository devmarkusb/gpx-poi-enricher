#!/usr/bin/env python3
"""
Add configurable POI waypoints near a GPX track.

Examples:
  python add_pois_to_gpx.py split.gpx camping.gpx --profile "Campingplatz"
  python add_pois_to_gpx.py split.gpx spielplaetze.gpx --profile "Spielplatz"
  python add_pois_to_gpx.py split.gpx zoos.gpx --profile "Zoo, Streichelzoo" --max-km 15

Notes:
- The route is sampled, then representative route points are reverse-geocoded to detect country
  segments (DE / FR / ES / others).
- Queries are sent to Overpass in small batches with retries and endpoint fallback.
- Search is tag-first. Fuzzy categories can optionally also use localized text fallback terms.
- Profile-specific defaults are applied unless explicitly overridden on the command line.
"""

import argparse
import math
import sys
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

COUNTRY_LABELS = {
    "DE": "Germany",
    "FR": "France",
    "ES": "Spain",
    "EN": "Generic",
}

SEARCH_PROFILES = {
    "Campingplatz": {
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
        "fuzzy": True,
        "symbol": "Campground",
    },
    "Spielplatz": {
        "tags": [
            {"key": "leisure", "value": "playground"},
        ],
        "terms": {
            "DE": ["Spielplatz", "Abenteuerspielplatz", "Wasserspielplatz"],
            "FR": ["aire de jeux", "terrain de jeux", "parc de jeux"],
            "ES": ["parque infantil", "zona de juegos", "área de juegos"],
            "EN": ["playground", "children playground"],
        },
        "fuzzy": False,
        "symbol": "Playground",
    },
    "Freibad, Erlebnisbad, Thermalbad": {
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
        "fuzzy": True,
        "symbol": "Swimming Area",
    },
    "Badesee, Strand": {
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
        "fuzzy": True,
        "symbol": "Beach",
    },
    "Freizeitpark": {
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
        "fuzzy": True,
        "symbol": "Amusement Park",
    },
    "Zoo, Streichelzoo": {
        "tags": [
            {"key": "tourism", "value": "zoo"},
            {"key": "animal", "value": "petting_zoo"},
        ],
        "terms": {
            "DE": ["Zoo", "Tierpark", "Streichelzoo"],
            "FR": ["zoo", "parc animalier", "ferme pédagogique"],
            "ES": ["zoológico", "parque zoológico", "granja escuela"],
            "EN": ["zoo", "petting zoo", "animal park"],
        },
        "fuzzy": True,
        "symbol": "Zoo",
    },
    "Aquarium": {
        "tags": [
            {"key": "tourism", "value": "aquarium"},
        ],
        "terms": {
            "DE": ["Aquarium"],
            "FR": ["aquarium"],
            "ES": ["acuario"],
            "EN": ["aquarium"],
        },
        "fuzzy": False,
        "symbol": "Aquarium",
    },
    "McDonalds": {
        "tags": [
            {"key": "amenity", "value": "fast_food"},
            {"key": "brand", "value": "McDonald's"},
            {"key": "name", "value": "McDonald's"},
            {"key": "brand:wikidata", "value": "Q38076"},
        ],
        "terms": {
            "DE": ["McDonald's", "McDonalds"],
            "FR": ["McDonald's", "McDo"],
            "ES": ["McDonald's"],
            "EN": ["McDonald's"],
        },
        "fuzzy": True,
        "symbol": "Fast Food",
    },
    "Restaurant mit Kinderkarte": {
        "tags": [
            {"key": "amenity", "value": "restaurant"},
        ],
        "terms": {
            "DE": ["Kinderkarte", "Familienrestaurant", "kinderfreundlich"],
            "FR": ["menu enfant", "restaurant familial", "adapté aux enfants"],
            "ES": ["menú infantil", "restaurante familiar", "apto para niños"],
            "EN": ["kids menu", "family restaurant", "child friendly restaurant"],
        },
        "fuzzy": True,
        "symbol": "Restaurant",
    },
    "Kinder Erlebnis aller Art": {
        "tags": [
        ],
        "terms": {
            "DE": ["Kindererlebnis", "Erlebniswelt", "Familienpark", "Indoor Spielplatz"],
            "FR": ["parc de loisirs", "activité enfant", "parc familial", "aire de jeux couverte"],
            "ES": ["parque de ocio", "actividad infantil", "parque familiar", "parque infantil cubierto"],
            "EN": ["kids attraction", "family attraction", "indoor playground", "children activity"],
        },
        "fuzzy": True,
        "symbol": "Scenic Area",
    },
    "allgemein spektakuläre kindertaugliche Sehenswürdigkeit": {
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
        "fuzzy": True,
        "symbol": "Scenic Area",
    },
}

ALIASES = {
    "camping": "Campingplatz",
    "campingplatz": "Campingplatz",
    "spielplatz": "Spielplatz",
    "freibad": "Freibad, Erlebnisbad, Thermalbad",
    "erlebnisbad": "Freibad, Erlebnisbad, Thermalbad",
    "thermalbad": "Freibad, Erlebnisbad, Thermalbad",
    "badesee": "Badesee, Strand",
    "strand": "Badesee, Strand",
    "freizeitpark": "Freizeitpark",
    "zoo": "Zoo, Streichelzoo",
    "streichelzoo": "Zoo, Streichelzoo",
    "aquarium": "Aquarium",
    "mcdonalds": "McDonalds",
    "restaurant": "Restaurant mit Kinderkarte",
    "kindererlebnis": "Kinder Erlebnis aller Art",
    "sehenswürdigkeit": "allgemein spektakuläre kindertaugliche Sehenswürdigkeit",
}

PROFILE_DEFAULTS = {
    "Campingplatz": {"max_km": 10.0, "sample_km": 12.0, "batch_size": 6},
    "Spielplatz": {"max_km": 3.0, "sample_km": 25.0, "batch_size": 4},
    "Freibad, Erlebnisbad, Thermalbad": {"max_km": 10.0, "sample_km": 20.0, "batch_size": 4},
    "Badesee, Strand": {"max_km": 10.0, "sample_km": 20.0, "batch_size": 4},
    "Freizeitpark": {"max_km": 10.0, "sample_km": 30.0, "batch_size": 3},
    "Zoo, Streichelzoo": {"max_km": 15.0, "sample_km": 20.0, "batch_size": 4},
    "Aquarium": {"max_km": 15.0, "sample_km": 20.0, "batch_size": 4},
    "McDonalds": {"max_km": 5.0, "sample_km": 20.0, "batch_size": 4},
    "Restaurant mit Kinderkarte": {"max_km": 8.0, "sample_km": 20.0, "batch_size": 4},
    "Kinder Erlebnis aller Art": {"max_km": 15.0, "sample_km": 20.0, "batch_size": 4},
    "allgemein spektakuläre kindertaugliche Sehenswürdigkeit": {"max_km": 20.0, "sample_km": 30.0, "batch_size": 3},
}

PROFILE_QUERY_BEHAVIOR = {
    "Campingplatz": {"retries": 3, "endpoints": 3, "allow_empty_on_failure": False},
    "Spielplatz": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": True},
    "Freibad, Erlebnisbad, Thermalbad": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": True},
    "Badesee, Strand": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": True},
    "Freizeitpark": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": False},
    "Zoo, Streichelzoo": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": False},
    "Aquarium": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": False},
    "McDonalds": {"retries": 2, "endpoints": 2, "allow_empty_on_failure": True},
    "Restaurant mit Kinderkarte": {"retries": 3, "endpoints": 3, "allow_empty_on_failure": True},
    "Kinder Erlebnis aller Art": {"retries": 3, "endpoints": 3, "allow_empty_on_failure": True},
    "allgemein spektakuläre kindertaugliche Sehenswürdigkeit": {"retries": 3, "endpoints": 3, "allow_empty_on_failure": True},
}

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


def detect_country_segments(sampled_points, session, min_spacing_for_reverse_km=40.0):
    country_points = OrderedDict()
    last_rev = None

    for pt in sampled_points:
        if last_rev is None:
            need = True
        else:
            need = haversine_km(last_rev[0], last_rev[1], pt[0], pt[1]) >= min_spacing_for_reverse_km

        if not need:
            continue

        try:
            cc = reverse_country_code(pt[0], pt[1], session)
            if cc:
                country_points.setdefault(cc, []).append(pt)
        except requests.RequestException as e:
            print(f"Reverse geocoding failed for {pt}: {e}", file=sys.stderr)

        last_rev = pt
        time.sleep(1.1)

    return country_points


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def escape_overpass_regex(s):
    special = r'\\.^$|?*+()[]{}'
    out = []
    for ch in s:
        if ch in special:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def canonical_profile_name(name):
    if name in SEARCH_PROFILES:
        return name
    return ALIASES.get(name.strip().lower(), name)


def profile_terms_for_country(profile_name, country_code):
    profile = SEARCH_PROFILES[profile_name]
    terms = []

    if country_code in profile["terms"]:
        terms.extend(profile["terms"][country_code])

    terms.extend(profile["terms"].get("EN", []))

    dedup = []
    seen = set()
    for term in terms:
        k = term.lower()
        if k not in seen:
            seen.add(k)
            dedup.append(term)

    return dedup


def build_query(points, max_km, profile_name, country_code):
    profile = SEARCH_PROFILES[profile_name]
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
                if value == "*":
                    lines.append(f'{sel}["{key}"];')
                else:
                    lines.append(f'{sel}["{key}"="{value}"];')

    terms = profile_terms_for_country(profile_name, country_code)
    regex = "|".join(escape_overpass_regex(t) for t in terms)

    if profile.get("fuzzy") and regex:
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

    return "[out:json][timeout:180];\n(\n" + "\n".join(lines) + "\n);\nout center tags;\n"


def query_overpass(session, query, profile_name, verbose=False):
    behavior = PROFILE_QUERY_BEHAVIOR[profile_name]
    max_retries = behavior["retries"]
    endpoint_count = behavior["endpoints"]
    allow_empty_on_failure = behavior.get("allow_empty_on_failure", False)

    headers = {"User-Agent": USER_AGENT}
    last_error = None
    urls = OVERPASS_URLS[:endpoint_count]

    for base_url in urls:
        for attempt in range(max_retries):
            try:
                r = session.post(base_url, data={"data": query}, headers=headers, timeout=240)
                content_type = r.headers.get("content-type", "")
                if r.ok and "json" in content_type.lower():
                    return r.json()

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

            except requests.RequestException as e:
                last_error = e
                wait_s = min(60, 5 * (2 ** attempt))
                print(
                    f"Request failed at {base_url} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}",
                    file=sys.stderr,
                )
                time.sleep(wait_s)

    if allow_empty_on_failure:
        print("Warning: all Overpass attempts failed for this batch; skipping batch.", file=sys.stderr)
        return {"elements": []}

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


def choose_name(tags, profile_name):
    for key in ("name", "official_name", "short_name", "brand", "operator"):
        val = tags.get(key, "").strip()
        if val:
            return val

    for tag in SEARCH_PROFILES[profile_name]["tags"]:
        if tag["value"] != "*" and tags.get(tag["key"]) == tag["value"]:
            return f"{profile_name} ({tag['key']}={tag['value']})"

    return profile_name


def choose_kind(tags, profile_name):
    matches = []

    for tag in SEARCH_PROFILES[profile_name]["tags"]:
        key = tag["key"]
        value = tag["value"]
        if value == "*":
            if key in tags:
                matches.append(f"{key}={tags[key]}")
        elif tags.get(key) == value:
            matches.append(f"{key}={value}")

    if matches:
        return f"{profile_name} [{', '.join(matches[:3])}]"
    return profile_name


def extract_candidates(data, track_points, max_km, profile_name):
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
            "name": choose_name(tags, profile_name),
            "kind": choose_kind(tags, profile_name),
            "distance_km": d,
            "tags": tags,
        }

    return list(dedup.values())


def add_waypoints_to_gpx(root, items, profile_name):
    symbol = SEARCH_PROFILES[profile_name].get("symbol", "Pin")

    for item in items:
        wpt = ET.Element(f"{{{GPX_NS}}}wpt", lat=f"{item['lat']:.6f}", lon=f"{item['lon']:.6f}")

        name_el = ET.SubElement(wpt, f"{{{GPX_NS}}}name")
        name_el.text = item["name"]

        type_el = ET.SubElement(wpt, f"{{{GPX_NS}}}type")
        type_el.text = profile_name

        desc_el = ET.SubElement(wpt, f"{{{GPX_NS}}}desc")
        desc_el.text = f"{item['kind']}; approx {item['distance_km']:.1f} km from track"

        sym_el = ET.SubElement(wpt, f"{{{GPX_NS}}}sym")
        sym_el.text = symbol

        cmt_el = ET.SubElement(wpt, f"{{{GPX_NS}}}cmt")
        cc = item["tags"].get("_country_code")
        terms = profile_terms_for_country(profile_name, cc) if cc else []
        cmt_el.text = "search terms: " + " / ".join(terms[:6]) if terms else "added from OSM tags"

        root.append(wpt)


def print_available_profiles():
    print("Available profiles:")
    for name in SEARCH_PROFILES:
        defaults = PROFILE_DEFAULTS.get(name, {})
        print(
            f"  - {name}"
            f"  [max_km={defaults.get('max_km')}, "
            f"sample_km={defaults.get('sample_km')}, "
            f"batch_size={defaults.get('batch_size')}]"
        )


def resolve_profile_params(profile_name, args):
    defaults = PROFILE_DEFAULTS[profile_name]

    max_km = args.max_km if args.max_km is not None else defaults["max_km"]
    sample_km = args.sample_km if args.sample_km is not None else defaults["sample_km"]
    batch_size = args.batch_size if args.batch_size is not None else defaults["batch_size"]

    return max_km, sample_km, batch_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_gpx", nargs="?", help="Input GPX with track")
    ap.add_argument("output_gpx", nargs="?", help="Output GPX with added POI waypoints")
    ap.add_argument("--profile", help="What to search for along the route")

    ap.add_argument("--sample-km", type=float, default=None, help="Track sampling spacing in km")
    ap.add_argument("--max-km", type=float, default=None, help="Max distance from track in km")
    ap.add_argument("--country-sample-km", type=float, default=40.0, help="Reverse geocode spacing in km (default: 40)")
    ap.add_argument("--batch-size", type=int, default=None, help="Overpass query batch size")
    ap.add_argument("--list-profiles", action="store_true", help="List supported search profiles and exit")
    ap.add_argument("--verbose", action="store_true", help="Show verbose Overpass error bodies")
    args = ap.parse_args()

    if args.list_profiles:
        print_available_profiles()
        return

    if not args.input_gpx or not args.output_gpx or not args.profile:
        ap.error("input_gpx, output_gpx and --profile are required unless --list-profiles is used")

    profile_name = canonical_profile_name(args.profile)
    if profile_name not in SEARCH_PROFILES:
        print(f"Unknown profile: {args.profile}", file=sys.stderr)
        print_available_profiles()
        sys.exit(2)

    max_km, sample_km, batch_size = resolve_profile_params(profile_name, args)

    tree, root, track_points = parse_gpx_trackpoints(args.input_gpx)
    sampled = sample_track_by_distance(track_points, spacing_km=sample_km)
    session = requests.Session()

    print(f"Loaded {len(track_points)} track points.")
    print(f"Sampled to {len(sampled)} points at ~{sample_km} km spacing.")
    print(f"Profile: {profile_name}")
    print(f"Using max_km={max_km}, sample_km={sample_km}, batch_size={batch_size}")

    country_segments = detect_country_segments(
        sampled,
        session,
        min_spacing_for_reverse_km=args.country_sample_km,
    )

    if not country_segments:
        country_segments = OrderedDict([("EN", sampled)])
        print("No country detection succeeded; falling back to generic EN terms.")
    else:
        print("Detected countries along route:", ", ".join(country_segments.keys()))

    all_candidates = OrderedDict()

    for cc, pts in country_segments.items():
        country_label = COUNTRY_LABELS.get(cc, cc)
        terms_preview = ", ".join(profile_terms_for_country(profile_name, cc)[:4])
        print(f"\nQuerying country {cc} ({country_label}) with terms: {terms_preview or '(tags only)'}")

        for batch in chunked(pts, batch_size):
            query = build_query(batch, max_km, profile_name, cc)
            data = query_overpass(
                session,
                query,
                profile_name=profile_name,
                verbose=args.verbose,
            )
            candidates = extract_candidates(data, track_points, max_km, profile_name)

            for item in candidates:
                item["tags"]["_country_code"] = cc
                key = (round(item["lat"], 5), round(item["lon"], 5))
                if key not in all_candidates:
                    all_candidates[key] = item

            time.sleep(1.0)

    items = sorted(all_candidates.values(), key=lambda x: (x["distance_km"], x["name"].lower()))

    print(f"\nAdding {len(items)} waypoints.")
    add_waypoints_to_gpx(root, items, profile_name)
    tree.write(args.output_gpx, encoding="utf-8", xml_declaration=True)
    print(f"Wrote: {args.output_gpx}")


if __name__ == "__main__":
    main()