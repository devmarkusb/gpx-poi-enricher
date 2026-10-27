"""Command-line argument contracts without live services."""

import sys

import pytest

from gpx_poi_enricher import cli


def test_explicit_zero_country_spacing_is_forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpx-poi-enricher",
            "in.gpx",
            "out.gpx",
            "--profile",
            "camping",
            "--country-sample-km",
            "0",
        ],
    )
    monkeypatch.setattr(cli, "load_profile", lambda *_: None)
    monkeypatch.setattr(cli, "enrich_gpx_file", lambda *a, **kw: calls.append((a, kw)))
    cli.main()
    assert calls[0][1]["country_sample_km"] == 0
    assert calls[0][1]["checkpoint_each_batch"] is True


def test_point_quick_defaults_and_explicit_radius(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "load_profile", lambda *_: None)
    monkeypatch.setattr(cli, "enrich_point_file", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpx-poi-enricher",
            "--point",
            "0,0",
            "--output",
            "out.gpx",
            "--profile",
            "camping",
            "--quick",
            "--max-km",
            "3",
            "--sample-km",
            "8",
        ],
    )
    cli.main()
    assert calls[0][0] == ("0,0", "out.gpx", "camping")
    assert calls[0][1]["max_km"] == 3
    assert "sample_km" not in calls[0][1]
    assert "ignored" in capsys.readouterr().err


def test_point_rejects_positional_gpx_paths(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpx-poi-enricher",
            "in.gpx",
            "--point",
            "0,0",
            "--output",
            "out.gpx",
            "--profile",
            "camping",
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
