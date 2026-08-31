# How a Lucas Green Book is made

A green book is the small booklet tour players carry: for every hole, a map of the green showing which
way it slopes and how a putt will break, plus the hole itself with its yardages and hazards.

This page explains how these are built, what every number on a card comes from, and which parts were
hard. It is written for three kinds of reader: someone assessing the engineering, someone at a course
who wants to know we did not take anything of theirs, and a golfer who is simply curious.

It is a description, not a recipe. The reasoning is here; the parameters, thresholds and rendering
logic are not.

The engine is software I wrote with AI as a coding assistant. The books are not AI-generated: every
slope, contour and arrow is computed from LiDAR by ordinary arithmetic, the same way every time.

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

## Where every number comes from

There are exactly four inputs. Nothing else contributes anything a card prints.

| What | Source | Status |
|---|---|---|
| Hole and green **shapes** | OpenStreetMap contributors | ODbL 1.0 — attributed in every book |
| **Elevation** behind slope, contours and break arrows | USGS 3DEP LiDAR and elevation service | U.S. Government public domain |
| **Par, yardage, handicap** | The published scorecard | Facts — not copyrightable |
| **Aerial reference**, where the shape data has a gap | USDA NAIP | U.S. Government public domain |

Slope, contours, break arrows and elevation change are **computed here** from public-domain
elevation. They are not copied, traced, or derived from anyone's product.

**No commercial green-reading product's data, imagery, artwork, symbol set, page layout or trade dress
was used, copied, referenced or reverse-engineered.** No Google, Apple, Esri, Maxar or Bing imagery
appears in any book. The full source-by-source record, with each licence and how it is honoured, is in
[`legal/`](legal/).

## The parts that were hard

**Turning a point cloud into a surface.** Airborne LiDAR does not arrive as a grid of ground heights.
It arrives as millions of individual returns — some off the ground, many off grass, trees, carts,
people, water. You need the ground, on a green, at a resolution fine enough that a tier a foot across
still exists after gridding. Where the returns are too sparse to support that, the honest answer is
to fall back to a coarser public elevation source and *record that you did*, per green, rather than
quietly averaging the two.

**Absolute accuracy is the wrong thing to worry about.** Published vertical accuracy for this kind of
survey sounds alarming next to a contour interval measured in centimetres. It turns out not to
matter: a datum offset moves an entire green up or down together, and break depends only on
*relative* height *inside* one green. What actually limits a read is spatial — how much fine detail
survives gridding and smoothing — and that is a different quantity that has to be reasoned about
separately. Getting that distinction right changed what the maps could honestly claim.

**Distance on a curved earth.** Every printed number — green depth, the yardage ladder, carry
distances, the scale bar, tilt percentage — is ultimately a difference between two coordinates
multiplied by a ground scale. Get that scale slightly wrong and nothing crashes; every distance in
the book is simply a little off, consistently, in a way no test that compares the book to itself will
ever catch. Making distances agree with the actual shape of the earth rather than a convenient
approximation touched every figure on every card.

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

## How it is kept honest

The governing rule is: **never print a number the data does not support, and never omit a hazard a
golfer can reach.** Refusing to print is always safer than printing something wrong, because a kid
aims at whatever the book shows as safe.

That rule is enforced by machinery rather than intention:

- **The records are generated, not written.** The provenance record and the verbatim legal text
  printed in the books are both derived from the built artifacts, and a check fails the build if
  either has gone stale. A legal record that can drift from what was actually printed is worse than
  none.
- **Surfaces are self-identifying.** A green surface is two files that only mean anything together —
  an elevation grid and the extent that places it on the earth. Each records a cryptographic digest
  of the other, and a reader refuses a mismatched pair, because holding the right grid beside the
  wrong extent produces no error at all: just a wrong slope on a card.
- **Checks must not be able to pass by finding nothing.** A verification that examines zero greens
  and a verification that examines all of them and finds no problem report the same thing. Several
  guards here exist specifically to make the difference visible.
- **Gates fail closed.** Where a decision is uncertain, the answer is no.

## Four modules, as concrete examples

These are **excerpts, published to be read.** They reference modules that are not published, so they
will not run as they stand — that is deliberate, not an oversight. They are here because they show how
the project is built rather than what it computes.

- **[`distribution.py`](distribution.py)** — the single answer to *"may this book be handed out?"*,
  written to fail closed, with the reasoning for each refusal in the code.
- **[`surface_io.py`](surface_io.py)** — the rule for committing a green surface to disk so that both
  halves land or neither does, and so a torn pair is detected rather than measured through.
- **[`fetch_lidar.py`](fetch_lidar.py)** — LiDAR tile discovery against a government service that
  rate-limits and has outages. Most of its length is about telling three things apart that look
  identical from outside: a service that is busy, a service that is answering, and a query with no data
  behind it. Guess optimistically and you build a green from a tile that never arrived.
- **[`fetch_lidar_alameda.py`](fetch_lidar_alameda.py)** — a decoder for one county whose tiles are
  named in a scheme nothing else understands, including the projected-CRS trap where the metre and
  US-survey-foot variants differ by a factor of 3.28 and picking the wrong one silently shifts every
  tile index. This is what public geospatial data is actually like: free, public domain, and still
  requiring a purpose-built decoder to find the four files covering one golf course.

What is **not** here: how a point cloud becomes a surface, how slope and break are derived from it, how
a card is composed, how the print scale is verified, and the test suite. Those are the project.

## What is published here, and what is not

Published: this page, the two modules above, and the [`legal/`](legal/) data-provenance record.

Not published: the green-reading and rendering logic, the hole and hazard layout, the card
composition, the verification tooling, the test suite, and the per-course data. Those are the project.

That is a deliberate line, not an oversight. The purpose of this repository is to let anyone verify
where the data comes from and get an accurate sense of the work — not to hand over a build.

## Accuracy and the rules

Green maps show general tilt and tiers, not exact break. **Always trust your own read.** The books
are *designed* to fall within Rule 4.3 size and scale limits, but conformance is a Committee-level,
per-competition decision — confirm before playing in an event.

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
