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
 maps-to-gpx          ← converts a directions URL to a routed GPX track
      │
      ▼
gpx-split-waypoints   ← optional: extract evenly-spaced split markers (see below)
      │
      ▼
gpx-poi-enricher      ← queries OpenStreetMap for POIs along the track
      │
      ▼
 waypoints.gpx        ← import into Garmin / OsmAnd / Google My Maps <https://www.google.com/mymaps>
```

All three commands are installed together and can be run alone or chained.

Split and POI steps each write **waypoints-only** GPX files (no `<trk>`). Import both the route file
and those waypoints in your app, or merge them externally if needed.

If a result file is too large (>5 MB) for your consumer app, <https://www.gpxtokml.com/> can help shrink it.

---

## Features

- **`maps-to-gpx`**: Google Maps directions URL (including short `maps.app.goo.gl` links) → routed
  GPX. Place-name stopovers via Nominatim; routing via the public OSRM API. Optional custom OSRM base
  URL or `OSRM_BASE_URL` env. No Google or OSRM API key required for the defaults.
- **`gpx-split-waypoints`**: read a track from an input GPX and write **only** evenly spaced split
  `<wpt>` markers (`Split 1`, …) for apps that limit imported waypoints.
- **`gpx-poi-enricher`**: enrich a GPX track with OpenStreetMap POIs using **11** built-in YAML
  profiles (camping, beaches, playgrounds, theme parks, restaurants, etc.). **`--quick`** smoke-test
  mode for fast, sparse sampling.
- **GUI** (`gpx-poi-enricher-gui`): **Easy** mode runs Maps URL → routed GPX(s) → POI enrichment in
  one flow; **Expert** exposes the enricher, split, and Maps→GPX tools as separate tabs. Optional
  **`--quick`** flag for both modes.
- Country-aware **`terms`** (`DE`, `FR`, `ES`, `EN`): reverse-geocoding along the route picks a
  country so queries can use localized strings where profiles define them.
- Overpass queries use several public endpoints with retries.
- Profiles: per-profile defaults for radius, sampling, batch size, and retries; everything can be
  overridden on the CLI. Custom profiles via YAML and optional **`GPX_POI_PROFILES_DIR`**.

---

## Installation

### From PyPI (recommended)

```bash
pip install gpx-poi-enricher          # CLI tools only
pip install "gpx-poi-enricher[gui]"   # CLI + desktop GUI (PyQt6)
```

### From source (development)

```bash
git clone https://github.com/devmarkusb/gpx-poi-enricher.git
cd gpx-poi-enricher
pip install -e ".[dev,gui]"
./scripts/setup-pre-commit.sh
```

---

## Quick Start

Google Maps URL → campsite waypoints:

```bash
# Step 1: directions link → routed GPX (track + stopover waypoints)
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Barcelona/" route.gpx

# Step 2 (optional): split markers only → route-split.gpx (import alongside route.gpx)
gpx-split-waypoints route.gpx route-split.gpx 10

# Step 3: POIs along the route track (use the same track file you want to query)
gpx-poi-enricher route.gpx camping.gpx --profile camping
```

---

## GUI

Launch:

```bash
gpx-poi-enricher-gui
```

Development equivalent: `python -m gpx_poi_enricher.gui` (with the package on `PYTHONPATH` or installed).

**Quick mode:** append `--quick` to use sparse enrichment defaults in Easy and Expert’s POI Enricher (title bar shows `[quick]`).

Requires the `gui` extra: `pip install "gpx-poi-enricher[gui]"`.

### Easy vs Expert

**Easy** — Primary Google Maps URL (required); optional **additional URLs** (one per line) for
alternate itineraries. Writes the primary routed GPX, optional alternate-route GPX files, optional
**detour** fragment GPX files where an alternate differs from the primary, then runs POI enrichment
on the tracks to search. Progress log and a list of generated files. Cancel stops after the current
Overpass batch.

**Expert** — Same three tools as the CLIs in tabs: **POI Enricher**, **Split Waypoints**,
**Maps → GPX**. The Maps → GPX tab also supports **multiple URLs** (primary + optional
alternates/detours), matching the richer routing behaviour in Easy.

Long-running work runs off the UI thread.

---

## Environment variables

**`GPX_POI_PROFILES_DIR`** — If set to an existing directory, built-in profiles are **replaced** by
every `*.yaml` in that folder (for private or dev profiles without editing the package).

**`OSRM_BASE_URL`** — Default OSRM API root ending in `/route/v1` for `maps-to-gpx`. Overridden per
run by **`--osrm-base-url`**.

---

## Command: maps-to-gpx

Converts **one** Google Maps directions URL to a routed GPX file.

- Resolves short `maps.app.goo.gl` links
- Path-style (`/maps/dir/A/B/C`) and query-style (`?api=1&origin=…`) URLs
- Place names → [Nominatim](https://nominatim.openstreetmap.org/)
- Routing → public [OSRM](http://router.project-osrm.org/) (or your own via env / `--osrm-base-url`)
- Output: `<trk>` geometry plus `<wpt>` for each user stopover

For **multiple routes or detour GPX** generation, use the GUI (Easy or Maps → GPX).

```
usage: maps-to-gpx [-h] [--mode {driving,cycling,walking}] [--name NAME]
                   [--osrm-base-url URL]
                   url output_gpx

