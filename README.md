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
| Slope / contours / arrows | **USGS 3DEP** LiDAR — 0.4 m ground returns (3DEP seamless mosaic where the point cloud has no returns; its source cell is measured per green, not assumed) | U.S. public domain |
| Par / yardage / handicap | Facts from the published scorecard | facts (not copyrightable) |
| Aerial tracing (2 greens OSM had not mapped) | **USDA NAIP** imagery | U.S. public domain |

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
                        #   (keeps an existing seamless fill rather than blanking a green it now
                        #    refuses; OVERWRITE=1 to blank it on purpose)
fetch_dem.py            #   THEN the USGS 3DEP seamless MOSAIC for the greens it refused -- a
                        #   multi-resolution service, so each patch records the source cell measured
                        #   out of its own pixels instead of a tier (fills gaps; keeps a green that
                        #   already reads rather than blanking it on a worse reply;
                        #   OVERWRITE=1 to replace a good surface on purpose)
fetch_trees.py          # trees from LiDAR returns 2.5-35 m above ground (never on greens/fairways/tees/bunkers)
fetch_hole_elev.py      # tee-to-green height change from the same LiDAR -> hole_elev.json (--write)
lidar_coverage.py       # greens & holes vs the tiles' header bboxes, + a dem_hd cross-check
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
Run the suite in a **shuffled order** now and then, not just as collected. It rebinds `COURSE` and
drops modules from `sys.modules` at 116 sites — counted across `tests/*.py` with comments and string
literals stripped, so every one of them executes; a plain `grep -c` reads higher, because the suite's
own comments discuss the idiom — so a test can silently reconfigure the next one, and file order alone
will never show it: a real `IndexError` in `render_hole` hid behind that for its whole life and only
appeared under shuffling:
```bash
python3 -m pytest tests/ -q --collect-only | grep '^tests/' | sed 's/ .*//' | sort -R > /tmp/ids
python3 -m pytest $(tr '\n' ' ' < /tmp/ids) -q      # shuffled
```
The autouse `_bind_a_course` fixture in `tests/conftest.py` restores the `COURSE` binding after every
test in this directory, so leakage should be structurally impossible across the whole suite: pytest
loads `tests/conftest.py` for every test module here, so every one of them inherits it. The shuffle is
how you find out it still is.

That site count is **generated, not typed** — as is the tracked-file count in
`legal/10_SOFTWARE_DEPENDENCIES.md`. Both are properties of this repository rather than of any book, so
any round that adds a test file or a `sys.modules` drop moves one of them; hand-typed, the pair went
stale three times in a single day. If a test tells you either figure is wrong, do not retype it:
```bash
python3 tools/gen_repo_figures.py          # rewrites just those two sentences
python3 tools/gen_repo_figures.py --check  # exits 1 while either is stale
```
The tracked count is the one `git ls-files` reports, so `git add` a new file before republishing.

`tools/check_scale.py` is the important one. It lays each book out in a real browser under print
media and measures the drawn green there, rather than trusting the SVG's own attributes — a
stylesheet can override those, which is exactly how 15 greens once printed over the legal scale
while every attribute looked correct. It exits non‑zero if any green exceeds 3/8 in : 5 yd. (It also
measures the printed 5‑yd bar in the PDF, and **that figure gates too** &mdash; the Rule 4.3 claim is
about the artifact a player carries, not the HTML it came from.) `tools/export_pdf.py` is the
companion, in two steps: the export beside each book records a digest of the HTML **and** a digest of
the exported PDF, and `--check` records nothing — it re‑derives both from the files on disk and
compares, so a stale export, a book printed by hand and a half‑written one are each named rather than
assumed. It used to say it "proves the PDF you would actually print came from the HTML on disk" while
recording the HTML's digest alone — which proved that a *note* beside the PDF named the current HTML.
Interrupting an export made the point: the writer truncates the book in place, so the printable
artifact came back with zero pages while its stamp still agreed, and `--check` exited 0. The export
stages and renames now, and a file with no trailer is refused whatever its stamp says.

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
python3 tools/check_osm_bbox.py --all # every printed hole's 68 m corridor lies inside its fetch box
COURSE=<slug> python3 tools/lidar_dates.py   # decodes the flight date from the LiDAR point records
python3 tools/cross_flight_check.py --all    # do two surveys of the same green print the same read?
```

A green surface is two files that only mean anything together — `dem_hd/holeNN.npy` carries no
georeference, so the sidecar's bbox is what places every pixel. Each sidecar records a SHA-256 of the
array committed beside it, and `render_green` refuses a pair that disagrees; a surface built before
that digest existed carries none, and is stamped from the array already on disk rather than left
unverifiable:
```bash
python3 surface_io.py            # how many built surfaces carry a pair digest
python3 surface_io.py --stamp    # stamp the ones that do not (writes sidecars only, never a .npy)
```
It reads every pair first and writes nothing at all if any one of them fails to load or disagrees with
its own metadata — a pair that is already torn has to be rebuilt, because stamping it would certify the
tear. Re-running it on a stamped tree is a no-op.
`check_osm_bbox.py` catches a fetch box so tight that features beside the hole were never downloaded —
the map then agrees with the footer because both count only what arrived. `lidar_dates.py` is where
the flight dates in the provenance table come from; a USGS *project name* is not a flight date, and
four courses were mislabelled by 2–12 years before these were decoded from the points themselves.

`cross_flight_check.py` exists because five of the twelve courses were flown across more than one
date, so their greens are built from a blend of passes — harmless if the passes agree, and a surface
spliced from two *different* greens if the course changed under the sensor between them. It grids
each pass separately and runs the same `render_green.green_summary()` the card prints from. It is
also the project's only measurement of how repeatable these surfaces are: see
[`legal/09_GREEN_SURFACE_REPEATABILITY.md`](legal/09_GREEN_SURFACE_REPEATABILITY.md).

## Editions &amp; extras
- **Standard pocket book** — 3.5×5″ cards, 4 per sheet, duplex **flipped on the LONG edge** (what
  every sheet note in the book itself says; on portrait paper that turns the sheet about its vertical
  centreline, which is the mirroring the imposition compensates for — a top/short‑edge flip prints
  every back behind the wrong front). The cut cards then read upright when you turn a leaf over its
  top edge. Slips into a back‑pocket
  yardage‑book cover. Each hole shows the back tee as the headline yardage, in its own tee colour.
- **Large‑print edition** (`COURSE=<slug> COACH=1 python3 generate.py`) — each hole split across two
  cards (course map, then green) with larger type, for coaches. Marked a **practice edition** (past
  the tournament scale, so not a conforming competition book).
- **3D‑printable binding** — [`green book binding.stl`](green%20book%20binding.stl), a printable
  cover/binding for the trimmed card deck.

**Print in colour.** Colour is a real data channel here, not decoration: ground steeper than 10% is
shown by colour *only* and deliberately carries no number, and a fairway bunker's sand sits within
3% grey of the fairway it lies in, so on a mono printer the bunkers all but disappear. Both books say
so on the guide card — the pocket edition's colour row and the enlarged edition's about card carry the
same line, and `tests/test_r17_print.py` measures the greyscale collapse off a rendered card rather
than trusting this paragraph.

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
