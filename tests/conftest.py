"""Shared pytest fixtures for the gpx_poi_enricher test suite."""

import pathlib

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_gpx_path():
    """Return the absolute path to the sample GPX track fixture file."""
    return str(FIXTURES_DIR / "sample_track.gpx")


@pytest.fixture
def sample_track_points():
    """Return a list of (lat, lon) tuples for the Munich-to-Barcelona test route.

    Points represent: Munich, Zurich, Lyon, Marseille, Barcelona.
    """
    return [
        (48.1351, 11.5820),
        (47.3769, 8.5417),
        (45.7640, 4.8357),
        (43.2965, 5.3811),
        (41.3851, 2.1734),
    ]


@pytest.fixture
def profiles_dir():
    """Return the path to the real profiles/ directory in the project root."""
    return pathlib.Path(__file__).parent.parent / "profiles"