positional arguments:
  url                   Google Maps directions URL (full or short
                        maps.app.goo.gl link)
  output_gpx            Output GPX file path

options:
  -h, --help            show this help message and exit
  --mode {driving,cycling,walking}
                        Transport mode for routing (default: driving)
  --name NAME           Track name written into the GPX file (default: Route)
  --osrm-base-url URL   OSRM API root ending in /route/v1 (default: public demo;
                        overrides OSRM_BASE_URL env if set)
```

**Examples:**

```bash
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Marseille/" route.gpx
maps-to-gpx "https://maps.app.goo.gl/ABC123" route.gpx
maps-to-gpx \
  "https://www.google.com/maps/dir/?api=1&origin=Paris&destination=Barcelona&waypoints=Lyon|Avignon" \
  route.gpx --name "France to Spain"
maps-to-gpx "https://www.google.com/maps/dir/Amsterdam/Utrecht/" route.gpx --mode cycling

# Self-hosted OSRM (URL must end with /route/v1)
maps-to-gpx "https://www.google.com/maps/dir/A/B/" route.gpx \
  --osrm-base-url "https://my-osrm.example.com/route/v1"
```

---

## Command: gpx-split-waypoints

Reads track points from the input GPX and writes **`segments - 1` waypoints** at even distances
along the track (`Split 1`, …). Each waypoint’s description holds the fractional position along
the track (e.g. `10.0% of track length`).

Output is **waypoints only** — not the original track. Use it as a companion file or merge in your toolchain.

Requires **`segments >= 2`**.

```
usage: gpx-split-waypoints input.gpx output.gpx [segments]

positional arguments:
  input.gpx     Input GPX file with a track (≥ 2 points)
  output.gpx    Output GPX (split waypoint markers only)
  segments      Split into N equal segments → N−1 markers (default: 10)
```

**Examples:**

```bash
gpx-split-waypoints route.gpx route-split.gpx       # default: 10 segments → 9 waypoints
gpx-split-waypoints route.gpx route-split.gpx 5     # 5 segments → 4 waypoints
```

---

## Command: gpx-poi-enricher

Queries OpenStreetMap along the input GPX track and writes **waypoints-only** output.

```
usage: gpx-poi-enricher [-h] [--profile PROFILE] [--max-km MAX_KM]
                        [--sample-km SAMPLE_KM] [--batch-size BATCH_SIZE]
                        [--country-sample-km COUNTRY_SAMPLE_KM]
                        [--progress-interval SEC] [--verbose] [--quick]
                        [--list-profiles]
                        [input_gpx] [output_gpx]
