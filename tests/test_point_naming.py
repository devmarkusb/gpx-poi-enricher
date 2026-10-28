"""Point-mode filenames describe the starting point, independent of POI results."""

from __future__ import annotations

import hashlib
import pathlib
from unittest.mock import patch

import pytest
import requests
import responses as resp_lib

from gpx_poi_enricher import enricher
from gpx_poi_enricher.geocoding import NOMINATIM_URL
from gpx_poi_enricher.naming import clean_label, point_output_stem
from gpx_poi_enricher.overpass import OVERPASS_URLS


def _poi(name: str, distance_km: float = 0.1, tags: dict | None = None) -> dict:
    return {
        "lat": 48.1351,
        "lon": 11.5820,
        "name": name,
        "kind": "Aquarium",
        "distance_km": distance_km,
        "tags": {"name": name} if tags is None else tags,
    }


# ---------------------------------------------------------------------------
# clean_label
# ---------------------------------------------------------------------------


def test_clean_label_cuts_long_names():
    label = clean_label("Zoologischer " * 10)
    assert 0 < len(label) <= 60
    assert not label.endswith(" ")


def test_clean_label_rejects_placeholders():
    assert clean_label("Unnamed") == ""
    assert clean_label("   ") == ""
    assert clean_label(None) == ""
    assert clean_label("  Zoo Berlin  ") == "Zoo Berlin"
    assert clean_label("Tiergarten,") == "Tiergarten"
    assert clean_label("###") == ""  # no alphanumeric content
    assert clean_label("a" * 80) == "a" * 60  # hard cut when there is no word boundary


# ---------------------------------------------------------------------------
# point_output_stem
# ---------------------------------------------------------------------------


def test_point_output_stem_hash_without_a_lookup_session():
    stem, source = point_output_stem((1, 2))
    assert source == "hash"
    assert stem == f"point-{hashlib.sha256(b'1.0000000,2.0000000').hexdigest()[:8]}"


@resp_lib.activate
def test_point_output_stem_uses_starting_place_name():
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Zoologischer Garten"}, status=200)
    stem, source = point_output_stem((48.1351, 11.5820), session=requests.Session())
    assert (stem, source) == ("Zoologischer Garten", "place")


@resp_lib.activate
def test_point_output_stem_hash_when_reverse_lookup_fails():
    # Nothing registered under Nominatim → the failed lookup falls back to point-{hash}.
    stem, source = point_output_stem((1, 2), session=requests.Session())
    assert source == "hash"
    assert stem == f"point-{hashlib.sha256(b'1.0000000,2.0000000').hexdigest()[:8]}"


@resp_lib.activate
def test_enrich_point_file_named_hash_is_tied_to_resolved_coordinates(
    monkeypatch, tmp_path, profiles_dir
):
    monkeypatch.setattr(enricher, "enrich_point", lambda *_a, **_k: [])
    paths = [
        enricher.enrich_point_file_named(location, tmp_path, "aquarium", profiles_dir)[0]
        for location in ("1,2", " geo:1.000, 2.000 ", "https://www.google.com/maps?q=1,2")
    ]
    assert paths[0] == paths[1] == paths[2]


# ---------------------------------------------------------------------------
# enrich_point_file (explicit output path, used by CLI / Expert tab)
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_enrich_point_file_writes_to_explicit_path(monkeypatch, tmp_path, profiles_dir):
    monkeypatch.setattr(
        enricher, "enrich_point", lambda point, profile, **kwargs: [_poi("Aquarium Berlin")]
    )
    out = tmp_path / "custom.gpx"
    items = enricher.enrich_point_file("48.1351,11.5820", out, "aquarium", profiles_dir)
    assert out.is_file()
    assert [i["name"] for i in items] == ["Aquarium Berlin"]


