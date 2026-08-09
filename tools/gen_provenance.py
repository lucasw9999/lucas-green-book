#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generate legal/03_PROVENANCE_BY_COURSE.md from what each course was ACTUALLY built from.

Why generate it: the hand-written table drifted badly. It documented 8 of 12 books, named the wrong
dataset for one course, and carried project-name "years" that were wrong by 2-12 years -- because a
USGS project name is not a flight date. A table transcribed by hand goes stale silently; one derived
from the artifacts cannot.

Everything here is read from the build outputs, never from prose:
  * dataset name   <- the laz/ tile filename prefix (the real project, not the label)
  * flight date    <- course.json lidar_flown, decoded from LAZ point records by tools/lidar_dates.py
  * density range  <- dem_hd/holeNN.json (npts / area, computed at build time)
  * digitized      <- elements tagged _digitized in osm_geom.json
  * caveats        <- build_mode, greens_possibly_outdated, and any green flagged insufficient

Run:  python3 tools/gen_provenance.py            # writes legal/03_PROVENANCE_BY_COURSE.md
      python3 tools/gen_provenance.py --check    # exits 1 if the file is stale (for CI / pre-merge)

Exit codes:  0 the record on disk matches the build artifacts (or it was rewritten)
             1 STALE -- the record does not match, and `--check` says so without touching it
             2 nothing could be checked: no course data present, or an argument this tool does not
               understand. AN UNRECOGNISED ARGUMENT IS EXIT 2 AND NOT A REWRITE -- see unknown_args.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import distribution  # noqa: E402
import surface_io  # noqa: E402  -- read_pair and DIGEST_KEY; see _seamless_cells and _digest_coverage
OUT = os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")

# THE ONLY ARGUMENT THIS TOOL UNDERSTANDS. Everything else is refused, and that is not tidiness.
# main() used to decide its mode with `if "--check" in sys.argv:` and fall through to the branch that
# OVERWRITES OUT, so every other argument selected the destructive one: `-check`, `--chek`, `--verify`,
# `-n`, `--check=1` and a bare `check` each rewrote legal/03_PROVENANCE_BY_COURSE.md, printed "wrote
# legal/03_PROVENANCE_BY_COURSE.md", and exited 0. The generated file itself carries "Verify with:
# python3 tools/gen_provenance.py --check", so a typo in that very command self-certified: it produced
# a record that matched the tree because it had just been written from it.
# 2b0e248 fixed the same one-character defect in tools/export_pdf.py, where it re-exported all 15 PDFs.
KNOWN_FLAGS = ("--check",)


def unknown_args(argv):
    """The arguments this tool does not understand -- EXACT membership, never a prefix or a substring.

    A separate named function rather than an inline comprehension because it is the whole safety of a
    destructive default, and tests/test_r16_gates.py grades one truth table across every tool in tools/
    that spells this rule -- the shape lidar_coverage._env_on's seven copies are kept safe by.
    This tool takes no positional argument at all, so a bare word is unknown too.
    """
    return [a for a in argv if a not in KNOWN_FLAGS]


# The card suppresses any measured tee-to-green change under this as level -- generate.py's
# elev_phrase(): `if ft is None or abs(ft) < 3: return ""`. It is spelled a SECOND time here, which is
# normally the fault this repo keeps fixing, because generate.py binds config.COURSE at import and
# would lock this whole-corpus generator to one course. The duplication is pinned instead:
# tests/test_phase1_regressions.py::test_provenance_counts_the_heights_the_cards_actually_print reads
# the literal out of generate.py and fails if the two ever disagree.
#
# It matters because this table published MEASURED holes as though they were PRINTED cards. Valley Hi
# measures 17 of 18 and prints 1.
PRINT_FLOOR_FT = 3.0


