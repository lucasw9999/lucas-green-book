<div align="center">

<img src="assets/banner.png" alt="Lucas Green Book" width="100%">

### Free **yardage &amp; green‑reading books** for junior golfers — built from open &amp; public‑domain data.

[![Website](https://img.shields.io/badge/🌐_lucasgreenbook.org-2b6a2b?style=flat-square)](https://lucasgreenbook.org)
[![Code](https://img.shields.io/badge/code-PolyForm_Noncommercial_1.0.0-1c4e8a?style=flat-square)](LICENSE)
[![Books](https://img.shields.io/badge/books-CC_BY--NC--ND_4.0-1c4e8a?style=flat-square)](https://creativecommons.org/licenses/by-nc-nd/4.0/)
[![Data](https://img.shields.io/badge/data-OpenStreetMap_+_USGS_3DEP-b8860b?style=flat-square)](#how-its-made)
![Free](https://img.shields.io/badge/free-for_every_junior-2b6a2b?style=flat-square)
![Rule 4.3](https://img.shields.io/badge/designed_for-Rule_4.3-555?style=flat-square)

**[🌐 Website](https://lucasgreenbook.org)** &nbsp;·&nbsp; [⛳ What it is](#what-it-is) &nbsp;·&nbsp; [🛰️ How it's made](#how-its-made) &nbsp;·&nbsp; [🔧 Pipeline](#pipeline-overview) &nbsp;·&nbsp; [⚖️ License](#license)

</div>

---

A **green book** is the little booklet tour players carry: a per‑hole map of the green's slope and
break, the hole layout, and the yardages. The good ones cost real money. **Lucas Green Book** makes
them **free**, so any junior can walk to the first tee with the same quality read as anyone else.

## Why this exists
Green‑reading books shouldn't cost more than the round. Every kid who tees it up deserves a fair,
honest read of the greens — not just the ones who can afford a premium product. This is a personal,
**not‑for‑profit** contribution to junior golf: free to print, use, and share.

## What it is
An open, course‑agnostic **engine** that turns public data into a palm‑size, printable book:

- 🟢 **Green maps** — computed slope %, iso‑elevation contours, downhill break arrows, and a
  5‑yard depth grid for each green.
- 🗺️ **Hole maps** — tee‑to‑green layout with bunkers, water, trees, and yardages.
- 📋 **Reference** — scorecard, tee ratings/slopes, and notes pages.
- 📐 Sized to slip into a back‑pocket yardage‑book cover and **designed to fall within the
  Rules of Golf 4.3** size/scale limits for green‑reading materials.

## The goal
Accurate, honest, free green books for junior golfers — **never fabricated**. If the data to do a
course *accurately* doesn't exist yet, we don't guess; we say so.

## How it's made
Everything is built from open data anyone can use:

| Layer | Source | License |
|---|---|---|
| Hole &amp; green geometry | [OpenStreetMap](https://www.openstreetmap.org) contributors | ODbL 1.0 |
| Slope / contours / arrows | **USGS 3DEP** LiDAR — 0.4 m ground returns (1 m seamless DEM fallback) | U.S. public domain |
| Par / yardage / handicap | Facts from the published scorecard | facts (not copyrightable) |

> **No commercial green‑reading product's data, imagery, artwork, layout, or trade dress is used,
> copied, or referenced. No Google / Apple / Esri / Maxar imagery is embedded.** The project is
> independent and not affiliated with, endorsed by, or sponsored by any course, club, association,
> or product. Course names are used only to identify the course. See [`legal/`](legal/) for the
> full data‑sources, licenses, attributions, and independent‑creation record.

## Pipeline (overview)
```text
fetch_osm.py            # OpenStreetMap geometry (greens, holes, fairways, bunkers, water)
fetch_lidar.py          # download USGS 3DEP LiDAR tiles covering the course (via The National Map)
fetch_lidar_alameda.py  #   Alameda County 2021 tile-name decoder (when TNM naming needs it)
fetch_dem_hd.py         # 0.4 m green surfaces from the raw LiDAR ground returns
fetch_dem.py            #   THEN USGS 3DEP seamless 1 m for the greens it refused (fills gaps;
                        #   OVERWRITE=1 to replace a good 0.4 m surface on purpose)
fetch_trees.py          # trees from LiDAR canopy returns (never placed on greens/fairways/tees/bunkers)
fetch_hole_elev.py      # tee-to-green height change from the same LiDAR -> hole_elev.json (--write)
lidar_coverage.py       # checks the downloaded tiles' DATA actually reaches the greens & holes
distribution.py         # one rule: may this book be handed out? (used by the legal record too)
render_green.py         # green slope map (arrows, contours, slope %, 5-yard depth grid)
render_hole.py          # tee -> green hole layout
generate.py             # lays out the palm cards -> printable HTML/PDF
```
See [`PIPELINE.md`](PIPELINE.md) for the full per‑course build steps.

## Install &amp; run
Python **3.11+**. Chromium is fetched separately by Playwright — it prints the book to PDF and is
also what the Rule 4.3 gate measures.
```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```
This repo ships the **engine only** — `courses/` is gitignored, so per‑course data and the generated
books stay local and are never published. To build a course, start from the documented template:
```bash
mkdir -p courses/my-course
cp examples/course.json courses/my-course/course.json    # then replace every value
COURSE=my-course python3 fetch_osm.py                    # then follow PIPELINE.md
```
Checks worth running on anything you build:
```bash
python3 -m pytest tests/ -q          # regression tests (skip cleanly with no course data)
python3 tools/check_scale.py         # measures the LAID-OUT green scale against Rule 4.3
python3 tools/export_pdf.py --check  # every PDF was exported from its current HTML
```
Run the suite in a **shuffled order** now and then, not just as collected. This file rebinds
`COURSE` and drops modules from `sys.modules` at 69 sites, so a test can silently reconfigure the next
one, and file order alone will never show it — a real `IndexError` in `render_hole` hid behind that for
its whole life and only appeared under shuffling:
```bash
python3 -m pytest tests/ -q --collect-only | grep '^tests/' | sed 's/ .*//' | sort -R > /tmp/ids
python3 -m pytest $(tr '\n' ' ' < /tmp/ids) -q      # shuffled
```
An autouse fixture now restores the `COURSE` binding after every test, so leakage should be structurally
impossible; the shuffle is how you find out it still is.

`tools/check_scale.py` is the important one. It lays each book out in a real browser under print
media and measures the drawn green there, rather than trusting the SVG's own attributes — a
stylesheet can override those, which is exactly how 15 greens once printed over the legal scale
while every attribute looked correct. It exits non‑zero if any green exceeds 3/8 in : 5 yd. (It also
reports the printed 5‑yd bar length from the PDF, but that figure is informational and does not
gate.) `tools/export_pdf.py --check` is the companion: it proves the PDF you would actually print
came from the HTML on disk.

**After adding a course, regenerate the two derived legal docs** — the test suite fails until you do,
and the failure names staleness rather than telling you which command fixes it:
```bash
python3 tools/gen_provenance.py       # rewrites legal/03_PROVENANCE_BY_COURSE.md from the artifacts
python3 tools/gen_disclaimers.py      # rewrites legal/05_DISCLAIMER_TEXT.md from what the books print
```
Both take `--check` instead, which is what CI and the suite use. Neither is optional: they are derived
from the build outputs precisely so the legal record cannot drift from what was actually printed.

Two more tools, useful when a course looks wrong rather than on every build:
```bash
python3 tools/check_osm_bbox.py --all # every printed hole's 45 m corridor lies inside its fetch box
COURSE=<slug> python3 tools/lidar_dates.py   # decodes the flight date from the LiDAR point records
```
`check_osm_bbox.py` catches a fetch box so tight that features beside the hole were never downloaded —
the map then agrees with the footer because both count only what arrived. `lidar_dates.py` is where
the flight dates in the provenance table come from; a USGS *project name* is not a flight date, and
four courses were mislabelled by 2–12 years before these were decoded from the points themselves.

## Editions &amp; extras
- **Standard pocket book** — 3.5×5″ cards, 4 per sheet, duplex, top‑flip; slips into a back‑pocket
  yardage‑book cover. Each hole shows the back tee as the headline yardage, in its own tee colour.
- **Large‑print edition** (`COURSE=<slug> COACH=1 python3 generate.py`) — each hole split across two
  cards (course map, then green) with larger type, for coaches. Marked a **practice edition** (past
  the tournament scale, so not a conforming competition book).
- **3D‑printable binding** — [`green book binding.stl`](green%20book%20binding.stl), a printable
  cover/binding for the trimmed card deck.

**Print in colour.** Colour is a real data channel here, not decoration: ground steeper than 10% is
shown by colour *only* and deliberately carries no number, and a fairway bunker's sand sits within
3% grey of the fairway it lies in, so on a mono printer the bunkers all but disappear. Both books say
so on the guide card.

## What's in this repo
- **Included:** the engine (Python), the build docs, `requirements.txt`, a documented
  [`examples/course.json`](examples/course.json) template, the regression tests, the Rule 4.3
  measurement tool, the 3D‑printable binding, and [`legal/`](legal/).
- **Not included:** the per‑course data (OSM/LiDAR caches) and the generated books.

## Accuracy &amp; the rules
Green maps show general tilt and tiers, not exact break — always trust your own read. The books are
**designed** to fall within Rule 4.3 limits, but conformance is a Committee‑level, per‑competition
decision — confirm before playing in an event.

## License
- **Code** → [PolyForm Noncommercial License 1.0.0](LICENSE): use, modify, and share for personal
  and non‑commercial purposes; keep the credit — **"Lucas Green Book" by Lucas Wu** — and preserve
  the open‑data attributions (© OpenStreetMap contributors / ODbL; USGS public domain).
- **The finished books** (generated PDFs) →
  [**CC BY‑NC‑ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/): free to print and share
  **with credit**, but not for sale and not to be altered.
- **Trademark** → **"Lucas Green Book"** and the flag emblem are **trademarks of Lucas Wu**; no
  trademark rights are granted. The underlying data keeps its own licenses — see [`legal/`](legal/).

<div align="center">

---

*Crafted by Lucas — a free contribution to junior golf.*
**[🌐 lucasgreenbook.org](https://lucasgreenbook.org)** · [info@lucasgreenbook.org](mailto:info@lucasgreenbook.org)

</div>
