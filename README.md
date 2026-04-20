# gpx-poi-enricher

**Enrich GPX tracks with Points of Interest from OpenStreetMap using configurable YAML profiles.**

[![CI](https://github.com/your-org/gpx-poi-enricher/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/gpx-poi-enricher/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/gpx-poi-enricher.svg)](https://pypi.org/project/gpx-poi-enricher/)

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Built-in Profiles](#built-in-profiles)
- [Usage](#usage)
- [Creating Custom Profiles](#creating-custom-profiles)
- [How It Works](#how-it-works)
- [Data Attribution](#data-attribution)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- Takes any GPX file containing a track and produces a new GPX file containing only waypoints — ready to import into Garmin, OsmAnd, or any other navigation app.
- 11 ready-to-use profiles covering camping, beaches, playgrounds, theme parks, restaurants, and more.
- Country-aware search terms: automatically detects which country each section of the route passes through and queries in the local language (DE, FR, ES, EN).
- Searches OpenStreetMap via the public Overpass API with multi-endpoint fallback for reliability.
- Configurable search radius, sampling interval, and batch size per profile — all overridable on the command line.
- Progress reporting to stderr so you know something is happening during long queries.
- Extensible: add a new profile by dropping a single YAML file into the `profiles/` directory.

---

## Installation

### From PyPI (recommended)

```bash
pip install gpx-poi-enricher
```

### From source (development)

```bash
git clone https://github.com/your-org/gpx-poi-enricher.git
cd gpx-poi-enricher
pip install -e ".[dev]"
```

---

## Quick Start

Find all campsites within 10 km of your route and write them to `camping.gpx`:

```bash
gpx-poi-enricher route.gpx camping.gpx --profile camping
```

Find playgrounds within 5 km (overriding the profile default of 3 km):

```bash
gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5
```

List all available built-in profiles:

```bash
gpx-poi-enricher --list-profiles
```

---

## Built-in Profiles

| Profile ID          | Description                                    | Default max_km |
|---------------------|------------------------------------------------|---------------|
| `camping`           | Campsite / motorhome stopover                  | 10.0          |
| `playground`        | Playground                                     | 3.0           |
| `outdoor_pool`      | Outdoor pool / water park / thermal bath       | 10.0          |
| `beach`             | Beach / swimming lake                          | 25.0          |
| `theme_park`        | Theme park / amusement park                    | 10.0          |
| `zoo`               | Zoo / petting zoo                              | 12.0          |
| `aquarium`          | Aquarium                                       | 15.0          |
| `mcdonalds`         | McDonald's restaurants                         | 5.0           |
| `restaurant`        | Family-friendly restaurant with kids menu      | 5.0           |
| `kids_activities`   | Kids activities of all kinds                   | 15.0          |
| `attractions`       | Family-friendly sights, viewpoints, museums    | 20.0          |

---

## Usage

```
usage: gpx-poi-enricher [-h] [--profile PROFILE] [--max-km MAX_KM]
                        [--sample-km SAMPLE_KM] [--batch-size BATCH_SIZE]
                        [--country-sample-km COUNTRY_SAMPLE_KM]
                        [--progress-interval SEC] [--verbose]
                        [--list-profiles]
                        [input_gpx] [output_gpx]

Enrich a GPX track with Points of Interest from OpenStreetMap.

Examples:
  gpx-poi-enricher route.gpx camping.gpx --profile camping
  gpx-poi-enricher route.gpx playgrounds.gpx --profile playground --max-km 5
  gpx-poi-enricher --list-profiles

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

### Key options explained

- **`--max-km`** — How far from the track a POI may be to be included. Larger values cast a wider net but produce more results and slower queries.
- **`--sample-km`** — The track is sampled at this interval before querying Overpass. Smaller values give denser coverage but proportionally more API calls.
- **`--batch-size`** — How many sample points are bundled into a single Overpass request. Tune this if you hit timeouts on slow connections.
- **`--country-sample-km`** — Distance between Nominatim reverse-geocode lookups used to determine the current country. Increase to reduce Nominatim traffic on very long routes.

---

## Creating Custom Profiles

A profile is a plain YAML file placed in the `profiles/` directory (or anywhere on a path you point the tool to in future versions). The filename without extension becomes the profile ID.

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

All fields in `defaults` can be overridden on the command line. The `terms` map is keyed by ISO 3166-1 alpha-2 country code; the tool selects the appropriate language based on the country detected along the route.

---

## How It Works

1. **Track sampling** — The input GPX track is sampled at `sample_km` intervals, producing a list of coordinates.
2. **Country detection** — Every `country_sample_km` kilometres, the tool calls the [Nominatim](https://nominatim.openstreetmap.org/) reverse-geocoding API to determine the current country code. This allows the profile's search terms to be localised.
3. **Overpass queries** — Sample points are grouped into batches. For each batch, an [Overpass API](https://overpass-api.de/) query is built from the profile's `tags` and the country-appropriate `terms`. The query fetches all matching OSM nodes and ways within `max_km` of each sample point.
4. **Deduplication** — Results from all batches are merged and deduplicated by OSM ID.
5. **GPX output** — Each unique POI is written as a `<wpt>` element to the output GPX file. Tracks and routes are intentionally excluded so the file contains only waypoints.

The tool rotates through several public Overpass API endpoints and retries failed requests automatically, making it resilient to temporary rate limits.

---

## Data Attribution

Map data is sourced from [OpenStreetMap](https://www.openstreetmap.org/) contributors and is made available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

> © OpenStreetMap contributors

Reverse geocoding is performed by the [Nominatim](https://nominatim.openstreetmap.org/) service, also provided by the OpenStreetMap Foundation.

**Please respect the usage policies of both services:**
- Nominatim: maximum 1 request per second; identify your application with a meaningful `User-Agent`.
- Overpass API: avoid bulk downloads; the tool's default batch and retry settings are chosen to be a considerate citizen of the public infrastructure.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Bug reports and feature requests can be filed as [GitHub issues](https://github.com/your-org/gpx-poi-enricher/issues).

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
