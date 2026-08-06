# Green Surface Repeatability — what the printed slope numbers are actually worth

Measured 2026‑08‑01 against the corpus on disk; every figure produced by
`tools/cross_flight_check.py` re‑measured 2026‑08‑02 after two further defects in that tool (see the
note under "Result"). **No single command produces this document**, and
saying otherwise was itself a defect: three of its blocks cannot be produced by the command this line
used to name. Each section now says what does.

| section | reproduce with |
|---|---|
| "The natural experiment", "Result" (except the raw‑point sentence), "The contour interval" | `python3 tools/cross_flight_check.py --all` — run from the repo root |
| the coverage figures quoted in the "Result" note (the‑Reserve's 26 pass/green pairs, north‑up vs the shipped south‑up row index) | a one‑off probe that wraps `cross_flight_check._cover` and reports both row conventions for every pass; not a shipped tool |
| the raw‑point‑level sentence under the Philadelphia table | a one‑off script, not a shipped tool; the method is stated in full beside the figures |
| "A second, independent line of evidence: flight‑line overlap" | a one‑off script, not a shipped tool; it reuses `cross_flight_check`'s own gridding and differs only in how the points are partitioned |
| the `withheld` / `synthetic` counts | a one‑off scan of every LAZ tile for those two classification‑flag bits on class‑2 points |
| the plane‑R² figures beside the `(faint)` threshold, above | a one‑off script, not a shipped tool: it re‑fits `render_green.green_summary()`'s own plane over each green's putting‑surface cells and reports 1 − SS_res/SS_tot. Pinned by `test_the_faint_mark_is_not_published_as_a_survey_noise_floor`, which re‑measures it |
| item 1 of "What this does and does not establish" (elevation) | `python3 tools/verify_elevation.py --all` — needs the network and `rasterio`. **Re‑measured 2026‑08‑05 from one run of that command that reached all 171 holes. The note inside that bullet records the figures it replaced and why they were bounds** |
| the before/after figures inside item 1 | one‑off measurements taken when those faults were fixed. They describe states of the code that no longer exist and **cannot** be reproduced from the corpus as it stands |

Every green card prints a dominant tilt to one decimal (`2.7%`), a `(faint)` mark where a single
plane is a poor description of that green and the card still names a side, and
15 cm contours, and all but one name a feed direction — micke‑grove 2 is flat enough that the plane
and the arrows disagree, so that card names none (see note 2).

**That `(faint)` sentence used to give the survey's own noise as the reason for the mark, and this
document's own tables contradict it.** The threshold behind the mark is 1.2% of tilt; the
worst tilt disagreement between two independent surveys of the same green, in the table below, is
**0.05 percentage points**, so the threshold sits **24×** above the largest disagreement ever
observed here, and the corpus's faintest printed green — 0.3% — is still 6× above it. The feed
direction is reproducible to **3.7°**, an eighth of the 45° sector a compass word names, and the
`clear`/`faint` mark itself never differed between passes. No green in this corpus has a plane fit
inside the survey noise, so "near this survey's limit" was not a caveat, it was a false one — and the
pocket book's guide card had turned it into advice, telling a junior to "trust the side less" on
exactly the greens where the side is best corroborated.

What the 1.2% threshold does track, and the reason it is well chosen and unchanged, is whether **one
plane is an adequate model** of the green. Fitting `render_green.green_summary()`'s own plane over
each green's putting surface and taking R² = 1 − SS_res/SS_tot: `clear` greens come out at p05 0.61
and a median of 0.90, `faint` greens at p05 0.02 and a median of 0.44. A faint green is not badly
measured — it is a green a single tilt describes badly, with tiers and hollows one word cannot carry.
The guide card now says so, and sends the reader to the arrows rather than away from the compass
word. The governing rule of this project is that it must never print a
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
of that green's interior cells**. 46 pass/green pairs were excluded on that basis; 33 greens had two
qualifying passes.

Which cells count as putting surface is decided **once, from the shipped surface**, and held fixed
for both passes. Each pass covers a green slightly differently and would otherwise classify slightly
different cells as too steep to putt, so the comparison would be measuring that reclassification
instead of the ground.

## Result

> Every figure below that comes from `cross_flight_check.py` was re‑measured on 2026‑08‑02, after two
> further defects were found in that tool. The first of the three, a grid‑orientation fault found
> 2026‑08‑01, is recorded last.
>
> **The vertical scale carried over between courses.** `check()` rebinds a course by dropping `config`,
> `geo` and `render_green` from `sys.modules` — but not `fetch_dem_hd`, which binds `config` and
> `DIR = config.COURSE_DIR` at module scope. So under `--all` every course after the first was gridded
> with the FIRST course's foot/metre scale. Five of the corpus's point clouds are US‑survey‑foot State
> Plane (0.3048) and six are metric (1.0), and the run starts on an ftUS one — so Philadelphia and the‑Reserve, both
> metric, had every tilt divided by 3.28. Philadelphia's five greens read 0.58 / 0.95 / 1.49 / 1.37 /
> 0.32 % where its own cards print 1.91 / 3.12 / 4.88 / 4.49 / 1.05 %, and two of its five
> `clear`/`faint` marks (holes 1 and 2) were pushed from `clear` to `faint`. Both passes were scaled wrong by the same factor, so the
> *conclusion* survived — but the previous version of this document printed the Philadelphia table
> straight out of that run, i.e. five numbers no card of that book prints.
>
> **That correction moved the noise floor the WRONG way, and this document now says so.** Differencing
> two correctly scaled metric surfaces yields larger centimetre figures than differencing two that were
> both shrunk 3.28×. RMS **0.56 cm** was published here; the honest number is **0.85 cm**, and the 15 cm
> contour interval is **18×** it rather than 27×. The claim still holds with a wide margin — it holds by
> less than was claimed.
>
> **The coverage gate was scored on a mirrored green.** `_cover` indexed a north‑up green mask
> (`render_green.poly_to_px`, row 0 = north) with a south‑up row index, so every pass was scored against
> the green flipped top‑to‑bottom. Over the‑Reserve's 26 pass/green pairs that moved coverage by up to
> 16.5 pp (hole 17: 67.6% read as 51.2%) and moved one pair across the 50% gate (hole 18: 61.6% read as
> 49.3%). The excluded‑pair count below therefore falls from 47 to **46**; no green gained a *second*
> qualifying pass, so n is unchanged at 33. This is the same north/south fault as the one below, in the
> same file, which had been fixed in `_summary` and never carried across to `_cover`.
>
> **And the first of the three.** `cross_flight_check.py` gridded each pass with
> `linspace(ymin, ymax, H)`, which puts row 0 at the SOUTH edge and samples bbox edges rather than cell
> centres — while the shipped surface, the green mask and the plane fit are all north‑up on cell centres.
> So the tool had been comparing a vertically mirrored surface, half a cell out, against the card's own
> conventions: over 90 greens that was a median 0.42 pp of tilt and 76° of aim away from what any card
> prints. Both passes were mirrored identically, so that conclusion survived unharmed too.
>
> The pattern across all three is worth stating plainly, because it is the reason none of them was
> caught by the agreement they were measuring: a fault applied EQUALLY to both passes cancels out of the
> comparison and leaves "the surveys agree" standing, while quietly detaching the numbers from the
> cards. Only checks against the shipped surface can see that class of fault, and the suite now has
> them.


**33 greens, each independently surveyed twice. Every pair agrees.**

| | worst observed |
|---|---|
| dominant tilt | **0.05 percentage points** |
| feed direction | **3.7°** |
| the `(faint)` mark (internally `clear` / `faint`) | never differed |

The strongest single case is Philadelphia Country Club, whose two passes are **100 days apart**
(2024‑12‑17 and 2025‑03‑27) and straddle a phased course restoration — the exact circumstance in
which a green *should* be caught changing. On the five greens both passes covered:

| hole | 2024‑12‑17 | 2025‑03‑27 | Δ tilt | Δ aim |
|---|---|---|---|---|
| 1 | 1.91% clear | 1.91% clear | 0.01 pp | 1.7° |
| 2 | 3.12% clear | 3.15% clear | 0.03 pp | 0.2° |
| 6 | 4.88% clear | 4.85% clear | 0.03 pp | 0.5° |
| 7 | 4.49% clear | 4.52% clear | 0.03 pp | 0.3° |
| 8 | 1.05% faint | 1.08% faint | 0.03 pp | 0.6° |

At the raw point level those two passes agree to a **median 0.03 ft (0.4 in), 95th percentile
0.13 ft**, over ~11,000 ground returns per green.

Six of the 33 pairs agreed physically but landed either side of a printed digit — 2.05% against
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
| 95th percentile | 1.86 cm |
| worst single cell | 6.27 cm |

The 15 cm contour interval is therefore about **18× the noise floor** of the surface it is drawn from.
The claim holds with a wide margin. Averaging 9.6–27.9 ground returns per square metre over these 33 greens (4.7–27.9 corpus‑wide) and then smoothing
over ~1.20 m (a Gaussian of sigma 3 pixels at the 0.4 m sampling above) beats single-pulse accuracy by
a large factor, which is why the relative figure is an order of magnitude better than the absolute spec.

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

That is the same order of answer the date split gave (RMS 0.85 cm) from a completely different decomposition of
the data — two independent flight lines of the same green, and two independent surveys months apart,
agree to about a centimetre either way. So the overlap points stay: dropping them would halve bay-view's
ground density in exchange for nothing measurable.

`withheld` and `synthetic` are a different matter and are now filtered out in `fetch_dem_hd.py`. Those
bits mark points the producer disowns — measurements it says not to use, and points computed rather than
observed — and neither belongs under a printed slope read. Scanning every one of the **71 of the 72 LAZ tiles in the corpus, 582,510,577 class‑2 ground returns** (callippe's `w6159n2046`, added later and overlapping no green, is not among them), finds **zero** of
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
   a corpus-median 82% of which is not green, against a median over an axis-aligned box at the tee that
   a mapped tee covers about 13% of. Those two region errors pointed opposite ways and largely cancelled
   in the printed *change*, which is why neither was visible in it: correcting only the green end would
   have shifted every height in the book by +0.45 ft. Corrected together they moved 102 of the then-177
   printed integers, made 6 heights appear and 2 disappear at the 3 ft floor, flipped no above/below
   word on any card that prints one, and took this tool's agreement with the independent DEM from a
   median 0.80 ft to 0.09 ft (a matched pair of `verify_elevation.py` figures from the era *before* its
   georeference fix, so neither is comparable with the corrected figures below — see the note in the
   first bullet). Both passes come
   from the same USGS program, sensor class and processing chain, so a *systematic* bias would be
   present in both and invisible to the comparisons above. Two kinds of systematic bias are worth
   separating, because only one of them stays open:
   - **Our own processing** — a vertical unit read wrong, a CRS or grid misalignment, a geoid/ellipsoid
     mixup. This IS bounded, by checking the *absolute* elevation of our surfaces against the 3DEP
     seamless DEM, a separately produced raster this project does not build — sampled over the **same
     green polygon** the pipeline measures, so the comparison is not dominated by a region mismatch.
     Over all 171 measured holes on the 11 courses — one run of `verify_elevation.py --all` on
     2026‑08‑05, which reached every one of them — the two agree to a **worst per‑course median of
     0.045 m** and a **worst single green of 0.312 m** (Merion); the printed tee‑to‑green *change*
     agrees to a **worst single hole of 2.46 ft** (Philadelphia 5), with per‑course medians from 0.03
     to 0.62 ft. At a *mapped* tee this tool reads the whole OSM tee pad where the pipeline reads the
     pad inside a 15 m window, so at those tees the change figures include a region difference that
     inflates them — they are upper bounds there, and the tool records why it is not re‑pointed at the
     pipeline's own choice. A corpus median and a median of per‑course medians are different statistics,
     and this bullet used to publish one figure for the pair: the **median of those eleven course
     medians is 0.069 ft**, the **median over all 171 holes is 0.067 ft**, and the mean **0.201 ft** —
     the tool prints all three, named. **2** of the 171 exceed 2 ft and **none** exceeds 3 ft. A
     US‑survey‑foot cloud read as metres would show tens of metres; a geoid/ellipsoid confusion about
     30 m in California. Neither is present. (This project has shipped a foot/metre fault before — it
     put 74 of 175 holes' elevations out by a median 298 ft — so the check is not hypothetical.)

     > **What the figures above replaced, and why they were quarantined for three days.** Until
     > 2026‑08‑05 this bullet published 0.10 m, 0.35 m and 3.14 ft, flagged as upper bounds awaiting
     > re‑measurement. They were produced by
     > `tools/verify_elevation.py` before 2026‑08‑02, when its patch fetcher was found to discard the
     > returned GeoTIFF's own georeference: it rebuilt its pixel centres from the bbox it *requested*,
     > while the ImageServer had **expanded** that bbox to match the square image size it was asked for.
     > So every sample sat at the wrong place on the ground and reached past the polygon it was meant to
     > be confined to — the short axis was expanded by more than 1.05× on 185 of the corpus's 198 greens,
     > worst 2.712× (castlewood‑valley 14), and on monarch‑bay 3 the mask took 2889 cells where the
     > returned georeference puts 1945 inside the green. That sample pulled in collar the polygon
     > excludes, which *inflates* the disagreement, so the direction was known and the size was not.
     >
     > The re‑run bears out the factor of two that the one course re‑measured by hand predicted —
     > merion's absolute‑offset median **0.1019 → 0.0522 m**, worst green **0.515 → 0.436 m**, both
     > one‑off measurements of a code state that no longer exists. Corpus‑wide the worst single green
     > went **0.47 → 0.312 m** and the worst per‑course median **0.10 → 0.045 m**. So the three rival
     > pre‑fix figures for one quantity that this note used to flag as never reconciled — 0.35 m here,
     > 0.47 m in the tool's own docstring, and merion's own 0.515 m — are all superseded by the single
     > run above. Why they disagreed was never established, and it is recorded because it is the reason
     > this bullet was quarantined rather than corrected in place. The tee‑to‑green *change* figures
     > carried the same fault at **both** ends, where it partly cancels, so their direction was never
     > known either; they are re‑measured above from the same run.
     >
     > The service that answered HTTP 502 from the machine where the fix was made answered on
     > 2026‑08‑05, so nothing here is a substituted guess — inventing one would be exactly the fault
     > this document exists to guard against. Re‑run `python3 tools/verify_elevation.py --all` and the
     > figures above are what it prints; `test_legal_09s_elevation_bound_is_what_the_elevation_service_gives_today`
     > runs that command and compares this bullet against it, which is the only check that can see this
     > record and the tool's own docstring go stale independently — as they just did. The *conclusion* —
     > that no tens‑of‑metres unit fault and no ~30 m geoid confusion is present — was never in doubt
     > either way: the correction moves centimetres, and those faults move tens of metres.
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
