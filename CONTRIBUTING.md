# Contributing to gpx-poi-enricher

## Development setup

```bash
git clone https://github.com/devmarkusb/gpx-poi-enricher.git && cd gpx-poi-enricher
uv sync --extra dev --extra gui   # .venv, editable install, dev + GUI deps (matches CI)
./scripts/setup-pre-commit.sh     # hooks + Conventional Commits on commit-msg
```

Without [uv](https://docs.astral.sh/uv/): `python3 -m venv .venv`, activate,
`pip install -e ".[dev,gui]"`, then run the hook script. If the venv came later:
`uv run pre-commit install --hook-type commit-msg`.

### Checks before a PR

```bash
uv run pytest
uv run pre-commit run --all-files
uv audit --locked --preview-features audit   # after dependency or lockfile changes
```

All tests must pass; audit fails if `uv.lock` is stale.

---

## Adding a profile

No Python needed — add `profiles/my_new_profile.yaml` (filename → profile id). Required fields:
`id`, `description`, `symbol`, `defaults`, `tags`, `terms`. See
[README](README.md#creating-custom-profiles).

```bash
uv run gpx-poi-enricher --list-profiles
```

Add a test that loads the profile and checks `id` and `description`.

---

## Pull requests

- **Describe what and why** — e.g. `Add aquapark profile`, not `fix stuff`.
- **Tests required** for features and bug fixes; CI rejects unjustified coverage drops.
- **`uv run pre-commit run --all-files`** and **`uv audit`** (when deps changed) must pass.
- **One concern per PR.**
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, …),
  imperative, first line ≤72 chars (e.g. `feat: add kids_activities profile`).

---

## API rate limits (development)

Mock HTTP in tests — do not hit live APIs.

- **Nominatim:** [usage policy](https://operations.osmfoundation.org/policies/nominatim/) — ≤1 req/s,
  meaningful `User-Agent`.
- **Overpass** (`overpass-api.de`, `overpass.kumi.systems`): community-run; no live API tests.

Cache responses locally when iterating on the same route.

---

## Android / Google Play

**Workflow:** `.github/workflows/android-play.yml` — signed AAB/APK on `v*` tags; optional Play
upload when `PLAY_SERVICE_ACCOUNT_JSON` is set (dispatched from Release after semantic-release on
`main`, same pattern as [gpx-link](https://github.com/devmarkusb/gpx-link)).

| Secret | Purpose |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | Base64 upload keystore (avoid GitHub 48KB truncation) |
| `ANDROID_KEYSTORE_PASSWORD` | Keystore password |
| `ANDROID_KEY_ALIAS` | Key alias |
| `ANDROID_KEY_PASSWORD` | Key password (PKCS12: same as keystore password) |
| `PLAY_SERVICE_ACCOUNT_JSON` | Play Console service account JSON (omit to skip upload) |

**Variable:** `PLAY_RELEASE_STATUS` (e.g. `draft`). Listing:
`android/fastlane/metadata/android/en-US/`. **versionCode** from `pyproject.toml` (same as
`android/app/build.gradle.kts`). Metadata-only: run workflow with **Listing/screenshots only**.

```bash
uv run --with pillow python scripts/generate_play_assets.py   # listing bitmaps
```

Local build (`android/`): `bundle install && bundle exec fastlane build_release`. Never commit
`keystore.properties`, keystores, or `play-console-service-account.json`.

---

## Reporting bugs

[Open an issue](https://github.com/devmarkusb/gpx-poi-enricher/issues) with:

1. Command run (sanitise paths if needed)
2. Full error / traceback
3. `python --version` and OS
4. Minimal repro GPX, if possible
