### Edit maps

1. create a track in Google Maps (start, finish, perhaps a handful of stopovers,
keep it one-way, even if you intend to go back)
2. `$ maps-to-gpx "<google-maps-url>" route.gpx [--mode driving|cycling|walking] [--name "My Route"]`
   (replaces mapstogpx.com — uses OSRM routing + Nominatim geocoding, no API key needed)
3. add-split-waypoints.py (split into 10 parts, e.g.)
4. If too large (>5MB), <https://www.gpxtokml.com/> before reimporting to
Google Maps with <https://www.google.com/mymaps>

To view and edit manually:

- https://gpx.studio/

Unfortunately, the maps saved in google are close to unusable as they
appear to be just dead images. What you might want is to save them
under 'your places' or any such list. The only way seems to be saving
them manually point for point again.

Repeat from 3. with/for
- `$ python add_pois_to_gpx.py split.gpx playground.gpx --profile "playground"`
- Note: add-campsites-to-gpx.py was the first version of the upper script, but
for campsites only