def _tile_project(slug, dem_source=""):
    """(project_label, n_tiles, from_filenames?) -- the real LiDAR project.

    Preferred source is the tile FILENAMES on disk, because a project name recorded by hand has
    been wrong before. Some early downloads saved bare tile ids (t390135.laz) with no project in the
    name; for those we fall back to the recorded dem_source label and say that is what we did.

    Counts the tiles PRESENT for this course, published as "tiles held" rather than "tiles used".

    Two attempts to count only what the build READ both failed, and the second failed in the
    dangerous direction. Filtering on mtime against the newest LiDAR-derived artifact first looked
    right -- callippe showed 10 files against a correct 7, three fetched by a later audit the build
    never saw. But the count then swung to 11 the moment fetch_hole_elev re-ran, because the TEE
    STAGE DOWNLOADS TILES AS IT RUNS: five of callippe's twelve are its own, over tees that sit
    outside every green's tile. mtime cannot tell an audit's stray download from a stage's
    legitimate one, so any count built on it moves with WHEN the stages last ran rather than with
    what they read.

    No stage records which tiles it consumed, so a true "used" count is not available from the
    artifacts at all. Rather than publish a number whose meaning shifts under it, publish the one
    that is exactly true -- what is on disk for this course -- and label it so it claims no more
    than that. Overstating what the book RESTS ON is the failure that matters here; "held" asserts
    presence and nothing about use."""
    cdir = os.path.join(ROOT, "courses", slug)
    tiles = glob.glob(os.path.join(cdir, "*.laz")) + glob.glob(os.path.join(cdir, "laz", "*.laz"))
    names = [os.path.basename(p) for p in tiles]
    if not names:
        return None, 0, False
    projects = set()
    for n in names:
        stem = re.sub(r"\.laz$", "", n)
        if not stem.startswith("USGS_LPC_"):
            continue                                   # bare tile id: carries no project name
        stem = stem[len("USGS_LPC_"):]
        stem = re.sub(r"__Co\d+$", "", stem)           # extra sub-project copy (fetch_lidar.copy_suffix)
        stem = re.sub(r"_w\d+n\d+$", "", stem)         # e.g. _w6153n2055
        stem = re.sub(r"_\d{2}[A-Z]{3}\d+$", "", stem)  # e.g. _18TVK474434
        stem = re.sub(r"_\d+$", "", stem)              # numeric tile id
        projects.add(stem)
    if projects:
        return "; ".join(sorted(projects)), len(names), True
    # fall back to the recorded label, flagged as such
    m = re.search(r"([A-Za-z0-9_]*(?:LiDAR|Lidar|LPC|County|Valley|Levee)[A-Za-z0-9_ ]*)", dem_source or "")
    label = (m.group(1).strip() if m else (dem_source or "").split(",")[0].strip()) or "not recorded"
    return label, len(names), False


def _band(vals, nd=2):
    """"2.70" for one value, "2.70–2.73" for a spread. Never a mean: no green carries a mean."""
    got = sorted({f"{v:.{nd}f}" for v in vals})
    return got[0] if len(got) == 1 else f"{got[0]}–{got[-1]}"


