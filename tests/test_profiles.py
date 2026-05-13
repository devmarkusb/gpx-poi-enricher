"""Tests for gpx_poi_enricher.profiles module.

Covers: load_profile, load_all_profiles, SearchProfile fields,
terms_for_country (deduplication, country fallback), FileNotFoundError.
"""

from __future__ import annotations

import pytest
import yaml

from gpx_poi_enricher.profiles import (
    SearchProfile,
    dump_profile_yaml,
    load_all_profiles,
    load_profile,
    profile_from_yaml_text,
    save_profile,
)

# ---------------------------------------------------------------------------
# load_profile – happy path
# ---------------------------------------------------------------------------


def test_load_profile_camping_returns_search_profile(profiles_dir):
    """load_profile('camping') must return a SearchProfile instance."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert isinstance(profile, SearchProfile)


def test_load_profile_camping_id(profiles_dir):
    """The loaded camping profile must have id='camping'."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert profile.id == "camping"


def test_load_profile_camping_description(profiles_dir):
    """The camping profile description must be non-empty."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert profile.description  # non-empty string


def test_load_profile_camping_symbol(profiles_dir):
    """The camping profile must have a non-empty symbol string."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert profile.symbol


def test_load_profile_camping_has_tags(profiles_dir):
    """The camping profile must define at least one OSM tag filter."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert len(profile.tags) > 0


def test_load_profile_theme_park_disables_early_cancel(profiles_dir):
    """theme_park disables empty-batch early exit (sparse POIs)."""
    profile = load_profile("theme_park", profiles_dir=profiles_dir)
    assert profile.early_cancel_if_no_pois is False


def test_must_match_terms_ands_tags_with_term_queries():
    """must_match_terms=True ANDs tag hits with keyword term matches."""
    profile = _make_profile(
        must_match_terms=True,
        tags=({"key": "tourism", "value": "theme_park"}, {"key": "leisure", "value": "water_park"}),
        terms={"DE": ["Familienpark", "Freizeitpark"], "EN": ["family park"]},
    )
    assert profile.must_match_terms is True
    assert profile.terms_for_country("DE")
    assert len(profile.tags) == 2


def test_load_profile_kids_activities_has_tag_and_term_queries(profiles_dir):
    """kids_activities combines leisure/tourism tags with name/alt_name term queries."""
    profile = load_profile("kids_activities", profiles_dir=profiles_dir)
    assert len(profile.tags) >= 1
    assert profile.terms_for_country("DE")


def test_load_profile_invalid_early_cancel_after_batches_raises(tmp_path):
    """early_cancel_after_batches < 1 with early cancel on must raise ValueError."""
    profile_data = {
        "id": "bad_early",
        "description": "x",
        "symbol": "Pin",
        "defaults": {
            "max_km": 5.0,
            "sample_km": 10.0,
            "batch_size": 2,
            "retries": 1,
            "early_cancel_if_no_pois": True,
            "early_cancel_after_batches": 0,
        },
        "tags": [],
        "terms": {"EN": ["test"]},
    }
    path = tmp_path / "bad_early.yaml"
    path.write_text(yaml.dump(profile_data), encoding="utf-8")
    with pytest.raises(ValueError, match="early_cancel_after_batches"):
        load_profile("bad_early", profiles_dir=tmp_path)


def test_load_profile_camping_must_match_terms(profiles_dir):
    """Camping profile uses default OR semantics (tags ∪ term hits)."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert profile.must_match_terms is False


def test_load_profile_restaurant_default_must_match_terms(profiles_dir):
    """Restaurant profile keeps OR semantics (tags ∪ text hits)."""
    profile = load_profile("restaurant", profiles_dir=profiles_dir)
    assert profile.must_match_terms is False


def test_load_profile_camping_tag_structure(profiles_dir):
    """Each tag in the camping profile must have 'key' and 'value' keys."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    for tag in profile.tags:
        assert "key" in tag
        assert "value" in tag


def test_load_profile_mcdonalds_preserves_and_clause(profiles_dir):
    """YAML ``and`` on a tag line must survive load (used by Overpass query builder)."""
    profile = load_profile("mcdonalds", profiles_dir=profiles_dir)
    amenity_tags = [t for t in profile.tags if t.get("key") == "amenity"]
    assert len(amenity_tags) == 1
    assert amenity_tags[0].get("and") == [{"key": "brand", "value": "McDonald's"}]


def test_load_profile_outdoor_pool_require_distinct_name(profiles_dir):
    """Outdoor pool profile drops unnamed tag-only hits (no generic GPX label)."""
    profile = load_profile("outdoor_pool", profiles_dir=profiles_dir)
    assert profile.require_distinct_name is True


def test_load_profile_outdoor_pool_swimming_pool_has_and_not(profiles_dir):
    """Outdoor pool profile must exclude tagged private / no-access swimming pools."""
    profile = load_profile("outdoor_pool", profiles_dir=profiles_dir)
    pool_tags = [
        t for t in profile.tags if t.get("key") == "leisure" and t.get("value") == "swimming_pool"
    ]
    assert len(pool_tags) == 1
    assert pool_tags[0].get("and_not") == [
        {"key": "access", "value": "private"},
        {"key": "access", "value": "no"},
    ]


def test_load_profile_camping_terms_is_dict(profiles_dir):
    """profile.terms must be a dict mapping language codes to lists."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert isinstance(profile.terms, dict)


