# Data Sources & Licenses

Every input used to build the books, its license, our obligation, and how we meet it.

## 1. OpenStreetMap — hole/green/fairway/bunker/water/tree geometry
- **License:** Open Database License (ODbL) 1.0.
- **What we take:** vector geometry (shapes/positions) of golf features, via the Overpass API. Cached locally as `osm_geom.json` / `osm_course.json`.
- **Our obligations & compliance:**
  - **Attribution:** ✔ Each book prints "© OpenStreetMap contributors, ODbL 1.0, osm.org/copyright."
  - **Produced Work — the notice duty is §4.3, not §4.5(b).** ODbL §4.3 ("Notice for using output (Contents)") is the clause that governs us: creating and using a Produced Work does *not* require the full §4.2 notice, but publicly using one obliges a notice "reasonably calculated" to tell anyone exposed to the work that the Contents came from the database and are available under ODbL. ✔ Done — every book prints exactly that. §3.1's grant states that "[t]hese rights explicitly include commercial use, and do not exclude any field of endeavour", so this notice is owed on the same terms regardless of distribution. Separately, **§4.5(b)** is what exempts a Produced Work from share‑alike, which is why the terms the **books** carry do not conflict with ODbL. §4.5(b) establishes that using the Database to create a Produced Work "does not create a Derivative Database for purposes of Section 4.4", so the Produced Work sits outside §4.4 whatever licence is on it.
  - **Share‑alike (§4.4) and §4.4(c).** ODbL 1.0 §4.4(c) states that a Derivative Database is Publicly Used if a Produced Work created from it is Publicly Used. For the courses where we supplemented OpenStreetMap with digitized features (see §4.6 below), those additions are licensed under ODbL 1.0 outright. For all other courses, the geometry consists of unmodified extracts kept as internal build inputs, for which §4.5(c) applies.
  - **§4.6 Access to Derivative Databases — an offer to recipients.** ODbL §4.6 requires that if you Publicly Use a Produced Work created from a Derivative Database, you must offer recipients a machine-readable copy of either the entire Derivative Database or a file containing all alterations made, free of charge over the internet.
    **Three courses** are affected where geometry was supplemented because OpenStreetMap had gaps:
    - **Wailea Golf Club (Emerald Course):** 168 features digitized from public-domain USDA NAIP and USGS 3DEP LiDAR (green rings, hole centrelines, teeing platforms, and bunkers, all tagged `_digitized`).
    - **Bay View Golf Club:** 2 greens hand-digitized from USDA NAIP (ways `900000005` and `900000007`, tagged `_digitized`).
    - **Baylands Golf Links:** Hole 7 back-tee pad (way `900000101`, tagged `_digitized`) and one vertex extension to OSM hole way `786150435` extending the centreline to the back pad.

    The alterations total **172 features across three courses**. In full compliance with §4.6, **these `_digitized` features are available in machine-readable form under ODbL 1.0 free of charge on request** at `info@lucasgreenbook.org`.

    For the remaining twelve courses, the geometry is an unmodified extract from OpenStreetMap, for which OSMF guidance directs users to openstreetmap.org (which every book's About panel prints).
  - **Contributor metadata:** A few OSM features carry a contributor `source:` tag naming aerial imagery (such as Bing). That is the original mapper's own provenance metadata inside licensed OSM data; we consume the ODbL‑licensed **vector geometry** only. No commercial provider's imagery is fetched, used, or reproduced.

## 2. USGS 3DEP elevation / LiDAR — green slope, contours, break arrows
- **License:** **U.S. Government public domain** — released without restriction by USDA‑FSA / USGS as U.S. Government data, with no copyright asserted (cf. 17 U.S.C. §105).
- **What we take:** raw elevation (the 3DEP LiDAR point clouds and/or the seamless DEM mosaic), via `elevation.nationalmap.gov` and the USGS LPC archive. That service is multi‑resolution; each green records the source cell measured out of its own elevation array rather than assuming a fixed tier.
- **What we make:** we **compute** the slope %, iso‑elevation contours, downhill break arrows, and depth grid ourselves from the raw point clouds. That mathematical analysis is **our own original work** over public‑domain data.
- **Obligations:** none legally required. We credit "public‑domain USGS 3DEP" as a courtesy.
- **Commercial posture:** USGS's policy confirms that USGS-authored or produced data is in the U.S. Public Domain with no field-of-use restrictions. The computed slope, contours, and arrows carry no third-party restrictions.

## 3. Scorecards — par, yardage, handicap, course rating and slope
- **Status:** **facts.** Par, per-tee yardages, stroke index, and USGA Course Rating / Slope Rating are uncopyrightable facts (*Feist Publications, Inc. v. Rural Telephone Service Co.*, 1991 — facts and "sweat of the brow" are not protected by copyright).
- **What we take:** **facts from published scorecards** — par, per‑hole yardage, stroke‑index, and each tee's Course Rating / Slope Rating, transcribed as numbers. Nothing of a scorecard's **graphic design, branding, or layout** is copied: no artwork, colour palette, table styling, or logos.
- **Course Rating and Slope Rating:** Transcribed from published cards and verified against the USGA's National Course Rating and Slope Database (NCRDB).
- **Cross‑checks:** Per‑hole par is corroborated by OpenStreetMap's `golf=hole` par tags where present, and each tee's per‑hole yardages must sum exactly to the published front/back/total yardages printed on the card.

## 3a. Published Local Rules — hazard designations
- **Status:** **facts.** A club's published Local Rules sheet states which ground on its own course is out of bounds, an environmentally sensitive area, or under a Local Rule.
- **What we print:** A text designation only (e.g., "ESA staked · no entry · Rule 17.1d · boundary not drawn") where published, never an unverified boundary line. Where OpenStreetMap carries no vector boundary for a hazard, we refuse to guess or fabricate a boundary line.

## 4. Licensed commercial imagery — NOT used
- **Standing rule:** copyrighted or licensed commercial imagery (Esri/Maxar, Google, Apple, Bing) does not enter this project, in any file, distributed or personal.
- **Verified:** no Esri/Maxar, Google, Apple or Bing imagery appears anywhere in this project.
- Where an aerial reference is needed, it comes exclusively from **public-domain USDA NAIP** (§4a).

## 4a. USDA NAIP (National Agriculture Imagery Program) — public domain
- **License:** **U.S. public domain** — released without restriction by USDA‑FSA as U.S. Government data, with no copyright asserted (cf. 17 U.S.C. §105).
- **Where used:** As the reference source for tracing features that OpenStreetMap did not map (the 172 features on three courses described in §1, each tagged `_digitized`).
- **What is derived:** **vector coordinates only.** No NAIP pixels or photographic imagery are embedded in any book. Tracing the outline of a physical putting surface records a geographic fact; it is not copying an image.

## 5. NOT used (and why it matters)
- **Google Maps / Apple Maps / Bing imagery:** **never fetched or embedded**. Their terms prohibit printed/offline derivative maps and redistribution — avoiding them entirely is a deliberate, defensible architectural choice.
- **Commercial green‑reading products (StrackaLine, GolfLogix, etc.):** **no data, imagery, symbols, layout, or trade dress** used or referenced anywhere. Every map is independently created from open public data.

## 6. The maker's own assets & book licensing
- **"Lucas Green Book" is a trademark of Lucas Wu.** The name, emblem, and SVG map/heat/contour/arrow styling are original, created by the maker.
- **Cover artwork:** The cover plate is original artwork directed and supplied by Lucas Wu, produced with a generative image model from his own prompt. It contains no words, no third-party imagery, and bare JFIF headers with no vendor or proprietary EXIF metadata.
- **The books:** The printed booklets and PDFs are **© 2026 Lucas Wu · Lucas Green Book™. All rights reserved.** Copies previously distributed under CC BY‑NC‑ND 4.0 remain under that licence for those copies (that grant is irrevocable as to those copies); subsequent copies carry All Rights Reserved terms.
- **The underlying open data is unaffected:** Anyone remains completely free to build their own books directly from the same OpenStreetMap, USGS 3DEP, and scorecard public sources under those sources' own open terms. What is reserved is this project's original rendering expression, never the public data underneath.
