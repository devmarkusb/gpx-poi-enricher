"""Profile loading and management.

Profiles are YAML files. Default search order (unless ``GPX_POI_PROFILES_DIR`` is set):

1. The ``profiles/`` directory next to the installed package (shipped built-ins).
2. The per-user directory (writable; overrides built-ins with the same ``id``).

On Android, *profiles_dir* is the app ``files/profiles`` root with ``builtin/`` and ``user/``
subdirectories (built-ins are copied from assets; user files live only under ``user/``).

Environment:

``GPX_POI_PROFILES_DIR``
    If set to an existing directory, **only** that directory is used (no merge with
    built-ins or user config — intended for tests and custom deployments).
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

import yaml

_PACKAGED_PROFILES_DIR = pathlib.Path(__file__).parent / "data" / "profiles"
_BUILTIN_PROFILES_DIR = (
    _PACKAGED_PROFILES_DIR
    if _PACKAGED_PROFILES_DIR.is_dir()
    else pathlib.Path(__file__).parent.parent.parent / "profiles"
)

_FALLBACK_DEFAULTS = {
    "max_km": 10.0,
    "sample_km": 20.0,
    "batch_size": 4,
    "retries": 2,
    "early_cancel_if_no_pois": True,
    "early_cancel_after_batches": 3,
}


def template_profile() -> SearchProfile:
    """Starter profile for UIs (new / import preview)."""
    return SearchProfile(
        id="my_profile",
        description="Custom search",
        symbol="Pin",
        tags=({"key": "tourism", "value": "attraction"},),
        terms={"EN": ["sightseeing"]},
        max_km=10.0,
        sample_km=5.0,
        batch_size=4,
        retries=2,
        early_cancel_if_no_pois=True,
        early_cancel_after_batches=3,
        must_match_terms=False,
        require_distinct_name=False,
    )


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
    early_cancel_if_no_pois: bool = True
    early_cancel_after_batches: int = 3
    must_match_terms: bool = False
    require_distinct_name: bool = False

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


def default_user_profiles_dir() -> pathlib.Path:
    """Writable directory for user profiles (desktop)."""
    if sys.platform == "win32":
        base = pathlib.Path(
            os.environ.get("APPDATA") or (pathlib.Path.home() / "AppData" / "Roaming")
        )
        return (base / "gpx-poi-enricher" / "profiles").resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return (pathlib.Path(xdg) / "gpx-poi-enricher" / "profiles").resolve()
    return (pathlib.Path.home() / ".config" / "gpx-poi-enricher" / "profiles").resolve()


def _profiles_dir_single() -> pathlib.Path:
    """Single directory from ``GPX_POI_PROFILES_DIR``, or built-in package directory."""
    env = os.environ.get("GPX_POI_PROFILES_DIR")
    if env:
        p = pathlib.Path(env)
        if p.is_dir():
            return p
    return _BUILTIN_PROFILES_DIR


def _resolved_profile_dirs(explicit: pathlib.Path | None) -> list[pathlib.Path]:
    """Ordered list of directories to scan; later entries win on duplicate ``id``."""
    if explicit is not None:
        root = explicit.resolve()
        builtin = root / "builtin"
        user = root / "user"
        if builtin.is_dir() or user.is_dir():
            return [d for d in (builtin, user) if d.is_dir()]
        return [root] if root.is_dir() else []

    base = _profiles_dir_single()
    env = os.environ.get("GPX_POI_PROFILES_DIR")
    if env:
        p = pathlib.Path(env)
        if p.is_dir():
            return [p]
    user = default_user_profiles_dir()
    out: list[pathlib.Path] = [base]
    if user.is_dir():
        out.append(user)
    return out


def _yaml_paths_in_dir(d: pathlib.Path) -> list[pathlib.Path]:
    return sorted([*d.glob("*.yaml"), *d.glob("*.yml")])


def _profiles_in_dir(d: pathlib.Path) -> dict[str, SearchProfile]:
    """Resolve aliases consistently; canonical files written by save_profile win."""
    profiles: dict[str, SearchProfile] = {}
    canonical_ids: set[str] = set()
    for path in _yaml_paths_in_dir(d):
        profile = _parse_profile(path)
        canonical = path.stem == profile.id
        if canonical or profile.id not in canonical_ids:
            profiles[profile.id] = profile
        if canonical:
            canonical_ids.add(profile.id)
    return profiles


def load_all_profiles(profiles_dir: pathlib.Path | None = None) -> dict[str, SearchProfile]:
    """Load YAML profiles from the default merge locations, or from *profiles_dir* only."""
    merged: dict[str, SearchProfile] = {}
    for d in _resolved_profile_dirs(profiles_dir):
        if not d.is_dir():
            continue
        merged.update(_profiles_in_dir(d))
    return merged


def load_all_profiles_with_sources(
    profiles_dir: pathlib.Path | None = None,
) -> dict[str, tuple[SearchProfile, str]]:
    """Like :func:`load_all_profiles` but records which directory last defined each ``id``.

    The ``source`` string is ``"builtin"``, ``"user"``, or the resolved directory path
    for a custom single-dir layout (tests / ``GPX_POI_PROFILES_DIR``).
    """
    merged: dict[str, tuple[SearchProfile, str]] = {}
    dirs = _resolved_profile_dirs(profiles_dir)
    for d in dirs:
        if not d.is_dir():
            continue
        label = _dir_source_label(d, dirs, profiles_dir)
        for p in _profiles_in_dir(d).values():
            merged[p.id] = (p, label)
    return merged


def _dir_source_label(
    d: pathlib.Path,
    dirs: list[pathlib.Path],
    explicit_root: pathlib.Path | None,
) -> str:
    env = os.environ.get("GPX_POI_PROFILES_DIR")
    if explicit_root is None and env and d.resolve() == pathlib.Path(env).resolve():
        return "user"
    if len(dirs) == 1:
        return "profiles"
    if explicit_root is not None:
        root = explicit_root.resolve()
        try:
            if d.resolve() == (root / "builtin").resolve():
                return "builtin"
            if d.resolve() == (root / "user").resolve():
                return "user"
        except OSError:
            pass
        return str(d)
    user = default_user_profiles_dir().resolve()
    try:
        if d.resolve() == user:
            return "user"
    except OSError:
        pass
    return "builtin"


def user_profiles_write_dir(profiles_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Directory where new/edited user profiles should be written."""
    if profiles_dir is not None:
        root = profiles_dir.resolve()
        u = root / "user"
        if (root / "builtin").is_dir() or (root / "user").is_dir():
            u.mkdir(parents=True, exist_ok=True)
            return u
        root.mkdir(parents=True, exist_ok=True)
        return root
    env = os.environ.get("GPX_POI_PROFILES_DIR")
    if env:
        root = pathlib.Path(env).resolve()
        if not root.is_dir():
            raise FileNotFoundError(
                f"GPX_POI_PROFILES_DIR must refer to an existing directory: {root}"
            )
        return root
    d = default_user_profiles_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_profile(profile_id: str, profiles_dir: pathlib.Path | None = None) -> SearchProfile:
    """Load a profile by id; later search directories override earlier ones."""
    pid = profile_id.strip().lower()
    dirs = _resolved_profile_dirs(profiles_dir)
    for d in reversed(dirs):
        if not d.is_dir():
            continue
        if profile := _profiles_in_dir(d).get(pid):
            return profile
    searched = ", ".join(str(x) for x in dirs) if dirs else "(no directories)"
    avail = sorted(load_all_profiles(profiles_dir).keys())
    raise FileNotFoundError(
        f"Profile '{profile_id}' not found. Looked in: {searched}\nAvailable: {avail}"
    )


