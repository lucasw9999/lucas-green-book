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
  tee   -- median Z of ground-classified returns over the hole's BACK TEE PAD, within TEE_R_M of the
           anchor. The window is not incidental: a mapped `golf=tee` polygon is often a whole tee
           complex, so the pad beyond it can be a different teeing ground several feet away. See
           tee_elevations, which measures both.
  green -- median Z of the GREEN INTERIOR of its own built surface (dem_hd/holeNN.npy, masked by the
           same polygon render_green draws the card from), which is already gated for density and
           coverage, so it inherits that honesty check for free. Six of the corpus's 198 surfaces come
           from the 3DEP seamless mosaic rather than from LiDAR, because no tile covers those greens;
           each row records WHICH, because the payload used to claim 0.4 m LiDAR for all of them.
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
    fallback disc);
  * the sampled tee ground spans more height than MAX_TEE_RELIEF_FT, so a median over it does not stand
    for a tee height -- 6 of the 172 sampled pads, and a cause of its own rather than a variant of the
    two above it: merion h1 holds 3851 ground returns on a pad it fails by relief, over a usable green
    surface;
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
import collections
import glob
import json
import math
import os
import sys

import numpy as np

import config
import geo
import surface_io                 # read_pair: the one definition of a pair worth measuring through
from geo import mlat, mlon   # the project's ONE figure of the Earth -- never re-declare these
import render_hole                 # for par3_exact_from_tee: one definition of "straight par 3"