def test_load_profile_camping_has_en_terms(profiles_dir):
    """The camping profile must have English (EN) terms."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert "EN" in profile.terms
    assert len(profile.terms["EN"]) > 0


def test_load_profile_camping_numeric_defaults(profiles_dir):
    """The camping profile must have positive numeric defaults for max_km, sample_km, etc."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    assert profile.max_km > 0
    assert profile.sample_km > 0
    assert profile.batch_size > 0
    assert profile.retries > 0


# ---------------------------------------------------------------------------
# load_profile – error handling
# ---------------------------------------------------------------------------


def test_load_profile_unknown_raises_file_not_found(profiles_dir):
    """load_profile with an unknown id must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_profile("this_profile_does_not_exist_xyz", profiles_dir=profiles_dir)


def test_load_profile_unknown_error_message_helpful(profiles_dir):
    """The FileNotFoundError message should mention the missing profile id."""
    with pytest.raises(FileNotFoundError, match="this_profile_does_not_exist_xyz"):
        load_profile("this_profile_does_not_exist_xyz", profiles_dir=profiles_dir)


def test_load_profile_custom_profiles_dir(tmp_path):
    """load_profile can load from a custom directory passed as profiles_dir."""
    profile_data = {
        "id": "test_custom",
        "description": "Test Custom Profile",
        "symbol": "Pin",
        "defaults": {"max_km": 5.0, "sample_km": 10.0, "batch_size": 2, "retries": 1},
        "tags": [{"key": "amenity", "value": "fuel"}],
        "terms": {"EN": ["gas station"]},
    }
    (tmp_path / "test_custom.yaml").write_text(yaml.dump(profile_data), encoding="utf-8")
    profile = load_profile("test_custom", profiles_dir=tmp_path)
    assert profile.id == "test_custom"
    assert profile.max_km == 5.0


# ---------------------------------------------------------------------------
# load_all_profiles
# ---------------------------------------------------------------------------


def test_load_all_profiles_returns_dict(profiles_dir):
    """load_all_profiles must return a dict."""
    result = load_all_profiles(profiles_dir=profiles_dir)
    assert isinstance(result, dict)


def test_load_all_profiles_contains_camping(profiles_dir):
    """load_all_profiles must include the 'camping' profile."""
    result = load_all_profiles(profiles_dir=profiles_dir)
    assert "camping" in result


def test_load_all_profiles_all_values_are_search_profiles(profiles_dir):
    """Every value in the dict returned by load_all_profiles must be a SearchProfile."""
    result = load_all_profiles(profiles_dir=profiles_dir)
    for key, value in result.items():
        assert isinstance(value, SearchProfile), f"Expected SearchProfile for key '{key}'"


def test_load_all_profiles_keys_match_ids(profiles_dir):
    """The dict keys must match the profile's own id field."""
    result = load_all_profiles(profiles_dir=profiles_dir)
    for key, profile in result.items():
        assert key == profile.id, f"Key '{key}' != profile.id '{profile.id}'"


def test_load_all_profiles_empty_dir_returns_empty_dict(tmp_path):
    """load_all_profiles on an empty directory must return an empty dict."""
    result = load_all_profiles(profiles_dir=tmp_path)
    assert result == {}


# ---------------------------------------------------------------------------
# SearchProfile.terms_for_country
# ---------------------------------------------------------------------------


def _make_profile(**kwargs) -> SearchProfile:
    """Build a minimal SearchProfile for testing; keyword args override defaults."""
    defaults = dict(
        id="test",
        description="Test",
        symbol="Pin",
        tags=(),
        terms={},
        max_km=10.0,
        sample_km=20.0,
        batch_size=4,
        retries=2,
        must_match_terms=False,
        require_distinct_name=False,
    )
    defaults.update(kwargs)
    return SearchProfile(**defaults)


def test_terms_for_country_returns_country_specific_terms():
    """terms_for_country('DE') must include German-specific terms."""
    profile = _make_profile(
        terms={"DE": ["Campingplatz", "Wohnmobilstellplatz"], "EN": ["campsite"]}
    )
    terms = profile.terms_for_country("DE")
    assert "Campingplatz" in terms
    assert "Wohnmobilstellplatz" in terms


