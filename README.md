<div align="center">

<img src="assets/banner.png" alt="Lucas Green Book" width="100%">

### Yardage &amp; green‑reading books, built from open &amp; public‑domain data.

[![Website](https://img.shields.io/badge/🌐_lucasgreenbook.org-2b6a2b?style=flat-square)](https://lucasgreenbook.org)
[![Data](https://img.shields.io/badge/data-OpenStreetMap_+_USGS_3DEP-b8860b?style=flat-square)](#how-theyre-made)
![Rule 4.3](https://img.shields.io/badge/designed_for-Rule_4.3-555?style=flat-square)

**[🌐 lucasgreenbook.org](https://lucasgreenbook.org)**

</div>

---

A **green book** is the booklet tour players carry: a per‑hole map of the green's slope and break, the
hole layout, and the yardages. **Lucas Green Book** makes them — palm‑size, printed, and built from
public data.

**This repository is the project's public record.** It documents every source each book is built
from and the licence each source carries, and explains how the books are made.

📖 **[How a Lucas Green Book is made](ENGINEERING.md)** — the data chain, the parts that were hard,
and how the numbers are kept honest.

The engine itself is not published. Four modules are included as **excerpts, to be read** — see
[`ENGINEERING.md`](ENGINEERING.md) for what they show and what is deliberately absent.

## What's in a book
- **Green maps** — computed slope %, iso‑elevation contours, downhill break arrows, and a 5‑yard
  depth grid for each green.
- **Hole maps** — tee‑to‑green layout with bunkers, water, trees, and yardages.
- **Reference** — scorecard, tee ratings and slopes, notes pages.
- Sized to slip into a back‑pocket yardage‑book cover and **designed to fall within the Rules of Golf
  4.3** size/scale limits for green‑reading materials.

## The standard
Accurate reads, never fabricated. Where the data to map a course accurately does not exist, the book
does not guess — the greens print blank and the book says why.

## How they're made
Every book is built from open data anyone can use:

| Layer | Source | License |
|---|---|---|
| Hole &amp; green geometry | [OpenStreetMap](https://www.openstreetmap.org) contributors | ODbL 1.0 |
| Slope / contours / arrows | **USGS 3DEP** LiDAR ground returns, with the 3DEP seamless mosaic where the point cloud has none | U.S. public domain |
| Par / yardage / handicap | Facts from the published scorecard | facts (not copyrightable) |
| Aerial tracing, where OSM lacks a green | **USDA NAIP** imagery | U.S. public domain |

Slope, contours and break arrows are **computed by this project** from public‑domain elevation — never
copied from anyone. Full detail, source by source, in [`legal/`](legal/); how it is actually done, in
[`ENGINEERING.md`](ENGINEERING.md).

## Independence
**No commercial green‑reading product's data, imagery, artwork, layout, or trade dress is used,
copied, or referenced. No Google, Apple, Esri, Maxar or Bing imagery is embedded in any book.**

Lucas Green Book is independent and **not affiliated with, endorsed by, or sponsored by** any course,
club, association, or product. Course names and marks belong to their owners and are used only to
identify the course.

**A course that would prefer not to be included can ask, and the book comes down:**
**[lucasgreenbook.org/removal](https://lucasgreenbook.org/removal)**

## Accuracy &amp; the rules
Green maps show general tilt and tiers, not exact break — always trust your own read. The books are
**designed** to fall within Rule 4.3 limits, but conformance is a Committee‑level, per‑competition
decision — confirm before playing in an event.

## Rights
- **"Lucas Green Book"** and the flag emblem are **trademarks of Lucas Wu.** No trademark rights are
  granted by anything in this repository.
- The books, this record, and the software that builds them are **© 2026 Lucas Wu.** The four modules
  included here are **excerpts published to be read** — they reference modules that are not published
  and will not run as they stand, and **no licence to use, modify or redistribute them is granted.**
  The terms for any individual book are printed on that book, which is authoritative for the copy you
  are holding.
- The underlying **data** is not owned by this project and keeps its own licences — see
  [`legal/`](legal/), and honour them if you use the same sources.

<div align="center">

---

**[🌐 lucasgreenbook.org](https://lucasgreenbook.org)** · [info@lucasgreenbook.org](mailto:info@lucasgreenbook.org)

</div>