```

**Positional arguments:**

- `input_gpx` — GPX with a track to sample
- `output_gpx` — GPX containing only `<wpt>` POIs

**Options (subset):**

- `--profile` — profile id (case-insensitive), required unless `--list-profiles`
- `--max-km`, `--sample-km`, `--batch-size`, `--country-sample-km` — override profile defaults
- `--progress-interval` — stderr progress interval in seconds (`0` disables; default `5`)
- `--verbose` — print verbose Overpass error bodies
- `--list-profiles` — print all profiles and defaults, then exit
- **`--quick`** — combines with unset overrides: about **500 km** sampling, **1 km** search radius,
  **500 km** country re-detection. Still overridden by explicit `--sample-km` / `--max-km` /
  `--country-sample-km`.

**Examples:**

```bash
gpx-poi-enricher route.gpx camping.gpx --profile camping
gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5
gpx-poi-enricher --list-profiles
gpx-poi-enricher route.gpx probe.gpx --profile camping --quick
```

### Key options explained

- **`--max-km`** — Maximum distance from the sampled track for a POI to be kept.
- **`--sample-km`** — Sampling step along the track before Overpass batching.
- **`--batch-size`** — Sample points bundled into one Overpass request (timeouts vs load).
- **`--country-sample-km`** — Minimum spacing between Nominatim reverse-geocode calls for country
  detection (default **40** when not using `--quick`).

---

## Built-in Profiles

Defaults come from each file under `profiles/`. Run `gpx-poi-enricher --list-profiles` for full
`sample_km`, `batch_size`, and `retries`.

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
| `restaurant` | Restaurant with Kids Menu | 5.0 |
| `kids_activities` | Children's Activities of All Kinds | 15.0 |
| `attractions` | Generally spectacular child-friendly attraction | 10.0 |

Profiles like **`attractions`** and **`kids_activities`** use **`terms`** (regex over OSM `name` /
`description` / `operator`) with empty **`tags`**; others rely mainly on **`tags`** and may add
**`terms`** for extra matches.

---

## Creating Custom Profiles

Add a YAML file. The **`id`** field or the filename (without `.yaml`) is the profile id.

When installed from PyPI, point **`GPX_POI_PROFILES_DIR`** at a folder of YAML files to use **only**
those profiles instead of the bundled set.

```yaml
# profiles/my_profile.yaml
id: my_profile
description: "My custom POI type"
symbol: Flag, Blue          # Garmin symbol name shown in the output GPX

defaults:
  max_km: 8.0
  sample_km: 4.0
  batch_size: 5
  retries: 3

# Matchers: ANY tag line can match OR (below) regex terms contribute extra selectors.
tags:
  - key: tourism
    value: museum
  - key: amenity
    value: fast_food
    and:
      key: cuisine
      value: pizza

terms:
  DE: ["Museum", "Schloss"]
  FR: ["musée", "château"]
  ES: ["museo", "castillo"]
  EN: ["museum", "castle"]
```

You need **at least one** of: non-empty **`tags`**, or **`terms`** for the current country plus shared
**`EN`** terms (otherwise Overpass query construction fails). All keys in **`defaults`** can be
overridden from the CLI.

---

## How It Works

### maps-to-gpx

1. Expand short URLs via HTTP redirects.
2. Parse path or query parameters; coordinates used as-is; names geocoded with Nominatim.
3. Route through OSRM; receive polyline geometry.
4. Emit GPX `<trk>` plus user `<wpt>` elements.

### POI enrichment

1. Sample the track every `sample_km`.
2. Every `country_sample_km`, reverse-geocode with Nominatim for ISO country codes.
3. Build Overpass QL per batch: **`tags`** → typed selectors around each sample; **`terms`** →
   case-insensitive regex on selected elements’ `name` / `description` / `operator` within `max_km`.
4. Merge results and deduplicate by OSM id.
5. Write POIs as `<wpt>` only; no tracks in the POI output file.

Overpass POSTs rotate through configured public mirrors and retry on failure.

---

## Data Attribution

Map data © [OpenStreetMap](https://www.openstreetmap.org/) contributors — [ODbL](https://opendatacommons.org/licenses/odbl/).

> © OpenStreetMap contributors

[Nominatim](https://nominatim.openstreetmap.org/) — OpenStreetMap Foundation.

Routing — [OSRM](http://project-osrm.org/) public demo (ODbL); same caveats as in earlier README:
usage limits, attribution, prefer self-hosted for heavy use.

**Usage policies:**

- Nominatim: ~1 request/s; meaningful `User-Agent` (the tool sends one identifying this project).
- Overpass: no bulk scraping; conservative defaults by design.
- OSRM demo: personal / non-commercial expectations; **`OSRM_BASE_URL`** / **`--osrm-base-url`** for your own stack.

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

After cloning: `./scripts/setup-pre-commit.sh` (hooks via `devmarkusb/pre-commit`, no submodule).

Bug reports and feature requests: [GitHub issues](https://github.com/devmarkusb/gpx-poi-enricher/issues).

---

## License

MIT — see [LICENSE](LICENSE).

[badge-ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions
