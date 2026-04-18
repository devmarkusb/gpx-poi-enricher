### Edit maps

1. create track im google maps (start, finish, perhaps a handful stopovers,
keep it one-way, even if you intend to go back)
2. mapstogpx.com
3. add-split-waypoints.py (split into 10 parts, e.g.)
4. If too large (>5MB), <https://www.gpxtokml.com/> before reimporting to
Google maps with <https://www.google.com/mymaps>

To view and edit manually:

- https://gpx.studio/

Unfortunately, the maps saved in google are close to unsusable as they
appear to be just dead images. What you might want is to save them
under 'your places' or any such list. The only way seems to be saving
them manually point for point again.

Repeat from 3. for
- `$ python add_pois_to_gpx.py split.gpx spielplatz.gpx --profile "spielplatz"`
