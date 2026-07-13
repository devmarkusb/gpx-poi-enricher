# gpx-poi-enricher

**CLI tools and a desktop GUI for turning Google Maps directions into routed GPX tracks and POI waypoint files.**

[![CI][badge-ci]][ci]
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://badge.fury.io/py/gpx-poi-enricher.svg)](https://pypi.org/project/gpx-poi-enricher/)

---

## Table of Contents

- [The Pipeline](#the-pipeline)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [GUI](#gui)
- [Environment variables](#environment-variables)
- [Command: maps-to-gpx](#command-maps-to-gpx)
- [Command: gpx-split-waypoints](#command-gpx-split-waypoints)
- [Command: gpx-poi-enricher](#command-gpx-poi-enricher)
- [Built-in Profiles](#built-in-profiles)
- [POI catalog](#poi-catalog)
- [Creating Custom Profiles](#creating-custom-profiles)
- [How It Works](#how-it-works)
- [Data Attribution](#data-attribution)
- [Contributing](#contributing)
- [License](#license)

---

## The Pipeline

```
Google Maps URL
      │
      ▼
 maps-to-gpx          ← directions URL → routed GPX track
      │
      ▼
gpx-split-waypoints   ← optional: evenly-spaced split markers
      │
      ▼
gpx-poi-enricher      ← OpenStreetMap POIs along the track
      │
      ▼
 waypoints.gpx        ← Garmin / OsmAnd / Google My Maps <https://www.google.com/mymaps>
```

All three commands install together and can be run alone or chained. Split and POI output are
**waypoints-only** GPX (no `<trk>`) — import alongside the route file or merge externally. Files
>5 MB? Try <https://www.gpxtokml.com/>.

---

## Features

- **`maps-to-gpx`** — Google Maps URL (incl. `maps.app.goo.gl`) → routed GPX via Nominatim + public
  OSRM; custom base URL via `OSRM_BASE_URL` or `--osrm-base-url`. No API keys for defaults.
- **`gpx-split-waypoints`** — evenly spaced split `<wpt>` markers for waypoint-limited apps.
- **`gpx-poi-enricher`** — OSM POIs along a track; **10** curated YAML profiles plus a **POI
  catalog** (~95 common types); **`--quick`** for sparse smoke tests.
- **GUI** (`gpx-poi-enricher-gui`) — **Easy**: URL → GPX(s) → POIs; **Expert**: CLI tools in tabs;
  **Profiles**: add POI types from the built-in catalog.
- Country-aware **`terms`** (`DE`, `FR`, `ES`, `EN`); Overpass mirrors with retries; per-profile
  defaults overridable on the CLI; custom YAML via **`GPX_POI_PROFILES_DIR`**.

---

## Installation

**Python 3.10+**. Use an isolated install — system Python is often
[externally managed](https://peps.python.org/pep-0668/) on Linux. Recommended: venv + pip:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install gpx-poi-enricher              # CLI
pip install "gpx-poi-enricher[gui]"       # CLI + PyQt6 GUI
```

**Alternatives:** `pipx install "gpx-poi-enricher[gui]"` (no activate); or
`uv tool install "gpx-poi-enricher[gui]"` with [uv](https://docs.astral.sh/uv/).

### Development

```bash
git clone https://github.com/devmarkusb/gpx-poi-enricher.git && cd gpx-poi-enricher
uv sync --extra dev --extra gui   # .venv + editable install (matches CI)
./scripts/setup-pre-commit.sh
uv run pytest                     # uv run <cmd> works without activating .venv
```

Without uv: venv + `pip install -e ".[dev,gui]"`. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Quick Start

Google Maps URL → campsite waypoints:

```bash
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Barcelona/" route.gpx
gpx-split-waypoints route.gpx route-split.gpx 10    # optional split markers
gpx-poi-enricher route.gpx camping.gpx --profile camping
```

---

## GUI

```bash
gpx-poi-enricher-gui          # requires [gui] extra — see Installation
gpx-poi-enricher-gui --quick  # sparse enrichment ([quick] in title bar)
```

From a clone: `uv run gpx-poi-enricher-gui`.

**macOS app bundle** (Finder/Dock icon, double-click): after `uv sync --extra gui`, run
`uv run python scripts/build_macos_app.py` → `dist/GPX POI Enricher.app`. Drag to Applications or
Dock. Rebuild after upgrading the package in `.venv`.

**Easy** — one primary Maps URL (required), optional extra URLs per line → routed GPX(s), optional
alternate/detour GPX files, then POI enrichment. Progress log + file list; cancel after current
Overpass batch.

**Expert** — POI Enricher, Split Waypoints, Maps → GPX, and **Profiles** tabs (same CLIs; Maps tab
supports multiple URLs like Easy). **Profiles → Add from catalog…** adds common OSM POI types
(museums, pharmacies, viewpoints, …) as editable user profiles. Long-running work is off the UI
thread.

---

## Environment variables

**`GPX_POI_PROFILES_DIR`** — existing directory of `*.yaml` **replaces** built-in profiles.

**`OSRM_BASE_URL`** — OSRM root ending in `/route/v1` for `maps-to-gpx` (override with
`--osrm-base-url`).

---

## Command: maps-to-gpx

One Google Maps directions URL → routed GPX (`<trk>` + stopover `<wpt>`). Short links, path-style
(`/maps/dir/A/B/C`), and query-style (`?api=1&origin=…`) URLs. Names →
[Nominatim](https://nominatim.openstreetmap.org/); routing → public
[OSRM](http://router.project-osrm.org/) or your own stack. Multiple routes/detours: use the GUI.

Run `maps-to-gpx --help` for `--mode`, `--name`, `--osrm-base-url`.

```bash
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Marseille/" route.gpx
maps-to-gpx "https://maps.app.goo.gl/ABC123" route.gpx
maps-to-gpx "https://www.google.com/maps/dir/Amsterdam/Utrecht/" route.gpx --mode cycling
maps-to-gpx "https://www.google.com/maps/dir/A/B/" route.gpx \
  --osrm-base-url "https://my-osrm.example.com/route/v1"   # must end with /route/v1
```

---

## Command: gpx-split-waypoints

Track → **`segments − 1`** evenly spaced waypoints (`Split 1`, …); description holds track position
(e.g. `10.0% of track length`). Waypoints only — companion file, not the original track.
`segments >= 2`.

```bash
gpx-split-waypoints route.gpx route-split.gpx       # 10 segments → 9 waypoints (default)
gpx-split-waypoints route.gpx route-split.gpx 5   # 5 segments → 4 waypoints
```

---

## Command: gpx-poi-enricher

Track GPX in → waypoints-only POI GPX out. Run `gpx-poi-enricher --help` for all flags.

- `--profile` — required unless `--list-profiles`
- `--max-km` — max distance from track to keep a POI
- `--sample-km` — sampling step along the track
- `--batch-size` — sample points per Overpass request
- `--country-sample-km` — Nominatim spacing for country detection (default **40**; **500** with
  `--quick`)
- `--progress-interval` — stderr progress in seconds (`0` off; default `5`)
- `--verbose` — verbose Overpass error bodies
- `--list-profiles` — list profiles and defaults, then exit
- `--quick` — sparse defaults (~500 km sample/country, 1 km radius) unless overrides are set

```bash
gpx-poi-enricher route.gpx camping.gpx --profile camping
gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5
gpx-poi-enricher --list-profiles
gpx-poi-enricher route.gpx probe.gpx --profile camping --quick
```

---

## Built-in Profiles

From `profiles/`. `gpx-poi-enricher --list-profiles` shows `sample_km`, `batch_size`, `retries`.

| Profile | Description (YAML) | Default max_km |
| :------ | :----------------- | -------------: |
| `camping` | Campsite | 10.0 |
| `playground` | Playground | 3.0 |
| `outdoor_pool` | Outdoor Pool, Adventure Pool, Thermal Bath | 10.0 |
| `beach` | Swimming Lake, Beach | 20.0 |
| `theme_park` | Theme Park | 12.0 |
| `zoo` | Zoo, Petting Zoo | 12.0 |
| `aquarium` | Aquarium | 15.0 |
| `mcdonalds` | McDonalds | 5.0 |
| `restaurant` | Restaurant | 2.0 |
| `kids_activities` | Children's Activities of All Kinds | 15.0 |

**`kids_activities`** matches mainly via **`terms`** (regex on OSM `name` / `description` /
`operator`); most others use **`tags`**, optionally plus **`terms`**.

---

## POI catalog

Besides the curated built-ins above, the app ships a **catalog of ~95 common OSM POI types**
(restaurants, museums, pharmacies, viewpoints, …) in
`src/gpx_poi_enricher/data/poi_catalog.yaml`.

**Desktop GUI:** Expert → **Profiles** → **Add from catalog…** — searchable list by category.
**Android:** **Profiles** tab → **Add from catalog…**

Choosing an entry writes a **user profile** YAML with:

- OSM **`tags`** from the catalog entry
- **`defaults`** from a preset bucket (`urban_dense`, `regional_sparse`, …) — e.g. tight radius for
  shops, wider radius for zoos
- empty **`terms`** (tag-only search; edit later if you need name matching)

If the profile id already exists (e.g. built-in `aquarium`), saving from the catalog creates a
**user override** with the same id. You can edit radius, symbols, or add `terms` afterward.

Programmatic use:

```python
from gpx_poi_enricher.poi_catalog import save_catalog_entry

save_catalog_entry("museum")  # writes ~/.config/gpx-poi-enricher/profiles/museum.yaml (desktop)
```

---

## Creating Custom Profiles

**Easiest:** use **Add from catalog…** in the GUI (see [POI catalog](#poi-catalog)) for standard OSM
types, then edit the generated YAML if needed.

**Manual:** add a YAML file; **`id`** or filename (without `.yaml`) is the profile id. With PyPI
installs, set **`GPX_POI_PROFILES_DIR`** to use **only** your profiles.

```yaml
# profiles/my_profile.yaml
id: my_profile
description: "My custom POI type"
symbol: Flag, Blue          # Garmin symbol in output GPX

defaults:
  max_km: 8.0
  sample_km: 4.0
  batch_size: 5
  retries: 3

tags:                       # any tag line can match
  - key: tourism
    value: museum
  - key: amenity
    value: fast_food
    and:
      key: cuisine
      value: pizza

terms:                      # regex selectors (per country + EN)
  DE: ["Museum", "Schloss"]
  FR: ["musée", "château"]
  ES: ["museo", "castillo"]
  EN: ["museum", "castle"]
```

Need non-empty **`tags`** or **`terms`** for the current country plus **`EN`** (else query build
fails). **`defaults`** keys are overridable on the CLI.

---

## How It Works

**maps-to-gpx:** expand short URLs → parse path/query (geocode names, keep coords) → OSRM route →
GPX `<trk>` + stopover `<wpt>`.

**POI enrichment:** sample every `sample_km` → reverse-geocode country every `country_sample_km` →
Overpass per batch (`tags` = typed selectors; `terms` = regex on name/description/operator within
`max_km`) → dedupe by OSM id → `<wpt>` only. Mirrors rotate; retries on failure.

---

## Data Attribution

Map data © [OpenStreetMap](https://www.openstreetmap.org/) contributors — [ODbL](https://opendatacommons.org/licenses/odbl/).
[Nominatim](https://nominatim.openstreetmap.org/) — OSM Foundation. Routing —
[OSRM](http://project-osrm.org/) public demo (ODbL).

**Usage policies:** Nominatim ~1 req/s + meaningful `User-Agent` (this project sends one); Overpass —
no bulk scraping; OSRM demo — personal/non-commercial; use **`OSRM_BASE_URL`** /
**`--osrm-base-url`** for heavy use.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues:
[GitHub](https://github.com/devmarkusb/gpx-poi-enricher/issues).

---

## License

MIT — [LICENSE](LICENSE).

[badge-ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions
