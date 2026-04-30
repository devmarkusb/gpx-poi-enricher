"""Tests for milestone / split waypoint helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import gpxpy
import gpxpy.gpx

from gpx_poi_enricher.split_cli import add_split_waypoints, milestone_label, milestone_sidecar_path


def _minimal_track_gpx(path: Path) -> None:
    gpx = gpxpy.gpx.GPX()
    t = gpxpy.gpx.GPXTrack()
    s = gpxpy.gpx.GPXTrackSegment()
    s.points.append(gpxpy.gpx.GPXTrackPoint(latitude=0.0, longitude=0.0))
    s.points.append(gpxpy.gpx.GPXTrackPoint(latitude=0.0, longitude=1.0))
    t.segments.append(s)
    gpx.tracks.append(t)
    path.write_text(gpx.to_xml(), encoding="utf-8")


def test_milestone_labels_and_counts() -> None:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.gpx"
        out = Path(td) / "out.gpx"
        _minimal_track_gpx(src)
        add_split_waypoints(str(src), str(out), segments=10)
        got = gpxpy.parse(out.read_text(encoding="utf-8"))
        names = [w.name for w in got.waypoints]
        assert len(names) == 10
        assert names[0] == milestone_label(1, 10)
        assert names[-1] == milestone_label(10, 10)
        assert len(got.tracks) == 0


def test_milestone_sidecar_path() -> None:
    assert milestone_sidecar_path("/tmp/a-b-full-02.gpx") == "/tmp/a-b-full-02-milestones.gpx"


def test_sidecar_has_no_track() -> None:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "Paris-Lyon-detour-02.gpx"
        _minimal_track_gpx(src)
        side = milestone_sidecar_path(src)
        add_split_waypoints(str(src), side, 3)
        g = gpxpy.parse(Path(side).read_text(encoding="utf-8"))
        assert len(g.waypoints) == 3
        assert len(g.tracks) == 0
