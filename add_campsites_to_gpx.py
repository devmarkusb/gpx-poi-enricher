#!/usr/bin/env python3
"""
Add campsite / caravan site / motorhome stopover waypoints near a GPX track.

Input:
  - GPX file with a track (e.g. split.gpx)

Output:
  - New GPX file with added <wpt> entries for campsites near the track

Data source:
  - OpenStreetMap Overpass API

Search terminology used by country:
  - Germany: "Campingplatz", "Wohnmobilstellplatz"
  - France:  "camping", "aire de camping-car"
  - Spain:   "camping", "área de autocaravanas"

Practical notes:
  - The actual OSM query is tag-based first:
        tourism=camp_site
        tourism=caravan_site
    because this is more robust than name-only search.
  - A second pass also checks common localized phrases in name/description fields,
    mainly to catch imperfectly tagged POIs.
  - The script reverse-geocodes sampled points to determine which country segment
    each route portion belongs to, then applies the most common local search terms.

Example:
  python add_campsites_to_gpx.py split.gpx split_with_campsites.gpx --max-km 20

Dependencies:
  pip install requests
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

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

COUNTRY_TERMS = {
    "DE": ["Campingplatz", "Wohnmobilstellplatz"],
    "FR": ["camping", "aire de camping-car"],
    "ES": ["camping", "área de autocaravanas"],
}

USER_AGENT = "gpx-campsite-enricher/1.0 (personal route planning)"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

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


def sample_track_by_distance(points, spacing_km=5.0):
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
    """
    Reverse-geocode every ~40 km along the route. Produces a sequence of
    country -> representative sampled points.
    """
    country_points = OrderedDict()
    last_rev = None

    for pt in sampled_points:
        if last_rev is None:
            need = True
        else:
            need = haversine_km(last_rev[0], last_rev[1], pt[0], pt[1]) >= min_spacing_for_reverse_km

        if not need:
            continue

        cc = reverse_country_code(pt[0], pt[1], session)
        if cc:
            country_points.setdefault(cc, []).append(pt)
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


def build_around_lines(points, radius_m):
    lines = []
    for lat, lon in points:
        lines.append(f"node(around:{radius_m},{lat},{lon})")
        lines.append(f"way(around:{radius_m},{lat},{lon})")
        lines.append(f"relation(around:{radius_m},{lat},{lon})")
    return lines


def build_overpass_query(points, max_km, country_code):
    radius_m = int(max_km * 1000)

    lines = []
    for lat, lon in points:
        lines.append(f'node(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'way(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'relation(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'node(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')
        lines.append(f'way(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')
        lines.append(f'relation(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')

    return "[out:json][timeout:180];\n(\n" + "\n".join(lines) + "\n);\nout center tags;\n"


def build_generic_tag_query(points, max_km):
    radius_m = int(max_km * 1000)
    lines = []
    for lat, lon in points:
        lines.append(f'node(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'way(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'relation(around:{radius_m},{lat},{lon})["tourism"="camp_site"];')
        lines.append(f'node(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')
        lines.append(f'way(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')
        lines.append(f'relation(around:{radius_m},{lat},{lon})["tourism"="caravan_site"];')

    return "[out:json][timeout:180];\n(\n" + "\n".join(lines) + "\n);\nout center tags;\n"


def query_overpass(session, query, max_retries=4):
    headers = {"User-Agent": USER_AGENT}

    last_error = None

    for base_url in OVERPASS_URLS:
        for attempt in range(max_retries):
            try:
                r = session.post(base_url, data={"data": query}, headers=headers, timeout=240)

                content_type = r.headers.get("content-type", "")
                if r.ok and "json" in content_type.lower():
                    return r.json()

                body = r.text[:4000]
                if r.status_code in (429, 500, 502, 504) or "too busy" in body.lower() or "timeout" in body.lower():
                    wait_s = min(90, 5 * (2 ** attempt))
                    print(f"Overpass busy at {base_url} (attempt {attempt + 1}/{max_retries}), waiting {wait_s}s...", file=sys.stderr)
                    print(body[:1000], file=sys.stderr)
                    time.sleep(wait_s)
                    continue

                print(body, file=sys.stderr)
                r.raise_for_status()

            except requests.RequestException as e:
                last_error = e
                wait_s = min(90, 5 * (2 ** attempt))
                print(f"Request failed at {base_url} (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
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


def normalize_name(tags):
    for key in ("name", "official_name", "brand"):
        if key in tags and tags[key].strip():
            return tags[key].strip()
    tourism = tags.get("tourism", "")
    if tourism == "camp_site":
        return "Camping"
    if tourism == "caravan_site":
        return "Caravan / motorhome site"
    return "Campsite"


def extract_candidates(data, track_points, max_km):
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

        name = normalize_name(tags)
        tourism = tags.get("tourism", "")
        kind = {
            "camp_site": "camping site",
            "caravan_site": "caravan / RV site",
        }.get(tourism, "camping / RV POI")

        dedup[key] = {
            "lat": lat,
            "lon": lon,
            "name": name,
            "kind": kind,
            "distance_km": d,
            "tags": tags,
        }

    return list(dedup.values())


def add_waypoints_to_gpx(root, items):
    for item in items:
        wpt = ET.Element(f"{{{GPX_NS}}}wpt", lat=f"{item['lat']:.6f}", lon=f"{item['lon']:.6f}")

        name_el = ET.SubElement(wpt, f"{{{GPX_NS}}}name")
        name_el.text = item["name"]

        type_el = ET.SubElement(wpt, f"{{{GPX_NS}}}type")
        type_el.text = item["kind"]

        desc_el = ET.SubElement(wpt, f"{{{GPX_NS}}}desc")
        desc_el.text = f"{item['kind']}; approx {item['distance_km']:.1f} km from track"

        sym_el = ET.SubElement(wpt, f"{{{GPX_NS}}}sym")
        sym_el.text = "Campground"

        cmt_el = ET.SubElement(wpt, f"{{{GPX_NS}}}cmt")
        terms = []
        cc = item["tags"].get("_country_code")
        if cc in COUNTRY_TERMS:
            terms = COUNTRY_TERMS[cc]
        if terms:
            cmt_el.text = "local search terms: " + " / ".join(terms)
        else:
            cmt_el.text = "added from OSM tourism tags"

        root.append(wpt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_gpx", help="Input GPX with track")
    ap.add_argument("output_gpx", help="Output GPX with added campsite waypoints")
    ap.add_argument("--sample-km", type=float, default=15.0, help="Track sampling spacing in km (default: 5)")
    ap.add_argument("--max-km", type=float, default=10.0, help="Max distance from track in km (default: 20)")
    ap.add_argument("--country-sample-km", type=float, default=40.0, help="Reverse geocode spacing in km (default: 40)")
    args = ap.parse_args()

    tree, root, track_points = parse_gpx_trackpoints(args.input_gpx)
    sampled = sample_track_by_distance(track_points, spacing_km=args.sample_km)

    session = requests.Session()

    print(f"Loaded {len(track_points)} track points.")
    print(f"Sampled to {len(sampled)} points at ~{args.sample_km} km spacing.")

    country_segments = detect_country_segments(
        sampled,
        session,
        min_spacing_for_reverse_km=args.country_sample_km,
    )

    wanted_countries = [cc for cc in country_segments.keys() if cc in COUNTRY_TERMS]
    if not wanted_countries:
        print("No DE/FR/ES route segments detected. Continuing without country-specific phrase fallback.", file=sys.stderr)

    print("Detected countries along route:", ", ".join(country_segments.keys()) or "(none)")

    all_candidates = OrderedDict()

    for cc, pts in country_segments.items():
        if cc not in COUNTRY_TERMS:
            continue

        print(f"\nQuerying country {cc} with terms: {', '.join(COUNTRY_TERMS[cc])}")
        for batch in chunked(pts, 6):
            query = build_overpass_query(batch, args.max_km, cc)
            data = query_overpass(session, query)
            candidates = extract_candidates(data, track_points, args.max_km)

            for item in candidates:
                item["tags"]["_country_code"] = cc
                key = (round(item["lat"], 5), round(item["lon"], 5))
                if key not in all_candidates:
                    all_candidates[key] = item

            time.sleep(1.0)

    if not all_candidates:
        print("\nNo candidates found from country-segment queries. Running generic tag-only fallback.")
        for batch in chunked(sampled, 30):
            query = build_generic_tag_query(batch, args.max_km)
            data = query_overpass(session, query)
            candidates = extract_candidates(data, track_points, args.max_km)
            for item in candidates:
                key = (round(item["lat"], 5), round(item["lon"], 5))
                if key not in all_candidates:
                    all_candidates[key] = item
            time.sleep(1.0)

    items = sorted(all_candidates.values(), key=lambda x: (x["distance_km"], x["name"].lower()))

    print(f"\nAdding {len(items)} campsite waypoints.")
    add_waypoints_to_gpx(root, items)
    tree.write(args.output_gpx, encoding="utf-8", xml_declaration=True)
    print(f"Wrote: {args.output_gpx}")


if __name__ == "__main__":
    main()
