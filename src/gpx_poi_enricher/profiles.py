"""Profile loading and management.

Profiles are defined as YAML files in the ``profiles/`` directory at the project root,
or in the directory pointed to by the ``GPX_POI_PROFILES_DIR`` environment variable.

Each profile YAML has the structure::

    id: camping
    description: "Campingplatz"
    symbol: Campground
    defaults:
      max_km: 10.0
      sample_km: 5.0
      batch_size: 6
      retries: 3
    tags:
      - key: tourism
        value: camp_site
    terms:
      DE: ["Campingplatz"]
      EN: ["campsite"]
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
from typing import Any

import yaml

_BUILTIN_PROFILES_DIR = pathlib.Path(__file__).parent.parent.parent / "profiles"

_FALLBACK_DEFAULTS = {
    "max_km": 10.0,
    "sample_km": 20.0,
    "batch_size": 4,
    "retries": 2,
}


@dataclasses.dataclass(frozen=True)
class SearchProfile:
    id: str
    description: str
    symbol: str
    tags: tuple[dict[str, Any], ...]
    terms: dict[str, list[str]]
    max_km: float
    sample_km: float
    batch_size: int
    retries: int

    def terms_for_country(self, country_code: str) -> list[str]:
        """Return deduplicated search terms for *country_code* + universal EN terms."""
        tmap = self.terms or {}
        result: list[str] = []
        seen: set[str] = set()

        for term in tmap.get(country_code, []) + tmap.get("EN", []):
            low = term.lower()
            if low not in seen:
                seen.add(low)
                result.append(term)

        return result


def _profiles_dir() -> pathlib.Path:
    env = os.environ.get("GPX_POI_PROFILES_DIR")
    if env:
        p = pathlib.Path(env)
        if p.is_dir():
            return p
    return _BUILTIN_PROFILES_DIR


def load_profile(profile_id: str, profiles_dir: pathlib.Path | None = None) -> SearchProfile:
    """Load a single profile by id from *profiles_dir* (or the default location)."""
    base = profiles_dir or _profiles_dir()
    for path in [base / f"{profile_id}.yaml", base / f"{profile_id}.yml"]:
        if path.exists():
            return _parse_profile(path)
    raise FileNotFoundError(
        f"Profile '{profile_id}' not found. Looked in: {base}"
        f"\nAvailable: {[p.stem for p in sorted(base.glob('*.yaml'))]}"
    )


def load_all_profiles(profiles_dir: pathlib.Path | None = None) -> dict[str, SearchProfile]:
    """Load every YAML profile from *profiles_dir* keyed by profile id."""
    base = profiles_dir or _profiles_dir()
    profiles: dict[str, SearchProfile] = {}
    for path in sorted(base.glob("*.yaml")):
        p = _parse_profile(path)
        profiles[p.id] = p
    return profiles


def _parse_profile(path: pathlib.Path) -> SearchProfile:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Profile file {path} must contain a YAML mapping at the top level.")

    profile_id = data.get("id") or path.stem
    defaults = {**_FALLBACK_DEFAULTS, **data.get("defaults", {})}

    return SearchProfile(
        id=profile_id,
        description=data.get("description", profile_id),
        symbol=data.get("symbol", "Pin"),
        tags=tuple(data.get("tags") or []),
        terms=data.get("terms") or {},
        max_km=float(defaults["max_km"]),
        sample_km=float(defaults["sample_km"]),
        batch_size=int(defaults["batch_size"]),
        retries=int(defaults["retries"]),
    )
