# gpx-poi-enricher

**A three-command toolkit for building POI-enriched GPX files from a Google Maps route.**

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
gpx-split-waypoints   ← adds evenly-spaced split markers (optional, for long routes)
      │
      ▼
gpx-poi-enricher      ← queries OpenStreetMap for POIs along the track
      │
      ▼
 waypoints.gpx        ← import into Garmin / OsmAnd / Google My Maps <https://www.google.com/mymaps>
```

All three commands are installed together and work independently or in sequence.
In the end, if the result file is too large (>5MB) for your consumer app, <https://www.gpxtokml.com/>
helps a lot.

---

## Features

- **`maps-to-gpx`**: convert a Google Maps directions URL (including short
  `maps.app.goo.gl` links) directly to a routed GPX file. Handles place-name
  waypoints via Nominatim geocoding and routes via the public OSRM API. No API
  key required.
- **`gpx-split-waypoints`**: add evenly-spaced split waypoints to a GPX track,
  useful for importing oversized files into apps that enforce a waypoint limit.
- **`gpx-poi-enricher`**: enrich any GPX track with Points of Interest from
  OpenStreetMap. 11 ready-to-use profiles covering camping, beaches,
  playgrounds, theme parks, restaurants, and more.
- **GUI**: a full desktop application (`gpx-poi-enricher-gui`) covering all
  three tools in a single window — no command line required.
- Country-aware search terms: automatically detects which country each section
  of the route passes through and queries in the local language
  (`DE`, `FR`, `ES`, `EN`).
- Searches OpenStreetMap via the public Overpass API with multi-endpoint fallback for reliability.
- Configurable search radius, sampling interval, and batch size per profile — all overridable on the command line.
- Extensible: add a new profile by dropping a single YAML file into the `profiles/` directory.

---

## Installation

### From PyPI (recommended)

```bash
pip install gpx-poi-enricher          # CLI tools only
pip install "gpx-poi-enricher[gui]"   # CLI tools + desktop GUI (requires PyQt6)
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

Full pipeline — Google Maps URL to a campsite waypoint file:

```bash
# Step 1: convert a Google Maps directions link to a GPX track
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Barcelona/" route.gpx

# Step 2 (optional): add split markers every ~10% of the route
gpx-split-waypoints route.gpx route-split.gpx 10

# Step 3: find all campsites within 10 km of the route
gpx-poi-enricher route.gpx camping.gpx --profile camping
```

---

## GUI

A desktop application that wraps all three CLI tools in a single window.

```bash
gpx-poi-enricher-gui
```

Requires the `gui` extra (`pip install "gpx-poi-enricher[gui]"`).

The window has three tabs:

| Tab | What it does |
| :-- | :----------- |
| **POI Enricher** | Select input/output GPX, choose a profile, tweak parameters, run enrichment. A live log shows progress; a results table lists every POI found. A Cancel button stops after the current Overpass batch. |
| **Split Waypoints** | Add evenly-spaced split markers to a GPX track. |
| **Maps → GPX** | Paste a Google Maps directions URL, pick a transport mode, and convert it to a routed GPX file. |

All long-running operations run in a background thread so the UI stays responsive.

---

## Command: maps-to-gpx

Converts a Google Maps directions URL to a routed GPX file.

