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
  fetch_dem.py           #   THEN seamless 1 m DEM for the greens fetch_dem_hd.py refused
                         #   (fills gaps; ONLY=/OVERWRITE=1 to narrow or force it)
  fetch_trees.py         # LiDAR canopy trees -> trees_lidar.json (off greens/fairways/tees/bunkers)
  fetch_hole_elev.py     # tee-to-green height from the same LiDAR -> hole_elev.json (--write)
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
      aerial_reference_PERSONAL.html   # HAND-MADE MASTER (poppy-ridge only) — see below
      aerial_reference_PERSONAL.pdf    #   printed from it by hand, NOT by tools/export_pdf.py
```

## The one artifact nothing here can rebuild

`courses/poppy-ridge-golf-course/aerial_reference_PERSONAL.html` is a **master**, and **no code in this
repo produces it**. It is ~260 kB with a public-domain USDA NAIP raster embedded as base64, hand-built
for the one yardage-mode course (no OSM geometry, blank greens), and its `.pdf` was printed from it by
hand — the PDFs' `/Creator` proves it: every one of the 15 books says the bare string `Chromium`
(Skia/PDF m147), while the aerial's is a full HeadlessChrome user-agent string under Skia/PDF m150.
Step 7 below says "always export with that tool, never by hand"; this file is the documented exception.

Treat it as source, not output:

- **Do not delete or truncate it.** `legal/01`, `legal/02` and `legal/07` all rest on it — they record
  that the original Esri/Maxar imagery was removed and the sheet rebuilt from NAIP. It is also the only
  record of the course's **pre-2025** layout, so it cannot be regenerated from current public imagery
  either, whatever code someone writes.
- It is watched by the suite's read-only `courses/` guard, which notices it being lost or rewritten but
  cannot bring it back.
- If it ever needs remaking, that is a NAIP fetch plus a hand layout plus a hand print, and the result
  will not be the same sheet.

## Build an existing course
```
COURSE=the-reserve-at-spanos-park python3 generate.py            # -> greenbook.html
COURSE=the-reserve-at-spanos-park COACH=1 python3 generate.py    # -> greenbook_coach.html (large-print)
python3 tools/export_pdf.py the-reserve-at-spanos-park       # -> greenbook.pdf (+ coach)
python3 tools/export_pdf.py --check                          # every PDF matches its HTML?
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
   `trees_lidar.json`, dropping any that fall on a green/fairway/tee/bunker. Then `fetch_dem.py`
   fills the gaps: it writes a 1 m seamless surface for each green `fetch_dem_hd.py` refused and
   leaves the 0.4 m ones alone, so the two compose per GREEN. Those cards print `1 m data`.
   `lidar_coverage.py` then checks the tiles' data footprint really reaches every green and hole
   centreline -- a tile can be present, correctly named, and hold no points where a green is.
6. **Elevation.** `fetch_hole_elev.py --write` measures each hole's tee-to-green height change from the
   same ground returns -- median Z at the back tee against the median of the green's own surface -- into
   `hole_elev.json`. Run it AFTER the surfaces exist, since it reads them. Skipping it is silent: the
   cards simply print no height line, which is also what a hole whose tee cannot be located does, so
   there is nothing on the page to tell a missing stage from an honest refusal. `tools/verify_elevation.py`
   cross-checks the result against the independent 3DEP seamless DEM; run it when adding a course.
7. **Build.** `generate.py` renders the combined cards -> `greenbook.html` (add `COACH=1` for the
   optional large-print edition), then `tools/export_pdf.py` -> `greenbook.pdf`. Always export with
   that tool, never by hand: hand-exported PDFs drifted three commits behind the engine once, and
   the printed book still showed a 40% slope label the code had already stopped emitting. The tool
   records a hash of the source HTML beside each PDF so `--check` can prove they match.
8. **Verify (never skip).** Eyeball each green (golf-plausible slope % and feed
   direction; near-flat greens marked "(faint)"), confirm hole layouts match
   satellite, and that yardages equal the scorecard.

## Data sources & licences (keep us clean)
- **USGS 3DEP / LiDAR** — public domain (US Government). No restriction.
- **OpenStreetMap** — ODbL: attribute "© OpenStreetMap contributors" (done on the
  book). Share-alike attaches only if we PUBLICLY RELEASE a modified OSM database; the
  cached extracts are build inputs and stay local, so it is not triggered. (This line
  used to say "keep any derived database open", which is stricter than ODbL §4.4
  actually is -- see `legal/01` for the precise reading.)
- **USDA NAIP** — public domain (US Government). Used to trace 2 greens OSM had not
  mapped; coordinates only, no pixels in any book.
- **Scorecard numbers** — facts (par/yardage/handicap); facts aren't copyrightable.
- We compute slope/contours ourselves from elevation. We do **not** copy any
  commercial product's data, images, or layout, and we don't use their name/logo.

## Designed for Rule 4.3
`legal/06` records the standing wording rule: we say **"designed to conform"**, never "conforms",
"legal", or "USGA-approved" -- neither the USGA nor the R&A approves green books at all, so there is
nothing to be approved by. This heading used to read "Competition legality" and the sentence below
called the build "conforming", which are the two words that rule exists to avoid.

The **standard** book is **designed to fall within** the limits as a single build: the green image scale is
capped safely under **3/8 in = 5 yd (1:480)** and the cards (3.5 × 5.0 in) sit well under the
**4.25 × 7 in** book limit, while still showing full contours/arrows/slope % (Rule 4.3 limits
the *scale and book size*, not the presence of detail). Conformance is still a Committee-level,
per-competition decision — confirm before an event. The **large-print edition** (`COACH=1`) is
intentionally enlarged past that scale, so it is a **practice aid, not a conforming competition
book** — use the standard pocket book for competition.
