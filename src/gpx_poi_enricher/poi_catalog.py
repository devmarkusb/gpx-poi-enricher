"""Curated OSM POI catalog for one-click profile creation.

The catalog ships as ``data/poi_catalog.yaml`` inside the package. Entries map to
:class:`~gpx_poi_enricher.profiles.SearchProfile` instances via named distance
presets (see :data:`PRESETS`).
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

import yaml

from .profiles import SearchProfile, profile_from_mapping, save_profile

_CATALOG_PATH = pathlib.Path(__file__).resolve().parent / "data" / "poi_catalog.yaml"

PRESETS: dict[str, dict[str, Any]] = {
    "local_small": {
        "max_km": 2.0,
        "sample_km": 10.0,
        "batch_size": 5,
        "retries": 2,
        "early_cancel_if_no_pois": True,
        "early_cancel_after_batches": 3,
    },
    "urban_dense": {
        "max_km": 3.0,
        "sample_km": 10.0,
        "batch_size": 8,
        "retries": 2,
        "early_cancel_if_no_pois": True,
        "early_cancel_after_batches": 3,
    },
    "suburban": {
        "max_km": 10.0,
        "sample_km": 5.0,
        "batch_size": 6,
        "retries": 3,
        "early_cancel_if_no_pois": True,
        "early_cancel_after_batches": 3,
    },
    "regional_sparse": {
        "max_km": 15.0,
        "sample_km": 7.0,
        "batch_size": 4,
        "retries": 2,
        "early_cancel_if_no_pois": False,
        "early_cancel_after_batches": 3,
    },
    "regional_wide": {
        "max_km": 20.0,
        "sample_km": 10.0,
        "batch_size": 4,
        "retries": 2,
        "early_cancel_if_no_pois": True,
        "early_cancel_after_batches": 3,
    },
}


@dataclasses.dataclass(frozen=True)
class CatalogEntry:
    id: str
    label: str
    symbol: str
    tags: tuple[dict[str, str], ...]
    preset: str


@dataclasses.dataclass(frozen=True)
class CatalogCategory:
    id: str
    label: str
    entries: tuple[CatalogEntry, ...]


def catalog_path() -> pathlib.Path:
    """Return the bundled catalog YAML path."""
    return _CATALOG_PATH


def load_catalog(path: pathlib.Path | None = None) -> tuple[CatalogCategory, ...]:
    """Load and validate the POI catalog."""
    p = path or _CATALOG_PATH
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"POI catalog ({p}) must be a mapping at the top level.")
    raw_categories = data.get("categories")
    if not isinstance(raw_categories, list):
        raise ValueError(f"POI catalog ({p}) must contain a 'categories' list.")

    categories: list[CatalogCategory] = []
    seen_ids: set[str] = set()
    for i, cat in enumerate(raw_categories):
        if not isinstance(cat, dict):
            raise ValueError(f"POI catalog categories[{i}] must be a mapping.")
        cat_id = str(cat.get("id") or "").strip()
        cat_label = str(cat.get("label") or cat_id).strip()
        if not cat_id:
            raise ValueError(f"POI catalog categories[{i}] needs a non-empty id.")
        raw_entries = cat.get("entries") or []
        if not isinstance(raw_entries, list):
            raise ValueError(f"POI catalog category '{cat_id}' entries must be a list.")
        entries: list[CatalogEntry] = []
        for j, item in enumerate(raw_entries):
            entry = _parse_entry(item, cat_id=cat_id, index=j)
            if entry.id in seen_ids:
                raise ValueError(f"Duplicate catalog entry id '{entry.id}'.")
            seen_ids.add(entry.id)
            entries.append(entry)
        categories.append(CatalogCategory(id=cat_id, label=cat_label, entries=tuple(entries)))
    return tuple(categories)


def _parse_entry(raw: Any, *, cat_id: str, index: int) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"POI catalog category '{cat_id}' entries[{index}] must be a mapping.")
    entry_id = str(raw.get("id") or "").strip().lower()
    if not entry_id:
        raise ValueError(f"POI catalog category '{cat_id}' entries[{index}] needs an id.")
    label = str(raw.get("label") or entry_id).strip()
    symbol = str(raw.get("symbol") or "Pin").strip() or "Pin"
    preset = str(raw.get("preset") or "suburban").strip()
    if preset not in PRESETS:
        raise ValueError(
            f"POI catalog entry '{entry_id}' uses unknown preset '{preset}'. "
            f"Known: {sorted(PRESETS)}"
        )
    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list) or not tags_raw:
        raise ValueError(f"POI catalog entry '{entry_id}' needs at least one tag.")
    tags: list[dict[str, str]] = []
    for k, tag in enumerate(tags_raw):
        if not isinstance(tag, dict) or "key" not in tag or "value" not in tag:
            raise ValueError(f"POI catalog entry '{entry_id}' tags[{k}] needs key and value.")
        tags.append({"key": str(tag["key"]), "value": str(tag["value"])})
    return CatalogEntry(
        id=entry_id,
        label=label,
        symbol=symbol,
        tags=tuple(tags),
        preset=preset,
    )


def catalog_entry_by_id(entry_id: str, path: pathlib.Path | None = None) -> CatalogEntry | None:
    """Return a catalog entry by id, or ``None`` if not found."""
    want = entry_id.strip().lower()
    for cat in load_catalog(path):
        for entry in cat.entries:
            if entry.id == want:
                return entry
    return None


def catalog_entry_to_mapping(entry: CatalogEntry) -> dict[str, Any]:
    """Build a YAML-compatible profile mapping for *entry*."""
    preset = PRESETS[entry.preset]
    return {
        "id": entry.id,
        "description": entry.label,
        "symbol": entry.symbol,
        "defaults": dict(preset),
        "tags": [dict(t) for t in entry.tags],
        "terms": {},
        "must_match_terms": False,
        "require_distinct_name": False,
    }


def catalog_entry_to_profile(entry: CatalogEntry) -> SearchProfile:
    """Materialize a :class:`SearchProfile` from a catalog entry."""
    return profile_from_mapping(catalog_entry_to_mapping(entry), path_hint=f"catalog:{entry.id}")


def save_catalog_entry(
    entry_id: str,
    profiles_dir: pathlib.Path | None = None,
    *,
    path: pathlib.Path | None = None,
) -> SearchProfile:
    """Create and save a user profile from a catalog entry id."""
    entry = catalog_entry_by_id(entry_id, path)
    if entry is None:
        raise KeyError(f"Catalog entry '{entry_id}' not found.")
    profile = catalog_entry_to_profile(entry)
    save_profile(profile, profiles_dir)
    return profile


def catalog_to_json(path: pathlib.Path | None = None) -> str:
    """Serialize the catalog for UIs (category tree with entry metadata)."""
    rows = []
    for cat in load_catalog(path):
        rows.append(
            {
                "id": cat.id,
                "label": cat.label,
                "entries": [
                    {
                        "id": e.id,
                        "label": e.label,
                        "symbol": e.symbol,
                        "preset": e.preset,
                    }
                    for e in cat.entries
                ],
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def flat_catalog_entries(path: pathlib.Path | None = None) -> list[tuple[str, str, str]]:
    """Return ``(entry_id, label, category_label)`` sorted for pickers."""
    out: list[tuple[str, str, str]] = []
    for cat in load_catalog(path):
        for entry in cat.entries:
            out.append((entry.id, entry.label, cat.label))
    out.sort(key=lambda x: (x[2].lower(), x[1].lower()))
    return out