def test_terms_for_country_always_includes_en():
    """terms_for_country must always append EN terms."""
    profile = _make_profile(terms={"DE": ["Campingplatz"], "EN": ["campsite"]})
    terms = profile.terms_for_country("DE")
    assert "campsite" in terms


def test_terms_for_country_deduplication_case_insensitive():
    """terms_for_country must deduplicate case-insensitively.

    If a country-specific term and an EN term are the same word (different case),
    only the first occurrence must appear in the result.
    """
    profile = _make_profile(terms={"ES": ["Camping"], "EN": ["camping"]})
    terms = profile.terms_for_country("ES")
    # "Camping" and "camping" are the same when lowercased; only one must appear.
    lower_terms = [t.lower() for t in terms]
    assert lower_terms.count("camping") == 1


def test_terms_for_country_unknown_country_falls_back_to_en():
    """terms_for_country for an unknown country code must still return EN terms."""
    profile = _make_profile(terms={"EN": ["campsite", "motorhome stopover"]})
    terms = profile.terms_for_country("ZZ")
    assert "campsite" in terms
    assert "motorhome stopover" in terms


def test_terms_for_country_empty_terms():
    """terms_for_country must return an empty list when terms is empty."""
    profile = _make_profile(terms={})
    assert profile.terms_for_country("DE") == []


def test_terms_for_country_preserves_order():
    """Country-specific terms must come before EN terms in the result."""
    profile = _make_profile(terms={"FR": ["camping", "aire de camping-car"], "EN": ["campsite"]})
    terms = profile.terms_for_country("FR")
    # "campsite" (EN) must appear after "camping" and "aire de camping-car" (FR).
    en_idx = terms.index("campsite")
    fr_idx = terms.index("camping")
    assert fr_idx < en_idx


def test_terms_for_country_no_duplicate_en_when_only_en_requested():
    """terms_for_country('EN') must not produce duplicate EN entries."""
    profile = _make_profile(terms={"EN": ["campsite", "caravan site"]})
    terms = profile.terms_for_country("EN")
    assert len(terms) == len({t.lower() for t in terms})


# ---------------------------------------------------------------------------
# SearchProfile is frozen (immutable)
# ---------------------------------------------------------------------------


def test_search_profile_is_frozen():
    """SearchProfile must be frozen (dataclass frozen=True) so attributes cannot be set."""
    profile = _make_profile()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        profile.id = "modified"  # type: ignore[misc]


def _minimal_profile_dict(profile_id: str, description: str) -> dict:
    return {
        "id": profile_id,
        "description": description,
        "symbol": "Pin",
        "defaults": {"max_km": 5.0, "sample_km": 10.0, "batch_size": 2, "retries": 1},
        "tags": [{"key": "tourism", "value": "attraction"}],
        "terms": {"EN": ["test"]},
    }


def test_merged_builtin_user_layout_user_wins(tmp_path):
    """When *profiles_dir* has builtin/ and user/, the user file wins for the same id."""
    root = tmp_path / "root"
    (root / "builtin").mkdir(parents=True)
    (root / "user").mkdir(parents=True)
    (root / "builtin" / "same.yaml").write_text(
        yaml.dump(_minimal_profile_dict("same", "from builtin")), encoding="utf-8"
    )
    (root / "user" / "same.yaml").write_text(
        yaml.dump(_minimal_profile_dict("same", "from user")), encoding="utf-8"
    )
    merged = load_all_profiles(profiles_dir=root)
    assert merged["same"].description == "from user"
    assert load_profile("same", profiles_dir=root).description == "from user"


def test_dump_yaml_roundtrip_matches_id(profiles_dir):
    """dump_profile_yaml → profile_from_yaml_text preserves id and key fields."""
    p = load_profile("camping", profiles_dir=profiles_dir)
    p2 = profile_from_yaml_text(dump_profile_yaml(p))
    assert p2.id == p.id
    assert p2.description == p.description
    assert p2.max_km == p.max_km


def test_save_profile_writes_user_file(tmp_path):
    """save_profile writes under *profiles_dir*/user/ for Android-style roots."""
    root = tmp_path / "root"
    (root / "builtin").mkdir(parents=True)
    (root / "user").mkdir(parents=True)
    prof = profile_from_yaml_text(
        yaml.dump(_minimal_profile_dict("alpha", "saved here")),
    )
    path = save_profile(prof, profiles_dir=root)
    assert path.parent == root / "user"
    assert path.exists()
    assert load_profile("alpha", profiles_dir=root).description == "saved here"
