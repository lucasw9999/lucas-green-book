# Green-Book Engine — per-course pipeline

Free, accurate green books from public data. One reusable engine at the repo root;
each course is a folder under `courses/<slug>/`.

```
greenbook/
  config.py              # picks the course (env COURSE=<slug>), loads course.json
  fetch_osm.py           # OSM geometry -> osm_geom.json / osm_course.json
  fetch_lidar.py         # download USGS 3DEP LiDAR tiles (via The National Map) -> laz/
  fetch_lidar_alameda.py #   Alameda County 2021 tile-name decoder (grabs all complementary copies)
  fetch_dem_hd.py        # raw LiDAR ground returns -> 0.4 m surface per green -> dem_hd/
  fetch_dem.py           #   OR seamless 1 m DEM per green (fallback where no dense LiDAR)
  fetch_trees.py         # LiDAR canopy trees -> trees_lidar.json (off greens/fairways/tees/bunkers)
  render_green.py        # green slope map (arrows, contours, %, depth grid)
  render_hole.py         # tee->green layout (bunkers, water, trees, yardage)
  generate.py            # lays out the palm cards -> greenbook.html  (COACH=1 -> large-print edition)
  courses/
    <slug>/
      course.json        # ALL course-specific inputs (see below)
      osm_geom.json      # cached: green polygons + hole centerlines (OSM)
      osm_course.json    # cached: tees/bunkers/water/fairways/holes (OSM)
      laz/               # cached: USGS LiDAR tiles (.laz) — large, deletable / re-downloadable
      dem_hd/            # cached: 0.4 m elevation per green (.npy + .json)
      trees_lidar.json   # cached: LiDAR tree markers per hole
      greenbook.pdf      # OUTPUT (print this);  greenbook_coach.pdf = optional large-print edition
```

## Build an existing course
```
COURSE=the-reserve-at-spanos-park python3 generate.py            # -> greenbook.html
COURSE=the-reserve-at-spanos-park COACH=1 python3 generate.py    # -> greenbook_coach.html (large-print)
# then render the .html -> .pdf (headless Chrome --print-to-pdf, or Cmd+P)
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
4. **🔎 Best LiDAR.** `fetch_lidar.py` pulls the newest dense USGS 3DEP tiles covering
   the course from The National Map into `laz/` (prefer QL1/QL2). For Alameda County 2021,
   `fetch_lidar_alameda.py` decodes the `w####n####` tile names and grabs **all** sub-project
   copies of each boundary tile (they are complementary, not duplicates). 🔎 If OSM is
   missing a green, digitize it from **public-domain NAIP** aerial and inject it — never guess.
5. **Surfaces & trees.** `fetch_dem_hd.py` clips ground-classified returns to each green and
   interpolates a 0.4 m surface -> `dem_hd/`; `fetch_trees.py` extracts canopy trees ->
   `trees_lidar.json`, dropping any that fall on a green/fairway/tee/bunker. Where no dense
   LiDAR exists, `fetch_dem.py` provides a 1 m seamless fallback.
6. **Build.** `generate.py` renders the combined cards -> `greenbook.html` -> print to
   `greenbook.pdf` (add `COACH=1` for the optional large-print edition).
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

## Competition legality (Rule 4.3)
The **standard** book is designed as a single **conforming** build: the green image scale is
capped safely under **3/8 in = 5 yd (1:480)** and the cards (3.5 × 5.0 in) sit well under the
**4.25 × 7 in** book limit, while still showing full contours/arrows/slope % (Rule 4.3 limits
the *scale and book size*, not the presence of detail). Conformance is still a Committee-level,
per-competition decision — confirm before an event. The **large-print edition** (`COACH=1`) is
intentionally enlarged past that scale, so it is a **practice aid, not a conforming competition
book** — use the standard pocket book for competition.
