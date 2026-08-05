#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Measure the ELEVATION CHANGE from each tee to its green, from the LiDAR already on disk.

Why: elevation is what makes a junior club up or down, and the card said nothing about it. A yardage
book normally does. We hold ground-classified returns over the whole course, so this is a measurement
we can make rather than a number we would have to invent.

What is printed is the CHANGE ITSELF -- "green 37 ft above the tee" -- not a "plays like +12 yd"
adjustment. Converting elevation into an effective yardage needs a ball-flight model (launch, spin,
apex, air density) that LiDAR cannot supply, so a printed "plays" figure would be exactly the kind of
confident-but-unsupported number this project refuses. The player brings the judgement; we bring the
measurement.

Method, per hole:
  tee   -- median Z of ground-classified returns over the hole's BACK TEE PAD
  green -- median Z of the GREEN INTERIOR of its own built surface (dem_hd/holeNN.npy, masked by the
           same polygon render_green draws the card from), which is already gated for density and
           coverage, so it inherits that honesty check for free
Both are medians, not means: a mean is dragged by a single mis-classified return, and a tee box is
flat enough that the median is the tee's height.

Finding the back tee is the whole difficulty -- see tee_anchor. A hole gets NO figure rather than a
guessed one, and the card simply omits the line, when ANY of these holds:
  * the hole has no mapped centreline in osm_geom.json, so there is nothing to place a tee on;
  * its mapped line neither spans the card yardage nor belongs to a straight par 3, so the back tee
    cannot be located (tee_anchor refuses rather than sample somewhere up the fairway);
  * the green has no usable surface -- no dem_hd patch, flagged insufficient, or a ring that
    rasterises to nothing (green_elevation);
  * the tee sample holds too few ground returns (MIN_RING_PTS on a mapped pad, MIN_TEE_PTS in the
    fallback box);
  * the mapped tee pad spans more height than MAX_TEE_RELIEF_FT, so a median over it does not stand
    for a tee height -- 6 of 177 holes, and a cause of its own rather than a variant of the two above
    it: merion h1 holds 3839 ground returns on a pad it fails by relief, over a usable green surface;
  * the change exceeds MAX_PLAUSIBLE_FT and can only be a units or datum fault.

Every refusal is PRINTED as it happens, with its reason. It is not RECORDED: hole_elev.json holds only
the holes that got a figure, so which of the six refused a given hole survives in this stage's run log
and nowhere else. This docstring used to claim "the count and the basis are recorded so every omission
is auditable" and tools/gen_provenance.py believed it -- legal/03 told readers that every hole without a
height had a tee that "could not be located or had no ground returns", on four courses where that was
not the reason (merion h1 and h11 each resolved an anchor and were refused for pad relief). The COUNT is
recoverable from the artifact -- holes on the card minus rows written -- and the count is all legal/03
now claims.

A row written here is also not the same thing as a height printed. generate.py suppresses any measured
change under 3 ft as level (elev_phrase), so the corpus's 171 measured holes print on 114 cards.

Run:  COURSE=<slug> python3 fetch_hole_elev.py [--write]
      --write records hole_elev.json in COURSE_DIR.
"""
import glob
import json
import math
import os
import sys

import numpy as np

import config
import geo
from geo import mlat, mlon   # the project's ONE figure of the Earth -- never re-declare these
import render_hole                 # for par3_exact_from_tee: one definition of "straight par 3"

DIR = config.COURSE_DIR
TEE_R_M = 15.0          # half-width of the box sampled around the tee point
MIN_TEE_PTS = 200       # box fallback only: below this the box barely reached the tee at all
# When the sample is the mapped TEE RING, "few points" no longer means "we probably missed the tee" --
# every point is inside the pad by construction, so the only question left is whether the median is
# stable. That is measurable, so it is measured rather than approximated by a count: a median's standard
# error is 1.253*sd/sqrt(n), and over the corpus's mapped pads that is 0.006-0.040 ft even at n = 89.
# The old 200 floor was calibrated against a 900 m2 box and refused 13 pads that carry a median good to
# a hundredth of a foot -- 8 holes lost a printed height for having a SMALL TEE. Gate on the number the
# figure is actually printed to instead.
# Gate on the pad's FLATNESS, not on the precision of its median. The first version of this gate used
# the standard error of the median (1.253*sd/sqrt(n)) with a 0.25 ft ceiling, and that gate was INERT:
# over the corpus it ranged 0.002-0.146 ft and refused nothing, and it cannot refuse anything above
# about 100 returns because sqrt(n) swamps sd. It also ranked the wrong way round -- castlewood-hill 18
# has 4.3 ft of relief and falls 1.06 ft per metre along the hole axis, which is not a tee, and it
# scored BETTER than philadelphia 18 (6.2 ft of relief) purely by having fewer points. Measured against
# the actual implied error, sd correlates 4x better than se (0.44 vs 0.11).
# (Those two read 5.1 and 9.1 ft here for as long as the gate has existed, which are their PEAK-TO-PEAK
# spreads. The gate measures p95-p5 -- see tee_elevations -- so the comment was quoting a spread the
# code never computes, on the one pad it names as the reason for the threshold. Re-measured through the
# shipped ring sampler: 4.30 and 6.22 ft.)
#
# What the figure needs is that the sampled ground IS a tee: a mown, near-level pad whose median stands
# for the whole of it. So bound the spread directly. 2.5 ft of relief across a pad admits a real teeing
# ground with a slight fall and rejects the cases where the box has walked off the pad onto a bank --
# it refuses castlewood-hill 18 and philadelphia 18, the two the SE gate waved through.
# 2.5 ft, tied to the thing it protects: the card suppresses any height under 3 ft as level, so a pad
# whose own sampled ground spans MORE than that cannot anchor a figure quoted to the nearest foot --
# the datum would be ambiguous by more than the smallest quantity the book is willing to print. Costs
# 6 of 177 holes their printed height (bay-view h3, castlewood-hill h9 and h18,
# merion h1 and h11, philadelphia h18). Printing nothing is the honest outcome for those.
# The corpus leaves an EMPTY BAND around the threshold, which is the evidence that it separates two
# populations rather than cutting through one: the flattest pad it refuses is castlewood-hill 9 at
# 2.75 ft and the steepest it accepts is philadelphia 3 at 2.13 ft, so 2.5 sits inside a 0.62 ft gap
# that no hole occupies. Both ends are pinned by
# test_a_tee_pad_that_is_not_level_refuses_to_anchor_a_printed_height, which is where to look before
# moving this number: the gate itself was exercised by NOTHING for as long as it existed, and deleting
# it left the whole suite green while merion h11 started printing "green 35.3 ft below the tee" off a
# pad spanning 3.1 ft.
MAX_TEE_RELIEF_FT = 2.5   # p5-p95 spread of the ring sample; a tee is level or it is not a tee
MIN_RING_PTS = 30         # and enough points for that spread to mean anything
GROUND = 2              # LAS classification for bare earth
# A tee-to-green change beyond this is not a golf hole, it is a units or datum fault. The largest real
# figure in the corpus is 151 ft (castlewood-hill 7, a genuinely hilly Pleasanton course), so this
# leaves better than half again of headroom. It exists because the unit bug this file once had produced
# 300-550 ft figures that printed on real cards and looked like data: a plausibility bound is the one
# check that would have stopped them at the source instead of needing a reader to notice.
MAX_PLAUSIBLE_FT = 250.0


def tee_anchor(hnum, line, greens):
    """(lat, lon, basis) for this hole's BACK TEE, or (None, None, reason) to refuse.

    The elevation change is only honest if the point sampled really is the tee, and two separate
    things can make the mapped centreline's tee end NOT the tee. Both are checked, not assumed:

      * The line may be traced GREEN-FIRST, in which case its first vertex is the green. This code
        used to take geometry[0]; that is the tee end on all 198 holes in the corpus today, so it
        worked by luck. A course mapped the other way round would have compared the green's own
        height against itself and reported an elevation change of about zero -- a number that reads
        as plausible rather than as obviously broken, which is the worst kind of wrong. geo.match_green
        decides which end is which.

      * The line may STOP SHORT of the back tee -- 19 of the 198 holes do, by up to 103 yd. (Was 22
        holes and 138 yd; valley-hi 17's 220 yd stub was replaced by its real 360 yd centreline when
        that course's osm_bbox was widened, which removed both the count and the worst case.) Sampling
        there measures the ground somewhere up the fairway and labels it the tee, and on a climbing
        hole those are not the same height. So:
          - line spans the card yardage      -> its tee end IS the tee; sample there.
          - straight PAR 3 that falls short   -> the tee is recoverable. A par 3 is played straight
            tee-to-green, so the tee lies on the hole's own axis at exactly the card yardage from the
            green centre; extrapolate to that point. This is the same collinearity that lets
            render_hole.par3_exact_from_tee print exact from-tee yardages on these holes.
          - anything else                     -> REFUSE. A par 4/5 card follows a played route that
            can dogleg, so there is no way to say where the missing yardage went.
    """
    green, gend, tend = geo.match_green(line, greens, label=f"hole {hnum}")
    la0 = sum(p['lat'] for p in line)/len(line)
    lo0 = sum(p['lon'] for p in line)/len(line)
    em = lambda la, lo: ((lo-lo0)*mlon(la0), (la-la0)*mlat(la0))
    same = lambda a, b: abs(a['lat']-b['lat']) < 1e-9 and abs(a['lon']-b['lon']) < 1e-9
    ordered = line if same(line[0], tend) else list(reversed(line))
    pts = [em(p['lat'], p['lon']) for p in ordered]
    arc_m = sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
                for i in range(len(pts)-1)) or 1.0
    chord_m = math.hypot(pts[-1][0]-pts[0][0], pts[-1][1]-pts[0][1]) or 1.0
    card_yd = config.HOLES[hnum][config.BACK_I]      # the tee the book is built on, not column 0
    card_m = card_yd*0.9144
    arc_yd = arc_m/0.9144
    if abs(arc_yd - card_yd) <= max(15.0, 0.05*card_yd):
        return tend['lat'], tend['lon'], "tee end of the mapped hole line"
    if render_hole.line_traced_past_the_tee(arc_yd, card_yd, chord_m/0.9144):
        # The line runs BEYOND the book's tee, so that tee lies ON the drawn line: walk back from the
        # green end until the remaining walk equals the card yardage. Interpolation on real geometry,
        # not extrapolation -- and the only reason it is needed is that a course whose OSM lines were
        # traced along a LONGER tee's route (the-reserve: lines follow Black, the book is built on Gold)
        # would otherwise sample the ground at the wrong tee, ~40 yd back, and call it this tee's height.
        want = card_m
        acc = 0.0
        for i in range(len(pts)-1, 0, -1):
            seg = math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1])
            if acc + seg >= want:
                f = (want - acc)/(seg or 1.0)          # fraction from pts[i] toward pts[i-1]
                tx = pts[i][0] + (pts[i-1][0]-pts[i][0])*f
                ty = pts[i][1] + (pts[i-1][1]-pts[i][1])*f
                return (ty/mlat(la0) + la0, tx/mlon(la0) + lo0,
                        f"walked back along the mapped line to the card {card_yd} yd "
                        f"(the line runs {arc_yd:.0f} yd, past this tee)")
            acc += seg
    if render_hole.par3_exact_from_tee(config.HOLES[hnum][0], arc_m, chord_m):
        gp = [em(p['lat'], p['lon']) for p in green['geometry']]
        gc = (sum(p[0] for p in gp)/len(gp), sum(p[1] for p in gp)/len(gp))
        te = pts[0]
        dx, dy = te[0]-gc[0], te[1]-gc[1]
        d = math.hypot(dx, dy) or 1.0
        tx, ty = gc[0] + dx/d*card_m, gc[1] + dy/d*card_m
        return (ty/mlat(la0) + la0, tx/mlon(la0) + lo0,
                f"par-3 tee extrapolated along the hole axis to the card {card_yd} yd "
                f"(mapped line runs {arc_yd:.0f} yd)")
    return None, None, (f"mapped line is {arc_yd:.0f} yd against a card {card_yd} yd, so its tee end "
                        f"is not the back tee and a par-{config.HOLES[hnum][0]} card can dogleg")


def tee_rings_latlon():
    """Every mapped `golf=tee` ring as (lats, lons) float arrays, in lat/lon.

    One loader for the pipeline and for tools/verify_elevation.py. The checker has to sample the DEM over
    the SAME regions this module samples the point cloud over, or its disagreement is dominated by the
    region difference rather than by anything about the data -- which is exactly what happened when only
    this side was corrected: the tool's median |diff| rose from 0.80 ft to 1.12 ft while our own agreement
    with the DEM's absolute green elevation improved. A reference that measures a different place is not
    an independent check, it is a second measurement of the bug.
    """
    try:
        with open(f"{DIR}/osm_course.json") as f:
            els = json.load(f).get("elements") or []
    except (OSError, ValueError):
        return []
    out = []
    for e in els:
        if (e.get("tags") or {}).get("golf") != "tee" or not e.get("geometry"):
            continue
        g = e["geometry"]
        if len(g) >= 4:
            out.append((np.asarray([p["lat"] for p in g], float),
                        np.asarray([p["lon"] for p in g], float)))
    return out


def ring_containing(la, lo, rings):
    """The (lats, lons) ring holding this lat/lon, or None. Ray-cast in a local metric frame so the
    lon/lat aspect ratio cannot distort the test on a small pad."""
    for rla, rlo in rings:
        k, kla = mlon(la), mlat(la)
        if _point_in_ring(lo*k, la*kla, rlo*k, rla*kla):
            return (rla, rlo)
    return None


def _tee_pads(anchors, crs):
    """{hole: (vx, vy)} -- the mapped `golf=tee` ring, in LAZ CRS units, that contains each anchor.

    The tee height was a median over an AXIS-ALIGNED BOX of half-width TEE_R_M around the anchor, and
    that box is mostly not tee. Measured over the corpus, a mapped tee covers about 13% of it on the six
    metric courses -- the same pathology as the green end, pointing the other way, because a box centred
    on a raised tee pad reaches down the surrounding ground and reads LOW. The two errors partly cancel
    in the printed CHANGE, which is why neither was visible in the figure: correcting only the green end
    would have shifted every height in the book by +0.47 ft.

    The rings are in osm_course.json and were never loaded. Refusing to guess when the anchor lands in
    none of them (8 of 177 holes): those fall back to the box, which is at least centred on the tee.
    """
    from pyproj import Transformer
    T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    rings = []
    for rla, rlo in tee_rings_latlon():
        vx, vy = T.transform(rlo.tolist(), rla.tolist())
        rings.append((np.asarray(vx, float), np.asarray(vy, float)))
    out = {}
    for hn, (tx, ty) in anchors.items():
        for vx, vy in rings:
            if _point_in_ring(tx, ty, vx, vy):
                out[hn] = (vx, vy)
                break
    return out


def _point_in_ring(px, py, vx, vy):
    """Ray-cast a single point against one ring. Scalar, used once per (hole, ring)."""
    inside = False
    n = len(vx)
    for i in range(n):
        j = i - 1
        if (vy[i] > py) != (vy[j] > py):
            xint = (vx[j]-vx[i])*(py-vy[i])/((vy[j]-vy[i]) or 1e-12) + vx[i]
            if px < xint:
                inside = not inside
    return inside


def _mask_in_ring(x, y, vx, vy):
    """Vectorised ray-cast of many points against one ring."""
    inside = np.zeros(len(x), dtype=bool)
    n = len(vx)
    for i in range(n):
        j = i - 1
        crosses = (vy[i] > y) != (vy[j] > y)
        with np.errstate(divide='ignore', invalid='ignore'):
            denom = vy[j] - vy[i]
            xint = (vx[j]-vx[i])*(y-vy[i])/(denom if denom else 1e-12) + vx[i]
        inside ^= crosses & (x < xint)
    return inside


def _crs_units_per_m(crs, la, lo):
    """How many LAZ-CRS horizontal units make one metre, measured rather than looked up.

    TEE_R_M = 15.0 was applied straight to CRS coordinates -- `np.abs(x - tx) < TEE_R_M` -- so on the
    five State Plane (US survey foot) courses the "15 m" box was 15 ft = 4.57 m, a 9.1 m square against
    30 m on the six metric ones: the same nominal measurement taken over areas differing by 10.8x. It
    also made MIN_TEE_PTS = 200 effectively 10.8x stricter there. verify_elevation.py's comment "same box
    fetch_hole_elev samples at the tee" was false on 5 of 11 courses because of it.

    Measured by transforming two points 15 m apart through the same transformer the samples came
    through, so it needs no unit introspection and cannot disagree with the projection actually used.
    """
    from pyproj import Transformer
    T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x0, y0 = T.transform(lo, la)
    x1, y1 = T.transform(lo, la + 15.0/mlat(la))
    d = math.hypot(x1-x0, y1-y0)
    return (d/15.0) if d > 1e-9 else 1.0


def _tee_points(anchors):
    """{hole: (x, y)} in the LAZ CRS for each hole's tee anchor, plus the CRS used.

    The CRS comes from geo.sole_laz_crs, which refuses a laz/ holding more than one. This read the
    FIRST tile's header and assumed the rest matched: mix a ftUS tile into a metric directory and every
    anchor here lands in another county, so no ground returns fall over any tee pad and each hole simply
    prints no height -- a refusal that looks like missing data rather than a mixed directory.
    """
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        return {}, None
    from pyproj import Transformer
    crs = geo.sole_laz_crs(f"{DIR}/laz")
    if crs is None:
        return {}, None
    T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return {hn: T.transform(lo, la) for hn, (la, lo) in anchors.items()}, crs


def tee_elevations(anchors):
    """{hole: (median_z, n_points, basis)} from ground returns over each hole's TEE PAD.

    Over the mapped `golf=tee` ring where the anchor lands in one, and over a true 15 m box where it
    does not. Both changes matter and they are independent:

      * the RING, not a box. A box centred on a raised tee pad also samples the ground it is raised
        above, so it reads the tee low -- measured at a median 0.20 ft and a mean 0.72 ft low over the
        169 holes whose anchor lands inside a mapped tee, and up to 1.90 ft on copper-valley. On the six
        metric courses the mapped tee is only about 13% of the box.
      * a true 15 m box in the FALLBACK, because TEE_R_M was applied in raw CRS units. See
        _crs_units_per_m: on the five US-survey-foot courses that made the box 9.1 m square instead of
        30 m, a 10.8x difference in sampled area for the same nominal measurement.
    """
    targets, crs = _tee_points(anchors)
    if not targets:
        return {}
    import laspy
    pads = _tee_pads(targets, crs)
    # one representative anchor is enough: a course spans far too little to change the scale factor
    _la, _lo = next(iter(anchors.values()))
    upm = _crs_units_per_m(crs, _la, _lo)
    R = TEE_R_M * upm                          # the box, now genuinely TEE_R_M metres in every CRS
    acc = {hn: [] for hn in targets}
    for path in sorted(glob.glob(f"{DIR}/laz/*.laz")):
        with laspy.open(path) as f:
            hb = f.header
            # skip a tile that cannot contain any tee box at all
            if all(x + R < hb.x_min or x - R > hb.x_max or
                   y + R < hb.y_min or y - R > hb.y_max
                   for x, y in targets.values()):
                continue
            for chunk in f.chunk_iterator(3_000_000):
                cl = np.asarray(chunk.classification)
                g = cl == GROUND
                if not g.any():
                    continue
                x = np.asarray(chunk.x)[g]
                y = np.asarray(chunk.y)[g]
                z = np.asarray(chunk.z)[g]
                for hn, (tx, ty) in targets.items():
                    # the box is still the PREFILTER even when a ring is used -- a ring test over every
                    # ground point in a 3 M-point chunk would be the slow way to get the same answer
                    m = (np.abs(x - tx) < R) & (np.abs(y - ty) < R)
                    if not m.any():
                        continue
                    ring = pads.get(hn)
                    if ring is None:
                        acc[hn].append(z[m])
                        continue
                    inr = _mask_in_ring(x[m], y[m], ring[0], ring[1])
                    if inr.any():
                        acc[hn].append(z[m][inr])
    out = {}
    for hn, parts in acc.items():
        if not parts:
            continue
        zs = np.concatenate(parts)
        on_pad = hn in pads
        basis = ("the mapped tee pad" if on_pad else
                 f"a {TEE_R_M:.0f} m box at the tee anchor (no mapped tee ring contains it)")
        rel = (float(np.percentile(zs, 95) - np.percentile(zs, 5)) if len(zs) >= 20
               else float(zs.max() - zs.min()) if len(zs) else float("inf"))
        out[hn] = (float(np.median(zs)), int(zs.size), basis, on_pad, rel)
    return out


def tee_median_is_trustworthy(n, relief_raw, on_pad, vscale):
    """(ok, reason) for one hole's tee sample. Two different questions, so two different gates.

    * RING: every point is inside the mapped tee, so the doubt is not whether the median is PRECISE --
      it always is, at these sample sizes -- but whether the ground under it is a tee at all. A median
      over a pad that falls 5 ft is stable and meaningless. Gate on the spread.
    * BOX: no containment guarantee. A handful of points there means the box barely reached the tee, and
      a tight median over five returns on a cart path is stable and wrong. The count is the only signal,
      so the original 200 floor stands.

    Split out as a predicate because the two branches are easy to conflate and a loosened gate is the
    failure mode this project is most exposed to. The first version of this function gated the ring on
    the standard error of the median and could not fail: measured across the corpus it never came within
    a factor of 1.7 of its own ceiling, and it scored a 5-ft-relief pad better than a flat one because
    se falls with sqrt(n). A gate that cannot refuse is worse than no gate, because it reads as one.
    """
    relief_ft = relief_raw * vscale * 3.28084
    if on_pad:
        if n < MIN_RING_PTS:
            return False, f"only {n} ground returns on the mapped tee pad (need {MIN_RING_PTS})"
        if relief_ft > MAX_TEE_RELIEF_FT:
            return False, (f"the mapped tee pad spans {relief_ft:.1f} ft of height (limit "
                           f"{MAX_TEE_RELIEF_FT}) -- that is not a level teeing ground, so a median "
                           f"over it does not stand for a tee height")
        return True, ""
    if n < MIN_TEE_PTS:
        return False, (f"only {n} ground returns in the {TEE_R_M:.0f} m box (need {MIN_TEE_PTS}); no "
                       f"mapped tee ring contains this anchor, so a small sample may not be the tee")
    return True, ""


def green_elevation(hole):
    """Median elevation of the GREEN INTERIOR, in METRES, or None.

    Already metres, both ways in: fetch_dem_hd.py scales LAZ Z by the CRS axis unit before gridding
    (its line `z = np.asarray(las.z)[g]*zscale`), and fetch_dem.py's seamless patches come from 3DEP
    in metres. So this value must NOT be scaled again -- see the note in main() on the bug that was.

    The MASK is the point. This took the median of the WHOLE .npy, and that array is the green's bounding
    box padded by fetch_dem_hd.MARGIN_M = 12 m on all four sides -- so the "measured height of the green"
    was a median over a region 5.5x the green's area, of which a corpus-median 82% is not green. It is
    fairway, bunker and rough surrounding a green that is usually a raised pad, so the figure read LOW:
    substituting the interior moves 177 holes by a mean +0.478 ft, positive on 140 of them, one-sided at
    p = 2.7e-15.

    The polygon was in the SAME meta file the whole time -- meta["polygon"] -- and render_green.py
    rasterises it to measure every slope, tilt and feed figure the card prints. One .npy, read two
    different ways by two modules in one pipeline; this one now reads it the way the card does, using
    render_green's own rasterisation so they cannot drift apart.

    Checked against an independent source, not just argued: median |difference| against the 3DEP seamless
    DEM over the same green polygon goes 0.161 m -> 0.018 m, better on 159 of 177 holes and in all 11
    courses. 3DEP independently reproduces the raised-pad mechanism (green interior above its padded
    patch by +0.179 m there against +0.144 m here, r = 0.909), so this is a region error, not a datum one.
    """
    mp = f"{DIR}/dem_hd/hole{hole:02d}.json"
    npy = mp.replace(".json", ".npy")
    if not (os.path.isfile(mp) and os.path.isfile(npy)):
        return None
    with open(mp) as f:
        meta = json.load(f)
    if meta.get("insufficient"):
        return None            # no trustworthy surface -> no elevation claim either
    a = np.load(npy).astype(float)
    a[~np.isfinite(a)] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    if np.all(np.isnan(a)):
        return None
    # render_green's own poly_to_px/point_in_poly. Note it builds its mask with a scanline fill and only
    # falls back to per-cell point_in_poly below 20 cells, so this is the same GEOMETRY, not literally
    # the same code path -- verified cell-for-cell identical on all 198 greens, but a change to that
    # scanline could diverge from this silently.
    import render_green as rg
    H, W = a.shape
    poly = rg.poly_to_px(meta["polygon"], meta["bbox"], W, H)
    mask = np.array([[rg.point_in_poly(c+0.5, r+0.5, poly) for c in range(W)] for r in range(H)])
    if not mask.any() or np.all(np.isnan(a[mask])):
        return None                          # a ring that rasterises to nothing states no height
    return float(np.nanmedian(a[mask]))


def is_plausible_change(change_ft):
    """False when a tee-to-green figure can only be a units or datum fault. See MAX_PLAUSIBLE_FT.

    Clean data cannot exercise this, so deleting the CALL in main() is invisible until a fault appears
    -- at which point the corpus test on the recorded figures catches it. That is defence in depth, not
    full coverage, and is stated here rather than implied."""
    return abs(change_ft) <= MAX_PLAUSIBLE_FT


def elevation_change_m(green_z_m, tee_z_raw, vscale):
    """Green minus tee, in metres. ONLY the tee height is raw LAZ Z, so only it takes the axis scale.

    Kept as a pure function because the mistake it encodes was invisible in every other check. The
    code read `(green - tee) * vscale`, subtracting a US-survey-foot tee height from an already-metric
    green height and scaling the difference. It produced confident, plausible, badly wrong figures on
    the 5 ftUS courses -- monarch-bay hole 3 printed "green 21 ft below the tee" against a real
    -6.2 ft -- while the 6 metric courses were exactly right, because vscale is 1.0 there and the two
    forms coincide. Merion is metric, so no amount of checking Merion could surface it.
    """
    return green_z_m - tee_z_raw * vscale


def _env_on(name):
    """An escape hatch is ON only if it is not an explicit off.

    Parsed the way fetch_trees._env_on parses its two, NOT for truthiness: bool(os.environ.get(..))
    makes ALLOW_ELEV_LOSS=0 and =false mean YES, and this one waives the guard that stands between a
    survey that came back thinner and a book that quietly stops printing a height it used to.
    """
    return os.environ.get(name, "").lower() not in ("", "0", "false", "no")


def stored_rows(path):
    """{hole: row} for the hole_elev.json already on disk; {} when there is none to compare against.

    An unreadable file is treated as no baseline rather than a hard stop, which is the call
    fetch_trees._stored_layer makes and the opposite of fetch_osm._digitized_of's -- and the
    distinction is whether a human made the data. Nothing here is hand-made: this run re-measures
    every hole from the tiles and the green surfaces, so a corrupt baseline costs this guard its
    comparison and nothing else.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return {str(h): r for h, r in (json.load(f).get("holes") or {}).items()}
    except Exception:
        return {}


def check_rows(rows, path):
    """Refuse to commit hole_elev.json when a hole that HAD a height no longer has one.

    This artifact was the only derived file under courses/ with no loss guard. Its siblings all have
    one, because every one of them can lose data for reasons that have nothing to do with the ground:
    fetch_osm._check_response (churn, a green floor, ALLOW_SHRINK), fetch_trees.check_layer
    (ALLOW_NO_TREES / ALLOW_TREE_LOSS and a per-hole floor), surface_io.commit_surface (the pair and
    its digest), lidar_dates.write_lidar_flown (load and set one key). Here there was only
    `if not rows: return 1`, which blocks TOTAL loss and nothing between that and everything.

    NO CRASH IS NEEDED TO CAUSE A PARTIAL ONE: fewer laz/ tiles on disk than last time, a first tile
    whose CRS reads differently (geo.vertical_scale keys off it), a tee box that used to just clear
    MIN_TEE_PTS. And the corpus cannot tell such a loss from the status quo, because this file is
    ALREADY partial on 8 of its 11 courses -- 171 rows over 198 holes, bay-view at 11 of 18, merion 12,
    monarch-bay 13, castlewood-hill 15, philadelphia 16, castlewood-valley 16, callippe 17, valley-hi
    17. A hole dropping out looks exactly like a hole that never had a figure.

    Nor does anything downstream object. generate.py omits the elevation line for a hole with no row,
    and gen_provenance's "measured on N of 18" follows the loss DOWN, so the book stays internally
    consistent and reads as finished; the only tripwire is `gen_provenance --check` calling the
    document STALE, and the remedy it prints regenerates the document, which launders the loss into
    the record.

    PER HOLE, not a total, for the reason fetch_trees.check_layer is: a course can hold its count while
    one hole trades places with another, and it is the named hole whose card silently loses its height.
    """
    prev = stored_rows(path)
    lost = sorted(int(h) for h in prev if h not in rows)
    if not lost:
        return
    detail = ", ".join(f"{h} ({prev[str(h)].get('change_ft')} ft)" for h in lost)
    if not _env_on("ALLOW_ELEV_LOSS"):
        raise SystemExit(
            "REFUSING to write %s: hole(s) %s had a measured height in the stored file and this run\n"
            "  produced none. Those cards would drop the elevation line with nothing to show a\n"
            "  measurement was lost -- the book stays self-consistent and legal/03's \"measured on N\n"
            "  of 18\" follows the loss down. Check that every laz/ tile is still on disk, that the\n"
            "  first tile's CRS still reads the same, and read the per-hole refusals printed above.\n"
            "  Set ALLOW_ELEV_LOSS=1 if the loss is real (a green rebuilt, a tee re-mapped)."
            % (path, detail))
    print("WARNING: ALLOW_ELEV_LOSS set -- hole(s) %s lose the height they had" % detail)


def write_hole_elev(path, payload):
    """Stage `payload` beside hole_elev.json and rename it into place, sweeping the stage either way.

    Extracted from main() so a TEST can drive it -- the same move lidar_dates.write_lidar_flown,
    fetch_dem.is_flat_fill and fetch_dem_hd.keeps_existing_surface record. Inline it could only be
    exercised by a full LiDAR run over a course with tiles on disk.

    THE STAGE IS SWEPT ON THE FAILURE PATH, which is what this write was missing while the project's
    other staged writes were being fixed for exactly that. course.json's went through
    write_lidar_flown and the surface pair's through commit_surface; this one was found third, and two
    more (fetch_osm's) were found after it -- eight in all, enumerated in
    test_no_staged_write_leaves_its_part_file_behind. Nothing
    globs for its leftover -- surface_io.sweep_staged only matches dem_hd's dot-prefixed `.hole*.part`.
    A `.part` is never valid data, because it is only renamed into place after the write returns, so
    anything still wearing the staged name is by construction incomplete. And under courses/ -- the one
    directory nothing sweeps, holding the only copy of these measurements -- a stray hole_elev.json.part
    beside hole_elev.json reads as an interrupted rewrite of the heights 114 cards print from.

    Staged rather than written in place for the reason lidar_dates gives about course.json, one notch
    weaker: this file IS derived and a re-run rebuilds it, but json.dump truncates on open and then
    streams, so a failure mid-encode leaves a wreck that is not obviously a wreck (measured elsewhere in
    this project at 327 bytes where 265 were). os.replace makes the old file survive intact instead.

    ENCODING NAMED on the write, as config.py's note on course.json argues for the read: json.dump's
    ensure_ascii keeps the bytes ASCII whatever the locale, and saying utf-8 costs nothing and removes
    the locale from the question entirely.
    """
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):     # a no-op once the rename above has happened
            os.remove(tmp)


