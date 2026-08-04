# The Horizontal Earth Model — and the Four Cards It Once Rounded the Other Way

Every distance this project prints is computed by multiplying a difference of degrees by a local ground
scale. This record states which scales those are, what the **previous** ones cost, and the name of every
card whose printed number changed when they were corrected — because a reader holding one of those cards
cannot read the source code, and until this record existed the disclosure lived nowhere else.

> **Not legal advice.** Like the rest of this folder, this is a record of what the build actually
> does, prepared so a claim about a printed number can be traced to a measurement.

## The model the build uses now

Two functions, `geo.mlat(latitude)` and `geo.mlon(latitude)`, used for every horizontal length in the
pipeline. They are the **true local WGS84 ground scales** — the meridian radius of curvature *M* and the
parallel arc *N*·cos φ — computed from `pyproj`'s own WGS84 ellipsoid parameters rather than
transcribed:

| | metres per degree at 37.8° N |
|---|---|
| latitude (`geo.mlat`) | 110 992.6954 |
| longitude (`geo.mlon`) | 88 070.4622 |

Everything the book prints that has a length in it rides on those two: green **depth** and width, the
grey **5‑yd ladder** and the printed 5‑yd scale bar, green **tilt %** (a rise over one of these runs),
the hole map's **yardage ticks** and the **carry** distances measured off them, and the **Rule 4.3 print
scale** the pocket edition claims to conform to.

They are the right two quantities because of how the data is sampled. The green surfaces are built on a
grid uniform in longitude and latitude (`fetch_dem_hd.py`: `lon_g = xmin + us*(xmax-xmin)`), so a green's
array is a plate‑carrée grid, and the local scales of such a grid are exactly *M* and *N*·cos φ. They are
**local scales, not a one‑degree geodesic**: a geodesic across a whole degree cuts inside the parallel
and reads 88 070.04 against 88 070.46 at 37.8° N.

There is exactly **one** copy of them, in `geo.py`. Ten files used to carry their own.

## The model it replaced, and what that cost

The **retired model used 111320.0** m per degree of latitude and 111320.0 × cos(latitude) per degree
of longitude — a sphere of radius 6 378 166 m. At **37.8 deg N**, the middle of this corpus, the true
local WGS84 scales are **110992.70 m per degree of latitude** and **88070.46 m per degree of
longitude**, so that model ran **+0.295% long in latitude** and **−0.125% short in longitude**. Those two
figures do not even agree with each other: the retired pair was internally inconsistent by 0.42
percentage points, which is larger than the 0.84% pixel anisotropy the green card had just been
corrected for.

Green depth is the one **length** the book derives from these scales and prints as a whole number.
Recomputed on the true scales, the retired figure was out by a median of 0.040 yd, a p95 of 0.094 yd
and a worst case of 0.111 yd (−0.138% to +0.297% relative), and on **four** cards that put the printed integer on the wrong
side of the half yard — each printed **one yard deeper** than the ground:

| Card | Printed before | Prints now | Ground length |
|---|---|---|---|
| `copper-valley-golf-club` hole 16 | 37 yd | 36 yd | 36.489 yd |
| `micke-grove-golf-links` hole 13 | 20 yd | 19 yd | 19.450 yd |
| `monarch-bay-golf-club` hole 1 | 35 yd | 34 yd | 34.451 yd |
| `the-reserve-at-spanos-park` hole 7 | 33 yd | 32 yd | 32.438 yd |

Two of those four — `copper-valley` 16 and `micke-grove` 13 — had been moved the **wrong way** by an
earlier partial fix, which corrected the raster's pixel anisotropy while leaving the datum wrong.
`monarch-bay-golf-club` hole 1 is one of the greens that falls back to the 1 m seamless DEM; the other
three are 0.4 m LiDAR. The model error was the same either way — it was not a data‑quality difference.

**This list is re‑measured, not transcribed.**
`tests/test_phase1_regressions.py::test_the_earth_model_and_the_cards_it_rounds_the_other_way_reach_the_READER`
re-derives every figure above off the built corpus — including re‑running the engine's own depth on the
retired constant this record names — and fails if a card is listed that did not move, or moved and is not
listed.

## What residual is left

Not zero, and the size is measured. The remaining difference is no longer a datum error at all: it is
only the difference between a plate‑carrée cell grid and a true geodesic across the ~30 yards of one
green. Over all 198 printed depths the **remaining residual is a median 0.0000006 yd, p95 0.0000052 yd
and worst 0.0000148 yd** — under two hundredths of a millimetre, against a printed integer that carries ±0.5 yd of rounding.
**No printed depth now rounds to the wrong side of a half yard**, and the test above asserts that too.

The hole map gained more than the green card did. A "150 to the green" tick is not drawn at a mapped
point: `render_hole.py` places it where the drawn centreline **crosses the circle of that radius about
the green centroid**. So the error a reader can feel at that tick is the printed radius against the
**true WGS84 geodesic** from the green centroid to the point the tick landed on — measured below at
every one of the **861** radius crossings the 198 drawn centrelines have, and over all **589**
centreline vertices for the last row:

| Tick radius | Retired model, worst | Now, worst |
|---|---|---|
| 100 yd tick | 0.2962 yd | 0.0013 yd |
| 150 yd tick | 0.4426 yd | 0.0018 yd |
| 200 yd tick | 0.5931 yd | 0.0021 yd |
| 250 yd tick | 0.7421 yd | 0.0022 yd |
| 300 yd tick | 0.8891 yd | 0.0019 yd |
| any centreline vertex, out to 595.8 yd | 1.5502 yd | 0.0023 yd |

