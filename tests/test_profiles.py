"""Tests for gpx_poi_enricher.profiles module.

Covers: load_profile, load_all_profiles, SearchProfile fields,
terms_for_country (deduplication, country fallback), FileNotFoundError.
"""

from __future__ import annotations

import pytest
import yaml

from gpx_poi_enricher.profiles import SearchProfile, load_all_profiles, load_profile

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


def test_load_profile_camping_tag_structure(profiles_dir):
    """Each tag in the camping profile must have 'key' and 'value' keys."""
    profile = load_profile("camping", profiles_dir=profiles_dir)
    for tag in profile.tags:
        assert "key" in tag
        assert "value" in tag


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
