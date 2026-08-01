# Green Surface Repeatability — what the printed slope numbers are actually worth

Measured 2026‑07‑31 with `tools/cross_flight_check.py --all`. Reproduce it with that command.

Every green card prints a dominant tilt to one decimal (`2.7%`), a `(faint)` mark where that tilt is
close to the survey's own noise floor and the card still names a side, and
15 cm contours, and all but one name a feed direction — micke‑grove 2 is flat enough that the plane
and the arrows disagree, so that card names none (see note 2). The governing rule of this project is that it must never print a
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

Which cells count as putting surface is decided **once, from the shipped surface**, and held fixed
for both passes. Each pass covers a green slightly differently and would otherwise classify slightly
different cells as too steep to putt, so the comparison would be measuring that reclassification
instead of the ground.

## Result

**33 greens, each independently surveyed twice. Every pair agrees.**

| | worst observed |
|---|---|
| dominant tilt | **0.06 percentage points** |
| feed direction | **3.9°** |
| the `(faint)` mark (internally `clear` / `faint`) | never differed |

The strongest single case is Philadelphia Country Club, whose two passes are **100 days apart**
(2024‑12‑17 and 2025‑03‑27) and straddle a phased course restoration — the exact circumstance in
which a green *should* be caught changing. On the five greens both passes covered:

| hole | 2024‑12‑17 | 2025‑03‑27 | Δ tilt | Δ aim |
|---|---|---|---|---|
| 1 | 0.83% faint | 0.84% faint | 0.01 pp | 2.1° |
| 2 | 0.91% faint | 0.92% faint | 0.01 pp | 0.4° |
| 6 | 1.58% clear | 1.57% clear | 0.01 pp | 0.1° |
| 7 | 1.43% clear | 1.44% clear | 0.00 pp | 0.3° |
| 8 | 0.27% faint | 0.28% faint | 0.01 pp | 1.5° |

At the raw point level those two passes agree to a **median 0.03 ft (0.4 in), 95th percentile
0.13 ft**, over ~11,000 ground returns per green.

Three of the 33 pairs agreed physically but landed either side of a printed digit — 2.05% against
2.06% prints as "2.0" and "2.1". That is rounding at the boundary, not disagreement, and the tool
reports it as such rather than as a failure.

## The contour interval

The guide card asserts, once per book, **"Contours join equal height (15 cm each)"**. That is a separate claim
from the tilt, and it needed its own check: if two surveys of the same green disagree by anything near
15 cm, then adjacent contour lines are inside the survey noise and the card is drawing detail it
cannot support.

Crucially, the figure that governs this is **relative**, not absolute. USGS quotes ~10 cm absolute
vertical accuracy for this class of LiDAR, and the project's own source used to cite that as its
honest limit — but an absolute offset moves an entire green up or down together and changes no read.
Break depends on height *differences within the one green*.

Differencing the two passes' **rendered** surfaces — each gridded at 0.4 m and smoothed the same way
the card is — over all 33 greens and 87,589 cells inside the green cores:

| | |
|---|---|
| RMS difference | **0.85 cm** |
| 95th percentile | 1.54 cm |
| worst single cell | 7.93 cm |

The 15 cm contour interval is therefore about **18× the noise floor** of the surface it is drawn from.
The claim holds with a wide margin. Averaging roughly 10–28 ground returns per square metre and then smoothing
over ~1.5 m beats single-pulse accuracy by a large factor, which is why the relative figure is an
order of magnitude better than the absolute spec.

## A second, independent line of evidence: flight-line overlap

The cross-flight check above splits the data by DATE. LAS also lets it be split by **swath**: every point
in the strip where two flight lines meet carries an `overlap` flag, which USGS sets so derivative
products *can* exclude those returns. Two courses here are heavily overlapped — bay-view at **47%** of
its ground points and the-reserve at **31%**.

Nothing in this pipeline filters them, so it is worth knowing whether they degrade the surface. Gridding
bay-view's overlap points and its non-overlap points **separately**, over all 18 greens:

| | |
|---|---|
| RMS difference | **1.16 cm** |
| 95th percentile | 2.23 cm |
| worst single cell | 3.60 cm |
| printed tilt | agrees within **0.07 pp** on every hole (below the 0.1 pp the card resolves) |

That is the same answer the date split gave (RMS 0.85 cm) from a completely different decomposition of
the data — two independent flight lines of the same green, and two independent surveys months apart,
agree to about a centimetre either way. So the overlap points stay: dropping them would halve bay-view's
ground density in exchange for nothing measurable.