def _seamless_cells(slug):
    """[(hole, cell E-W m, cell N-S m)] for every green built from the seamless mosaic. MEASURED.

    This document published "N green(s) fall back to the 1 m seamless DEM" and the notes bullet called
    it "the USGS 3DEP seamless 1 m DEM". Neither was measured, and both were wrong: 3DEP's seamless
    ImageServer is a MULTI-RESOLUTION MOSAIC, and at the only greens this project has taken from it the
    tier that answered has a source cell of 2.72 m E-W x 3.43 m N-S -- its 1/9 arc-second tier at those
    latitudes. The record overstated resolution by 2.7x and 3.4x, about 9x in area, and so did the six
    cards, and nothing could catch either because both were copies of one typed string.

    Measured from the .npy arrays and their own bboxes, so it needs no network and no service metadata:
    a bilinear resample is piecewise linear along each axis, so the spacing of its second-difference
    spikes IS the source grid. render_green owns that measurement (source_lattice) because it also owns
    the statement of what these surfaces can resolve; this file must not carry a second copy of it.

    render_green binds a course at import, so COURSE is pointed at the slug being measured -- which
    exists by construction here -- and put back. The measurement itself is course-agnostic.

    THE ARRAY AND ITS SIDECAR ARE READ AS A PAIR, through surface_io.read_pair. The selection below
    still reads each sidecar alone, because "is this green seamless?" is a question about the sidecar;
    the MEASUREMENT is taken from a pair whose recorded shape and array_sha256 have been checked. It was
    a bare json.load plus a bare np.load, and the figure this function publishes into a legal exhibit is
    derived from BOTH halves -- the second differences come from the array, the metres-per-pixel they are
    measured against come from the sidecar's bbox and W/H. A pair torn by commit_surface's two
    os.replace calls would put a source cell in legal/03 that nothing measured, which is the exact
    defect this function exists to have fixed (a hand-typed "1 m" that overstated resolution ~9x).
    """
    bases = []
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
        try:
            with open(p, encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        if "seamless" in str(m.get("source", "")).lower() and os.path.exists(p[:-5] + ".npy"):
            bases.append(p[:-5])
    if not bases:
        return []
    prev = os.environ.get("COURSE")
    os.environ["COURSE"] = slug
    try:
        import numpy as np
        import render_green
        from geo import mlat, mlon
    finally:
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
    out = []
    for b in bases:
        raw, m, _digest = surface_io.read_pair(b)
        arr = raw.astype("float64")
        arr[~np.isfinite(arr)] = np.nan
        arr[np.abs(arr) > 1e30] = np.nan
        xmin, ymin, xmax, ymax = m["bbox"]
        clat = m["green_center"][0]
        lat = render_green.source_lattice(arr, (xmax - xmin) * mlon(clat) / m["W"],
                                          (ymax - ymin) * mlat(clat) / m["H"])
        if lat["resampled"]:
            out.append((int(m["hole"]), lat["cell_ew_m"], lat["cell_ns_m"]))
    return sorted(out)


def _seamless_clause(cells, n_seam):
    """The Green slope row's fallback clause, from the measurement rather than from prose."""
    if not cells:
        return (f"{n_seam} green(s) come from the **3DEP seamless mosaic**, source cell **NOT "
                f"MEASURED** — no resampling lattice was found in those arrays")
    holes = ", ".join(str(h) for h, _e, _n in cells)
    return (f"{n_seam} green(s) come from the **3DEP seamless mosaic** instead, source cell "
            f"**{_band(c[1] for c in cells)} m E-W × {_band(c[2] for c in cells)} m N-S** measured "
            f"from those arrays (holes {holes}); the flight date above is NOT theirs — nothing in "
            f"this build decodes an acquisition date for that raster")


def _greens(slug):
    """(count, density_lo, density_hi, n_seamless, n_insufficient, n_with_density) over the built
    green surfaces. n_with_density is separate from count because a seamless green records none,
    and a density RANGE must be published against the greens it was actually measured over."""
    metas = []
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
        try:
            metas.append(json.load(open(p)))
        except Exception:
            pass
    if not metas:
        return 0, None, None, 0, 0, 0
    dens = [m["density"] for m in metas if m.get("density")]
    seam = sum(1 for m in metas if "seamless" in str(m.get("source", "")).lower())
    insuf = sum(1 for m in metas if m.get("insufficient"))
    return (len(metas), (min(dens) if dens else None), (max(dens) if dens else None), seam,
            insuf, len(dens))


def _elevation(slug):
    """(n_printed, n_measured, n_holes, n_extrapolated) from hole_elev.json, or zeros.

    PRINTED and MEASURED are different numbers, and this returned only the second while the table
    published it as the first. generate.py suppresses any measured change under PRINT_FLOOR_FT as level,
    so a row in hole_elev.json is NOT a figure on a card: across the corpus 171 measured holes print on
    114 of 198 cards, and the two counts differ on 9 of 11 courses. Valley Hi measured 17 of 18 and its
    row said "the other 1 print no height" while the book prints ONE height and withholds seventeen,
    sixteen of them measured fine. Micke Grove and The Reserve measured all 18, so their rows carried no
    caveat at all while 14 and 12 cards print nothing.

    This table's whole purpose is that every printed number is traceable to an artifact, so the count it
    leads with has to be the count of printed numbers.

    It also has to distinguish the two BASES, because they are not equally direct: most holes are
    sampled at the tee end of the mapped centreline, but on a short par 3 the tee is extrapolated
    along the hole axis to the card yardage. A reader auditing a figure needs to know which -- so
    n_extrapolated counts the PRINTED ones, which are the only figures there is anything to audit.
    """
    p = os.path.join(ROOT, "courses", slug, "hole_elev.json")
    if not os.path.isfile(p):
        return 0, 0, 0, 0
    try:
        rows = json.load(open(p)).get("holes") or {}
    except Exception:
        return 0, 0, 0, 0
    try:
        card = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("holes") or {}
    except Exception:
        card = {}
    holes = len(card) or 18
    printed = []
    for k, r in rows.items():
        # generate.py's own reading of this file, spelled the same way: a row with no change_ft at all
        # is dropped, the UNROUNDED figure is preferred where present (comparing the floor against a
        # value already rounded to 0.1 ft let 2.956 ft print as "green 3 ft"), and change_ft is the
        # fallback for records written before change_ft_exact existed.
        if card and k not in card:
            continue                     # not a hole on the card: there is nothing to print it on
        if r.get("change_ft") is None:
            continue
        ft = r.get("change_ft_exact")
        ft = r.get("change_ft") if ft is None else ft
        if ft is None or abs(ft) < PRINT_FLOOR_FT:
            continue
        printed.append(r)
    extrap = sum(1 for r in printed if "extrapolated" in str(r.get("tee_basis", "")))
    return len(printed), len(rows), holes, extrap



def _osm_extract_date(slug):
    """Earliest OSM data timestamp across this course's extracts, as YYYY-MM-DD, or None.

    Overpass stamps every response with osm3s.timestamp_osm_base -- the instant of the planet data the
    answer was computed from. It has been sitting unread in every extract on disk while this table went
    to real trouble over the LiDAR side, decoding flight dates out of the point records because four
    courses had been mislabelled by 2-12 years by their project names.

    The same argument applies to geometry. The card tells a reader the hole and green SHAPES come from
    OpenStreetMap, and it prints the flight date so they can judge whether the SLOPE is current. Without
    the extract date they cannot judge the same thing about the shapes: a re-bunkered hole or a re-routed
    green looks exactly as authoritative as a current one. Today every extract is a day or two old, so
    this records a fact rather than fixing a live problem -- which is the moment to record it, before a
    course goes two years without a refetch and nothing says so.

    EARLIEST of the three files, deliberately: geometry, course features and relations are separate
    Overpass calls a minute or so apart, and the honest claim about a book is the age of its oldest
    ingredient.
    """
    stamps = []
    for fn in ("osm_geom.json", "osm_course.json", "osm_relations.json"):
        p = os.path.join(ROOT, "courses", slug, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                t = (json.load(fh).get("osm3s") or {}).get("timestamp_osm_base")
        except (OSError, ValueError):
            continue
        if t:
            stamps.append(str(t))
    return min(stamps)[:10] if stamps else None


def _digitized(slug):
    p = os.path.join(ROOT, "courses", slug, "osm_geom.json")
    if not os.path.exists(p):
        return []
    try:
        els = json.load(open(p))["elements"]
    except Exception:
        return []
    return [e.get("id") for e in els if "_digitized" in (e.get("tags") or {})]


def _row(slug, seam_cells=None):
    j = json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
    name = j.get("name", slug)
    # Both from distribution.py, with the SAME normalisation, but they are different questions: the
    # Status column is a policy verdict, "yardage mode: blank greens" is a fact about the data. They
    # used to be derived separately -- this line was an exact `== "yardage"` match while Status asked
    # distribution.py -- so a mis-cased or space-padded build_mode in a hand-edited course.json
    # printed "Personal" in Status and a LiDAR density sentence in Green slope, in the same row.
    # Deriving one FROM the other would be the mirror fault: the day a second reason makes a course
    # non-distributable, the slope cell would claim yardage mode for a course not in it.
    distributable, label, _why = distribution.distribution_status(j)
    yardage_mode = distribution.is_yardage(j)
    proj, ntiles, from_names = _tile_project(slug, j.get('dem_source', ''))
    ngreens, dlo, dhi, seam, insuf, ndens = _greens(slug)
    dig = _digitized(slug)
    stale = sorted(j.get("greens_possibly_outdated", []))
    flown_rec = j.get("lidar_flown") or {}
    flown = flown_rec.get("label")
    # A flight range is only as trustworthy as what it was measured over. tools/lidar_dates.py
    # narrows the range to the points that actually lie over the greens and records that in `basis`;
    # when it cannot -- no point over any green, or no green geometry to place -- it falls back to the
    # union over WHOLE TILES and says so there. This table read only `label`, so that fallback would
    # have been published as a flight date with no hint that a tile 1.3 km from any green may have set
    # its extremes, which is the exact fault the lidar_dates change was made to fix. Qualify it here.
    # Fail closed. A record with NO basis was written before that distinction existed, and its label
    # WAS the union over whole tiles -- so an absent basis must read as the weaker claim, not the
    # stronger one. Only a basis that positively says "points within ..." earns an unqualified date.
    basis = flown_rec.get("basis") or ""
    flown_note = "" if basis.startswith("points within") else \
        " *(range measured over whole tiles, not only the points over the greens)*"

    # Read the geometry claim off the ARTIFACTS, like every other field in this table. This line was
    # `geom = "OSM (ODbL)"`, hardcoded for every course -- so legal/03 asserted OSM provenance for
    # poppy-ridge, which has no osm_geom.json, no osm_course.json, and draws zero polygons. A false
    # source claim, in the one document whose purpose is to be handed to someone asking where the data
    # came from, and in a file whose own header promises it "cannot drift from what was actually built".
    #
    # Either reading of that row was bad: if the course HAD used OSM it would be missing its ODbL 4.3
    # notice, and since it did not, the record claimed a source that was never touched.
    osm_files = [f for f in ("osm_geom.json", "osm_course.json")
                 if os.path.exists(os.path.join(ROOT, "courses", slug, f))]
    if not osm_files:
        geom = "**none** — no OpenStreetMap data was fetched for this course"
    else:
        geom = "OSM (ODbL)"
        osm_date = _osm_extract_date(slug)
        geom += f", extract **{osm_date}**" if osm_date else ", extract date **not recorded**"
        if dig:
            geom += f"; {len(dig)} green(s) hand-added, tagged `_digitized` (ids {', '.join(str(d) for d in dig)})"

    if yardage_mode:
        slope = "**none** — yardage mode: blank greens to mark your own read"
    elif not ngreens:
        slope = "not built"
    else:
        bits = [f"computed by us from **USGS 3DEP LiDAR** (public domain)"]
        if proj:
            # "tiles held", not "tiles used": no stage records which tiles it consumed, and the tee
            # stage downloads its own as it runs, so any "used" count would be a guess. See
            # _tile_project for the two attempts that got this wrong.
            bits.append(f"project `{proj}` ({ntiles} tiles held)"
                        + ("" if from_names else " *(label recorded in course.json; these tiles\u2019 filenames carry no project name)*"))
        if flown:
            bits.append(f"**flown {flown}**{flown_note}")
        if dlo is not None:
            # len(dens), not len(metas): a density RANGE describes the greens it was computed from.
            # monarch-bay has 18 greens of which 6 are seamless with density None, so this published
            # "15.2-19.5 pts/m2 over 18 greens @0.4 m" -- a range over 12 greens attributed to 18,
            # six of which are not @0.4 m at all and are counted again in the next clause.
            bits.append(f"{dlo:g}–{dhi:g} pts/m² over {ndens} greens @0.4 m")
        if seam:
            # Measured once by the caller and threaded through, so the row, the shared note and the
            # per-course correction under "Sources in full" are three renderings of ONE measurement
            # rather than three chances to disagree.
            bits.append(_seamless_clause(
                _seamless_cells(slug) if seam_cells is None else seam_cells, seam))
        slope = ", ".join(bits)

    nprint, nelev, nholes, nextrap = _elevation(slug)
    if nelev:
        # PRINTED first, then MEASURED. This note used to report only the measured count and call it
        # holes that carry a height, which was wrong on 9 of 11 courses -- see _elevation.
        bits = [f"tee-to-green **height change printed on {nprint} of {nholes} cards**, measured on "
                f"{nelev} of {nholes} holes from the same public LiDAR (ground returns at the tee vs "
                f"the green's own surface)"]
        if nextrap:
            bits.append(f"{nextrap} of the printed figures "
                        f"{'use' if nextrap > 1 else 'uses'} a tee extrapolated along the hole axis "
                        f"to the card yardage, because the mapped line stops short of the back tee")
        nfloor = nelev - nprint
        if nfloor:
            # The reason these print nothing IS recorded: the measurement is on disk and the floor is
            # generate.py's. This is the only omission this table can account for hole by hole.
            bits.append(f"{nfloor} measured hole{'s' if nfloor > 1 else ''} "
                        f"{'fall' if nfloor > 1 else 'falls'} under the {PRINT_FLOOR_FT:g} ft floor "
                        f"and print{'' if nfloor > 1 else 's'} no height")
        if nelev < nholes:
            # And this one it CANNOT. It used to say "the tee could not be located or had no ground
            # returns", derived from the row count alone -- a cause no artifact records, and false:
            # fetch_hole_elev also refuses a hole whose mapped tee pad is too uneven for its median to
            # stand for a tee height (merion h1 and h11 both resolved an anchor and were refused that
            # way), and for three other reasons besides. hole_elev.json holds only the holes that GOT a
            # figure, so the refusal survives in that stage's run log and nowhere else. Say that.
            k = nholes - nelev
            bits.append(f"{k} hole{'s' if k > 1 else ''} {'were' if k > 1 else 'was'} never measured; "
                        f"which check refused {'them' if k > 1 else 'it'} is not recorded in "
                        f"hole_elev.json (see *Holes that print no height*)")
        elev_note = "; ".join(bits)
    else:
        elev_note = ""

    notes = []
    if elev_note:
        notes.append(elev_note)
    if stale:
        # The caveat AND its basis, together. "rebuilt after the flight" is an assertion about 9 of
        # philadelphia's 18 cards, and its evidence was recorded in sources.scorecard -- which this table
        # truncates to the first sentence for readability, so the justification never reached the row
        # that makes the claim. A reader auditing the caveat could not see why it was made.
        note = (f"greens on holes {', '.join(str(h) for h in stale)} were **rebuilt after the "
                f"flight** — those cards are labelled *pre-rebuild data*")
        basis = re.sub(r"\s+", " ", str(j.get("greens_outdated_basis") or "")).strip()
        note += f" ({basis})" if basis else " *(basis not recorded — see greens_outdated_basis)*"
        notes.append(note)
    if insuf:
        notes.append(f"{insuf} green(s) had no usable point cloud and print no read")
    if dig:
        notes.append("hand-added greens were traced from public-domain USDA NAIP because OSM had none")
    # The TREE layer's coverage gap belongs here too. This table already records where the green
    # surfaces come from the seamless mosaic instead of the point cloud -- with the source cell MEASURED
    # off those arrays, which is what `_seamless_clause` writes and why no figure is named here -- and how
    # many holes carry a measured height change, so the one
    # remaining per-hole data limitation it did not report was trees: they are found by height above
    # ground in the point cloud, so a hole the survey does not reach draws none -- and on the card that
    # is indistinguishable from a hole that genuinely has none. Monarch Bay 1, 17 and 18 are the case,
    # and they are exactly the three holes lidar_coverage.py reports as having centreline outside the
    # point data, which is why the blank is the survey's edge rather than open ground.
    tp = os.path.join(ROOT, "courses", slug, "trees_lidar.json")
    if os.path.exists(tp):
        try:
            with open(tp, encoding="utf-8") as fh:
                tl = json.load(fh)
        except (OSError, ValueError):
            tl = {}
        if tl and any(tl.values()):
            bare = sorted(int(h) for h, v in tl.items() if not v)
            if bare:
                notes.append(
                    # Claims only what an empty tree list can support. This asserted that "the point
                    # cloud does not reach those corridors" -- a CAUSE the artifact cannot supply:
                    # trees_lidar.json writes the same empty list whether the hole has no trees, no
                    # survey coverage, returns rejected by the height/class filter, or every marker
                    # landed on a playing surface. generate.py says so in as many words ("it cannot
                    # prove WHY a hole is empty, hence 'no tree data' rather than a coverage claim"),
                    # so this exhibit was overclaiming past the engine it documents.
                    #
                    # It also quoted the card. The card prints three words -- "no tree data" -- and
                    # the word "unmapped" appears in none of the 15 built books, so a legal document
                    # was quoting card wording that does not exist.
                    f"**no tree markers on hole{'s' if len(bare) > 1 else ''} "
                    f"{', '.join(str(h) for h in bare)}** \u2014 the tree layer comes from LiDAR "
                    f"returns above ground, and an empty hole cannot say WHY (no trees there, no "
                    f"survey coverage, or returns rejected by the height/class filter), so the maps "
                    f"show them treeless and those cards are marked \u201cno tree data\u201d")
    # Every card prints a Rating/Slope table. Those are the only printed numbers whose source this table
    # did not report, and 7 of 12 courses have none recorded -- while the panel's own note said "All
    # yardages from the official scorecard", which a reader takes as covering the columns beside them.
    # Report the gap rather than let it stay invisible; an uncited number should be visibly uncited.
    rating_src = re.sub(r"\s+", " ", str((j.get("sources") or {}).get("rating") or "")).strip()
    if any(t.get("rating") is not None for t in (j.get("tees") or [])):
        notes.append(f"tee rating/slope: {rating_src}" if rating_src else
                     "**tee rating/slope source NOT recorded** — the cards print them; nothing cites them")
    # the SAME rule any publisher uses -- see distribution.py for why this is shared (resolved above,
    # so the Status column and the slope text cannot disagree)
    status = f"**{label} ✅**" if distributable else label

    # first sentence of the recorded scorecard provenance, so the table stays readable
    # The table keeps this cell short to stay readable, and that truncation has now twice DISCARDED
    # recorded provenance: the basis for philadelphia's pre-rebuild caveat and five courses' rating/slope
    # sources were all written into this one field and cut off. Two fixes, because a silent cut is the
    # actual fault: say when it happened, and reproduce every source in full below the table.
    sc_full = re.sub(r"\s+", " ", (j.get("sources", {}) or {}).get("scorecard", "")).strip()
    sc = sc_full
    if len(sc) > 190:
        cut = sc[:190].rsplit(". ", 1)[0]
        # ...and always mark it. It used to re-close the sentence with a full stop, so valley-hi's cell
        # ended "transcribed directly; all." -- a mid-sentence cut that reads like a finished thought.
        sc = ((cut + ". …") if len(cut) > 60 else sc[:190] + "…") + f" *(full text: [{name}](#sources-in-full))*"
    return f"| {name} | {status} | {geom} | {slope} | {sc or '—'} | {'; '.join(notes) or 'clean'} |"


def build():
    # ignore scratch/underscore dirs: transient course folders (cold-build tests, staging) must not
    # make the provenance doc look stale and fail the drift check. One spelling of that rule, shared
    # with gen_disclaimers and cross_flight_check -- see distribution.is_corpus_slug.
    slugs = distribution.course_slugs(ROOT)
    # Every course's seamless greens, measured ONCE, before anything is written: the row clause, the
    # shared note and the per-course correction all render this same measurement.
    seam_cells = {s: _seamless_cells(s) for s in slugs}
    rows = [_row(s, seam_cells[s]) for s in slugs]
    # Corpus totals for the "Holes that print no height" note, summed from the same artifacts the rows
    # were built from rather than written down beside them -- a hand-kept total in a generated document
    # is the drift this file exists to prevent.
    _elev = [_elevation(s) for s in slugs]
    tot_print = sum(e[0] for e in _elev)
    tot_meas = sum(e[1] for e in _elev)
    tot_cards = sum(e[2] for e in _elev if e[1])
    floor_totals = ("\n  Across this corpus **{} measured holes print on {} of {} cards**.".format(
        tot_meas, tot_print, tot_cards) if tot_cards else "")
    full = []
    for slug in slugs:
        j = json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
        full.append(f"### {j.get('name', slug)}")
        for key in sorted(j.get("sources") or {}):
            val = re.sub(r"\s+", " ", str((j.get("sources") or {})[key])).strip()
            if val:
                full.append(f"- **{key}** — {val}")
        for key in ("greens_outdated_basis", "dem_source"):
            val = re.sub(r"\s+", " ", str(j.get(key) or "")).strip()
            if val:
                full.append(f"- **{key}** — {val}")
        # DERIVED, and printed beside the transcribed fields on purpose. Those fields are reproduced
        # uncut because that is this section's job, and several of them describe the seamless fallback
        # as "1 m" -- a resolution that was never measured and is wrong by 2.7x E-W and 3.4x N-S. The
        # honest repair for a verbatim record is not to edit the quote, it is to publish the
        # measurement next to it and say which way the quote errs.
        cells = seam_cells.get(slug) or []
        if cells:
            full.append(
                f"- **measured source cell (seamless greens)** — "
                f"**{_band(c[1] for c in cells)} m E-W × {_band(c[2] for c in cells)} m N-S** over "
                f"hole{'s' if len(cells) > 1 else ''} "
                f"{', '.join(str(h) for h, _e, _n in cells)}, measured from the built arrays by "
                f"`render_green.source_lattice`. DERIVED, not transcribed: where a recorded field "
                f"above calls that data *1 m*, it overstates the resolution — the mosaic answered from "
                f"3DEP's 1/9 arc-second tier. No acquisition date for that raster is recorded anywhere "
                f"in this build.")
        full.append("")
    full_text = chr(10).join(full)
    # The shared note's figures come from the same measurement as every row's. Nothing here is written
    # down by hand: the claim this replaces ("the USGS 3DEP seamless 1 m DEM ... and the card says
    # `1 m data`") was two copies of one typed string, in a legal record and on six cards, with nothing
    # able to check either against the other.
    _all = [c for cs in seam_cells.values() for c in cs]
    seamless_note = ""
    if _all:
        seamless_note = (
            f" That service is a MULTI-RESOLUTION MOSAIC, so its sampling is not its resolution: at "
            f"every green this project has taken from it, the tier that answered carries a source cell "
            f"of **{_band(c[1] for c in _all)} m E-W × {_band(c[2] for c in _all)} m N-S** — 3DEP's "
            f"1/9 arc-second tier at these latitudes. This record and the cards both called it *1 m* "
            f"until it was measured out of the arrays themselves "
            f"(`render_green.source_lattice`, no network needed); that was an overstatement of about "
            f"9x in area, and the cards now print the measured cell instead of a tier. Separately, "
            f"**no acquisition date for that raster is recorded anywhere in this build** — "
            f"`tools/lidar_dates.py` decodes flight dates from LAZ point records and this path has no "
            f"point cloud — so a row's flight date covers its 0.4 m greens only, and the cards say so.")
    elif any(_greens(s)[3] for s in slugs):
        seamless_note = (" Its source cell could NOT be measured from the built arrays, so no "
                         "resolution is claimed for those greens here.")
    return f"""# Provenance by Course

<!-- GENERATED by tools/gen_provenance.py -- do not hand-edit; re-run it instead.
     Every field is read from the build artifacts (laz/ tile names, dem_hd metadata, osm_geom.json,
     course.json), never from prose, so this table cannot drift from what was actually built.
     Verify with: python3 tools/gen_provenance.py --check -->

Exactly what data built each book. "Distributed" = built from open, public-domain and factual inputs
only, and handed out on that basis; "Personal" = do not distribute. This records what the build DID; it
is not legal advice and states no legal conclusion.

**Every book on this list is built only from:** OpenStreetMap geometry (ODbL 1.0), slope/contours
computed by us from public-domain USGS 3DEP LiDAR, par/yardage/handicap **facts** from published
scorecards, and — where an aerial or a missing green is needed — public-domain USDA NAIP.
No Esri/Maxar, Google, Apple or Bing imagery, and nothing from any commercial green-reading product.

**Flight dates are decoded from the LiDAR point records** (`tools/lidar_dates.py`), not from the
project name. Four courses were mislabelled by 2–12 years before this was measured, so the dataset
names below are taken from the actual tile filenames on disk.

**Geometry carries a date for the same reason.** Each row's OSM *extract* date is the earliest
`osm3s.timestamp_osm_base` across that course's Overpass responses — the instant of the planet data
they were computed from, read off the files rather than recorded by hand. The flight date lets a reader
judge whether the green SLOPE is current; without this one they cannot judge the same thing about the
hole and green SHAPES, and a re-bunkered hole looks exactly as authoritative as a current one.

| Course | Status | Geometry | Green slope | Scorecard | Notes |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Notes on the special cases
- **Seamless-mosaic fallback.** A few greens have no usable LiDAR ground returns — bayside holes over
  water, or greens under heavy canopy. Those use the USGS **3DEP seamless DEM service** instead of the
  0.4 m point cloud: still public domain, just less sharp.{seamless_note}
- **Holes that print no height.** Every row above counts three things separately, and they are not the
  same thing: cards that PRINT a tee-to-green height, holes that were MEASURED, and holes that were
  never measured at all. A measured change under **{PRINT_FLOOR_FT:g} ft** is suppressed as level
  (`generate.py`, `elev_phrase`), because the two independent sources that figure was checked against
  disagree by more than that on some holes — so a measurement is not a printed number.{floor_totals}
  `fetch_hole_elev.py` declines to measure a hole at all when any of these holds: the hole has no mapped
  centreline; its mapped line neither spans the card yardage nor belongs to a straight par 3, so the back
  tee cannot be placed; there is **no usable green surface**; the tee sample holds too few ground
  returns; the mapped tee pad spans more height than `MAX_TEE_RELIEF_FT`, so a median over it does not
  stand for a tee height; or the change exceeds `MAX_PLAUSIBLE_FT` and can only be a units or datum
  fault. **Which of those applied to a given hole is printed in that stage's run log and is not written
  into `hole_elev.json`**, which records only the holes that got a figure — so the rows above do not
  attribute an individual omission and this record will not guess one. Earlier wording did guess: it told
  the reader that every hole without a height had a tee that could not be found or had no ground returns,
  on four courses where that was not the reason.
- **Hand-added greens.** Where OSM mapped no green at all, the putting surface was traced from
  **public-domain USDA NAIP** imagery and tagged `_digitized`. Only coordinates are derived; no
  imagery is embedded in any book. `fetch_osm.py` refuses to overwrite a cache it cannot read, so a
  re-fetch cannot silently delete this geometry.
- **Greens rebuilt after the flight.** Where a course was reconstructed after its LiDAR was flown,
  the map is real measured data but may no longer match the ground. Those cards are labelled
  *pre-rebuild data* and the guide page names the holes.
- **Yardage mode.** Where no trustworthy post-construction elevation exists at all, the book prints
  verified yardages with **blank greens** rather than slope maps that could be wrong.
- **Jay Blasi routing diagram (Poppy Ridge):** only **viewed**, to establish hole numbering; never
  reproduced or embedded. Extracting factual hole positions is not copying.

## Sources in full

The table above shortens the Scorecard column to stay readable. Everything recorded for each course is
reproduced here uncut, so a claim can always be traced to what was actually written down.

{full_text}"""


def _digest_coverage():
    """(n_with_digest, n_metas) over every built green surface.

    A COVERAGE figure for a guard that is silent when it does nothing. surface_io.commit_surface writes
    array_sha256 beside each array and render_green refuses a pair whose array does not hash to it --
    and that test used to read `meta.get(DIGEST_KEY) not in (None, digest)`, so a MISSING key was
    accepted. That looked like the right call (a surface built before the digest existed has nothing to
    compare against) and it meant the check was INERT on every surface not rebuilt since. When this was
    written that was all 198 of them: 0% coverage, and no artifact anywhere said so.

    Disclosure was the wrong half to add on its own -- it is a figure, not a guard. The 198 sidecars
    were stamped from the arrays already beside them (surface_io.stamp_digest, `python3 surface_io.py
    --stamp`), which moved no printed number because the digest lives only in the sidecar, and a missing
    digest is an error now. So this counter should read n of n on any tree whose surfaces were built or
    stamped by this code, and anything less is a sidecar someone replaced by hand.

    Still printed rather than enforced HERE: the enforcement lives on the read side, where the pair is
    actually used, and turning the document generator red would be reporting someone else's gate.
    Not written into legal/03 either: the document records what each BOOK was built from, and this is a
    fact about how thoroughly this repo can re-verify its own intermediate files.
    """
    with_digest = total = 0
    for slug in distribution.course_slugs(ROOT):
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            total += 1
            try:
                with open(p, encoding="utf-8") as fh:
                    if surface_io.DIGEST_KEY in json.load(fh):
                        with_digest += 1
            except Exception:
                pass
    return with_digest, total


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # REFUSED BEFORE A SINGLE FILE IS READ, so the message can only mean "I did not understand you"
    # and never gets mistaken for a verdict about the tree. The old shape was `if "--check" in
    # sys.argv:` with the WRITE as its else, so a typo did not fail -- it regenerated the legal record
    # and exited 0. Exit 2, the same code this tool already answers for "nothing could be checked".
    stray = unknown_args(argv)
    if stray:
        print(f"unknown argument(s): {' '.join(stray)}\n"
              f"usage: gen_provenance.py [--check]\n"
              f"  with no argument this REWRITES {os.path.relpath(OUT, ROOT)}, so an argument this "
              f"tool does not recognise is refused rather than treated as one it does.")
        return 2
    # The SAME enumerator build() uses, deliberately. This was a raw glob over courses/*/course.json
    # while build() calls distribution.course_slugs(), which drops `_`-prefixed scratch directories --
    # so a tree holding nothing but one leftover fixture (a fresh clone plus one crashed test; this
    # repo's own suite creates such directories) passed the guard, built a table of ZERO courses, and
    # --check declared the committed record STALE with a printed remedy that DESTROYS it: obeying
    # "Re-run: python3 tools/gen_provenance.py" took 139 lines and 12 documented books down to 51 and
    # none. A guard that answers a different question from the body is not a guard.
    # tools/gen_disclaimers.py routes its own guard through the same filtered helper for this reason.
    if not distribution.course_slugs(ROOT):
        # "no courses" is not the same as "stale". On a fresh clone courses/ is gitignored and empty,
        # so regenerating produced an EMPTY table and --check reported the committed 12-row table as
        # stale -- turning the repo's front door red for someone who had done nothing wrong.
        print("no course data present (courses/ is gitignored, and `_`-prefixed scratch directories "
              "are not courses) -- nothing to check against.")
        return 2
    text = build()
    if "--check" in argv:
        # Said BEFORE the staleness verdict, so it is printed on the pass as well as the fail: a
        # coverage figure that only appears when something else is already wrong is not a disclosure.
        digested, metas = _digest_coverage()
        if metas:
            print(f"pair digests: {digested} of {metas} green surfaces carry "
                  f"{surface_io.DIGEST_KEY}"
                  + ("" if digested == metas else
                     f"; the other {metas - digested} are read UNVERIFIED -- render_green now REFUSES "
                     f"a pair whose meta carries no digest, so those holes will not render. Stamp them "
                     f"from the arrays already on disk: python3 surface_io.py --stamp"))
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            print("STALE: legal/03_PROVENANCE_BY_COURSE.md does not match the build artifacts.\n"
                  "  Re-run: python3 tools/gen_provenance.py")
            return 1
        print("legal/03_PROVENANCE_BY_COURSE.md is up to date")
        return 0
    open(OUT, "w").write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({text.count(chr(10))} lines, "
          f"{len([l for l in text.splitlines() if l.startswith('| ') and not l.startswith('| Course |') and not l.startswith('|---')])} courses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
