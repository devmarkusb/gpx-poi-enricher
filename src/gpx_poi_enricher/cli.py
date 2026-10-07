"""Command-line interface for gpx-poi-enricher."""

from __future__ import annotations

import argparse
import sys

from .enricher import enrich_gpx_file, enrich_point_file
from .profiles import load_all_profiles, load_profile


def _list_profiles() -> None:
    profiles = load_all_profiles()
    print("Available profiles (pass the id with --profile):\n")
    for p in profiles.values():
        ec = (
            "off"
            if not p.early_cancel_if_no_pois
            else f"after {p.early_cancel_after_batches} empty batches"
        )
        print(
            f"  {p.id:<22} {p.description}\n"
            f"  {'':22} max_km={p.max_km}  sample_km={p.sample_km}  "
            f"batch_size={p.batch_size}  retries={p.retries}  early_cancel={ec}\n"
        )


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="gpx-poi-enricher",
        description=(
            "Search around a GPX track or point for Points of Interest from OpenStreetMap.\n\n"
            "Examples:\n"
            "  gpx-poi-enricher route.gpx camping.gpx --profile camping\n"
            "  gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5\n"
            "  gpx-poi-enricher --point '52.038993,13.748653' --output nearby.gpx --profile aquarium\n"
            "  gpx-poi-enricher --list-profiles"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("input_gpx", nargs="?", help="Input GPX file with a track")
    ap.add_argument("output_gpx", nargs="?", help="Output GPX file (waypoints only)")
    ap.add_argument(
        "--point",
        metavar="LAT,LON|MAPS_URL",
        help="Search around coordinates or a Google Maps place link",
    )
    ap.add_argument(
        "--output",
        dest="point_output_gpx",
        help="Output GPX path when using --point",
    )
    ap.add_argument("--profile", help="Profile id, e.g. camping or playground (case-insensitive)")
    ap.add_argument(
        "--max-km",
        type=float,
        default=None,
        help="Override max distance from track or radius around a point (km)",
    )
    ap.add_argument(
        "--sample-km",
        type=float,
        default=None,
        help="Override track sampling interval (unused with --point)",
    )
    ap.add_argument(
        "--batch-size", type=int, default=None, help="Override Overpass query batch size"
    )
    ap.add_argument(
        "--country-sample-km",
        type=float,
        default=None,
        help="Min spacing (km) between track country lookups (default: 40)",
    )
    ap.add_argument(
        "--progress-interval",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Print progress to stderr every SEC seconds (default: 5; 0 = off)",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Print Overpass error bodies (track searches only)",
    )
    ap.add_argument("--list-profiles", action="store_true", help="List built-in profiles and exit")
    ap.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Smoke-test mode: 1 km radius; tracks also use sparse sampling/country checks (500 km). "
            "Produces results in seconds. "
            "Individual --sample-km / --max-km / --country-sample-km still override."
        ),
    )
    ap.add_argument(
        "--checkpoint-each-batch",
        dest="checkpoint_each_batch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After each Overpass batch, overwrite the output GPX with POIs found so far "
            "for track searches (same file as the final result), so partial results survive interruptions. "
            "Enabled by default; pass --no-checkpoint-each-batch to disable."
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

    if args.point is not None:
        if args.input_gpx or args.output_gpx:
            ap.error("With --point, use --output FILE and omit positional GPX paths")
        if not args.point_output_gpx or not args.profile:
            ap.error("--point requires --output FILE and --profile")
    else:
        if args.point_output_gpx:
            ap.error("--output is only used with --point")
        if not args.input_gpx or not args.output_gpx or not args.profile:
            ap.error(
                "input_gpx, output_gpx, and --profile are required unless --point or "
                "--list-profiles is given"
            )

    sample_km_explicit = args.sample_km is not None
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

    if args.point is not None:
        if sample_km_explicit:
            print("Note: --sample-km is ignored for a point search.", file=sys.stderr)
        if args.verbose:
            print("Note: verbose response bodies are disabled for point searches.", file=sys.stderr)
        enrich_point_file(
            args.point,
            args.point_output_gpx,
            profile_id,
            max_km=args.max_km,
            batch_size=args.batch_size,
            progress_interval=args.progress_interval,
            verbose=args.verbose,
        )
        return

    kwargs = {
        "max_km": args.max_km,
        "sample_km": args.sample_km,
        "batch_size": args.batch_size,
        "country_sample_km": args.country_sample_km or 40.0,
        "progress_interval": args.progress_interval,
        "verbose": args.verbose,
    }

    enrich_gpx_file(
        args.input_gpx,
        args.output_gpx,
        profile_id,
        checkpoint_each_batch=args.checkpoint_each_batch,
        **kwargs,
    )


if __name__ == "__main__":
    main()
