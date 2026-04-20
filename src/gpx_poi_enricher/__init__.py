"""
gpx-poi-enricher: Enrich GPX tracks with Points of Interest from OpenStreetMap.

Uses Overpass API for spatial queries and Nominatim for country-aware search terms,
driven by configurable YAML profiles (see the bundled ``profiles/`` directory).

Basic usage::

    from gpx_poi_enricher.enricher import enrich_track

    items = enrich_track(
        track_points=[(48.8566, 2.3522), (41.3851, 2.1734)],
        profile_id="camping",
    )
"""

__version__ = "0.1.0"
__author__ = "gpx-poi-enricher contributors"
__license__ = "MIT"
