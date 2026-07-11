"""Tests for gpx_poi_enricher.poi_catalog."""

from __future__ import annotations

import pathlib

import pytest

from gpx_poi_enricher.poi_catalog import (
    PRESETS,
    catalog_entry_by_id,
    catalog_entry_to_profile,
    catalog_path,
    catalog_to_json,
    load_catalog,
    save_catalog_entry,
)


def test_catalog_path_exists():
    assert catalog_path().is_file()


def test_load_catalog_has_categories():
    cats = load_catalog()
    assert len(cats) >= 8
    labels = {c.label for c in cats}
    assert "Food & drink" in labels
    assert "Tourism & culture" in labels


def test_catalog_entry_ids_unique():
    seen: set[str] = set()
    for cat in load_catalog():
        for entry in cat.entries:
            assert entry.id not in seen
            seen.add(entry.id)
    assert len(seen) >= 80


def test_catalog_entry_by_id_restaurant():
    entry = catalog_entry_by_id("restaurant")
    assert entry is not None
    assert entry.label == "Restaurant"
    assert entry.preset == "urban_dense"
    assert entry.tags[0]["key"] == "amenity"


def test_catalog_entry_by_id_unknown():
    assert catalog_entry_by_id("not_a_real_poi_type_xyz") is None


def test_catalog_entry_to_profile_uses_preset():
    entry = catalog_entry_by_id("aquarium")
    assert entry is not None
    profile = catalog_entry_to_profile(entry)
    assert profile.id == "aquarium"
    assert profile.description == "Aquarium"
    assert profile.max_km == PRESETS["regional_sparse"]["max_km"]
    assert profile.early_cancel_if_no_pois is False
    assert profile.tags[0]["value"] == "aquarium"


def test_catalog_entry_to_profile_playground_local_small():
    entry = catalog_entry_by_id("playground")
    assert entry is not None
    profile = catalog_entry_to_profile(entry)
    assert profile.max_km == PRESETS["local_small"]["max_km"]


def test_catalog_to_json_is_valid_json():
    import json

    data = json.loads(catalog_to_json())
    assert isinstance(data, list)
    assert data[0]["entries"][0]["id"]


def test_save_catalog_entry_writes_user_profile(tmp_path: pathlib.Path):
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "user").mkdir(parents=True)
    profile = save_catalog_entry("cafe", profiles_dir)
    assert profile.id == "cafe"
    out = profiles_dir / "user" / "cafe.yaml"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "amenity" in text
    assert "cafe" in text


def test_save_catalog_entry_unknown_raises(tmp_path: pathlib.Path):
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "user").mkdir(parents=True)
    with pytest.raises(KeyError, match="not found"):
        save_catalog_entry("missing_entry", profiles_dir)