# ---------------------------------------------------------------------------
# enrich_point_file_named
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lookup_status", [200, 503])
@resp_lib.activate
def test_enrich_point_file_named_keeps_point_name_across_profiles(
    lookup_status, monkeypatch, tmp_path, profiles_dir
):
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Starting Point"}, status=lookup_status)
    results = iter([[_poi("Aquarium Berlin")], [_poi("Campground")], []])
    monkeypatch.setattr(enricher, "enrich_point", lambda *_a, **_k: next(results))

    paths = [
        pathlib.Path(enricher.enrich_point_file_named("1,2", tmp_path, profile, profiles_dir)[0])
        for profile in ("aquarium", "camping", "aquarium")
    ]

    stem = (
        "Starting Point"
        if lookup_status == 200
        else f"point-{hashlib.sha256(b'1.0000000,2.0000000').hexdigest()[:8]}"
    )
    assert paths == [tmp_path / f"{stem}-{p}.gpx" for p in ("aquarium", "camping", "aquarium")]


@pytest.mark.parametrize(
    "location", ["Aquarium Berlin", "https://www.google.com/maps/place/Aquarium+Berlin/"]
)
@resp_lib.activate
def test_enrich_point_file_accepts_named_poi(location, monkeypatch, tmp_path, profiles_dir):
    monkeypatch.setattr("gpx_poi_enricher.geocoding.time.sleep", lambda *_: None)
    resp_lib.add(
        resp_lib.GET,
        "https://nominatim.openstreetmap.org/search",
        json=[{"lat": "1", "lon": "2", "display_name": "Aquarium Berlin"}],
        status=200,
    )
    points = []

    def search(point, profile, **kwargs):
        points.append(point)
        return []

    monkeypatch.setattr(enricher, "enrich_point", search)
    output = tmp_path / "pois.gpx"
    enricher.enrich_point_file(location, output, "aquarium", profiles_dir)

    assert points == [(1.0, 2.0)]
    assert output.is_file()


@resp_lib.activate
def test_enrich_point_file_named_writes_named_gpx(monkeypatch, tmp_path, profiles_dir):
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Starting Point"}, status=200)
    items = [_poi("Aquarium Berlin", 0.2)]
    monkeypatch.setattr(enricher, "enrich_point", lambda point, profile, **kwargs: items)
    path, written = enricher.enrich_point_file_named(
        "48.1351,11.5820", tmp_path, "aquarium", profiles_dir
    )
    expected = tmp_path / "Starting Point-aquarium.gpx"
    assert pathlib.Path(path) == expected
    assert written is items
    assert expected.is_file()
    assert "<wpt" in expected.read_text(encoding="utf-8")


@resp_lib.activate
def test_enrich_point_file_named_uses_place_name_when_no_pois(monkeypatch, tmp_path, profiles_dir):
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Tiergarten"}, status=200)
    monkeypatch.setattr(enricher, "enrich_point", lambda point, profile, **kwargs: [])
    path, written = enricher.enrich_point_file_named(
        "48.1351,11.5820", tmp_path, "aquarium", profiles_dir
    )
    assert pathlib.Path(path) == tmp_path / "Tiergarten-aquarium.gpx"
    assert written == []


@resp_lib.activate
def test_enrich_point_file_named_forwards_radius_override(monkeypatch, tmp_path, profiles_dir):
    seen: dict = {}

    def fake(point, profile, **kwargs):
        seen.update(kwargs)
        return [_poi("Aquarium Berlin")]

    monkeypatch.setattr(enricher, "enrich_point", fake)
    enricher.enrich_point_file_named(
        "48.1351,11.5820", tmp_path, "aquarium", profiles_dir, max_km=7.5
    )
    assert seen["max_km"] == 7.5


@resp_lib.activate
def test_enrich_point_file_named_end_to_end(tmp_path, profiles_dir):
    """Real pipeline (mocked HTTP): the start point names the GPX, regardless of hits."""
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Starting Point"}, status=200)
    for url in OVERPASS_URLS:
        resp_lib.add(
            resp_lib.POST,
            url,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 48.14,
                        "lon": 11.58,
                        "tags": {"name": "Aquarium Berlin", "tourism": "aquarium"},
                    }
                ]
            },
            status=200,
        )
    with patch("gpx_poi_enricher.enricher.time.sleep"):
        path, items = enricher.enrich_point_file_named(
            "48.1351,11.5820", tmp_path, "aquarium", profiles_dir, progress_interval=0
        )
    out = pathlib.Path(path)
    assert out == tmp_path / "Starting Point-aquarium.gpx"
    assert [i["name"] for i in items] == ["Aquarium Berlin"]
    assert "<wpt" in out.read_text(encoding="utf-8")
