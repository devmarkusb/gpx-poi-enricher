# Contributing to gpx-poi-enricher

Thank you for your interest in contributing. This document covers everything you need to get started.

---

## Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/devmarkusb/gpx-poi-enricher.git
cd gpx-poi-enricher
```

### 2. Create a virtual environment and install in editable mode

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The `[dev]` extra installs testing and linting dependencies (`pytest`, `ruff`, `pre-commit`, etc.).

### 3. Install git hooks

```bash
./scripts/setup-pre-commit.sh
```

This bootstraps hooks using `devmarkusb/pre-commit` in one-shot mode (without adding a submodule).
It also installs a `commit-msg` hook that enforces [Conventional Commits](https://www.conventionalcommits.org/)
once the dev environment exists so `pre-commit` is available.

If you set up the venv after running the script, install the hook once: `pre-commit install --hook-type commit-msg`.

### 4. Run the test suite

```bash
pytest
```

All tests must pass before submitting a pull request.

### 5. Run linters/format checks

```bash
pre-commit run --all-files
```

---

## Adding a New Profile

Adding a profile requires no Python code. Simply create a YAML file in the `profiles/` directory:

```
profiles/my_new_profile.yaml
```

The filename without the `.yaml` extension becomes the profile ID (lower-case, no
spaces). Follow the structure of any existing profile. The required fields are
`id`, `description`, `symbol`, `defaults`, `tags`, and `terms`. See
[README.md](README.md#creating-custom-profiles) for a fully annotated example.

After adding the file, verify it loads correctly:

```bash
gpx-poi-enricher --list-profiles
```

Please add at least one test that loads the new profile and checks that the
expected `id` and `description` are present.

---

## Pull Request Guidelines

- **Describe what and why**: the PR description should explain the motivation and
  summarise the changes. A title like "Add aquapark profile" is fine;
  "fix stuff" is not.
- **Tests are required**: new features and bug fixes must include tests. The CI
  will reject PRs that reduce overall coverage without justification.
- **pre-commit must pass** — run `pre-commit run --all-files` locally and fix all reported issues before pushing.
- **One concern per PR**: keep PRs focused. If you want to fix a bug and add a
  feature, open two separate PRs.
- **Commit messages**: follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `chore:`, …), imperative mood, and keep the first line under 72 characters
  (e.g. `feat: add kids_activities profile`).

---

## API Rate Limit Reminder

This tool uses two public, free-to-use APIs. Please be mindful of the load you
place on them, both when developing and in production use:

- **Nominatim** (reverse geocoding): the
  [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/)
  requires a maximum of **1 request per second** and a meaningful `User-Agent`
  header. Do not send bulk geocoding requests in tests; mock the HTTP calls
  instead.
- **Overpass API**: the public instances at `overpass-api.de` and
  `overpass.kumi.systems` are community-run. Do not write tests that hit the
  live API. Use mocks or cassettes. Avoid queries that download large areas; the
  default `batch_size` and `max_km` values in the profiles are already tuned to
  be considerate.

If you are running the tool repeatedly during development on the same route,
consider caching responses locally rather than hammering the live endpoints.

---

## Android builds and Google Play

The **`Android Play release`** workflow (`.github/workflows/android-play.yml`) builds a signed **AAB**
and **APK**, attaches them to the GitHub **Release** for `v*` tags, and optionally uploads to
**Google Play** when `PLAY_SERVICE_ACCOUNT_JSON` is set. After **semantic-release** on **`main`**,
the **Release** workflow dispatches this workflow on the new tag (same pattern as
[gpx-link](https://github.com/devmarkusb/gpx-link)).

**Secrets** (repository → Settings → Secrets and variables → Actions):

| Secret | Purpose |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | Base64 of the upload keystore (`.jks` or `.p12`; avoid GitHub’s 48KB truncation) |
| `ANDROID_KEYSTORE_PASSWORD` | Keystore password |
| `ANDROID_KEY_ALIAS` | Signing key alias |
| `ANDROID_KEY_PASSWORD` | Key password (for PKCS12, use the same value as the keystore password) |
| `PLAY_SERVICE_ACCOUNT_JSON` | Full JSON of the Play Console API service account (omit to skip Play upload) |

**Variable** (optional): `PLAY_RELEASE_STATUS` (e.g. `draft` while the Play listing is still a draft
app; omit or use `completed` once allowed).

**Store listing** lives under `android/fastlane/metadata/android/en-US/` (`title.txt`, descriptions,
`whatsnew.txt`, images). **versionCode** comes from **`pyproject.toml`** `version = "…"` (same formula
as `android/app/build.gradle.kts`). For **metadata-only** updates without a new binary, run the
workflow manually with **Listing/screenshots only**.

Regenerate listing bitmaps:

```bash
uv run --with pillow python scripts/generate_play_assets.py
```

Local Fastlane (from `android/`): `bundle install` then e.g. `bundle exec fastlane build_release`. Do
not commit `keystore.properties`, keystores, or `play-console-service-account.json`.

---

## Reporting Bugs

Please open a [GitHub issue](https://github.com/devmarkusb/gpx-poi-enricher/issues) and include:

1. The command you ran (sanitise any personal path information if needed).
2. The full error output (including the traceback if applicable).
3. Your Python version (`python --version`) and OS.
4. If possible, a minimal GPX file that reproduces the problem.