def main():
    if config.BUILD_MODE == "yardage":
        print(f"{config.SLUG} is a yardage-mode course: no green surfaces, so no elevation change "
              f"to measure against.")
        return 0
    els = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    _loc = config.COURSE.get("location") or {}
    holes = geo.hole_lines(els, _loc.get("lat"), _loc.get("lon"))   # one shared, deterministic choice
    if not holes:
        print("no hole centrelines in osm_geom.json"); return 1

    # Vertical units: the Z we compare must be metres. geo.vertical_scale RAISES rather than assume,
    # which is what we want -- a ftUS cloud read as metres would report a 3.28x elevation change. And
    # the CRS it is asked about must be the CRS of EVERY tile, not of whichever one the glob reached
    # first: geo.sole_laz_crs refuses a mixed laz/, because on a near pair this scale would be wrong by
    # 3.28 and the card would print a confident wrong height. Same reader fetch_dem_hd builds the green
    # surfaces through, so the two stages cannot disagree about what CRS this course's cloud is in.
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        print(f"{config.SLUG}: no LAZ on disk, so tee heights cannot be measured"); return 2
    vscale = geo.vertical_scale(config.COURSE.get("lidar_crs") or geo.sole_laz_crs(f"{DIR}/laz"))

    greens = [e for e in els if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    anchors, refused, bases = {}, {}, {}
    for hn in sorted(holes):
        la, lo, basis = tee_anchor(hn, holes[hn]["geometry"], greens)
        bases[hn] = basis
        if la is None:
            refused[hn] = basis
        else:
            anchors[hn] = (la, lo)
            refused[hn] = None
            if not basis.startswith("tee end"):
                print(f"  hole {hn:2d}: {basis}")

    tees = tee_elevations(anchors)
    rows = {}
    print(f"{config.SLUG}  ({len(holes)} holes, tee pad or {TEE_R_M:g} m box, Z x {vscale:g} -> m)")
    for hn in sorted(holes):
        gz = green_elevation(hn)
        tz_n = tees.get(hn)
        if refused[hn] is not None:
            print(f"  hole {hn:2d}: no elevation figure -- {refused[hn]}")
            continue
        tee_ok, tee_why = (tee_median_is_trustworthy(tz_n[1], tz_n[4], tz_n[3], vscale)
                           if tz_n else (False, "no ground returns at the tee"))
        if gz is None or not tee_ok:
            why = "no usable green surface" if gz is None else tee_why
            print(f"  hole {hn:2d}: no elevation figure -- {why}")
            continue
        tz, n, tee_region = tz_n[0], tz_n[1], tz_n[2]
        # UNITS. The green surface is ALREADY metres (see green_elevation); the tee median is raw LAZ
        # Z, so only IT takes the CRS axis scale. Getting this wrong was silent and large: the code
        # read `(gz - tz) * vscale`, subtracting a ftUS tee height from a metric green height and then
        # scaling the difference. On every US-survey-foot course that produced a confident, plausible,
        # badly wrong figure -- monarch-bay hole 3 printed "green 21 ft below the tee" for a real
        # -6.2 ft. Metric courses (merion, philadelphia) were unaffected because vscale is 1.0 there,
        # which is exactly why spot-checking Merion did not reveal it.
        tz_m = tz * vscale
        d_m = elevation_change_m(gz, tz, vscale)
        if not is_plausible_change(d_m * 3.28084):
            print(f"  hole {hn:2d}: no elevation figure -- {d_m*3.28084:+.0f} ft is not a golf hole, "
                  f"it is a units or datum fault (green {gz:.1f} m, tee {tz_m:.1f} m)")
            continue
        rows[str(hn)] = {"tee_z_m": round(tz_m, 2),
                         "green_z_m": round(gz, 2),
                         "change_m": round(d_m, 2),
                         # Stored to 0.1 ft for display, and UNROUNDED beside it because generate.py
                         # gates on 3 ft and rounding first moves values across that line: micke-grove
                         # 6 measures 2.956 ft and the-reserve 10 measures -2.952 ft, both stored as
                         # 3.0, both printed as "green 3 ft" -- a figure the module's own floor forbids,
                         # by a floor written because two honest sources disagree by more than the
                         # number below it. Two cards were printing it. A threshold must see the
                         # measurement, not a display value.
                         "change_ft": round(d_m * 3.28084, 1),
                         "change_ft_exact": d_m * 3.28084,
                         "tee_points": n,
                         "tee_basis": bases[hn],
                         # WHERE the tee height was sampled, not just how the anchor was found. Both are
                         # auditable failure points and they fail independently: a correct anchor sampled
                         # over the wrong region is the fault this field exists to expose.
                         "tee_region": tee_region}
        d_ft = d_m * 3.28084
        word = "above" if d_ft > 0 else "below"
        print(f"  hole {hn:2d}: green {abs(d_ft):5.1f} ft {word} the tee   "
              f"({d_m:+.1f} m, {n} tee returns)")

    if not rows:
        print("  no hole got a figure -- writing nothing"); return 1
    print(f"  => {len(rows)} of {len(holes)} holes measured")
    if "--write" in sys.argv:
        p = f"{DIR}/hole_elev.json"
        # LAST GATE BEFORE THE BYTES LAND, like fetch_trees.check_layer: everything above measures the
        # tiles, and this asks whether the measurement is one the book may be rebuilt on.
        check_rows(rows, p)
        write_hole_elev(p, {"tee_radius_m": TEE_R_M, "min_tee_points": MIN_TEE_PTS,
                            "source": "USGS 3DEP LiDAR ground returns (class 2) vs the green's own "
                                      "0.4 m surface",
                            "holes": rows})
        print(f"  wrote {os.path.relpath(p, config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
