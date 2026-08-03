# The Horizontal Earth Model — and the Four Cards It Rounds the Other Way

Every distance this project prints is computed on a simple local flat‑earth model, and that model is
**not** the ellipsoid the source data is referenced to. The gap is small, it is measured, and on four
specific cards it is large enough to move a printed integer. This record states the model, the size of
the offset, and the name of every card the offset moves — because a reader holding one of those cards
cannot read the source code, and until this record existed the disclosure lived nowhere else.

> **Not legal advice.** Like the rest of this folder, this is a record of what the build actually
> does, prepared so a claim about a printed number can be traced to a measurement.

## The model

Two constants, used for every horizontal length in the pipeline:

| | metres per degree |
|---|---|
| latitude | `111320.0` |
| longitude | `111320.0 × cos(latitude)` |

That is a sphere of radius 6 378 166 m. Everything the book prints that has a length in it rides on
those two numbers: green **depth** and width, the grey **5‑yd ladder** and the printed 5‑yd scale bar,
green **tilt %** (a rise over one of these runs), the hole map's **yardage ticks** and the **carry**
distances measured off them, and the **Rule 4.3 print scale** the pocket edition claims to conform to.

The green surfaces themselves are sampled on a grid that is uniform in longitude and latitude
(`fetch_dem_hd.py`: `lon_g = xmin + us*(xmax-xmin)`), so a green's array is a plate‑carrée grid and
those two constants are exactly the scales that convert it to ground.

## The offset, measured

At **37.8°N** — the middle of this corpus — the true local WGS84 scales are **110992.70 m per degree
of latitude** and **88070.46 m per degree of longitude**, so this model runs **+0.295% long in
latitude** and **−0.125% short in longitude**. (Local scales, not a one‑degree geodesic: the meridian
radius of curvature *M*, and the parallel arc *N*·cos φ, which is what a grid uniform in degrees is
actually spaced by. Computed with `pyproj`'s own WGS84 ellipsoid.)

Any single printed length therefore sits somewhere inside a band from −0.125% to +0.295% of the truth,
depending on which way it runs across the ground. Two consequences of that are worth separating,
because only the first one reaches a printed integer.

## What it costs the printed green depth

Green depth is the one **length** the book derives from these constants and prints as a whole number.
Recomputing all 198 printed depths on the true local scales — no bbox arithmetic, no raster, the same
front‑to‑back line of play the card measures — the printed figure is out by a **median 0.040 yd, p95
0.094 yd and worst 0.111 yd** (−0.138% to +0.297% relative). The true local scales reproduce the WGS84
**geodesic** length of that very line to 1.5 × 10⁻⁵ yd on all 198 greens, so this is the model's error
and not an artifact of how it was measured.

A printed integer already carries ±0.5 yd of rounding, so on 194 of the 198 cards this changes nothing
a reader could act on. On **four** it puts the printed integer on the wrong side of the half yard —
each of these four prints **one yard deeper** than the ground:

| Card | Prints | Ground length |
|---|---|---|
| `copper-valley-golf-club` hole 16 | 37 yd | 36.489 yd |
| `micke-grove-golf-links` hole 13 | 20 yd | 19.450 yd |
| `monarch-bay-golf-club` hole 1 | 35 yd | 34.451 yd |
| `the-reserve-at-spanos-park` hole 7 | 33 yd | 32.438 yd |

`monarch-bay-golf-club` hole 1 is one of the greens that falls back to the 1 m seamless DEM; the other
three are 0.4 m LiDAR. The model error is the same either way — it is not a data‑quality difference.

**This list is re‑measured, not transcribed.**
`tests/test_phase1_regressions.py::test_the_earth_model_and_the_cards_it_rounds_the_other_way_reach_the_READER`
recomputes every figure above off the built corpus and fails if a card is named that is no longer on
the boundary, or is on the boundary and not named. If a green is re‑traced, or the earth model is ever
migrated, this table cannot go quietly stale.

## What else rides on it, and why nothing else is named

The same ±0.3% applies to every other printed length, but none of them turns it into a visible number:

- **The 5‑yd scale bar**: 0.3% of 5 yd is 0.015 yd, which at the printed 0.36 in : 5 yd is 0.001 in on
  paper — below what a home printer can render.
- **The Rule 4.3 print scale**: the ground scale `tools/check_scale.py` divides by moves by a median
  **−0.083%** (−0.089% to −0.058%) across the 198 greens if the model is corrected. The worst gated
  green reads 0.3602 in : 5 yd against the 0.375 in cap — a **4.0% margin** — so a shift two orders of
  magnitude smaller than the margin cannot take a conforming green over the cap. See
  `06_RULE_4.3_CONFORMANCE.md`.
- **Green tilt %** is a rise over one of these runs, so it is off by the same relative amount: a
  printed 2.3% would be 2.293%. That is under the printed resolution of 0.1 pp for every green in the
  corpus, though a handful sit close enough to a rounding boundary that a coherent migration would move
  them.
- **Hole‑map yardage ticks and carries** are off by at most 0.30% of the radius — under 1 yd out to the
  300 yd ticks the book prints, against club gaps of 10–15 yd, and the labels are integers. `geo.py`
  holds the per‑radius measurement.

## Why it is not corrected

Recorded here so the decision is auditable rather than invisible:

1. `111320.0` is written as a literal in **ten files** and imported from none of them: `geo.py`
   defines it, and **nine more re-declare it** — `fetch_dem.py`, `fetch_dem_hd.py`,
   `fetch_hole_elev.py`, `fetch_osm.py`, `fetch_trees.py`, `render_green.py`, `render_hole.py`,
   `tools/check_scale.py`, `tools/verify_elevation.py`. (`fetch_osm.py`'s two copies are inline inside
   a distance calculation and are not called `R_LAT`, so an audit that greps for the name finds eight.)
   It is not a one‑line change.
2. `tools/check_scale.py` re‑derives the constant to gate the Rule 4.3 print scale. A renderer that
   moved while the gate did not would stop being measured on the metric that sized it.
3. Correcting it for **depth alone** would print one green's depth on the ellipsoid while the same
   card's tilt %, its 5‑yd bar, its Rule 4.3 sizing, its hole‑map ticks and its carries stayed on the
   sphere — two figures of the Earth on one card, which is worse than one consistent approximation.
4. A coherent migration moves printed output on every book and therefore wants its own change, its own
   rebuild of all 15 books and its own re‑reading of the scale gate. `geo.py` carries the engineering
   detail of what it would move.

The judgement is that a bounded, disclosed 0.3% is safer than a partial correction — but the judgement
was only ever defensible **with** the disclosure, and the disclosure is this record.

## What a reader should do with this

Treat a printed green depth as **±1 yd**, which is what an integer rounded from a 0.3% model is worth.
On the four cards named above, read the printed depth as the shallower neighbour if you are clubbing
for a back pin. Nothing here changes a **read** — break comes from relative height inside one green,
and a uniform 0.3% horizontal stretch does not move an arrow, a contour or a tier. See
`09_GREEN_SURFACE_REPEATABILITY.md` for what the slope numbers are worth, and note that its
geoid/ellipsoid paragraph is about the **vertical** datum; this record is the horizontal one.

## How to re‑measure any figure above

```
python3 -m pytest tests/test_phase1_regressions.py -k earth_model -q
python3 -m pytest tests/test_phase1_regressions.py -k exactness_is_measured_against -q
python3 tools/check_scale.py
```

The first re‑derives the scales, the offsets, the residual and the four cards from the built corpus and
`pyproj`; the second pins the same arithmetic where the constant lives; the third re‑measures the Rule
4.3 margin quoted above.
