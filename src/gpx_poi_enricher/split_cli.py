"""CLI: add evenly-spaced split waypoints along a GPX track."""

from __future__ import annotations

import sys

import gpxpy
import gpxpy.gpx


def _collect_track_points(gpx):
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            points.extend(segment.points)
    if len(points) < 2:
        raise ValueError("GPX must contain at least 2 track points.")
    return points


def _cumulative_lengths(points):
    cum = [0.0]
    total = 0.0
    for i in range(1, len(points)):
        total += points[i - 1].distance_2d(points[i])
        cum.append(total)
    return cum


def _interpolate(a, b, t):
    lat = a.latitude + t * (b.latitude - a.latitude)
    lon = a.longitude + t * (b.longitude - a.longitude)
    if a.elevation is not None and b.elevation is not None:
        ele = a.elevation + t * (b.elevation - a.elevation)
    else:
        ele = a.elevation if a.elevation is not None else b.elevation
    return gpxpy.gpx.GPXWaypoint(latitude=lat, longitude=lon, elevation=ele)


def _point_at_distance(points, cum, target):
    if target <= 0:
        return gpxpy.gpx.GPXWaypoint(
            latitude=points[0].latitude,
            longitude=points[0].longitude,
            elevation=points[0].elevation,
        )
    if target >= cum[-1]:
        return gpxpy.gpx.GPXWaypoint(
            latitude=points[-1].latitude,
            longitude=points[-1].longitude,
            elevation=points[-1].elevation,
        )
    for i in range(1, len(cum)):
        if cum[i] >= target:
            seg_len = cum[i] - cum[i - 1]
            if seg_len == 0:
                return gpxpy.gpx.GPXWaypoint(
                    latitude=points[i].latitude,
                    longitude=points[i].longitude,
                    elevation=points[i].elevation,
                )
            t = (target - cum[i - 1]) / seg_len
            return _interpolate(points[i - 1], points[i], t)
    return gpxpy.gpx.GPXWaypoint(
        latitude=points[-1].latitude,
        longitude=points[-1].longitude,
        elevation=points[-1].elevation,
    )


def add_split_waypoints(input_file: str, output_file: str, segments: int = 10) -> None:
    with open(input_file, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    points = _collect_track_points(gpx)
    cum = _cumulative_lengths(points)
    total = cum[-1]

    out_gpx = gpxpy.gpx.GPX()
    for i in range(1, segments):
        frac = i / segments
        wpt = _point_at_distance(points, cum, total * frac)
        wpt.name = f"Split {i}"
        wpt.description = f"{frac * 100:.1f}% of track length"
        out_gpx.waypoints.append(wpt)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(out_gpx.to_xml())


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print(f"Usage: {sys.argv[0]} input.gpx output.gpx [segments]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    segments = int(sys.argv[3]) if len(sys.argv) == 4 else 10

    if segments < 2:
        raise ValueError("segments must be >= 2")

    add_split_waypoints(input_file, output_file, segments)


if __name__ == "__main__":
    main()