- Follows redirects for short `maps.app.goo.gl` URLs
- Handles both path-style (`/maps/dir/A/B/C`) and query-style (`?api=1&origin=...`) URLs
- Geocodes place names via [Nominatim](https://nominatim.openstreetmap.org/) (no API key)
- Routes via the public [OSRM](http://router.project-osrm.org/) API (no API key)
- Writes a `<trk>` with the full routed geometry and `<wpt>` markers for each stopover

```
usage: maps-to-gpx [-h] [--mode {driving,cycling,walking}] [--name NAME]
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
```

**Examples:**

```bash
# Path-style URL with place names
maps-to-gpx "https://www.google.com/maps/dir/Paris/Lyon/Marseille/" route.gpx

# Short URL
maps-to-gpx "https://maps.app.goo.gl/ABC123" route.gpx

# Query-style URL with multiple stopovers, custom name
maps-to-gpx \
  "https://www.google.com/maps/dir/?api=1&origin=Paris&destination=Barcelona&waypoints=Lyon|Avignon" \
  route.gpx --name "France to Spain"

# Cycling route
maps-to-gpx "https://www.google.com/maps/dir/Amsterdam/Utrecht/" route.gpx --mode cycling
```

---

## Command: gpx-split-waypoints

Adds evenly-spaced waypoints along a GPX track, named `Split 1`, `Split 2`,
etc. Useful when an app or device has a waypoint import limit and a long route
needs to be broken into manageable segments.

```
usage: gpx-split-waypoints input.gpx output.gpx [segments]

positional arguments:
  input.gpx     Input GPX file with a track
  output.gpx    Output GPX file (original track + split waypoints)
  segments      Number of equal segments to split into (default: 10)
```

**Examples:**

```bash
# Split into 10 equal segments (default)
gpx-split-waypoints route.gpx route-split.gpx

# Split into 5 segments
gpx-split-waypoints route.gpx route-split.gpx 5
```

---

## Command: gpx-poi-enricher

Queries OpenStreetMap for Points of Interest along a GPX track and writes them as waypoints to a new GPX file.

```
usage: gpx-poi-enricher [-h] [--profile PROFILE] [--max-km MAX_KM]
                        [--sample-km SAMPLE_KM] [--batch-size BATCH_SIZE]
                        [--country-sample-km COUNTRY_SAMPLE_KM]
                        [--progress-interval SEC] [--verbose]
                        [--list-profiles]
                        [input_gpx] [output_gpx]

positional arguments:
  input_gpx             Input GPX file with a track
  output_gpx            Output GPX file (waypoints only)

options:
  -h, --help            show this help message and exit
  --profile PROFILE     Profile id, e.g. camping or playground
                        (case-insensitive)
  --max-km MAX_KM       Override max distance from track (km)
  --sample-km SAMPLE_KM
                        Override track sampling interval (km)
  --batch-size BATCH_SIZE
                        Override Overpass query batch size
  --country-sample-km COUNTRY_SAMPLE_KM
                        Min distance (km) between Nominatim reverse-geocode
                        calls (default: 40)
  --progress-interval SEC
                        Print progress to stderr every SEC seconds
                        (default: 5; 0 = off)
  --verbose             Print verbose Overpass error bodies
  --list-profiles       List built-in profiles and exit
```

**Examples:**

```bash
# Find campsites within 10 km of the route
gpx-poi-enricher route.gpx camping.gpx --profile camping

# Find playgrounds within 5 km (overriding the profile default of 3 km)
gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5

# List all available built-in profiles
gpx-poi-enricher --list-profiles
```

### Key options explained

- **`--max-km`**: how far from the track a POI may be to be included. Larger
  values cast a wider net but produce more results and slower queries.
- **`--sample-km`**: the track is sampled at this interval before querying
  Overpass. Smaller values give denser coverage but proportionally more API
  calls.
- **`--batch-size`**: how many sample points are bundled into a single Overpass
  request. Tune this if you hit timeouts on slow connections.
- **`--country-sample-km`**: distance between Nominatim reverse-geocode lookups
  used to determine the current country. Increase to reduce Nominatim traffic
  on very long routes.

---

## Built-in Profiles

| Profile ID        | Description                                 | Default max_km |
| :---------------- | :------------------------------------------ | -------------: |
| `camping`         | Campsite / motorhome stopover               |           10.0 |
| `playground`      | Playground                                  |            3.0 |
| `outdoor_pool`    | Outdoor pool / water park / thermal bath    |           10.0 |
| `beach`           | Beach / swimming lake                       |           25.0 |
| `theme_park`      | Theme park / amusement park                 |           10.0 |
| `zoo`             | Zoo / petting zoo                           |           12.0 |
| `aquarium`        | Aquarium                                    |           15.0 |
| `mcdonalds`       | McDonald's restaurants                      |            5.0 |
| `restaurant`      | Family-friendly restaurant with kids menu   |            5.0 |
| `kids_activities` | Kids activities of all kinds                |           15.0 |
| `attractions`     | Family-friendly sights, viewpoints, museums |           20.0 |

---

## Creating Custom Profiles

A profile is a plain YAML file placed in the `profiles/` directory. The
filename without extension becomes the profile ID.

```yaml
# profiles/my_profile.yaml
id: my_profile
description: "My custom POI type"
symbol: Flag, Blue          # Garmin symbol name shown in the output GPX

defaults:
  max_km: 8.0               # default search radius from the track
  sample_km: 4.0            # sample the track every N km
  batch_size: 5             # sample points per Overpass request
  retries: 3                # number of Overpass retry attempts

# One or more OSM tag matchers. Results matching ANY entry are included.
tags:
  - key: tourism
    value: museum
  - key: historic
    value: castle
  # Optional sub-filter: both conditions must match
  - key: amenity
    value: fast_food
    and:
      key: cuisine
      value: pizza

# Country-specific search terms used to name waypoints.
# Omit or set to {} if not needed.
terms:
  DE: ["Museum", "Schloss", "Burg"]
  FR: ["musée", "château"]
  ES: ["museo", "castillo"]
  EN: ["museum", "castle"]
```

All fields in `defaults` can be overridden on the command line. The `terms` map
is keyed by ISO 3166-1 alpha-2 country code; the tool selects the appropriate
language based on the country detected along the route.

---

## How It Works

### maps-to-gpx

1. **URL expansion**: short `maps.app.goo.gl` links are resolved by following
   HTTP redirects.
2. **Waypoint extraction**: the URL path (`/maps/dir/A/B/C`) or query
   parameters (`origin`, `waypoints`, `destination`) are parsed. Coordinate
   waypoints (`48.8566,2.3522`) are used directly; place-name waypoints are
   geocoded via Nominatim.
3. **Routing**: waypoints are sent to the
   [OSRM](http://router.project-osrm.org/) public routing API, which returns a
   full road-snapped geometry.
4. **GPX output**: the routed geometry is written as a `<trk>` element; the
   user waypoints (start, stopovers, end) are written as `<wpt>` elements.

### POI enrichment flow

1. **Track sampling**: the input GPX track is sampled at `sample_km` intervals,
   producing a list of coordinates.
2. **Country detection**: every `country_sample_km` kilometres, the tool calls
   the [Nominatim](https://nominatim.openstreetmap.org/) reverse-geocoding API
   to determine the current country code. This allows the profile's search
   terms to be localised.
3. **Overpass queries**: sample points are grouped into batches. For each
   batch, an [Overpass API](https://overpass-api.de/) query is built from the
   profile's `tags` and the country-appropriate `terms`. The query fetches all
   matching OSM nodes and ways within `max_km` of each sample point.
4. **Deduplication**: results from all batches are merged and deduplicated by
   OSM ID.
5. **GPX output**: each unique POI is written as a `<wpt>` element to the
   output GPX file. Tracks and routes are intentionally excluded so the file
   contains only waypoints.

The tool rotates through several public Overpass API endpoints and retries
failed requests automatically, making it resilient to temporary rate limits.

---

## Data Attribution

Map data is sourced from
[OpenStreetMap](https://www.openstreetmap.org/) contributors and is made
available under the
[Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

> © OpenStreetMap contributors

Geocoding and reverse geocoding are performed by the
[Nominatim](https://nominatim.openstreetmap.org/) service, provided by the
OpenStreetMap Foundation.

Routing is performed by the [OSRM](http://project-osrm.org/) public demo server,
also based on OpenStreetMap data (ODbL).

**Please respect the usage policies of all three services:**

- Nominatim: maximum 1 request per second; identify your application with a meaningful `User-Agent`.
- Overpass API: avoid bulk downloads; the tool's default batch and retry
  settings are chosen to be a considerate citizen of the public infrastructure.
- OSRM demo server: personal/non-commercial use; attribution required; access
  may be withdrawn without notice. Consider
  [self-hosting](https://github.com/Project-OSRM/osrm-backend) for production
  workloads.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a pull request.
Run `./scripts/setup-pre-commit.sh` once after cloning to bootstrap git hooks
via `devmarkusb/pre-commit` (no submodule required).

Bug reports and feature requests can be filed as
[GitHub issues](https://github.com/devmarkusb/gpx-poi-enricher/issues).

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

[badge-ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions/workflows/ci.yml/badge.svg
[ci]: https://github.com/devmarkusb/gpx-poi-enricher/actions
