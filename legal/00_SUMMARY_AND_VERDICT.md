# Summary & Verdict

**Reviewed:** 2026‑07‑13. Whole project: generator code, all 7 course folders, fetch scripts,
every generated HTML/PDF, and embedded assets. An independent adversarial "opposing counsel"
pass was run in addition to a direct audit.

## Verdict

### ✅ The six DISTRIBUTED books are CLEAN
The Reserve at Spanos Park · Copper Valley · Monarch Bay (Tony Lema) · Castlewood Valley ·
Castlewood Hill · Callippe Preserve.

Each is built **only** from:
1. **OpenStreetMap** geometry — hole/green/fairway/bunker/water/tree shapes — under the
   **Open Database License (ODbL 1.0)**, attributed in the book.
2. **Green slope/contours/arrows we compute ourselves** from **USGS 3DEP** elevation /
   LiDAR — **U.S. federal public domain** (17 U.S.C. §105, no copyright).
3. **Par / yardage / handicap** from **published scorecards** — these are **facts**, and
   facts are not copyrightable (*Feist v. Rural Telephone*, 1991).

Confirmed by audit:
- **No competitor's data, images, artwork, symbol set, page layout, or trade dress** was
  used, copied, referenced, or reverse‑engineered.
- **No competitor brand name** (StrackaLine, GolfLogix, etc.) appears anywhere in any book
  (grep‑verified across all HTML/PDF).
- **No Google, Apple, Bing, or Esri/Maxar imagery** is embedded in any distributed book.
- Every book carries the "About & legal" panel (independence, open‑data provenance,
  nominative trademark use, non‑affiliation, removal‑on‑request, no‑warranty, Rule‑4.3
  designed‑not‑guaranteed).

**These are safe to hand out and safe to host online.**

### ✅ Poppy Ridge Esri issue — RESOLVED (2026‑07‑13)
Poppy Ridge was rebuilt in 2025, so no open (OSM/USGS) data of the new layout exists yet. Its
aerial originally embedded **Esri/Maxar imagery** (restricted license). **That has been removed**
and the aerial rebuilt from **USDA NAIP (U.S. public domain)**, clearly labeled as the **pre‑2025
(old) layout — site/area reference only.** The project now contains **no Esri/Maxar, Google, or
Apple imagery anywhere.** The Poppy **yardage cards** (scorecard facts) are clean and current.
Honest caveat: NAIP predates the rebuild, so its aerial shows the old course (labeled as such).
See `07_POPPY_RIDGE_ESRI_IMAGERY.md`.

## Risk ranking (from the adversarial review)
| # | Item | Severity |
|---|---|---|
| 1 | Esri/Maxar imagery in Poppy aerial | **RESOLVED** — removed, rebuilt from public-domain NAIP |
| 2 | Competitor copyright / trade dress / trademark vs. 6 books | Weak → Frivolous |
| 3 | Course names / depicting a private club | Weak (nominative use) → handled |
| 4 | "Designed to conform · Rule 4.3" / no‑warranty | Weak, well‑mitigated |
| 5 | Viewing (not copying) the Jay Blasi routing diagram | Frivolous |
| 6 | OSM ODbL / USGS public domain compliance | Clean |
| 7 | Internal "StrackaLine" text in README/code comments (not in books) | Cosmetic — cleaned |

## The rule we live by
Distributed books use **open data + public domain + facts only**. If a source is
copyrighted and licensed (Google/Apple/Esri/Maxar/any commercial product), it does **not**
go into anything we hand out. Full stop.