DIR = config.COURSE_DIR
TEE_R_M = 15.0          # half-width of the square WINDOW the mapped-pad sample is confined to
# ONE role now, and the second one went undocumented for as long as the ring sampler existed: because
# tee_elevations applies this BEFORE the ring test, it is the WINDOW the mapped-pad sample is confined
# to. So on the pads whose ring reaches past it, the sample is pad INTERSECT window and both the height
# and the relief the gate bounds are measured over that window, not over the whole pad. That is the
# right sample and it is derived from a measurement rather than inherited from the fallback: see
# tee_elevations. It is NO LONGER the fallback region -- see TEE_FALLBACK_R_M.
TEE_FALLBACK_R_M = 6.0  # radius of the disc sampled when NO mapped tee ring holds the anchor
# MEASURED FROM THE CORPUS, not chosen. The pad branch samples the mapped ring intersected with the
# window, and the median area of that region is 113.5 m^2 over the 177 mapped pads (the 12.6% share
# _tee_pads publishes, against the 900 m^2 box); a disc of that area has a radius of 6.0104 m. So the
# fallback now samples a region the size of a teeing ground, centred on the anchor, which is what the
# pad branch gets from the polygon and the fallback had no way to ask for.
#
# WHAT IT REPLACED, and why: the fallback was a full TEE_R_M box -- 900 m^2 of whatever surrounds the
# anchor -- and the relief check sits inside `if on_pad:`, so nothing bounded how much height that
# sample could span. bay-view 16's box spanned 31.9 ft over 10,532 returns on a HILLSIDE and its median
# sat 1.90 ft below the ground at its own anchor, so its card printed "green 46 ft below the tee" for a
# hole its own near-anchor returns put at 48. Applying the relief gate to that branch instead would have
# silenced all five fallback cards for a spread that is an artifact of the REGION rather than a property
# of the tee; sampling the region properly fixes the cause.
#
# COST, measured: 2 of the 5 printed integers move: bay-view 16 46 -> 48 and merion 9 34 -> 33. The
# other three (castlewood-hill 4, merion 3, merion 15) do not move at ANY radius between 0.2 m and the
# window.
#
# SWEPT CONTINUOUSLY, at 0.01 m, because a discrete probe gets this wrong: at {2.5, 5, 7.5, 10} m all
# five look settled, and merion 9's printed integer flips from 33 to 32 at 5.66 m -- 0.34 m below this
# radius, the tightest margin any of the five has. Above, the nearest flip is 7.87 m away. bay-view 16
# prints 48 from 0.2 m all the way to 13.11 m, so the value that arrives sits in a 12.9 m-wide band
# while the 46 it replaces occupied a 1.6 m sliver at the very top of the box's range. That merion 9
# margin is thin and is published rather than smoothed: its change measures -32.553 ft, 0.053 ft from
# the 32/33 rounding boundary, so the integer is genuinely near a tie and the radius is not tuned to
# pick a side of it.
MIN_TEE_PTS = 25        # fallback disc only: below this the disc barely reached the tee at all
# RE-DERIVED for the smaller region. This was 200, calibrated against the 900 m^2 box -- 0.2222
# returns/m^2 -- and left at 200 over a 113.097 m^2 disc it would have meant something 8x stricter than
# it says, which is the exact fault _crs_units_per_m records about this same constant. Preserving the
# areal density it encoded gives 0.2222 * pi * 6.0^2 = 25.1 -> 25.
# Latent either way today: the thinnest fallback sample is castlewood-hill 4's 984 returns, a 39.4x
# margin, and it refuses nothing above r = 0.85 m. What it changes is the next course whose fallback
# anchor sits on thin ground. It also has to stay above the 20 returns `_spread` needs before it uses
# percentiles, or every fallback row's recorded relief would quietly become a peak-to-peak.
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
# for the whole of it. So bound the spread directly. 2.5 ft of relief across the sampled ground admits a
# real teeing ground with a slight fall and rejects a pad that steps or falls away under the window --
# it refuses castlewood-hill 18 and philadelphia 18, the two the SE gate waved through.
# 2.5 ft, tied to the thing it protects: the card suppresses any height under 3 ft as level, so ground
# whose own spread is MORE than that cannot anchor a figure quoted to the nearest foot -- the datum would
# be ambiguous by more than the smallest quantity the book is willing to print. Costs
# 6 of the 172 sampled pads their printed height (bay-view h3, castlewood-hill h9 and h18,
# merion h1 and h11, philadelphia h18). Printing nothing is the honest outcome for those.
# The corpus leaves an EMPTY BAND around the threshold, which is the evidence that it separates two
# populations rather than cutting through one: the flattest pad it refuses is castlewood-hill 9 at
# 2.75 ft and the steepest it accepts is philadelphia 3 at 2.13 ft, so 2.5 sits inside a 0.62 ft gap
# that no hole occupies. Both ends are pinned by
# test_a_tee_pad_that_is_not_level_refuses_to_anchor_a_printed_height, which is where to look before
# moving this number: the gate itself was exercised by NOTHING for as long as it existed, and deleting
# it left the whole suite green while merion h11 started printing "green 35.3 ft below the tee" off a
# pad spanning 3.1 ft.
# THAT BAND IS A STATEMENT ABOUT THE PAD BRANCH ALONE. It was offered as evidence for the threshold
# without saying so, and the threshold sits inside a predicate with a second branch that never reaches
# it: the fallback branch gates on COUNT only and accepts bay-view 16, whose sample spans 7.8 ft over
# the 6.0 m disc (31.9 ft over the 15 m box that disc replaced). See
# tee_median_is_trustworthy, which now states that cost instead of leaving it to be discovered.
# NOR IS IT A STATEMENT ABOUT THE WHOLE MAPPED PAD. 7 pads span more than MAX_TEE_RELIEF_FT over the
# whole ring while the sampled window is level -- callippe-preserve 11, merion 14, merion 16,
# micke-grove 8, philadelphia 4, philadelphia 11 and philadelphia 15 -- and all but micke-grove 8 print
# a height today. Gating on the whole ring
# instead would refuse all seven, and that is the wrong call on the evidence rather than the safe one:
# a `golf=tee` polygon is not reliably one teeing ground (see tee_elevations), so on those seven the
# beyond-window part of the ring is a different tee. The window's own answer holds up where it can be
# tested -- an anchor displaced 10 m moves those seven medians by a median 0.85 ft and at most 1.44 ft
# (merion 14), inside the 3 ft floor the book prints above. Both figures are graded against the LiDAR by
# test_every_figure_behind_the_tee_relief_gate_is_the_one_the_lidar_gives, and the pad-wide spread is
# recorded per row as `tee_pad_relief_ft` so this is auditable from the artifact and not only from here.
MAX_TEE_RELIEF_FT = 2.5   # p5-p95 spread of the SAMPLE; a tee is level or it is not a tee
MIN_RING_PTS = 30         # and enough points for that spread to mean anything
PRINT_FLOOR_FT = 3.0      # generate.elev_phrase suppresses any smaller change as level
# Spelled here as well as in generate.py and tools/gen_provenance.py -- three copies of one threshold,
# for the reason gen_provenance gives about its own: generate.py binds ONE course at import, so nothing
# upstream of the book can ask it. check_rows needs the number because a row can cross this floor and
# silently drop its card's line while keeping its key; the three spellings are pinned together by
# test_the_elevation_loss_guard_sees_a_height_that_stops_printing.
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
    that box is mostly not tee. Measured over the corpus by rasterising every ring against its own box,
    a mapped tee covers a median 12.6% and a mean 13.6% of it across all 177 mapped pads (per-course
    medians 4.9% on valley-hi to 23.6% on merion) -- the same pathology as the green end, pointing the
    other way, because a box centred on a raised tee pad reaches down the surrounding ground and reads
    LOW. The two errors partly cancel in the printed CHANGE, which is why neither was visible in the
    figure: correcting only the green end would have shifted every height in the book by +0.45 ft.

    That share was published as "about 13% on the six metric courses", and the qualifier was a leftover:
    it dates from when TEE_R_M was applied in raw CRS units and the box really was 9.1 m square on the
    five US-survey-foot courses, so only the metric six had a 30 m box to compare against.
    _crs_units_per_m fixed that, and a corpus figure printed under a six-course label is a figure nobody
    can check -- the six-metric-course median is 9.8%, not 13%.

    The rings are in osm_course.json and were never loaded. Refusing to guess when the anchor lands in
    none of them (5 of the 182 anchors this corpus resolves -- bay-view 16, castlewood-hill 4, merion 3,
    merion 9 and merion 15): those fall back to a TEE_FALLBACK_R_M disc at the anchor, sized to the
    median mapped pad, which is the nearest thing to a pad that can be had without a polygon.

    Published as 8 of 177 holes at 4b19d2f. THE CHANGE WAS febbbba AND NOT c7a4f65, which 9cc3bce
    credited: febbbba widened four courses' OSM fetch box, and three anchors that used to fall back now
    sit inside `golf=tee` ways that fetch had never asked for -- way/692110589 (castlewood-hill 1),
    way/690850042 (castlewood-valley 7) and way/690831855 (castlewood-valley 14), the exact three its own
    message names as newly reachable drawn features -- while it re-derived only the tree layer, so
    nothing re-ran this stage. Its "No printed FIGURE moved" held only for that reason: castlewood-valley
    7 and 14 went on printing card 8 and card 30 off a 15 m box (+8.478 and -29.520 ft) until 9cc3bce
    regenerated the artifact and read +7.458 and -31.980 ft off the newly mapped pads.
    The earth-model correction did not do it, and that is measured rather than argued: re-derive every
    anchor from today's cache under the retired constant pair (111320.0 m/deg of latitude and
    111320.0*cos(lat) of longitude) and under the live WGS84 scales, changing nothing else, and the
    anchor count, the fallback count and the holding ring of every single anchor come out identical.
    Only 5 anchors differ at all -- the ones a par-3 extrapolation or a walk-back computes, the only
    paths that arithmetic touches -- and by at most 0.4442 m, on merion 3, the other four 0.2842,
    0.2379, 0.2208 and 0.0731 m. (Published here as "under 0.1 m", and in 1030fc6's message as "at most
    0.07 m", which is the SMALLEST of those five quoted as the largest -- the same median-as-worst-case
    shape this docstring records fixing at the green end. The refutation is unaffected either way: it
    rests on ring membership being identical on every anchor, not on how far the five that move move.)
    A `tee end of the mapped hole line` anchor is a raw OSM vertex and is bit-identical across it, which
    is the basis both castlewood-valley holes use.
    What c7a4f65 DID move is the sampled window's SIZE, through _crs_units_per_m: at merion it is
    0.2570% wider in CRS units, and that is the whole of merion h1's 3839 -> 3851 and h11's
    3917 -> 3923 ground-return drift, off anchors that do not move. That third attribution stands.
    All of it is graded by
    test_the_box_fallback_count_is_attributed_to_the_change_that_moved_those_anchors, because an
    attribution is a claim about cause and this repo graded none until then.
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
    """{hole: (median_z, n_points, basis, on_pad, relief)} from ground returns at each hole's TEE.

    Over the part of the mapped `golf=tee` ring that lies inside a TEE_R_M window at the anchor where the
    anchor lands in a ring, and over a true TEE_R_M box where it does not. Three things matter here and
    they are independent:

      * the RING, not a box. A box centred on a raised tee pad also samples the ground it is raised
        above, so it reads the tee low -- measured at a median 1.00 ft and a mean 1.10 ft low over the
        172 mapped pads that carry ground returns, worst 5.45 ft (philadelphia 16). Copper Valley is the
        worst course at a median 1.90 ft and a worst 3.43 ft (hole 6). (Published as a median 0.20 and a
        mean 0.72 ft over 169 holes, and "up to 1.90 ft on copper-valley" -- which was that course's
        MEDIAN quoted as a worst case, the same mistake this project has already fixed once elsewhere.
        Both averages predate the true-metre box, which grew the five ftUS courses' sampled area 10.8x
        and so pulled their box medians further down.) How little of the box is tee at all is in
        _tee_pads.
      * the WINDOW. The box is applied BEFORE the ring test, so the accumulated sample is ring INTERSECT
        window wherever the ring reaches past the window ON AN AXIS -- 55 of the 177 mapped pads, the
        farthest reaching 63.0 m from its anchor (micke-grove 17) -- and 51 of those actually lose
        ground returns to it.
        THE AXIS COUNT IS THE ONE THAT CLIPS, and this sentence used to quote the RADIAL one against it:
        57 rings reach past 15 m radially, up to 65.7 m (philadelphia 16), but the window is applied as
        `abs(x - tx) < R and abs(y - ty) < R`, so a ring can reach 18 m diagonally and still sit wholly
        inside it. 57 overstates the clipping by 2 pads. ba34e52 drew exactly this distinction and
        corrected it in tools/verify_elevation.py and generate.py, and did not reach the producer that
        does the clipping. All three counts are now graded against the predicate each one names.
        The comment inside the loop used to
        describe the box as a prefilter a ring test would merely reach more slowly, as though the window
        changed nothing; it changes the sample on those 51, and 7 pads span more than MAX_TEE_RELIEF_FT
        over the whole ring while the sampled window is level.
        The window is nonetheless the RIGHT sample, and that is measured rather than asserted. Widening
        it from 10 m to 15 m moves the median by a corpus median 0.000 ft (mean 0.035, worst 0.89 ft on
        micke-grove 8, over 0.5 ft on 2 of the 172): it has converged. Going on to the WHOLE ring
        moves it by up to 1.87 ft
        (philadelphia 4), over 0.5 ft on 10 of them -- because a `golf=tee` polygon is not reliably one
        teeing ground. This corpus maps 28 rings over bay-view's 18 holes and 83 over copper-valley's,
        so on the merged-complex courses the ring reaches a DIFFERENT tee box, several feet from the one
        the book is built on, and a median over that is a blend of two tees rather than this tee's
        height. So the window stays, the label says window (see the `tee_region` recorded per row), and
        the pad-wide spread is recorded beside it.
      * a TEE_FALLBACK_R_M DISC in the FALLBACK, centred on the anchor, sized to the median mapped pad.
        This was a full TEE_R_M box in raw CRS units, so it was two separate faults: 9.1 m square on the
        five US-survey-foot courses against 30 m on the six metric ones (a 10.8x difference in sampled
        area for the same nominal measurement -- see _crs_units_per_m), and then, once that was a true
        30 m box everywhere, 900 m^2 of whatever surrounds the anchor with no relief bound on it at all.
        See TEE_FALLBACK_R_M for the derivation and for the two printed integers it moves.

    `relief` is the p95-p5 spread of the SAMPLE -- the region the median came from, which is what
    tee_median_is_trustworthy bounds. `pad_relief` beside it is the same spread over the WHOLE mapped
    ring, measured but not gated on, so a reader can see the seven pads above from the artifact; it is
    `None` on a fallback row, which has no pad to measure.
    """
    targets, crs = _tee_points(anchors)
    if not targets:
        return {}
    import laspy
    pads = _tee_pads(targets, crs)
    # one representative anchor is enough: a course spans far too little to change the scale factor
    _la, _lo = next(iter(anchors.values()))
    upm = _crs_units_per_m(crs, _la, _lo)
    R = TEE_R_M * upm                 # the window, now genuinely TEE_R_M metres in every CRS
    RF = TEE_FALLBACK_R_M * upm       # and the fallback disc, likewise
    acc = {hn: [] for hn in targets}
    pad_acc = {hn: [] for hn in targets}       # the WHOLE ring, recorded rather than gated on
    # Per hole, how far the sample has to reach: the fallback disc where there is no ring, otherwise the
    # window or the whole ring where that is wider. Only the pad-wide spread needs the wider reach; the
    # median and the gate still see the window.
    reach = {}
    for hn, (tx, ty) in targets.items():
        ring = pads.get(hn)
        reach[hn] = (RF if ring is None else
                     max(R, float(np.max(np.abs(ring[0] - tx))), float(np.max(np.abs(ring[1] - ty)))))
    for path in sorted(glob.glob(f"{DIR}/laz/*.laz")):
        with laspy.open(path) as f:
            hb = f.header
            # skip a tile that cannot contain any tee sample at all
            if all(x + reach[hn] < hb.x_min or x - reach[hn] > hb.x_max or
                   y + reach[hn] < hb.y_min or y - reach[hn] > hb.y_max
                   for hn, (x, y) in targets.items()):
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
                    # A box test over a 3 M-point chunk is the cheap way in; a ring test over all of it
                    # would not be affordable. But on a mapped pad this box is the WINDOW as well as the
                    # prefilter -- it CLIPS the ring on 51 of the corpus's mapped pads, which the comment
                    # here used to deny -- so the wider `reach` is filtered separately for the pad-wide
                    # spread. On a FALLBACK hole `reach` is already the disc's bounding box, and the disc
                    # itself is cut below.
                    h = reach[hn]
                    m = (np.abs(x - tx) < h) & (np.abs(y - ty) < h)
                    if not m.any():
                        continue
                    xm, ym, zm = x[m], y[m], z[m]
                    ring = pads.get(hn)
                    if ring is None:
                        # A DISC, not the box that bounds it: the box's corners reach 1.41x further than
                        # its faces, and on a hillside that is the whole difference between the tee and
                        # the ground it sits above. Nothing about the CRS axes has anything to do with
                        # which way a teeing ground faces, so the region must not depend on them.
                        near = (xm - tx) ** 2 + (ym - ty) ** 2 < RF * RF
                        if near.any():
                            acc[hn].append(zm[near])
                        continue
                    win = (np.abs(xm - tx) < R) & (np.abs(ym - ty) < R)
                    inr = _mask_in_ring(xm, ym, ring[0], ring[1])
                    if inr.any():
                        pad_acc[hn].append(zm[inr])
                        if (inr & win).any():
                            acc[hn].append(zm[inr & win])
    out = {}
    for hn, parts in acc.items():
        if not parts:
            continue
        zs = np.concatenate(parts)
        on_pad = hn in pads
        pad_zs = np.concatenate(pad_acc[hn]) if pad_acc[hn] else None
        out[hn] = (float(np.median(zs)), int(zs.size), tee_sample_region(on_pad), on_pad,
                   _spread(zs), None if pad_zs is None else _spread(pad_zs))
    return out


