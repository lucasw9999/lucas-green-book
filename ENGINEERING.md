# How a Lucas Green Book is made

A green book is the small booklet tour players carry: for every hole, a map of the green showing which
way it slopes and how a putt will break, plus the hole itself with its yardages and hazards.

This page explains how these are built, what every number on a card comes from, and which parts were
hard. It is written for three kinds of reader: someone assessing the engineering, someone at a course
who wants to know we did not take anything of theirs, and a golfer who is simply curious.

It is a description, not a recipe. The reasoning is here; the parameters, thresholds and rendering
logic are not.

The engine is software I wrote with AI as a coding assistant. Every slope, contour and arrow is
computed from the LiDAR by ordinary arithmetic — the same numbers every time.

---

## The problem

A green looks flat. It is not. A putting surface that reads as level to the eye can fall a foot from
back to front across several distinct tiers, and the difference between reading that correctly and
guessing is most of putting.

So the question is: **can you tell a player how a green slopes, accurately, without ever setting foot
on it?**

That constraint is the whole project. Every book here is built remotely, from data anyone can
download, without entering a course or asking anyone for anything. It is what keeps the work
independent — and it is also what makes it hard, because you inherit whatever the public data happens
to be rather than measuring what you want.

---

## Where every number comes from

There are exactly four inputs. Nothing else contributes anything a card prints.

| What | Source | Status |
|---|---|---|
| Hole and green **shapes** | OpenStreetMap contributors | ODbL 1.0 — attributed in every book |
| **Elevation** behind slope, contours and break arrows | USGS 3DEP LiDAR point clouds & elevation service | U.S. Government public domain |
| **Par, yardage, handicap, ratings** | Published scorecards & USGA NCRDB | Facts — not copyrightable (*Feist*, 1991) |
| **Aerial reference**, where shape data has a gap | USDA NAIP imagery | U.S. Government public domain |

Slope, contours, break arrows and elevation change are **computed here** from public-domain
elevation. They are not copied, traced, or derived from anyone's product.

**No commercial green-reading product's data, imagery, artwork, symbol set, page layout or trade dress
was used, copied, referenced or reverse-engineered.** No Google, Apple, Esri, Maxar or Bing imagery
appears in any book. The full source-by-source record, with each licence and how it is honoured, is in
[`legal/`](legal/).

---

## The parts that were hard

**Turning a point cloud into a surface.** Airborne LiDAR does not arrive as a grid of ground heights.
It arrives as millions of individual returns — some off the ground, many off grass, trees, carts,
people, water. You need the ground, on a green, at a resolution fine enough that a tier a foot across
still exists after gridding. Where the returns are too sparse to support that, the honest answer is
to fall back to a coarser public elevation source and *record that you did*, per green, rather than
quietly averaging the two.

**Absolute accuracy is the wrong thing to worry about.** Published vertical accuracy for airborne
surveys sounds alarming next to a contour interval measured in centimetres. It turns out not to
matter: a datum offset moves an entire green up or down together, and break depends only on
*relative* height *inside* one green. What actually limits a read is spatial — how much fine detail
survives gridding and smoothing — and that is a different quantity that has to be reasoned about
separately. Getting that distinction right changed what the maps could honestly claim.

**Distance on a curved earth.** Every printed number — green depth, the yardage ladder, carry
distances, the scale bar, tilt percentage — is ultimately a difference between two coordinates
multiplied by a ground scale. Get that scale slightly wrong and nothing crashes; every distance in
the book is simply a little off, consistently, in a way no test that compares the book to itself will
ever catch. Making distances agree with the actual ellipsoidal shape of the earth rather than a
convenient spherical approximation touched every figure on every card.

**Rule 4.3 applies to the paper, not the file.** The Rules of Golf limit the size and scale of
green-reading material. The obvious way to check that is to inspect the drawing instructions — and it
is the wrong way, because a stylesheet can override them and a green can print larger than its markup
claims. So the check lays each book out in a real browser under print conditions and measures the
green as drawn, and separately measures the printed artifact itself. The claim is about what a player
carries in a pocket, so that is what gets measured.

**Two surveys of the same green should say the same thing.** Some courses were flown across more than
one date, which means a green can be built from a blend of passes. Harmless if the passes agree —
and if the ground changed between them, it is a surface spliced from two different greens. So passes
are separated and compared: build the read twice, independently, and see whether they match. This
doubles as the only real measure of how repeatable these surfaces are, which is the sort of thing you
want to know before handing a book to anyone who is going to trust it.