**This table was wrong in both columns until 2026-08-04, and the correction is recorded rather than
quietly applied.** It read `~100 yd | 0.43 | 0.0003`, `~200 | 0.73 | 0.0013`, `~300 | 0.99 | 0.0027`,
`furthest vertex (595 yd) | 1.55 | 0.0077`, and nothing re-derived a single cell of it.

The retired column was **arithmetically impossible**. Because the retired pair scaled latitude and
longitude by one constant and its cosine, any length it measured was out by a fraction lying between its
two axis errors: the retired pair's **worst relative offset over these 589 vertices is +0.2975%**, and
it is **at most +0.3008% at the corpus's southernmost hole (37.4529 deg N)** — that ceiling is
`111320 / geo.mlat`. A 100 yd radius therefore cannot be out by more than 0.30 yd, 200 by more than
0.60, or 300 by more than 0.90 — and 0.43, 0.73 and 0.99 each exceed the bound for their row. Those
figures reproduce as the worst error anywhere in the 50-yard **band above** each tick, i.e. "between
this tick and the next", printed in a column headed *Tick radius*. A reader holding a card with a 100 yd
tick was told his was out by up to 0.43 yd; the true worst at that tick was 0.2962 yd.

The "now" column was measured in a frame the engine does not use. Its published values grow
quadratically in the radius, which a residual measured in `render_hole`'s frame does not — the engine
takes both scales at the **centroid of the drawn line**, so the residual is bounded by that line's own
extent and stops growing. The published column reproduces only with the scales anchored at the **green**
(0.0004 / 0.0012 / 0.0025 / 0.0077), which nothing in the pipeline does. The effect was to understate
the residual at the 100 yd row by about 4x and overstate the headline worst by 3x. Every one of those
figures is a millimetre or two against a printed integer, which is the point: nobody could have caught
it by reading a card, and an unmeasured figure in a legal record is wrong at whatever size the
arithmetic happens to make it.

`tests/test_phase1_regressions.py::test_the_hole_map_tick_error_table_is_measured_at_the_ticks_it_is_printed_against`
now re-derives every cell above off the built corpus, checks that `geo.py`'s note quotes the same
figures, and refuses any retired-model figure that exceeds the relative-offset bound for its own radius.

## The Rule 4.3 print scale

`tools/check_scale.py` divides the drawn size of each green by that same ground scale to report "inches
per 5 yd", and `render_green.py` multiplies by it to **size** the drawing in the first place
(`legal_kf = 0.36 * px_m / 4.572`). Both sides therefore had to move together, and did — the gate now
imports the scales from `geo.py` instead of re‑deriving them, so the renderer can never be measured
against a ruler it is not built on.

Measured across the 198 greens, the correction moves that ground scale by a **median −0.083%** (−0.089%
to −0.058%), which shifts the reported figure by under **+0.09%**. The worst gated green reads **0.3601
in : 5 yd** against the 0.375 in cap — a **4.0% margin** — so the shift is more than forty times smaller
than the headroom, and 26 of 198 greens changed printed size by 0.001–0.003 in. No green moved from
inside the cap to outside it, and the number of greens sitting at the cap is unchanged at 26. See
`06_RULE_4.3_CONFORMANCE.md`.

## Why it was corrected, and why it took three attempts

Recorded here so the history is auditable rather than invisible:

1. `111320.0` was written as a literal in **ten files** and imported from none of them: `geo.py` defined
   it and **nine more re‑declared it** — `fetch_dem.py`, `fetch_dem_hd.py`, `fetch_hole_elev.py`,
   `fetch_osm.py`, `fetch_trees.py`, `render_green.py`, `render_hole.py`, `tools/check_scale.py`,
   `tools/verify_elevation.py`. (`fetch_osm.py`'s two copies were inline inside a distance calculation
   and not called `R_LAT`, so an audit that grepped for the name found eight.) There was no single knob
   to turn, and that was twice taken as a reason to defer rather than as a reason to build one.
2. The suite's own ground truth for green depth was a great circle on **the same sphere**, so a test
   asserting all 198 printed depths could not see that four of them were wrong. The reference was the
   assumption. It is now the WGS84 geodesic.
3. A partial fix is worse than none: correcting depth alone would have printed one green's depth on the
   ellipsoid while the same card's tilt %, its 5‑yd bar, its Rule 4.3 sizing, its hole‑map ticks and its
   carries stayed on the sphere — two figures of the Earth on one card.

So it was done as one change: one home for the scales, every module importing them, the print‑scale gate
migrated in the same commit as the renderer it gates, the suite's ground truth re‑based on the true
geodesic, and all 15 books rebuilt.

## What a reader should do with this

Treat a printed green depth as **±0.5 yd**, which is what an integer rounded from a measured length is
worth — the rounding is now the dominant term, not the earth model. Nothing here changes a **read**:
break comes from relative height inside one green, and a uniform horizontal scale change does not move an
arrow, a contour or a tier. If you are holding a book printed before this correction, the four cards
named above print one yard deeper than the ground. See `09_GREEN_SURFACE_REPEATABILITY.md` for what the
slope numbers are worth, and note that its geoid/ellipsoid paragraph is about the **vertical** datum;
this record is the horizontal one.

## How to re‑measure any figure above

```
python3 -m pytest tests/test_phase1_regressions.py -k earth_model -q
python3 -m pytest tests/test_phase1_regressions.py -k exactness_is_measured_against -q
python3 -m pytest tests/test_phase1_regressions.py -k re_declares -q
python3 tools/check_scale.py
```

The first re‑derives the scales, the retired model's offset, the residual and the four cards from the
built corpus and `pyproj`; the second pins the same arithmetic where the scales live; the third asserts
no module has grown its own copy again; the fourth re‑measures the Rule 4.3 margin quoted above.
