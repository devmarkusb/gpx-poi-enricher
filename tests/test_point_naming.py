"""Point-mode output naming: nearest named POI → Nominatim place → point-{hash}."""

from __future__ import annotations

import hashlib
import pathlib
from unittest.mock import patch

import requests
import responses as resp_lib

from gpx_poi_enricher import enricher
from gpx_poi_enricher.geocoding import NOMINATIM_URL
from gpx_poi_enricher.naming import clean_label, nearest_poi_label, point_output_stem
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
# nearest_poi_label
# ---------------------------------------------------------------------------


def test_nearest_poi_label_returns_closest_named_poi():
    items = [_poi("Zoo Entrance", 0.1), _poi("Aquarium Berlin", 0.5)]
    assert nearest_poi_label(items) == "Zoo Entrance"


def test_nearest_poi_label_skips_candidates_without_an_osm_name():
    # No name-like OSM tag → the enricher filled in the profile description.
    fallback = _poi("Aquarium", 0.1, tags={"tourism": "aquarium"})
    items = [fallback, _poi("Aquarium Berlin", 0.5)]
    assert nearest_poi_label(items) == "Aquarium Berlin"


def test_nearest_poi_label_ignores_placeholders_and_empty_input():
    assert nearest_poi_label([]) == ""
    assert nearest_poi_label(None) == ""
    assert nearest_poi_label([_poi("Unnamed", tags={"name": "Unnamed"})]) == ""


def test_nearest_poi_label_cuts_long_names():
    label = nearest_poi_label([_poi("Zoologischer " * 10)])
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


def test_point_output_stem_prefers_named_poi():
    assert point_output_stem("1,2", [_poi("Aquarium Berlin")]) == ("Aquarium Berlin", "poi")


def test_point_output_stem_hash_without_candidates_or_point():
    stem, source = point_output_stem("1,2", [])
    assert source == "hash"
    assert stem == f"point-{hashlib.sha256(b'1,2').hexdigest()[:8]}"


@resp_lib.activate
def test_point_output_stem_falls_back_to_reverse_place_name():
    resp_lib.add(resp_lib.GET, NOMINATIM_URL, json={"name": "Zoologischer Garten"}, status=200)
    stem, source = point_output_stem(
        "1,2", [], point=(48.1351, 11.5820), session=requests.Session()
    )
    assert (stem, source) == ("Zoologischer Garten", "place")


@resp_lib.activate
def test_point_output_stem_hash_when_reverse_lookup_fails():
    # Nothing registered under Nominatim → the failed lookup falls back to point-{hash}.
    stem, source = point_output_stem(
        "1,2", [], point=(48.1351, 11.5820), session=requests.Session()
    )
    assert source == "hash"
    assert stem == f"point-{hashlib.sha256(b'1,2').hexdigest()[:8]}"


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


@resp_lib.activate
def test_enrich_point_file_named_writes_named_gpx(monkeypatch, tmp_path, profiles_dir):
    items = [_poi("Aquarium Berlin", 0.2)]
    monkeypatch.setattr(enricher, "enrich_point", lambda point, profile, **kwargs: items)
    path, written = enricher.enrich_point_file_named(
        "48.1351,11.5820", tmp_path, "aquarium", profiles_dir
    )
    expected = tmp_path / "Aquarium Berlin-aquarium.gpx"
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
    """Real pipeline (mocked HTTP): the nearest named Overpass hit names the GPX."""
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
    assert out == tmp_path / "Aquarium Berlin-aquarium.gpx"
    assert [i["name"] for i in items] == ["Aquarium Berlin"]
    assert "<wpt" in out.read_text(encoding="utf-8")
