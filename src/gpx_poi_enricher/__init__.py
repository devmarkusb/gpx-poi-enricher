"""
gpx-poi-enricher: Find OpenStreetMap Points of Interest along tracks or around points.

Uses Overpass API for spatial queries and Nominatim for country-aware search terms,
driven by configurable YAML profiles (see the bundled ``profiles/`` directory).

Basic usage::

    from gpx_poi_enricher.enricher import enrich_point, enrich_track
    from gpx_poi_enricher.profiles import load_profile

    profile = load_profile("camping")

    items = enrich_track(
        track_points=[(48.8566, 2.3522), (41.3851, 2.1734)],
        profile=profile,
    )

    nearby = enrich_point((48.8566, 2.3522), profile)
"""

__version__ = "0.1.0"
__author__ = "gpx-poi-enricher contributors"
__license__ = "MIT"
