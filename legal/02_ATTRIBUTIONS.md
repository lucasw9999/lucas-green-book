# Required Attributions

These are the attribution notices the project uses. They appear in the books and should
appear on any website that hosts them.

## Printed in every distributed book ("About & legal" panel)
- **OpenStreetMap:** "© OpenStreetMap contributors" + "Open Database License (ODbL) 1.0" +
  "osm.org/copyright".
- **USGS:** "public‑domain USGS 3DEP" (courtesy credit; not legally required).
- **Scorecard:** described as facts from the published scorecard.

## OSM required-attribution string

**What the books actually print** (`generate.py`, both editions -- verified present in all 14 books
that use OSM data; the 15th uses none):
> Produced Work from **OpenStreetMap** data (© OpenStreetMap contributors, **ODbL 1.0**,
> osm.org/copyright)

OSMF's canonical long form, for reference:
> © OpenStreetMap contributors — data available under the Open Database License (ODbL).
> https://www.openstreetmap.org/copyright

Both satisfy ODbL §4.3. This section used to quote only the long form, which is not the string in use
-- a file whose purpose is to record the exact notices we print should quote the printed one first.

## If hosting the books on a website, add a footer:
> Maps © this project. Course geometry © OpenStreetMap contributors (ODbL,
> openstreetmap.org/copyright). Elevation: USGS 3DEP (public domain). Independent, not for
> sale, not affiliated with any course or product.

## Poppy Ridge aerial — Esri/Maxar imagery REMOVED 2026‑07‑13, now USDA NAIP
This file formerly embedded Esri/Maxar imagery, which carries "Imagery © Esri / Maxar" (Esri's
mandated credit is "Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community").
**Attribution alone never granted redistribution rights for that imagery**, so it was deleted rather
than merely marked personal: the aerial was rebuilt from **public‑domain USDA NAIP** and labelled as
the pre‑2025 layout. NAIP is a U.S. Government work and legally requires no attribution; we credit
it in the book anyway. See `07_POPPY_RIDGE_ESRI_IMAGERY.md`.
