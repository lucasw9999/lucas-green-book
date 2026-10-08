# How a Lucas Green Book is made

Lucas Green Book produces yardage and green-reading books from open and public-domain data.
This page describes the sources, verification and limitations. It does not publish the production
engine, its processing parameters or its internal tests.

## Data sources

| What appears in a book | Source | Status |
|---|---|---|
| Hole and green geometry | OpenStreetMap contributors | ODbL 1.0 |
| Elevation behind slope, contours and arrows | USGS 3DEP | U.S. public domain |
| Par, yardage, handicap and ratings | Published scorecards and the USGA Course Rating and Slope Database | Facts |
| Aerial reference where mapped geometry is incomplete | USDA NAIP | U.S. public domain |

Slope, contours, break arrows and elevation change are computed by this project from public-domain
elevation data. Published scorecard facts are transcribed, not copied as scorecard artwork.

No commercial green-reading product's data, imagery, artwork, symbol set, page layout or trade dress
is used, copied or referenced. No Google, Apple, Esri, Maxar or Bing imagery is embedded in a book.

Source and licence information is in [`legal/`](legal/). Published course-specific records are in
[`legal/03_PROVENANCE_BY_COURSE.md`](legal/03_PROVENANCE_BY_COURSE.md); their scope is the courses
listed in that record, not a live inventory of current availability.

## Verification and limitations

The build checks source provenance, mapped-hazard coverage and printed size and scale. Dated
summaries of completed work and verification are in [`PROGRESS.md`](PROGRESS.md).

The governing rules are:

- Never print a number the data does not support.
- Never omit a hazard the golfer can reach.

These are build requirements, not a guarantee that the underlying public data is complete or current.
Where source data cannot support a read, that read is withheld rather than invented. A course may
be withheld from distribution when the available data does not describe its current ground.

Green maps show general tilt and tiers, not exact break. Always trust your own read.

Pocket and pro editions are designed to fall within Rule 4.3 size and scale limits. Coach editions
are practice aids, not conforming competition books. Check the notices in your specific edition
and confirm with your Committee before using a book in an event; tournament Local Rules may
restrict its use. This repository makes no claim of approval by a governing body.

## What this repository publishes

This repository contains selected provenance records, attribution and licence information,
project updates, and four existing reference excerpts:

- [`distribution.py`](distribution.py) — distribution-eligibility checks.
- [`surface_io.py`](surface_io.py) — stored surface-data handling.
- [`fetch_lidar.py`](fetch_lidar.py) — access to public LiDAR tiles.
- [`fetch_lidar_alameda.py`](fetch_lidar_alameda.py) — handling county-specific LiDAR tile names.

These excerpts are unchanged by the documentation update. They depend on unpublished modules and
are not a runnable release of the production engine. See [`LICENSE`](LICENSE) for their terms,
including the treatment of earlier software licences.

The current green-reading and rendering engine, hazard-corridor algorithms, card-composition
logic, internal tests, processing parameters and working corpus are not published here.
Applicable data-licence obligations still apply; keeping the engine private does not override them.

## Contact and independence

Lucas Green Book is not affiliated with, endorsed by or sponsored by any course, club,
association or competing product. Course names and marks identify the courses and belong to their owners.

- Request a book: [lucasgreenbook.org/request](https://lucasgreenbook.org/request)
- Request removal: [lucasgreenbook.org/removal](https://lucasgreenbook.org/removal)
- Contact: [info@lucasgreenbook.org](mailto:info@lucasgreenbook.org)

*Lucas Green Book™ — by Lucas Wu. © 2026 Lucas Wu.*
