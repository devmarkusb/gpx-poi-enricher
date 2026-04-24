"""Command-line interface for gpx-poi-enricher."""

from __future__ import annotations

import argparse
import sys

from .enricher import enrich_gpx_file
from .profiles import load_all_profiles, load_profile


def _list_profiles() -> None:
    profiles = load_all_profiles()
    print("Available profiles (pass the id with --profile):\n")
    for p in profiles.values():
        print(
            f"  {p.id:<22} {p.description}\n"
            f"  {'':22} max_km={p.max_km}  sample_km={p.sample_km}  "
            f"batch_size={p.batch_size}  retries={p.retries}\n"
        )


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="gpx-poi-enricher",
        description=(
            "Enrich a GPX track with Points of Interest from OpenStreetMap.\n\n"
            "Examples:\n"
            "  gpx-poi-enricher route.gpx camping.gpx --profile camping\n"
            "  gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5\n"
            "  gpx-poi-enricher --list-profiles"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("input_gpx", nargs="?", help="Input GPX file with a track")
    ap.add_argument("output_gpx", nargs="?", help="Output GPX file (waypoints only)")
    ap.add_argument("--profile", help="Profile id, e.g. camping or playground (case-insensitive)")
    ap.add_argument(
        "--max-km", type=float, default=None, help="Override max distance from track (km)"
    )
    ap.add_argument(
        "--sample-km", type=float, default=None, help="Override track sampling interval (km)"
    )
    ap.add_argument(
        "--batch-size", type=int, default=None, help="Override Overpass query batch size"
    )
    ap.add_argument(
        "--country-sample-km",
        type=float,
        default=None,
        help="Min distance (km) between Nominatim reverse-geocode calls (default: 40)",
    )
    ap.add_argument(
        "--progress-interval",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Print progress to stderr every SEC seconds (default: 5; 0 = off)",
    )
    ap.add_argument("--verbose", action="store_true", help="Print verbose Overpass error bodies")
    ap.add_argument("--list-profiles", action="store_true", help="List built-in profiles and exit")
    ap.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Smoke-test mode: sparse sampling (500 km), tiny search radius (1 km), "
            "country re-detection every 500 km. Produces results in seconds. "
            "Individual --sample-km / --max-km / --country-sample-km still override."
        ),
    )
    return ap


# Values applied by --quick when the individual flag was not explicitly set
_QUICK_SAMPLE_KM = 500.0
_QUICK_MAX_KM = 1.0
_QUICK_COUNTRY_KM = 500.0


def main() -> None:
    ap = _build_parser()
    args = ap.parse_args()

    if args.list_profiles:
        _list_profiles()
        return

    if not args.input_gpx or not args.output_gpx or not args.profile:
        ap.error(
            "input_gpx, output_gpx, and --profile are required unless --list-profiles is given"
        )

    profile_id = args.profile.strip().lower()
    try:
        load_profile(profile_id)  # validate early
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.quick:
        if args.sample_km is None:
            args.sample_km = _QUICK_SAMPLE_KM
        if args.max_km is None:
            args.max_km = _QUICK_MAX_KM
        if args.country_sample_km is None:
            args.country_sample_km = _QUICK_COUNTRY_KM

    kwargs = {
        "max_km": args.max_km,
        "sample_km": args.sample_km,
        "batch_size": args.batch_size,
        "country_sample_km": args.country_sample_km or 40.0,
        "progress_interval": args.progress_interval,
        "verbose": args.verbose,
    }

    enrich_gpx_file(args.input_gpx, args.output_gpx, profile_id, **kwargs)


if __name__ == "__main__":
    main()
