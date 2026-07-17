# Lucas Green Book

Free, printable **green books** for junior golfers — built entirely from open and
public‑domain data.  🌐 **[lucasgreenbook.org](https://lucasgreenbook.org)**

A "green book" is the little booklet tour players carry: a per‑hole map of the green's
slope and break, the hole layout, and the yardages. The good ones cost real money.
**Lucas Green Book** makes them for free, so any junior can walk to the first tee with the
same quality read as anyone else.

## Why this exists
Green‑reading books shouldn't cost more than the round. Every kid who tees it up deserves a
fair, honest read of the greens — not just the ones who can afford a premium product. This is
a personal, **not‑for‑profit** contribution to junior golf: free to print, use, and share.

## What it is
An open, course‑agnostic **engine** that turns public data into a palm‑size, printable book
for a golf course:
- **Green maps** — computed slope %, iso‑elevation contours, downhill break arrows, and a
  5‑yard depth grid for each green.
- **Hole maps** — tee‑to‑green layout with fairway, bunkers, water, trees, and yardages.
- **Reference** — scorecard, tee ratings/slopes, and notes pages.
- Sized to slip into a back‑pocket yardage‑book cover and **designed to fall within the
  Rules of Golf 4.3** size/scale limits for green‑reading materials.

## The goal
Accurate, honest, free green books for junior golfers — never fabricated, never for sale.
If the data to do a course *accurately* doesn't exist yet, we don't guess; we say so.

## How it's made — open data only
Everything is built from sources anyone can use:
- **Hole & green geometry:** [OpenStreetMap](https://www.openstreetmap.org) contributors,
  under the Open Database License (ODbL).
- **Green slope / contours / arrows:** computed by this engine from **USGS 3DEP** LiDAR —
  0.4 m ground returns where dense coverage exists, or the 1 m seamless DEM as a fallback —
  U.S. federal **public domain**.
- **Par / yardage / handicap:** facts from the published scorecard.

**No commercial green‑reading product's data, imagery, artwork, layout, or trade dress is
used, copied, or referenced. No Google / Apple / Esri / Maxar imagery is embedded.** The
project is independent and not affiliated with, endorsed by, or sponsored by any course,
club, association, or product. Course names are used only to identify the course. See the
[`legal/`](legal/) folder for the full data‑sources, licenses, attributions, and
independent‑creation record.

## Pipeline (overview)
```
fetch_osm.py            # OpenStreetMap geometry (greens, holes, fairways, bunkers, water)
fetch_lidar.py          # download USGS 3DEP LiDAR tiles covering the course (via The National Map)
fetch_lidar_alameda.py  #   Alameda County 2021 tile-name decoder (used when TNM naming needs it)
fetch_dem_hd.py         # 0.4 m green surfaces from the raw LiDAR ground returns
fetch_dem.py            #   OR USGS 3DEP seamless 1 m per green (fallback where no dense LiDAR)
fetch_trees.py          # trees from LiDAR canopy returns (never placed on greens/fairways/tees/bunkers)
render_green.py         # green slope map (arrows, contours, slope %, 5-yard depth grid)
render_hole.py          # tee -> green hole layout
generate.py             # lays out the palm cards -> printable HTML/PDF
```
See [`PIPELINE.md`](PIPELINE.md) for the full per‑course build steps.

## Editions & extras
- **Standard pocket book** — 3.5×5″ cards, 4 per sheet, duplex, top‑flip; slips into a
  back‑pocket yardage‑book cover. Each hole shows the back tee as the headline yardage, in
  its own tee colour.
- **Large‑print edition** (`COURSE=<slug> COACH=1 python3 generate.py`) — same paper‑saving
  layout, but each hole is split across two cards (course map, then green) with larger type,
  for coaches and anyone who wants an easier read. It's marked a **practice edition**
  (enlarged past the tournament scale, so not a conforming competition book).
- **3D‑printable binding** — [`green book binding.stl`](green%20book%20binding.stl), a
  printable cover/binding for the trimmed card deck.

## What's in this repo (and what isn't)
- **Included:** the engine (Python), the build docs, a 3D‑printable binding
  (`green book binding.stl`), and the [`legal/`](legal/) folder.
- **Not included:** the `courses/` folder — per‑course data (OSM/LiDAR caches) and the
  generated books are kept **local**, not in version control.

## A note on accuracy & the rules
Green maps show general tilt and tiers, not exact break — always trust your own read. The
books are **designed** to fall within Rule 4.3 limits, but conformance is a Committee‑level,
per‑competition decision — confirm before playing in an event.

## License
**Free for personal, non‑commercial use — not for commercial use.** The code in this repository
is released under the [PolyForm Noncommercial License 1.0.0](LICENSE): you may use, modify, and
share it for personal and other non‑commercial purposes, **but not commercially**. If you use or
share it, please keep the credit — **"Lucas Green Book" by Lucas Wu** — and preserve the open‑data
attributions (© OpenStreetMap contributors / ODbL; USGS public domain). The underlying data keeps
its own licenses — see [`legal/`](legal/).

---
*Crafted by Lucas · a free contribution to junior golf · not for sale.*
*[lucasgreenbook.org](https://lucasgreenbook.org) · info@lucasgreenbook.org*
