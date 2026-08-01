# Green Surface Repeatability — what the printed slope numbers are actually worth

Measured 2026‑07‑31 with `tools/cross_flight_check.py --all`. Reproduce it with that command.

Every green card prints a dominant tilt to one decimal (`2.7%`), a qualifier (`firm` / `subtle`), a
feed direction, and 15 cm contours. The governing rule of this project is that it must never print a
number the data does not support — but until this measurement, **nothing recorded what the data
supports.** The accuracy disclaimers were honest in intent and unevidenced in fact. This is the
evidence.

## The natural experiment

Five of the twelve courses were flown by USGS across more than one date, so some greens were
surveyed **twice, independently** — different flight lines, different atmospheric conditions,
separate GPS/IMU solutions, and in one case a different season. Nobody designed this as a control;
it is a property of how the tiles were collected. Splitting the ground returns by their per‑point
GPS timestamp recovers each pass, and each pass can then be gridded on its own and pushed through
the same `render_green.green_summary()` the card is printed from.

A pass that merely clips the edge of a green cannot check anything — its least‑squares plane is
fitted to a sliver. So a pass is only compared when it independently put a ground return in **≥50%
of that green's interior cells**. 47 pass/green pairs were excluded on that basis; 33 greens had two
qualifying passes.

## Result

**33 greens, each independently surveyed twice. Every pair agrees.**

| | worst observed |
|---|---|
| dominant tilt | **0.04 percentage points** (e.g. 6.12% vs 6.16%) |
| feed direction | **4.3°** |
| `firm` / `subtle` qualifier | never differed |

The strongest single case is Philadelphia Country Club, whose two passes are **101 days apart**
(2024‑12‑17 and 2025‑03‑27) and straddle a phased course restoration — the exact circumstance in
which a green *should* be caught changing. On the five greens both passes covered:

| hole | 2024‑12‑17 | 2025‑03‑27 | Δ tilt | Δ aim |
|---|---|---|---|---|
| 1 | 0.83% subtle | 0.84% subtle | 0.01 pp | 2.1° |
| 2 | 0.91% subtle | 0.92% subtle | 0.01 pp | 0.4° |
| 6 | 1.58% firm | 1.57% firm | 0.01 pp | 0.1° |
| 7 | 1.43% firm | 1.44% firm | 0.00 pp | 0.3° |
| 8 | 0.27% subtle | 0.28% subtle | 0.01 pp | 1.5° |

At the raw point level those two passes agree to a **median 0.03 ft (0.4 in), 95th percentile
0.13 ft**, over ~11,000 ground returns per green.

Three of the 33 pairs agreed physically but landed either side of a printed digit — 2.05% against
2.06% prints as "2.0" and "2.1". That is rounding at the boundary, not disagreement, and the tool
reports it as such rather than as a failure.

## What this does and does not establish

**Does:** the printed read is *reproducible*. Re-fly the course and the card comes out the same. The
numbers are not artifacts of one pass's noise, one flight line's geometry, or the interpolation
finding shape in randomness. For a book that prints a tilt to one decimal, this is the property that
had to hold, and it holds with two orders of magnitude of margin.

**Does not:**
1. **This is precision, not accuracy.** Both passes come from the same USGS program, sensor class and
   processing chain. A *systematic* bias — a vertical datum offset, a consistent ground‑classification
   bias in turfgrass — would be present in both and invisible here. Bounding that needs a
   ground‑truth survey, which this project does not have and cannot get from public data.
2. **It validates the dominant plane, not the detail.** Tilt, aim and the firm/subtle qualifier are
   what were compared. It says nothing about whether an individual 15 cm contour or a single arrow on
   a subtle green is right.
3. **n = 33 greens on 5 courses, one LiDAR program.** Four of the five course pairs are days apart
   and leaf‑off winter or summer; only Philadelphia spans a season.
4. It cannot detect a change that happened *before* the first pass or *after* the last. Poppy Ridge's
   2025 rebuild post‑dates all available coverage, which is why that course has no green maps at all.

None of this weakens the books' existing wording — "general tilt and tiers, not exact break … always
trust your own read" — it supports it, and now with a number behind it.

## Why the tool shares the renderer's math

`cross_flight_check.py` calls `render_green.green_summary()` rather than computing a plane its own
way. That function was extracted to module scope for exactly this reason: a checker with its own copy
of the arithmetic stops verifying the card the moment either copy changes, and would then report
agreement about a number nobody prints.