**Knowing when to print nothing.** One course in this project was rebuilt after the last public
survey. Its greens are physically different from anything in the data. The book for it prints
verified yardages and **deliberately blank greens**, marked personal-use, rather than a slope map
that would be confidently wrong. There is code whose only job is to answer *"may this book be handed
out?"* — and the published provenance record is generated from the same function, so the record and
the artifact cannot disagree.

---

## Engineering Case Studies

### 1. Geodesy on the Fairway: Why the Earth is Not a Sphere

Every distance a yardage book prints begins as a pair of geographic coordinates $(\phi, \lambda)$ on the earth.
The common shortcut in hobby cartography is to treat the earth as a sphere of radius $R = 6,378,166\text{ m}$,
converting degrees of latitude and longitude with fixed multipliers ($111,320\text{ m/deg}$ and $111,320 \times \cos\phi$).

On a golf course, that shortcut breaks down. At $37.8^\circ\text{ N}$ (the latitude of many California courses),
the difference between the spherical approximation and the true WGS84 reference ellipsoid is approximately
**$0.33\text{ m}$ per $100\text{ m}$ of ground distance**.

Across a 35-yard putting green, a 30 cm distortion shifts depth contours and can flip whether a green depth
rounds up or down. Across a 450-yard hole, it introduces multiple yards of error into fairway runout markers and
hazard carries. Furthermore, Rule 4.3 limits green illustrations to a strict scale ceiling of 3/8 inch to 5 yards
(1:480); a scale derived from an approximate earth model introduces systematic bias into that compliance claim.

To eliminate this, Lucas Green Book computes all horizontal distances using the **exact local WGS84 ground scales**:
- **Meridian radius of curvature (North–South):**
  $$M(\phi) = \frac{a(1 - e^2)}{(1 - e^2 \sin^2\phi)^{3/2}}$$
- **Parallel radius of curvature (East–West):**
  $$N(\phi)\cos\phi = \frac{a \cos\phi}{\sqrt{1 - e^2 \sin^2\phi}}$$
where $a = 6,378,137.0\text{ m}$ and $e^2 \approx 0.00669437999014$ from the WGS84 ellipsoid definition.

Because airborne LiDAR surfaces are sampled on plate-carrée latitude/longitude grids, scaling coordinate differences
by $(M(\phi), N(\phi)\cos\phi)$ yields exact metric dimensions that match on-course laser rangefinder measurements.

---

### 2. Topological Dissection of Double Greens

Certain historic and modern courses feature **double greens** — a single massive putting surface shared by
two distinct holes (for example, holes 10 and 17 at Wailea Emerald, a continuous $\approx 1,260\text{ m}^2$
putting surface fronting a lake).

A naive elevation plane fitted across the entire double green produces an absurd result: the fitted plane is
dominated by the elevation step *between* the two lobes (across the central connecting ridge), yielding a tilt
vector and fall line that belongs to neither hole. A golfer on hole 10 would be shown break arrows pointing
away from them when the actual putting surface feeds toward the front.

Rather than manually drawing artificial split lines, the engine solves this topologically:
1. The combined putting surface mask is rasterized at high resolution ($0.15\text{ m}$ grid).
2. We compute the Euclidean distance transform across the interior of the polygon.
3. A topological neck-finding algorithm traces component mergers under decreasing distance thresholds, locating
   the exact geographic saddle point where the two lobes join (a narrow $4.1\text{ m}$ throat).
4. The transitional neck band — where the surface is narrower than twice the throat width — is identified.
   Elevation analysis confirms this band represents the inter-hole transition ($7.1^\circ$ median slope, compared
   to $2.6^\circ$–$2.9^\circ$ within the actual putting lobes).
5. The transitional neck is excluded, and the surface is cleanly segmented into two independent topological lobes.
6. Each lobe is bound to its respective hole by line-of-play proximity and pin placement.

Each card receives an honest, independent planar read and contour map representing only the putting surface
that hole actually plays, without arbitrary manual intervention.

---

### 3. Data Honesty: When Refusing to Print is the Only Right Answer

The cardinal build rule of this project is:
> **Never print a number the data does not support, and never omit a hazard a golfer can reach.**

In golf cartography, printing an inaccurate number is far more dangerous than leaving a blank. A junior golfer
relies on the booklet to choose a club over a forced carry; if the book shows open ground where a newly dug
bunker sits, or shows a false break because the survey predated a green reconstruction, the player pays the penalty.

The worked example is **Poppy Ridge Golf Course**. The course underwent a complete architectural renovation in
2025 by architect Jay Blasi, altering greens, corridors, and bunkering. However, the latest available public-domain
USGS 3DEP LiDAR survey of that property was flown prior to the renovation.