def _spread(zs):
    """p95-p5 of a sample, in its own vertical units. Peak-to-peak below 20 points, where percentiles
    interpolate between too few order statistics to mean anything; `inf` on nothing, so an empty sample
    can only be refused."""
    if not len(zs):
        return float("inf")
    if len(zs) >= 20:
        return float(np.percentile(zs, 95) - np.percentile(zs, 5))
    return float(zs.max() - zs.min())


def tee_sample_region(on_pad):
    """WHERE the tee median was taken, named as the region it is -- the `tee_region` recorded per row.

    This said "the mapped tee pad" for every pad row, and on the 57 pads whose ring reaches past the
    window that names a region several times the one sampled. It is a field whose whole job is to let a
    reader audit one card, and tools/verify_elevation.py samples its reference over the WHOLE ring on the
    stated grounds that both sides measure the same place -- so the label being loose is how a checker
    ends up measuring a different region and calling the difference data.

    The fallback half names a DISC and its radius, because that is the whole of what a reader can check
    about a height taken where no polygon exists. It said "a 15 m box" until the fallback stopped being
    one; see TEE_FALLBACK_R_M."""
    return (f"the mapped tee pad within the {TEE_R_M:.0f} m window at the tee anchor" if on_pad else
            f"a {TEE_FALLBACK_R_M:g} m disc at the tee anchor (no mapped tee ring contains it)")


