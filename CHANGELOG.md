# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] - 2026-04-21

### Added

- Initial Python package structure under `src/gpx_poi_enricher/` with a `pyproject.toml`-based build.
- 11 built-in YAML profiles: `camping`, `playground`, `outdoor_pool`, `beach`,
  `theme_park`, `zoo`, `aquarium`, `mcdonalds`, `restaurant`, `kids_activities`,
  `attractions`.
- CLI entry point `gpx-poi-enricher` with positional `input_gpx` / `output_gpx`
  arguments and options `--profile`, `--max-km`, `--sample-km`, `--batch-size`,
  `--country-sample-km`, `--progress-interval`, `--verbose`, and
  `--list-profiles`.
- Country-aware search terms: Nominatim reverse-geocoding is used to detect the
  country along the route, selecting the appropriate language variant (`DE`,
  `FR`, `ES`, `EN`) from the profile's `terms` map.
- Overpass API integration with multi-endpoint fallback (rotates through several
  public instances) and configurable per-profile retry logic.
- `ProgressHeartbeat` utility that prints periodic progress lines to stderr during long-running Overpass query batches.
- Comprehensive test suite covering profile loading, GPX parsing, Overpass
  query generation, and the CLI argument parser.

[Unreleased]: https://github.com/devmarkusb/gpx-poi-enricher/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/devmarkusb/gpx-poi-enricher/releases/tag/v0.1.0