`withheld` and `synthetic` are a different matter and are now filtered out in `fetch_dem_hd.py`. Those
bits mark points the producer disowns — measurements it says not to use, and points computed rather than
observed — and neither belongs under a printed slope read. Every tile in the corpus carries **zero** of
both, so the filter changes no shipped surface: rebuilding bay-view with it produced all 36 files
byte-identical. It is there for the next course's tiles.

## What this does and does not establish

**Does:** the printed read is *reproducible*. Re-fly the course and the card comes out the same. The
numbers are not artifacts of one pass's noise, one flight line's geometry, or the interpolation
finding shape in randomness. For a book that prints a tilt to one decimal, this is the property that
had to hold, and it holds with two orders of magnitude of margin.

**Does not:**
1. **This is precision, not accuracy** — with one part of that now bounded separately, and with the
   caveat that both figures below were measured *after* the tee-to-green height was moved onto the
   feature polygons. Before that, the printed height was a median over the green plus a 12 m collar,
   82% of which is not green, against a median over an axis-aligned box at the tee that a mapped tee
   covers about 13% of. Those two region errors pointed opposite ways and largely cancelled in the
   printed *change*, which is why neither was visible in it: correcting only the green end would have
   shifted every height in the book by +0.46 ft. Corrected together they moved 102 of the then-177 printed
   integers, made 6 heights appear and 2 disappear at the 3 ft floor, flipped no above/below word on
   any card that prints one, and took this tool's agreement with the independent DEM from a median
   0.80 ft to 0.09 ft. Both passes come
   from the same USGS program, sensor class and processing chain, so a *systematic* bias would be
   present in both and invisible to the comparisons above. Two kinds of systematic bias are worth
   separating, because only one of them stays open:
   - **Our own processing** — a vertical unit read wrong, a CRS or grid misalignment, a geoid/ellipsoid
     mixup. This IS bounded, by checking the *absolute* elevation of our surfaces against the 3DEP
     seamless DEM, a separately produced raster this project does not build — sampled over the **same
     green polygon** the pipeline measures, so the comparison is not dominated by a region mismatch.
     Over all 171 measured holes on the 11 courses the two agree to a **worst per‑course median of
     0.10 m and a worst single green of 0.35 m**; the printed tee‑to‑green *change* agrees to a
     **median 0.09 ft, worst 3.14 ft**. A US‑survey‑foot cloud
     read as metres would show tens of metres; a geoid/ellipsoid confusion about 30 m in California.
     Neither is present. (This project has shipped a foot/metre fault before — it put 74 of 175 holes'
     elevations out by a median 298 ft — so the check is not hypothetical.)
   - **The source program itself** — its absolute vertical datum, or a consistent
     ground‑classification bias in turfgrass. That remains open: the seamless DEM is derived from the
     same LiDAR, so it cannot independently confirm the program's own datum, and both products take
     class‑2 ground returns. Bounding it needs a ground‑truth survey this project cannot get from
     public data. For the contour and break claims it matters less than it sounds, because a bias
     shared by the whole green cancels out of every height *difference* — and no green card prints an
     absolute elevation.
2. **It validates the dominant plane and the surface the contours follow, not every feature.** Tilt,
   aim, the `clear`/`faint` qualifier and the 15 cm interval are what were compared. It does not establish
   that any individual arrow on a faint-fall green points the right way — and one green, micke‑grove 2, is
   flat enough that the plane and its own arrows disagree by 179.5°, so the card names no direction there
   at all.
3. **n = 33 greens on 5 courses, one LiDAR program.** Four of the five course pairs are days apart and
   leaf‑off winter or summer; only Philadelphia spans a season.
4. It cannot detect a change that happened *before* the first pass or *after* the last. Poppy Ridge's
   2025 rebuild post‑dates all available coverage, which is why that course has no green maps at all.

None of this weakens the books' existing wording — the pocket card says "general tilt & tiers, not
exact break, and may contain errors", the enlarged one "general tilt, not exact break — trust your own
read" — it supports it, and now with a number behind it.

## Why the tool shares the renderer's math

`cross_flight_check.py` calls `render_green.green_summary()` rather than computing a plane its own
way. That function was extracted to module scope for exactly this reason: a checker with its own copy
of the arithmetic stops verifying the card the moment either copy changes, and would then report
agreement about a number nobody prints.