def _parse_profile(path: pathlib.Path) -> SearchProfile:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and not data.get("id"):
        data["id"] = path.stem
    return profile_from_mapping(data, path_hint=str(path))


def validate_search_defaults(*, max_km, sample_km, batch_size, retries) -> None:
    """Reject invalid distances and counts before constructing queries or batches."""
    for key, value in (
        ("max_km", max_km),
        ("sample_km", sample_km),
        ("batch_size", batch_size),
        ("retries", retries),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or (value < 0 if key == "retries" else value <= 0)
            or (key in {"batch_size", "retries"} and int(value) != value)
        ):
            constraint = "nonnegative" if key == "retries" else "positive"
            kind = "integer" if key in {"batch_size", "retries"} else "number"
            raise ValueError(f"{key} must be a finite {constraint} {kind}.")


def _parse_tag_subclauses(
    raw: Any, *, path_hint: str, tag_index: int, field: str
) -> list[dict[str, str]]:
    """Normalize ``and`` / ``and_not`` entries to a list of ``{key, value}`` mappings."""
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, str]] = []
    for j, sub in enumerate(items):
        if not isinstance(sub, dict) or "key" not in sub or "value" not in sub:
            raise ValueError(
                f"Profile ({path_hint}): tags[{tag_index}].{field}[{j}] "
                "must be a mapping with key and value."
            )
        out.append({"key": str(sub["key"]), "value": str(sub["value"])})
    return out