A naive automated build would process the pre-2025 elevation data and generate crisp, attractive slope maps —
which would be confidently, dangerously wrong on every green.

Our pipeline refused to do that. The engine was put into **yardage mode**: it verified tee-to-green corridor lengths,
drew known fairways and hazards, and printed **deliberately blank greens** with an explicit notice explaining
why slope data was withheld. The book was designated Personal Use Only and subsequently parked from distribution
until a fresh public-domain survey is flown.

A system that knows when to say *"no"* is the only kind of system whose *"yes"* can be trusted.

---

### 4. Anti-Vacuous Verification Floors

The subtlest and most dangerous bug in automated spatial verification is the **vacuous pass** — a test or gate
that reports success because it examined zero items.

Consider a tool that checks whether any green in the corpus exceeds Rule 4.3's 1:480 scale ceiling. If a directory
path changes, or if an argument resolves to an empty course list, a naive loop:
```python
failures = [green for green in load_greens() if green.scale > CAP]
assert len(failures) == 0
```
will find 0 failures, exit with code 0, and display a reassuring green checkmark — having inspected nothing at all.

To eliminate this failure mode, every verification tool and test in the project enforces an **anti-vacuous floor**:
- Every check must assert a minimum inspected population (`assert len(inspected) >= 15`).
- Multi-survey repeatability checks must assert that candidate flight passes were actually partitioned and compared.
- Verification gates must prove discrimination by demonstrating that synthetic or historical defects are reliably caught.

A guard that cannot distinguish between *"no defects found"* and *"looked at zero data"* is worse than no guard at all.

---

## How it is kept honest

The governing rule is enforced by automated architecture rather than good intentions:

- **The records are generated, not written.** The provenance record and the legal disclaimer text
  printed in the books are derived directly from the built artifacts. A legal record that can drift
  from what was actually printed is worse than none.
- **Surfaces are self-identifying.** A green surface is two files that only mean anything together —
  an elevation grid and the metadata extent that places it on the earth. Each sidecar records a
  cryptographic SHA-256 digest of the array committed beside it. The reader strictly refuses a mismatched
  pair, preventing an interrupted build from pairing a new elevation grid with a previous extent.
- **Gates fail closed.** Where data is sparse, uncorroborated, or ambiguous, the pipeline halts or
  withholds the read.

---

## Four excerpt modules, published to be read

These are **excerpts, published to be read.** They reference modules that are not published, so they
will not run as they stand — that is deliberate, not an oversight. They are here because they illustrate
how the project enforces engineering discipline:

- **[`distribution.py`](distribution.py)** — the single answer to *"may this book be handed out?"*,
  written to fail closed, with the reasoning for each refusal in the code.
- **[`surface_io.py`](surface_io.py)** — the rule for committing a green surface to disk so that both
  halves land or neither does, and so an interrupted write is detected rather than measured through.
- **[`fetch_lidar.py`](fetch_lidar.py)** — LiDAR tile discovery against a government service that
  rate-limits and has outages. Tells apart a busy service, a valid reply, and an empty footprint query.
- **[`fetch_lidar_alameda.py`](fetch_lidar_alameda.py)** — a decoder for one county whose tiles are
  named in a specialized local projection, demonstrating how open geospatial data is handled in practice.

---

## What is published here, and what is not

**Published:** this page, the four excerpt modules above, and the complete [`legal/`](legal/) provenance record.

**Not published:** the green-reading and rendering logic, the hole corridor algorithms, the card
composition and layout engine, the verification test suite, and the per-course data caches.

That is a deliberate, permanent boundary. The purpose of this repository is to let anyone verify
where our data comes from, how our obligations are met, and how the engineering is kept honest — not
to publish a turn-key reproduction of our engine.

---

## Accuracy and the rules

Green maps show general tilt and tiers, not exact break. **Always trust your own read.** The books
are *designed* to fall within Rule 4.3 size and scale limits, but conformance is a Committee‑level,
per‑competition decision — confirm before playing in an event.

## Getting one, or getting yours removed

You can request a book for your course at
**[lucasgreenbook.org/request](https://lucasgreenbook.org/request)**. For a club, a team or a coach
that wants copies, get in touch.

If you represent a course and would prefer not to be included, ask and it comes down — no reason
needed: **[lucasgreenbook.org/removal](https://lucasgreenbook.org/removal)**

Anything else, including a course that isn't listed:
**[info@lucasgreenbook.org](mailto:info@lucasgreenbook.org)**

---

*Lucas Green Book™ — by Lucas Wu. © 2026 Lucas Wu.*
