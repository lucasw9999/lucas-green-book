# Green-Book Engine — per-course pipeline

Free, accurate green books from public data. One reusable engine at the repo root;
each course is a folder under `courses/<slug>/`.

```
greenbook/
  config.py            # picks the course (env COURSE=<slug>), loads course.json
  fetch_dem_hd.py      # raw LiDAR ground returns -> 0.4 m surface per green
  render_green.py      # green slope map (arrows, contours, %, F/C/B, depth grid)
  render_hole.py       # tee->green layout (bunkers, water, yardage)
  generate.py          # lays out the palm cards -> greenbook.html
  courses/
    <slug>/
      course.json      # ALL course-specific inputs (see below)
      osm_geom.json    # cached: green polygons + hole centerlines (OSM)
      osm_course.json  # cached: tees/bunkers/water/holes (OSM)
      laz/             # cached: USGS LiDAR tiles (.laz) — large, deletable
      dem_hd/          # cached: 0.4 m elevation per green (.npy + .json)
      greenbook.html   # OUTPUT
      greenbook.pdf    # OUTPUT (print this)
```

## Build an existing course
```
COURSE=the-reserve-at-spanos-park python3 generate.py
# then render greenbook.html -> greenbook.pdf (headless Chrome / Cmd+P)
```

## Add a NEW course (what an agent does each time)
Most steps are generic; a few need per-course research/judgment (marked 🔎).

1. **🔎 Identify the course & scorecard.** Geocode the address (OSM Nominatim).
   Find the authoritative scorecard (NCGA/BlueGolf, state GA, or the club) and
   record par, per-hole handicap, and yardages for every tee. These are *facts*.
2. Create `courses/<slug>/course.json` with name, address, lat/lon, tees, the
   `holes` table, `osm_bbox`, and the LiDAR project + tile IDs.
3. **Geometry (OSM).** Query Overpass for `golf=green` (polygons + hole `ref`),
   `golf=hole` centerlines, tees, bunkers, water within `osm_bbox`; cache to
   `osm_geom.json` / `osm_course.json`. 🔎 Sanity-check that greens match hole
   numbers (each hole-end within a few metres of a distinct green; no dupes).
4. **🔎 Best LiDAR.** Query USGS TNM / OpenTopography for the highest-density
   point cloud covering the course (prefer newest, QL1/QL2). Record the tile IDs
   in `course.json`, download the `.laz` tiles to `laz/`.
5. **Surfaces.** `fetch_dem_hd.py` clips ground-classified returns to each green
   and interpolates a 0.4 m surface -> `dem_hd/`.
6. **Build.** `generate.py` renders the combined cards -> `greenbook.html` ->
   print to `greenbook.pdf`.
7. **Verify (never skip).** Eyeball each green (golf-plausible slope % and feed
   direction; near-flat greens flagged "subtle"), confirm hole layouts match
   satellite, and that yardages equal the scorecard.

## Data sources & licences (keep us clean)
- **USGS 3DEP / LiDAR** — public domain (US Government). No restriction.
- **OpenStreetMap** — ODbL: attribute "© OpenStreetMap contributors" (done on the
  book) and keep any derived database open.
- **Scorecard numbers** — facts (par/yardage/handicap); facts aren't copyrightable.
- We compute slope/contours ourselves from elevation. We do **not** copy any
  commercial product's data, images, or layout, and we don't use their name/logo.

## Competition legality (IMPORTANT)
The detailed book (fine contours, dense arrows, slope %) is a **practice/casual**
aid and is **NOT conforming** for events played under the Rules of Golf (incl.
AJGA). Rule 4.3 limits green images to a scale no more detailed than
**3/8 inch = 5 yards (1:480)** in a book **≤ 4.25" × 7"**, showing only significant
slopes/tiers. A **tournament-legal mode** (coarse-scale, simplified) must be built
separately for in-competition use. See the chat notes / TODO.
