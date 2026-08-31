# Data Sources & Licenses

Every input used to build the books, its license, our obligation, and how we meet it.

## 1. OpenStreetMap — hole/green/fairway/bunker/water/tree geometry
- **License:** Open Database License (ODbL) 1.0.
- **What we take:** vector geometry (shapes/positions) of golf features, via the Overpass API
 . Cached locally as `osm_geom.json` / `osm_course.json`.
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
    machine‑readable access to either that database or a file of our alterations. **One** course is
    affected, because for that one we added geometry OSM did not have: **Bay View** (2 hand‑digitized
    greens, tagged `_digitized`). Every other course is an unmodified extract, for
    which OSMF's own guidance is simply to refer people to openstreetmap.org — which the About panel
    already does. The alterations are small (2 features on one course, well under OSMF's
    "less than 100 features" insubstantiality threshold), but the obligation is cheap to honour:
    **on request we will supply those `_digitized` features under ODbL 1.0.** Anyone wanting them can
    ask at the contact address printed in every book.
  - Note: a few OSM features carry a contributor `source:` tag naming an imagery provider. That is
    the original mapper's own provenance metadata inside licensed OSM data; we consume the
    ODbL‑licensed **vector geometry** only. No provider's imagery is used or reproduced.

## 2. USGS 3DEP elevation / LiDAR — green slope, contours, break arrows
- **License:** **U.S. Government public domain** (17 U.S.C. §105 — no copyright in federal works).
- **What we take:** raw elevation (the seamless DEM mosaic and/or 3DEP LiDAR point clouds), via
  `elevation.nationalmap.gov` and the USGS LPC archive. That
  service is **multi‑resolution**, so no single cell size describes it and this record names none: each
  green records the source cell measured out of its own array rather than assuming a tier. Graded
  against those arrays, never against this sentence.
- **What we make:** we **compute** the slope %, iso‑elevation contours, downhill arrows, and
  depth grid ourselves. That analysis is **our own original work** over
  public‑domain data — we own the output.
- **Obligations:** none legally required. We credit "public‑domain USGS 3DEP" as a courtesy.

## 3. Scorecards — par, yardage, handicap
- **Status:** **facts.** Par, yardages per tee, and stroke‑index are not copyrightable
  (*Feist*, 1991 — facts and "sweat of the brow" are not protected).
- **What we take:** **facts from the published scorecard** — par, per‑hole yardage and stroke‑index,
  read off published cards and transcribed as numbers. Nothing of a card's **design or layout** is
  copied: no artwork, no colour scheme, no table shape, no logo. Which figures were reconciled and
  which are single‑source is recorded per course in the project's own provenance record.
- **Cross‑checks we do run:** against **our own open data** — per‑hole par is corroborated by
  OpenStreetMap's `golf=hole` par tags, and each tee's per‑hole yardages must sum to the total the
  card itself prints. Both are arithmetic on facts, not a second edition of anyone's card.

## 4. Licensed commercial imagery — NOT used
- **Standing rule:** copyrighted or licensed imagery (Esri/Maxar, Google, Apple, Bing) does not enter
  this project, in any file, distributed or personal. Such imagery is licensed for viewing in a
  provider's own map client; exporting it, redistributing it, or printing a derivative of it is not
  permitted without a separate paid licence, so it has no place in a printed book.
- **Verified:** no Esri/Maxar, Google, Apple or Bing imagery appears anywhere in this project —
  checked across every tracked file and by inspecting embedded images for vendor strings and EXIF.
- Where an aerial reference is genuinely needed, it comes from **public-domain USDA NAIP** (§4a).

## 4a. USDA NAIP (National Agriculture Imagery Program) — public domain
- **License:** **U.S. public domain** (a U.S. Government work, 17 U.S.C. §105). No attribution is
  legally required; we credit it anyway.
- **Where used:** the Poppy Ridge aerial reference, and as the tracing source for a small number of
  greens that OpenStreetMap did not map at all (Bay View 2 — tagged `_digitized`). Those are the only
  features in the project not taken straight from OpenStreetMap, and they are offered under ODbL 1.0
  on request per §4.6 above.
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