def profile_from_mapping(data: Any, path_hint: str = "?") -> SearchProfile:
    """Build a :class:`SearchProfile` from a YAML/JSON-like mapping (mutating copies ok)."""
    if not isinstance(data, dict):
        raise ValueError(f"Profile ({path_hint}) must be a mapping at the top level.")

    profile_id = str(data.get("id") or "profile").strip().lower()
    if not profile_id:
        raise ValueError(f"Profile ({path_hint}) needs a non-empty id.")

    raw_defaults = data.get("defaults") or {}
    if not isinstance(raw_defaults, dict):
        raise ValueError(f"Profile ({path_hint}): defaults must be a mapping.")
    defaults = {**_FALLBACK_DEFAULTS, **raw_defaults}

    early_cancel = bool(defaults["early_cancel_if_no_pois"])
    early_after = int(defaults["early_cancel_after_batches"])
    if early_cancel and early_after < 1:
        raise ValueError(
            f"Profile ({path_hint}): early_cancel_after_batches must be >= 1 "
            f"when early_cancel_if_no_pois is true (got {early_after})."
        )

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ValueError(f"Profile ({path_hint}): tags must be a list.")
    tags_list: list[dict[str, Any]] = []
    for i, item in enumerate(tags_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Profile ({path_hint}): tags[{i}] must be a mapping with key/value.")
        if "key" not in item or "value" not in item:
            raise ValueError(f"Profile ({path_hint}): tags[{i}] must have key and value.")
        tag_dict: dict[str, Any] = {"key": str(item["key"]), "value": str(item["value"])}
        if "and" in item:
            tag_dict["and"] = _parse_tag_subclauses(
                item["and"], path_hint=path_hint, tag_index=i, field="and"
            )
        if "and_not" in item:
            tag_dict["and_not"] = _parse_tag_subclauses(
                item["and_not"], path_hint=path_hint, tag_index=i, field="and_not"
            )
        tags_list.append(tag_dict)

    terms_raw = data.get("terms") or {}
    if not isinstance(terms_raw, dict):
        raise ValueError(f"Profile ({path_hint}): terms must be a mapping of language -> list.")
    terms: dict[str, list[str]] = {}
    for lang, vals in terms_raw.items():
        lang_s = str(lang).strip()
        if not lang_s:
            continue
        if isinstance(vals, str):
            terms[lang_s] = [vals]
        elif isinstance(vals, list):
            terms[lang_s] = [str(v) for v in vals]
        else:
            raise ValueError(f"Profile ({path_hint}): terms[{lang!r}] must be a list or string.")

    max_km = float(defaults["max_km"])
    sample_km = float(defaults["sample_km"])
    batch_size = float(defaults["batch_size"])
    retries = float(defaults["retries"])
    validate_search_defaults(
        max_km=max_km, sample_km=sample_km, batch_size=batch_size, retries=retries
    )

    return SearchProfile(
        id=profile_id,
        description=str(data.get("description", profile_id)),
        symbol=str(data.get("symbol", "Pin")),
        tags=tuple(tags_list),
        terms=terms,
        max_km=max_km,
        sample_km=sample_km,
        batch_size=int(batch_size),
        retries=int(retries),
        early_cancel_if_no_pois=early_cancel,
        early_cancel_after_batches=early_after,
        must_match_terms=bool(data.get("must_match_terms", False)),
        require_distinct_name=bool(data.get("require_distinct_name", False)),
    )


def _tag_mapping_for_dump(tag: dict[str, Any]) -> dict[str, Any]:
    """YAML/JSON-serializable tag line (key/value plus optional ``and`` / ``and_not``)."""
    out: dict[str, Any] = {"key": tag["key"], "value": tag["value"]}
    if "and" in tag:
        raw = tag["and"]
        out["and"] = [dict(x) for x in raw] if isinstance(raw, list) else dict(raw)
    if "and_not" in tag:
        raw = tag["and_not"]
        out["and_not"] = [dict(x) for x in raw] if isinstance(raw, list) else dict(raw)
    return out


def profile_to_mapping(profile: SearchProfile) -> dict[str, Any]:
    """Serialize a profile to a YAML-compatible dict."""
    return {
        "id": profile.id,
        "description": profile.description,
        "symbol": profile.symbol,
        "defaults": {
            "max_km": profile.max_km,
            "sample_km": profile.sample_km,
            "batch_size": profile.batch_size,
            "retries": profile.retries,
            "early_cancel_if_no_pois": profile.early_cancel_if_no_pois,
            "early_cancel_after_batches": profile.early_cancel_after_batches,
        },
        "tags": [_tag_mapping_for_dump(t) for t in profile.tags],
        "terms": {k: list(v) for k, v in profile.terms.items()},
        "must_match_terms": profile.must_match_terms,
        "require_distinct_name": profile.require_distinct_name,
    }


def dump_profile_yaml(profile: SearchProfile) -> str:
    """Return UTF-8 YAML text for *profile*."""
    return yaml.safe_dump(
        profile_to_mapping(profile),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def profile_from_yaml_text(text: str) -> SearchProfile:
    """Parse a profile from YAML string (for import / advanced editor)."""
    data = yaml.safe_load(text)
    return profile_from_mapping(data, path_hint="<yaml>")


def profile_from_json_text(text: str) -> SearchProfile:
    """Parse a profile from JSON string."""
    data = json.loads(text)
    return profile_from_mapping(data, path_hint="<json>")


def save_profile(profile: SearchProfile, profiles_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Write *profile* to the user writable directory as ``{id}.yaml``."""
    profile = dataclasses.replace(profile, id=normalize_profile_id(profile.id))
    out_dir = user_profiles_write_dir(profiles_dir)
    path = out_dir / f"{profile.id}.yaml"
    text = dump_profile_yaml(profile)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=out_dir, suffix=".tmp", delete=False
        ) as fh:
            temporary = pathlib.Path(fh.name)
            fh.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def delete_user_profile(profile_id: str, profiles_dir: pathlib.Path | None = None) -> bool:
    """Remove ``{id}.yaml`` / ``{id}.yml`` from the user directory only. Returns True if a file was removed."""
    profile_id = normalize_profile_id(profile_id)
    out_dir = user_profiles_write_dir(profiles_dir)
    removed = False
    for p in _yaml_paths_in_dir(out_dir):
        if _parse_profile(p).id == profile_id:
            p.unlink()
            removed = True
    return removed


_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _validate_profile_id(profile_id: str) -> None:
    pid = profile_id.strip().lower()
    if not _ID_RE.match(pid):
        raise ValueError(
            "Profile id must be lowercase, start with a letter, and contain only "
            "letters, digits, and underscores (max 64 characters)."
        )


def normalize_profile_id(profile_id: str) -> str:
    """Return a validated lowercase id or raise ValueError."""
    pid = profile_id.strip().lower()
    _validate_profile_id(pid)
    return pid
