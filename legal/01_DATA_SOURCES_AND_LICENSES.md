# Data Sources & Licenses

Every input used to build the books, its license, our obligation, and how we meet it.

## 1. OpenStreetMap — hole/green/fairway/bunker/water/tree geometry
- **License:** Open Database License (ODbL) 1.0.
- **What we take:** vector geometry (shapes/positions) of golf features, via the Overpass API
  (`fetch_osm.py`). Cached locally as `osm_geom.json` / `osm_course.json`.
- **Our obligations & compliance:**
  - **Attribution:** ✔ Each book prints "© OpenStreetMap contributors, ODbL 1.0,
    osm.org/copyright."
  - **Produced Work:** the rendered book is a "Produced Work" under ODbL — we must attribute
    and note the data is under ODbL. ✔ Done. We are **not** required to open‑license the PDFs.
  - **Share‑alike trap (avoided):** ODbL share‑alike only attaches if we publicly release a
    **modified OSM database**. We keep the extracted `osm_*.json` as internal build inputs and
    do not publish them as a standalone dataset. If we ever do, that dataset must ship under ODbL.
  - Note: some OSM features carry a contributor `source:` tag (e.g. one "bing" in Monarch data)
    — that is the original mapper's own provenance metadata inside licensed OSM data; we consume
    the ODbL‑licensed **vector geometry**, not any Bing imagery. Nothing Bing‑copyrighted is used.

## 2. USGS 3DEP elevation / LiDAR — green slope, contours, break arrows
- **License:** **U.S. Government public domain** (17 U.S.C. §105 — no copyright in federal works).
- **What we take:** raw elevation (seamless 1 m DEM and/or 3DEP LiDAR point clouds), via
  `elevation.nationalmap.gov` and the USGS LPC archive (`fetch_dem*.py`, `fetch_lidar*.py`).
- **What we make:** we **compute** the slope %, iso‑elevation contours, downhill arrows, and
  depth grid ourselves (`render_green.py`). That analysis is **our own original work** over
  public‑domain data — we own the output.
- **Obligations:** none legally required. We credit "public‑domain USGS 3DEP" as a courtesy.

## 3. Scorecards — par, yardage, handicap
- **Status:** **facts.** Par, yardages per tee, and stroke‑index are not copyrightable
  (*Feist*, 1991 — facts and "sweat of the brow" are not protected).
- **Sources (cross‑checked):** official course sites, BlueGolf/NCGA, USGA course‑rating DB,
  GolfLink — used only to verify the numbers, not to copy any card's design/layout.

## 4. Esri World Imagery / Maxar — POPPY RIDGE ONLY, NOT DISTRIBUTED
- **License:** **restrictive.** Esri Master License Agreement; the imagery is Maxar's
  copyrighted content. Export/redistribution/printed‑derivative use is **not** permitted
  without a separate paid license.
- **Where used:** ONLY the Poppy Ridge personal aerial reference (rebuilt‑2025 course with no
  open data yet). Marked "PERSONAL — not for distribution." **This is the one non‑open source
  in the project and must never be distributed.** See `07_POPPY_RIDGE_ESRI_IMAGERY.md`.

## 5. NOT used (and why it matters)
- **Google Maps / Apple Maps / Bing imagery:** **never fetched or embedded** (verified). Their
  terms prohibit printed/offline derivative maps and redistribution — avoiding them entirely is
  a deliberate, defensible choice.
- **Any commercial green‑book product** (StrackaLine, GolfLogix, etc.): **no data, imagery,
  symbols, layout, or brand** used anywhere.

## 6. The maker's own assets
- **"Lucas Green Book" brand, cover art, SVG map/heat/contour/arrow rendering:** original,
  created by the maker.
- **Instagram QR** (`@lucaswu.golf`): the maker's own account.
