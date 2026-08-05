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
  fetch_dem.py           #   THEN the 3DEP seamless MOSAIC for the greens fetch_dem_hd.py refused
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

## The two artifacts nothing here can rebuild

### The Poppy Ridge aerial sheet

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

### The branded QR master

`lucaswu.golf_qr_small.png` sits at the repo root, is **untracked and gitignored**
(`.gitignore`: `lucaswu.golf_qr*.png`), and `generate.py` embeds it base64 into **every** book
(`IG_QR`). So it is required for the byte-for-byte rebuild that
`test_cold_build_reproduces_every_book_byte_for_byte` asserts, and a fresh clone does not have it —
`generate._data_uri` prints a note and omits it, which is honest but means a clone's books differ from
these. **No code in this repo produces it and nothing here decodes it**; it came out of a branded-QR
generator, so it cannot be regenerated identically even knowing what it points at.

What is verified about it, and what measured each line — no decoder is installed here, so the method
matters as much as the figure:

- **Geometry, re-derived on every suite run** (`test_the_branded_qr_master_is_recorded_as_unreproducible`):
  it is **41x41 modules**, which makes it QR **version 6** and **172 codewords**, both timing
  patterns alternate over their whole length, and the one alignment pattern reads as a textbook 5x5 ring
  at **(34,34)** — the version-6 row of ISO/IEC 18004's alignment table. Those checks are what make the
  size a measurement rather than a guess: a misaligned or wrongly sized grid produces none of them.
- **Error-correction level M, mask pattern 2**, and **the master is stored mirrored across its main
  diagonal** (`test_the_qr_masters_ecc_level_and_error_budget_are_measured_not_unknowable`). Read
  `grid[col][row]`, both copies of the 15-bit format information are `0x5E7C` — an exact BCH(15,5)
  codeword for M/mask 2, Hamming distance **0**, the two copies XOR to zero. An earlier round recorded
  the level as unknowable, "disagreeing by more than the 3 bits BCH(15,5) can correct" and decoding to
  "Q and H". That was the mirror: read as stored with the canonical coordinate table the copies come out
  `0x1F3D` (Q, distance 3) and `0x1FBD` (H, distance 4), which is where "Q and H" came from. Both
  readings are pinned, so the misreading cannot be mistaken for a measurement again.
- **The centre logo covers 13x13 = 169 modules**, rows and columns 14–26, exactly centred in the symbol.
  Measured from the fully blank scan lines that bracket it — no ink anywhere along them — which land on
  module boundaries **14.00 and 27.00**. (Per-cell ink coverage cannot do this: adjacent dark dots merge
  and fill their cells completely, so **15 of the 755** dark cells outside the logo also reach coverage
  1.00. That count is window-dependent and so is stated with its window: 15 in the **closed** cell window
  the grid sampler itself reads with — `_qr_cell_cover(..., 0, 1)`, which includes the boundary pixel the
  next cell shares — against 31 in a **half-open** window and 28 truncating instead of rounding. An
  earlier round published 31 and named no window.)
- **The Reed-Solomon budget is 88% spent, with one codeword of headroom.** Version 6 at level M is 4
  blocks of 27 data + 16 EC codewords (4 x 43 = 172), correcting **t = 8 codeword errors per block**. The
  169 logo modules fall inside **28 of the 172 codewords — 7 in every one of the four blocks**, so 7 of 8
  in the worst (and every) block. Consequence, measured: of the 164 one-module-wide straight lines across
  this symbol (41 rows, 41 columns, 41 diagonals, 41 anti-diagonals), **162 push at least one block past
  t = 8** and make it undecodable. The two that do not are the timing row and column, which carry no
  codeword. A single crease or pen line through the code, in almost any orientation, kills the scan.
