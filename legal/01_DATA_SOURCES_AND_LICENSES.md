# Data Sources & Licenses

Every input used to build the books, its license, our obligation, and how we meet it.

## 1. OpenStreetMap — hole/green/fairway/bunker/water/tree geometry
- **License:** Open Database License (ODbL) 1.0.
- **What we take:** vector geometry (shapes/positions) of golf features, via the Overpass API
  (`fetch_osm.py`). Cached locally as `osm_geom.json` / `osm_course.json`.
- **Our obligations & compliance:**
  - **Attribution:** ✔ Each book prints "© OpenStreetMap contributors, ODbL 1.0,
    osm.org/copyright."
  - **Produced Work — the notice duty is §4.3, not §4.5(b).** ODbL §4.3 ("Notice for using
    output (Contents)") is the clause that governs us: creating and using a Produced Work does
    *not* require the full §4.2 notice, but publicly using one obliges a notice "reasonably
    calculated" to tell anyone exposed to the work that the Contents came from the database and are
    available under ODbL. ✔ Done — every book prints exactly that. Separately, **§4.5(b)** is what
    exempts a Produced Work from share‑alike, which is why CC BY‑NC‑ND on the books does not
    conflict with ODbL. Earlier revisions of this file cited §4.5(b) for the attribution duty
    itself; that was the wrong clause for the right conclusion.
  - **Share‑alike (§4.4):** attaches only if we publicly release a **modified OSM database**. We
    keep the extracted `osm_*.json` as internal build inputs and do not publish them as a standalone
    dataset. If we ever do, that dataset must ship under ODbL.
  - **§4.6 — the on‑request offer, which §4.4 alone does not cover.** Publicly using a Produced Work
    that was made *from a Derivative Database* obliges us, **on request**, to offer recipients
    machine‑readable access to either that database or a file of our alterations. Two courses are
    affected, because for those we added geometry OSM did not have: **Bay View** and **Valley Hi**
    (2 hand‑digitized greens each, tagged `_digitized`). The other ten are unmodified extracts, for
    which OSMF's own guidance is simply to refer people to openstreetmap.org — which the About panel
    already does. The alterations are small (2 features on one course, well under OSMF's
    "less than 100 features" insubstantiality threshold), but the obligation is cheap to honour:
    **on request we will supply those `_digitized` features under ODbL 1.0.** Anyone wanting them can
    ask at the contact address printed in every book.
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

## 4. Esri World Imagery / Maxar — FORMERLY used on one personal file, REMOVED 2026‑07‑13
- **License:** **restrictive.** Esri Master License Agreement; the imagery is Maxar's
  copyrighted content. Export/redistribution/printed‑derivative use is **not** permitted
  without a separate paid license — which is why it was removed rather than kept even personally.
- **Where it was used:** ONLY the Poppy Ridge personal aerial reference (a course rebuilt in 2025
  with no open data of the new layout yet). **It is gone.** On 2026‑07‑13 the Esri‑derived files
  were deleted and the aerial was rebuilt from **public‑domain USDA NAIP**, labelled as the
  pre‑2025 layout. **The project now contains no Esri/Maxar imagery anywhere**, distributed or not —
  verified by grep across every tracked file and all of git history, and by inspecting the embedded
  JPEG for vendor strings and EXIF. See `07_POPPY_RIDGE_ESRI_IMAGERY.md`.
- **Standing rule:** copyrighted/licensed imagery (Esri/Maxar, Google, Apple, Bing) never enters
  this project again, in any file, distributed or personal.

## 4a. USDA NAIP (National Agriculture Imagery Program) — public domain
- **License:** **U.S. public domain** (a U.S. Government work, 17 U.S.C. §105). No attribution is
  legally required; we credit it anyway.
- **Where used:** the Poppy Ridge aerial reference, and as the tracing source for a small number of
  greens that OpenStreetMap did not map at all (Bay View 2 — tagged `_digitized`, ways 900000005 and
  900000007). Valley Hi's hole‑16 green was traced from NAIP in an earlier build; `check_osm_bbox.py`
  then found that course's OSM box ~46 m short at hole 16, a widened box recovered the REAL green
  1.3 m away (33 vertices against the tracing's 17), and the tracing was dropped — so no
  NAIP‑derived geometry remains in that book, and it no longer prints the NAIP credit.
- **What is derived:** **coordinates only.** No NAIP pixels are embedded in any book. Tracing the
  outline of a real putting surface records a fact about the ground; it is not copying an image, and
  the image is public domain in any case.

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
