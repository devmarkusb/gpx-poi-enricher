# Agent instructions (gpx-poi-enricher)

Portable project rules for coding agents. Prefer this file as the single source of truth;
tool-specific files should only add thin pointers or scoping.

## 1. Project overview

Python package (**Hatchling** build, **uv** for env and runs) that enriches GPX tracks with OSM
POIs via YAML profiles, plus CLIs and an optional **PyQt6** GUI. The repo root also contains an
**`android/`** Kotlin app (**Chaquopy** bundles Python; **Gradle**) for Google Play. Public HTTP
usage includes Overpass, Nominatim, and optional OSRM—see `README.md` for behavior and
attribution.

## 2. Build commands

- **Install deps (dev, matches CI):** `uv sync --extra dev`
- **Optional GUI dev deps:** `uv sync --extra dev --extra gui`
- **Build wheel/sdist:** `uv build` (artifacts under `dist/`)

## 3. Test commands

- **Python (matches CI coverage flags):**
  `uv run pytest --cov=gpx_poi_enricher --cov-report=term-missing --cov-report=xml -v`
- **Python (quick local):** `uv run pytest` (uses `[tool.pytest.ini_options]` in
  `pyproject.toml`)
- **Dependency audit (matches CI):** `uv audit --locked --preview-features audit`
- **Android unit tests:** `./gradlew test` from `android/` — **unverified** without a local SDK;
  needs `ANDROID_HOME` or `sdk.dir` in `android/local.properties`. CI uses
  `.github/workflows/android-play.yml` for releases, not a routine Gradle test job.

## 4. Formatting and linting

- **Full hook suite (matches CI “lint” job):** `uv run pre-commit run --all-files`
  Includes **Ruff** (lint + format), **pyupgrade**, **markdownlint**, **codespell**, generic file
  checks, and hooks for **gersemi** / **clang-format** (no CMake/C++ in tree at time of writing;
  hooks still run as configured).
- **Ruff only (fast):** `uv run ruff check .` and `uv run ruff format .` (or
  `ruff format --check .` for no writes)
- **Markdownlint config:** `.markdownlint.yaml`
- **Optional local setup:** `./scripts/setup-pre-commit.sh` installs hooks via an external
  helper; not required if you use `uv run pre-commit` directly.

## 5. Architecture and important directories

| Path | Role |
| --- | --- |
| `src/gpx_poi_enricher/` | Library and CLI/GUI entrypoints |
| `tests/` | `pytest` suite (HTTP mocking via `responses`) |
| `profiles/` | Built-in YAML POI profiles shipped with the tool |
| `android/` | Play Store app, Fastlane metadata, Gradle/Chaquopy integration |
| `pyproject.toml` | Project metadata, Ruff/pytest/coverage/semantic-release settings |

Android `versionCode` / `versionName` are derived from `pyproject.toml`—keep releases consistent
when bumping versions.

## 6. Coding conventions

- **Python:** Target **3.10+**; Ruff `line-length = 100`, rules `E,F,W,I,UP` with `E501` ignored.
  Match existing module layout and CLI patterns in `cli.py`, `maps_to_gpx_cli.py`, etc.
- **Kotlin/Android:** Follow existing package `com.gpxpoienricher`, Material patterns, and
  Chaquopy-related constraints in `android/app/build.gradle.kts`.
- **Profiles:** YAML schema is user-facing; preserve backward compatibility for existing keys and
  documented CLI flags.

## 7. Testing expectations

- Run **`uv run pytest`** (or CI-equivalent with coverage) before finishing changes that touch
  Python logic, CLI behavior, or profiles loading.
- Prefer **mocked HTTP** in tests (`responses`); do not add tests that hit live
  Overpass/Nominatim/OSRM by default.
- For Android changes, run Gradle tests locally when SDK is available; if not, state that tests
  were not run.

## 8. Files and directories agents must not edit without explicit approval

- **Lockfiles:** `uv.lock`, `android/Gemfile.lock`
- **Secrets and local env:** paths from `.gitignore` for keys—e.g. `android/local.properties`,
  `android/keystore.properties`, `*.jks`, `android/play-console-service-account.json`, repo-root
  `local.properties`
- **Generated / vendored / build output:** `dist/`, `build/`, `.eggs/`, `htmlcov/`,
  `.pytest_cache/`, `.ruff_cache/`, `android/vendor/`, `.mb-pre-commit-gen/`, `.venv/`
- **CI release / deployment automation:** `.github/workflows/release.yml`,
  `.github/workflows/android-play.yml` (and signing/upload secrets)—only when the user explicitly
  requests release pipeline work
- **Large binary or store-only assets:** respect `.gitignore` for Play metadata churn (e.g.
  generated changelogs under `android/fastlane/metadata/...`)

## 9. Security and privacy constraints

- **Never commit** keystores, Play service JSON, API keys, or tokens; use placeholders in
  code/docs and local files only.
- **User data:** GPX/routes may contain sensitive locations; do not log full coordinates or upload
  fixtures with real user tracks without scrubbing.
- **Network defaults:** Project uses public endpoints; do not ship hard-coded private keys or
  org-internal URLs without explicit product direction.

## 10. Review checklist before final response

- [ ] Commands run (or clearly marked skipped / unverified) align with sections 2–4.
- [ ] No accidental edits to lockfiles, secrets paths, or generated dirs.
- [ ] Python tests pass when behavior changed; Android tests noted if SDK missing.
- [ ] Dependency audit passes when dependency metadata or lock state changed.
- [ ] **Conventional commits** may be enforced on `main` via CI + `conventional-pre-commit`—follow
  conventional style for commit messages when asked to commit.

## Maintenance policy (layering)

- **Global / user:** IDE preferences, personal MCP servers, machine `local.properties`, local
  `.venv`.
- **Repository root:** This `AGENTS.md`, thin `CLAUDE.md`, `.cursor/rules/*.mdc` adapters,
  `pyproject.toml`, CI—shared by all contributors.
- **Nested:** No separate nested `AGENTS.md` unless Android or another subtree gains a conflicting
  toolchain; until then, Android notes live in this file.
- **Session / chat:** Task-only scope (e.g. “fix profile X”)—do not fork long-lived rules there.

Note: **`.claude/` is gitignored** in this repo (local Claude Code only). Versioned agent guidance
should stay in `AGENTS.md` / `CLAUDE.md` unless the team deliberately stops ignoring `.claude/` for
shared hooks.