- **Payload `https://www.instagram.com/lucaswu.golf?utm_source=qr`**, which is what the printed caption
  "Instagram @lucaswu.golf" claims. Established OUTSIDE this project environment, since nothing here
  decodes it: **zxing-cpp and pyzbar independently**, both first try, logo in place, no preprocessing.
  (OpenCV's `QRCodeDetector` failed on the same image, so not every decoder manages it.) Corroborated
  here without a decoder: re-encoding that exact URL at version 6 / level M / mask 2 reproduces the
  mirrored master in **1589 of 1681 modules**, and all **80** differing data modules lie inside the 13x13
  logo footprint — 25 corrupted codewords, at most 7 in any block against t = 8, i.e. inside correction
  capacity. The other 12 differences are the rounded finder corners the brand rendering draws, which
  carry no data. That corroboration needs the `qrcode` encoder, which this project does not declare, so
  the suite does not run it — it is recorded here as a method, with its figures, for the next reader.
- **Printed size, which is the other half of that budget.** `.dqr img { width: 0.92in }` in `generate.py`
  **sizes the WHOLE asset**, and the asset is 560x643 px: the 41-module symbol occupies 448 px of the
  width — exactly 0.800 of it — with a baked-in "LUCASWU.GOLF" caption band underneath. So the
  declaration implies a 0.736 in symbol and **0.0180 in = 0.456 mm per module**, not the 0.0224 in that
  0.92/41 would imply — but the declaration is not what reaches paper. In all twelve shipped books the
  asset is **placed at 66.75 pt** = 0.927083 in = exactly **89 CSS px**: the renderer takes 0.92 in =
  88.32 px and lands on a whole pixel. So the symbol prints **0.741667 in** and the printed module is
  0.0180894 in = **0.4595 mm per printed module**, 0.8% more than the declaration implies. Measured on
  monarch-bay page 6 at 600 dpi, the symbol's ink spans **445 px at a min-channel threshold of 128** —
  0.741667 in, the placed symbol to the pixel — widening to 446 px at threshold 200 and 447 at 250. (An
  earlier round published that span as 0.7433 in "the difference being antialiased edge pixels", which
  read a 0.0057 in PLACEMENT difference as ink bleed and so made the CSS-derived 0.456 mm look confirmed
  by the measurement that refutes it. A span that moves with the threshold is published with its
  threshold.) With one codeword of Reed-Solomon headroom, a 0.4595 mm module is the thin part: a crease
  or a biro line is a whole module wide. Whether 0.92 in was
  meant for the symbol or the asset is **not recorded anywhere** — the declaration arrived with the
  initial engine commit among a screen of other CSS, no document states a target size or a minimum module
  pitch, and a CSS width on an `<img>` sizes the asset, which is what this one has always done. It is
  left as it is on that basis, and the figures are pinned instead
  (`test_the_printed_qr_module_is_smaller_than_its_css_width_implies_and_the_record_says_so` for the
  declaration and the master,
  `test_the_printed_qr_module_is_the_width_the_renderer_places_not_the_width_the_css_asks_for` for what
  the books actually print).
- **Quiet zone**, in the master itself: 5.12 modules left and right, 5.39 above, and **3.56 modules
  below**, where the caption band starts. ISO/IEC 18004 asks for 4, so the bottom margin is marginally
  short — measured and recorded rather than rounded up.

Treat it as source, not output: it is watched by the suite's read-only guard (see `UNTRACKED_MASTERS`),
and if it is lost, the books can still be built — they will simply be different books.

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
   fills the gaps: it writes a seamless-mosaic surface for each green `fetch_dem_hd.py` refused and
   leaves the 0.4 m ones alone, so the two compose per GREEN. Those cards carry a coarse-data caveat
   naming the source cell measured off that green's own array (`render_green.source_lattice`) — not a
   product tier: 3DEP's seamless service is a MULTI-RESOLUTION MOSAIC, and at every green this stage
   has run on it answered from the 1/9 arc-second tier, so the label used to say `1 m` and was wrong
   by 2.7x E-W and 3.4x N-S.
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