def tee_median_is_trustworthy(n, relief_raw, on_pad, vscale):
    """(ok, reason) for one hole's tee sample. Two different questions, so two different gates.

    * RING: every point is inside the mapped tee, so the doubt is not whether the median is PRECISE --
      it always is, at these sample sizes -- but whether the ground under it is a tee at all. A median
      over a pad that falls 5 ft is stable and meaningless. Gate on the spread OF THE SAMPLE: `relief_raw`
      is the p95-p5 of the very returns the median came from, which is the pad inside a TEE_R_M window at
      the anchor and NOT always the whole pad (see tee_elevations). The whole pad's spread is measured
      too, and recorded rather than gated on; the derivation beside MAX_TEE_RELIEF_FT says why.
    * FALLBACK DISC: no containment guarantee. A handful of points there means the disc barely reached
      the tee, and a tight median over five returns on a cart path is stable and wrong. The count is the
      only signal, so a count floor is what gates it -- MIN_TEE_PTS, re-derived from the 200 that was
      calibrated against the old 900 m^2 box. THE RELIEF CHECK IS STILL NEVER REACHED ON THIS BRANCH,
      and that is deliberate: the disc legitimately reaches off a raised tee onto the ground below it,
      so its spread measures the region and not the tee, and gating on it would silence all five
      fallback cards for an artifact. What made that acceptable to state and not merely to assert is
      that the REGION is now the size of a teeing ground: bay-view 16's sample spans 7.8 ft over the
      6.0 m disc where the old 15 m box spanned 31.9 ft over 10,532 returns, and its median is now the
      ground at its own anchor rather than 1.90 ft below it. That card printed 46 and prints 48.
      See TEE_FALLBACK_R_M for the derivation, the two printed integers it moves, and the swept margins.

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
            return False, (f"the sampled tee ground spans {relief_ft:.1f} ft of height (limit "
                           f"{MAX_TEE_RELIEF_FT}) -- that is not a level teeing ground, so a median "
                           f"over it does not stand for a tee height")
        return True, ""
    if n < MIN_TEE_PTS:
        return False, (f"only {n} ground returns in the {TEE_FALLBACK_R_M:g} m disc at the anchor "
                       f"(need {MIN_TEE_PTS}); no mapped tee ring contains this anchor, so a small "
                       f"sample may not be the tee")
    return True, ""


def green_elevation(hole):
    """Median elevation of the GREEN INTERIOR, in METRES, or None.

    Already metres, both ways in: fetch_dem_hd.py scales LAZ Z by the CRS axis unit before gridding
    (its line `z = np.asarray(las.z)[g]*zscale`), and fetch_dem.py's seamless patches come from 3DEP
    in metres. So this value must NOT be scaled again -- see the note in main() on the bug that was.

    The MASK is the point. This took the median of the WHOLE .npy, and that array is the green's bounding
    box padded by fetch_dem_hd.MARGIN_M = 12 m on all four sides -- so the "measured height of the green"
    was a median over a region a corpus-median 5.5x the green's area, of which a corpus-median 82% is
    not green. It is fairway, bunker and rough surrounding a green that is usually a raised pad, so the
    figure read LOW: substituting the interior moves 171 holes by a mean +0.4527 ft, positive on 137 of
    them, which a one-sided sign test puts at p = 3.7e-16. (Published here as "+0.478 ft, positive on
    140" of 177 holes, which was the corpus before fd39647; as "+0.47 ft" in _tee_pads and "+0.46 ft" in
    legal/09 -- four values for one quantity, none of them measured by anything. All three records are
    now graded against this corpus by
    test_the_printed_height_is_measured_over_the_green_and_not_its_surroundings, which had both medians
    in hand already and was throwing the difference away. The two region figures in the sentence above
    are graded there as well, off the same masks; each says WHICH statistic it is, because a ratio
    published without one is a ratio a re-deriver can miss while doing everything right.)

    The polygon was in the SAME meta file the whole time -- meta["polygon"] -- and render_green.py
    rasterises it to measure every slope, tilt and feed figure the card prints. One .npy, read two
    different ways by two modules in one pipeline; this one now reads it the way the card does, using
    render_green's own rasterisation so they cannot drift apart.

    Checked against an independent source, not just argued: median |difference| against the 3DEP seamless
    DEM over the same green polygon goes 0.161 m -> 0.018 m, better on 159 of 177 holes and in all 11
    courses. 3DEP independently reproduces the raised-pad mechanism (green interior above its padded
    patch by +0.179 m there against +0.144 m here, r = 0.909), so this is a region error, not a datum one.

    THE PAIR IS READ AS A PAIR, through surface_io.read_pair. This loaded the sidecar with json.load and
    the array with np.load and checked NEITHER the shape the meta records nor the array_sha256 it records
    -- only `insufficient` and NaN-ness -- so a pair torn by the two os.replace calls in
    surface_io.commit_surface (this run's array beside last run's sidecar) placed the mask by the WRONG
    bbox and this function returned a number for it. PIPELINE.md runs this stage at step 6, before
    generate.py at step 7, so that number reached hole_elev.json FIRST; render_green refuses the same
    hole at render time, but its remedy named only the surface rebuild, after which the render succeeds
    and hole_elev.json still holds the figure measured through the tear. Measured over the real 198
    pairs, a 5 m torn bbox moves the height by a median 0.18 ft, p95 0.60 ft, worst 1.04 ft -- printed in
    WHOLE FEET under a 3 ft floor, so this was a missing guard rather than a live wrong number.

    A TEAR STOPS THE RUN rather than returning None. The None arm of this function means "no height can
    honestly be stated for this hole", and generate.py then omits the line -- which PIPELINE.md's own
    step 6 note says is indistinguishable from an honest refusal. A torn pair is not a refusal, it is a
    broken tree, and the run that produced it may have torn more than one hole.
    """
    base = f"{DIR}/dem_hd/hole{hole:02d}"
    if not (os.path.isfile(base + ".json") and os.path.isfile(base + ".npy")):
        return None
    try:
        a_raw, meta, _digest = surface_io.read_pair(base)
    except ValueError as e:
        raise SystemExit(
            f"{config.SLUG} hole {hole}: {e}\n"
            f"  The array and the sidecar committed beside it are from DIFFERENT RUNS, so the green\n"
            f"  ring would be rasterised against ground these pixels do not cover and this hole's\n"
            f"  height would be measured through that. Rebuild the surface AND re-measure -- \n"
            f"  hole_elev.json is derived, so it stays stale until this stage runs again:\n"
            f"    COURSE={config.SLUG} ONLY={hole} OVERWRITE=1 python3 fetch_dem_hd.py\n"
            f"    COURSE={config.SLUG} ONLY={hole} python3 fetch_dem.py\n"
            f"    COURSE={config.SLUG} python3 fetch_hole_elev.py --write")
    if meta.get("insufficient"):
        return None            # no trustworthy surface -> no elevation claim either
    a = a_raw.astype(float)
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


def green_source(hole):
    """The dem_hd patch's OWN `source` for this hole, or None -- what the green height was measured on.

    Read here rather than assumed, because it is not one thing. 192 of the corpus's 198 surfaces are 0.4 m
    LiDAR ground returns; 6 come from the 3DEP seamless mosaic, because no LAZ tile covers those greens
    (monarch-bay 1, 9, 10, 16, 17 and 18). What is recorded is the patch's OWN `source` verbatim, not a
    reading of it -- fetch_dem.py has since stopped asserting a resolution it did not measure and now
    writes the source cell it measures per green, so the string will change under those six when they are
    rebuilt, and a row must follow its patch rather than a constant. The payload published "the green's
    own 0.4 m surface" for EVERY row regardless, and two of those six carry a row -- monarch-bay 9
    (suppressed under the print floor) and monarch-bay 16, whose card prints "green 8 ft above the tee".

    It is not only a wrong label. tools/verify_elevation.py checks each recorded height against the 3DEP
    seamless service, so on those two rows it compares that service against a patch BUILT FROM it and
    returns +0.0 -- indistinguishable from agreement, on the two greens whose surface has no independent
    check at all. Recording the real source per row is what lets the checker (and a reader) tell the
    difference. Kept out of green_elevation so that function's return type stays one number."""
    mp = f"{DIR}/dem_hd/hole{hole:02d}.json"
    if not os.path.isfile(mp):
        return None
    try:
        with open(mp, encoding="utf-8") as f:
            return json.load(f).get("source")
    except (OSError, ValueError):
        return None


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
    survey that came back thinner and a book that quietly stops printing a height it used to. It now
    really does waive that -- check_rows watched only for a row DISAPPEARING, so a row that survived and
    crossed the print floor took the line off its card with nothing to waive.
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

    AND A ROW CAN SURVIVE AND STILL STOP PRINTING. The comparison was over KEY SETS alone, and
    generate.elev_phrase suppresses any measured change under PRINT_FLOOR_FT as level -- so a hole going
    3.05 -> 2.95 ft keeps its key, passes this guard, and drops the line off its card with nothing raised
    and nothing printed. That is the same silent partial loss, through the one door this function did not
    watch, and it is live rather than hypothetical: 5 rows sit within 0.15 ft of it -- copper-valley 4 at
    +3.14, micke-grove 6 at +2.96, micke-grove 9 at -3.03, micke-grove 13 at -3.05 and the-reserve 10 at
    -2.95. So both kinds are refused, and ALLOW_ELEV_LOSS waives both, which is what _env_on's docstring
    has always claimed it waives.
    """
    prev = stored_rows(path)
    lost = sorted(int(h) for h in prev if h not in rows)
    silenced = sorted(int(h) for h, r in prev.items()
                      if h in rows and prints_a_height(r) and not prints_a_height(rows[h]))
    if not lost and not silenced:
        return
    bits = []
    if lost:
        bits.append("dropped: " + ", ".join(f"{h} ({prev[str(h)].get('change_ft')} ft)" for h in lost))
    if silenced:
        # the EXACT figures, both sides. `change_ft` is stored to 0.1 ft, so a row crossing the floor
        # reads "3.0 -> 3.0" there and the message would name a hole and then show it not moving.
        bits.append("fell under the %g ft print floor: " % PRINT_FLOOR_FT
                    + ", ".join(f"{h} ({_ft_str(prev[str(h)])} -> {_ft_str(rows[str(h)])} ft)"
                                for h in silenced))
    detail = "; ".join(bits)
    if not _env_on("ALLOW_ELEV_LOSS"):
        raise SystemExit(
            "REFUSING to write %s: hole(s) that printed a height in the stored file would print\n"
            "  none after this run -- %s.\n"
            "  Those cards would drop the elevation line with nothing to show a\n"
            "  measurement was lost -- the book stays self-consistent and legal/03's \"measured on N\n"
            "  of 18\" follows the loss down. Check that every laz/ tile is still on disk, that the\n"
            "  first tile's CRS still reads the same, and read the per-hole refusals printed above.\n"
            "  Set ALLOW_ELEV_LOSS=1 if the loss is real (a green rebuilt, a tee re-mapped)."
            % (path, detail))
    print("WARNING: ALLOW_ELEV_LOSS set -- hole(s) lose the height they had -- %s" % detail)


def prints_a_height(row):
    """Does this row put a height on a card? The floor generate.elev_phrase applies, on the UNROUNDED
    figure for the reason change_ft_exact exists: comparing a threshold against a value already rounded
    to 0.1 ft is how 2.956 ft once printed as "green 3 ft" under a gate that forbids anything under 3."""
    ft = _exact_ft(row)
    return ft is not None and abs(ft) >= PRINT_FLOOR_FT


def _exact_ft(row):
    """The unrounded change in feet, falling back to the 0.1 ft field for a row written before it
    existed -- the same order generate._hole_elev reads them in, so the two cannot disagree about which
    number a threshold sees."""
    ft = row.get("change_ft_exact")
    return row.get("change_ft") if ft is None else ft


def _ft_str(row):
    """`_exact_ft` for a message. A row can legitimately carry no figure at all -- that is what a hole
    losing its height looks like -- so this must not be a format string on None."""
    ft = _exact_ft(row)
    return "no figure" if ft is None else f"{ft:+.2f}"


def source_line(rows):
    """The payload's one-line `source`, BUILT from the rows so it cannot name a surface none of them used.

    The hand-written version said "USGS 3DEP LiDAR ground returns (class 2) vs the green's own 0.4 m
    surface" for every course, and it was false wherever a green's patch came from the 3DEP seamless
    mosaic -- monarch-bay 9 and 16 in this corpus. (Said "the 3DEP seamless 1 m DEM" until this round:
    that mosaic answered from a tier measuring 2.72 m E-W x 3.43 m N-S at every green this project has
    taken from it, so the label overstated it by about 9x in area.) Deriving it from `green_source`
    means the summary and
    the per-row field are one measurement rendered twice rather than two claims that can disagree, which
    is the fault this project keeps finding in pairs of records."""
    counts = collections.Counter(r.get("green_source") or "unrecorded" for r in rows.values())
    greens = "; ".join(f"{n} row(s) over {s}" for s, n in sorted(counts.items()))
    return ("USGS 3DEP LiDAR ground returns (class 2) at the tee, against the green's own built "
            f"surface -- {greens}")


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
    print(f"{config.SLUG}  ({len(holes)} holes, mapped pad in a {TEE_R_M:g} m window or a "
          f"{TEE_FALLBACK_R_M:g} m disc, Z x {vscale:g} -> m)")
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
                         "tee_region": tee_region,
                         # The spread of the sample the median came from, and the spread of the WHOLE
                         # mapped pad beside it. The gate bounds the first; the second is what an audit
                         # of "is that really a tee?" needs, and it was measurable only by re-running
                         # the sampler by hand. 7 pads differ across MAX_TEE_RELIEF_FT -- see the
                         # derivation beside that constant.
                         "tee_relief_ft": round(tz_n[4] * vscale * 3.28084, 3),
                         "tee_pad_relief_ft": (None if tz_n[5] is None else
                                               round(tz_n[5] * vscale * 3.28084, 3)),
                         # WHAT the green height was measured on, per row. The payload used to publish
                         # "the green's own 0.4 m surface" for all of them; see green_source.
                         "green_source": green_source(hn)}
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
        # WHAT WAS MEASURED, AND WHAT ACTUALLY GATED IT. This published
        # {"tee_radius_m": 15.0, "min_tee_points": 200} beside a source line naming a 0.4 m surface, and
        # all three were claims rather than records: nothing in the repo reads any of them, MIN_TEE_PTS
        # gated 5 of the corpus's 171 rows (the other 166 came off a mapped pad, where the gates are
        # MIN_RING_PTS and MAX_TEE_RELIEF_FT and the fallback floor is never consulted), and 2 rows are
        # measured over a patch built from the 3DEP seamless mosaic. So the gate set is published in
        # full, and the source line is BUILT from the rows -- one derivation, not a second copy to drift.
        # BOTH sampled regions are published, because there are two and a row names only its own: the
        # window for a mapped pad and the fallback disc's radius for an anchor in no ring.
        write_hole_elev(p, {"tee_window_m": TEE_R_M,
                            "tee_fallback_radius_m": TEE_FALLBACK_R_M,
                            "gates": {"min_pad_points": MIN_RING_PTS,
                                      "max_sample_relief_ft": MAX_TEE_RELIEF_FT,
                                      "min_fallback_points": MIN_TEE_PTS,
                                      "max_change_ft": MAX_PLAUSIBLE_FT,
                                      "print_floor_ft": PRINT_FLOOR_FT},
                            "source": source_line(rows),
                            "holes": rows})
        print(f"  wrote {os.path.relpath(p, config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
