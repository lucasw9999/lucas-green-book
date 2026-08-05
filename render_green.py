#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Render ONE green from real cached USGS elevation + OSM polygon.

Everything drawn is computed from measured USGS 3DEP elevation -- 0.4 m LiDAR
ground returns where available (1 m seamless DEM as an honest fallback):
  * downhill flow arrows = -gradient of the (denoised) surface
  * contour lines        = iso-elevation of the surface
  * slope heat           = |gradient|, fixed golf scale (0=flat green .. >=5%=red)
The whole drawing is rotated so the hole's APPROACH is at the bottom of the panel.

Honest limit, and it is NOT vertical noise. USGS quotes ~10 cm absolute vertical accuracy, but that
is a datum offset: it moves a whole green up or down together and changes no read, because break
depends on RELATIVE height inside the one green. Measured against a second independent survey of the
same greens, the smoothed surface these contours are drawn from repeats to RMS 0.85 cm (p95 1.86),
so the 15 cm interval is ~18x the noise -- see legal/09_GREEN_SURFACE_REPEATABILITY.md.
What genuinely cannot be resolved is SPATIAL and non-geometric. The smoothing is a Gaussian of sigma
3 PIXELS -- 1.20 m on a 0.4 m LiDAR grid, and about 1.5 m only on the six 0.5 m seamless greens --
and what it erases is set by its measured amplitude response, not by that sigma: it keeps 0.0002 at
1.5 m, 0.17 at 4 m, 0.32 at 5 m and 0.50 at 6.4 m, so the half-amplitude wavelength is 6.4 m. A 5 m
hollow is drawn a third as deep as it is, and anything much under 6 m across is gone. This paragraph
understated that as "about a metre and a half" for a long time -- 4.3x out, in the one place whose job
is to bound what the book cannot see. On top of the geometry, no elevation model knows grain, firmness,
moisture, mowing direction or a fresh hole location. So this reads real tilt and tiers, never sub-inch
break -- that still needs an on-site survey and your own eyes.
"""
import json, math, os
import numpy as np
import config
import surface_io
from geo import mlat, mlon          # the project's ONE figure of the Earth -- never re-declare these

DEM = os.path.join(config.COURSE_DIR, "dem_hd")

def gauss(a, sig_px):
    r = max(1, int(sig_px*3)); x = np.arange(-r, r+1)
    k = np.exp(-(x**2)/(2*sig_px*sig_px)); k /= k.sum()
    a = np.apply_along_axis(lambda m: np.convolve(m, k, 'same'), 0, a)
    a = np.apply_along_axis(lambda m: np.convolve(m, k, 'same'), 1, a)
    return a

def erode(mask, n):
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:,:]  &= m[:-1,:]; e[:-1,:] &= m[1:,:]
        e[:,1:]  &= m[:,:-1]; e[:,:-1] &= m[:,1:]
        m = e
    return m

def poly_to_px(poly, bbox, W, H):
    xmin, ymin, xmax, ymax = bbox
    return [((lon-xmin)/(xmax-xmin)*W, (ymax-lat)/(ymax-ymin)*H) for lat, lon in poly]

def point_in_poly(x, y, poly):
    inside = False; n = len(poly); j = n-1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi):
            inside = not inside
        j = i
    return inside

# Strength the heat layer is composited at. It is NOT full: the contours, the flow arrows, the slope
# numbers and the outline are all drawn OVER these cells, and at full strength the dark-red end
# swallows the line work the reader has to follow across it.
#
# A CONSTANT, and referenced by name everywhere, because it decides what reaches PAPER. Every cell
# prints 255 - HEAT_OPACITY*(255 - c) per channel over white, so the ramp's own RGB is a colour the
# book never puts on a page. Two things were grading the intent instead of the ink while this was a
# literal buried in an f-string: the mono-print gate believed it had 5.69 grey levels of headroom
# over its 6.0 bar when the truth is 1.25, and the guide card drew its three key swatches at full
# strength -- so the reddest cell any map can draw printed nearer the 2.5% swatch than the 5% one.
HEAT_OPACITY = 0.62

def heat_color(slope_pct):
    """Green -> amber -> red by steepness, with LIGHTNESS that falls monotonically.

    The ramp used to brighten to a pale yellow at the 2.5% midpoint before darkening to red, so its
    grey value FOLDED: 0.00% and 3.65% both printed grey 170. On a home mono printer -- which is how a
    junior actually prints this -- dead flat and a severe slope were the same shade, and 26% of all
    heat cells in the shipped books collided with a slope at least 1.5 points different. Worse, the
    legend inverted: a 3.6% cell matched the FLAT swatch.

    Fixed by darkening the mid and end stops so luminance falls 189 -> 62 with no reversal, which
    keeps the colour reading identical (hues still 120 deg green, amber, red) while making the
    grayscale print monotonic. Geometry is untouched, so no scale, layout, or Rule 4.3 measurement
    moves.

    ON PAPER that is at least 7 grey levels per 1.5 points of slope, not the 11.69 the stops
    themselves separate. These values never print: render() composites the heat layer at
    HEAT_OPACITY over white, so the page runs grey 214.3 -> 135.8 where the ramp runs 189.3 -> 62.8,
    and the worst 1.5-point separation is 7.25. This docstring published the 11 for a long time --
    the figure a restyler would tune against, in the one place it is written down, describing a
    colour the book does not print. Ordering and monotonicity survive the composite exactly (it is a
    positive linear scale), so no shipped read ever inverted from this; the headroom did not survive.
    """
    t = min(max(slope_pct/5.0, 0), 1)
    stops = [(0.0,(150,205,150)),(0.5,(206,170,60)),(1.0,(150,40,32))]
    for a in range(len(stops)-1):
        t0,c0 = stops[a]; t1,c1 = stops[a+1]
        if t <= t1:
            f = 0 if t1==t0 else (t-t0)/(t1-t0)
            c = tuple(int(c0[k]+(c1[k]-c0[k])*f) for k in range(3))
            return f"rgb({c[0]},{c[1]},{c[2]})"
    return "rgb(210,90,70)"

def rot(x, y, cx, cy, deg):
    a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
    dx, dy = x-cx, y-cy
    return (cx + dx*ca - dy*sa, cy + dx*sa + dy*ca)

# 1/sqrt(2), NOT 0.71. These eight vectors are compared by DOT PRODUCT against a unit downhill
# vector, so the winner is the longest PROJECTION and they must all be the same length or the
# comparison is rigged: hypot(0.71, 0.71) = 1.00409, which made every diagonal out-project every
# cardinal by 0.41% and moved the cardinal/diagonal sector boundary from 22.500 to 22.218 degrees --
# eight "octants" alternately 44.44 and 45.56 degrees wide. Two of 198 greens sat inside that
# 0.282-degree band and printed the FARTHER word: castlewood-valley 13 printed "front-right" over
# "front" (dots 0.926871 against 0.924661) and the-reserve 8 "back-right" over "right" (0.926260
# against 0.925261), telling a reader the ball feeds off a corner where the fall is square to the
# front edge. Do not re-round these to two decimals to tidy the line up.
SQ2 = math.sqrt(0.5)
DIRS = [(0,-1,"back"),(SQ2,-SQ2,"back-right"),(1,0,"right"),(SQ2,SQ2,"front-right"),
        (0,1,"front"),(-SQ2,SQ2,"front-left"),(-1,0,"left"),(-SQ2,-SQ2,"back-left")]


def screen_m_per_unit(theta, px_x, px_y):
    """(mx, my): ground METRES per view unit along the rotated frame's x and y axes.

    ONE home for the conversion every printed green size goes through, because there were two and both
    were wrong the same way. A DEM pixel is not square: fetch_dem_hd derives W and H from the bbox's
    metric extent and truncates each to a whole pixel independently, so px_x/px_y runs 0.99157 to
    1.00813 across the corpus. Both call sites multiplied a chord by the SCALAR mean (px_x + px_y)/2,
    and a chord that runs in an arbitrary direction across an anisotropic grid does not scale by the
    mean of the two axes -- it scales by the axes decomposed along its own direction.

    Measured against the ground length of the very line the card measured, the scalar mean was out by a
    median 0.019 yd, p95 0.082 and worst 0.109 (0.413% relative), and three printed depths landed on the
    wrong side of a half yard: copper-valley 16 printed 36 against 36.595, merion 14 printed 38 against
    38.531, micke-grove 13 printed 19 against 19.506. Seven widths move too; width_yd reaches no card
    today. Done per axis the agreement is exact to 1.5e-5 yd AGAINST THE TRUE WGS84 GEODESIC of that
    line, over all 198 greens -- which is the ground, and naming the reference is the point.

    It did not used to be the ground. This figure was once quoted against the engine's own sphere of
    111320 m/deg, and that sphere is neither of the ellipsoid's radii: it ran +0.295% long in latitude
    and -0.125% short in longitude, an error LARGER than the anisotropy corrected here, and it put four
    of 198 printed depths on the wrong side of a half yard. So an exactness against it read as agreement
    with the ground and was agreement with the assumption. Both axes now come from `geo.mlat`/`geo.mlon`,
    the project's single figure of the Earth, so this card's depth, its tilt %, its printed 5-yd bar, its
    Rule 4.3 sizing and its hole map are all on one earth; geo.py holds the measurement.

    The six seamless greens are NOT among the movers of the ANISOTROPY fix and must not be: their
    recorded bbox is metre-consistent to within 0.08%, so their per-axis conversion was already right.
    Two earlier attempts at that fix measured "ground truth" on a different figure of the Earth -- a
    0.3% error, larger than the anisotropy -- and "corrected" those six on the strength of it. The two
    errors are genuinely different and keeping them apart is still the point: the anisotropy is the
    RATIO of the two pixel axes, the datum is their absolute SIZE. The datum error has since been
    corrected on its own terms, which is why one seamless green (monarch-bay 1) does move here.

    Takes the two SCREEN axes rather than a single direction because that is what the card measures
    along: depth and the 5-yd ladder run down screen y (the line of play), width across screen x.
    """
    ux, uy = rot(1.0, 0.0, 0.0, 0.0, -theta)      # screen +x, as a vector in pixel space
    vx, vy = rot(0.0, 1.0, 0.0, 0.0, -theta)      # screen +y
    return math.hypot(ux*px_x, uy*px_y), math.hypot(vx*px_x, vy*px_y)

def play_line_span(rp):
    """(front_y, back_y, midx) for a rotated green: where the LINE OF PLAY enters and leaves it.

    The datum for everything the card says about depth. It used to be the rotated polygon's BOUNDING
    BOX -- max(rys) to min(rys) -- and on a green set square to the approach those are the same thing,
    which is why it survived. On a green set DIAGONALLY they are not: the frontmost and backmost
    vertices are corners on opposite sides of the green, and the box spans far more than the green is
    deep anywhere a ball actually lands.

    castlewood-valley 14 is the worked case. A 125 yd par 3 whose green is a clean parallelogram lying
    ~45 degrees across the approach: the card printed "41yd deep" and ruled its grey ladder out to 40,
    on a green that is 20 yd deep down the line the pin ring sits on. That is two clubs of margin for a
    back pin, on the shortest hole of the round -- the single largest thing this book has told a reader
    that its own drawing contradicts. Corpus-wide 87 of 198 greens printed a depth 3+ yd too deep and
    53 were 5+ yd too deep.

    The box was also the ladder's ZERO, so the two errors compounded: on castlewood-valley 14 the front
    corner sits 14.8 yd nearer the approach than the front edge at the middle, so a reader standing on
    the front-middle was already reading ~15 on a ladder captioned "yd from the front edge".

    Measuring at the lateral middle fixes both with one number, and it is the line the reader plays:
    the pin ring is drawn on it, and the ladder now zeroes where the printed depth starts, so the
    headline figure and the top rung cannot disagree. The centre line crosses the outline exactly
    twice on all 198 greens in the corpus, so this is single-valued everywhere -- it is not picking
    an outer extent across a notch.
    """
    rxs = [q[0] for q in rp]
    midx = (min(rxs) + max(rxs)) / 2.0
    ys, n = [], len(rp)
    for i in range(n):
        x1, y1 = rp[i]; x2, y2 = rp[(i+1) % n]
        if (x1 > midx) != (x2 > midx):
            ys.append(y1 + (y2-y1)*(midx-x1)/(x2-x1))
    if len(ys) < 2:
        # Provably unreachable for any real green: ys counts state transitions of (x > midx) around a
        # closed ring, so its length is exactly even, and midx lies strictly between min and max
        # whenever they differ -- so there is at least one transition. The only trigger is a ring with
        # zero lateral extent after rotation, which is not a polygon. Raise rather than fall back to the
        # bounding box: the box is the very measure this function exists to replace, and returning it
        # silently would print a depth that is wrong in exactly the way the card claims to have fixed.
        raise ValueError("green ring has no lateral extent in the approach frame; cannot measure depth")
    # PAIRS, not extremes. max(ys), min(ys) was the same min/max-of-crossings pattern that this commit
    # replaced 40 lines below in xspans(), where it drew a ladder rung straight across a concavity.
    # A green bitten on one side crosses the play line four times, and taking the extremes would report
    # the notch as green: on a synthetic bite 33% of the printed span was outside the outline, and the
    # pin ring -- drawn at the middle of this span -- landed outside its own green. No corpus green
    # crosses more than twice today, but 55 of 198 already have a four-crossing band, the nearest just
    # 3.12 yd from the play line on merion 9 where the interior gap is 21.3 yd. That is one OSM re-trace
    # away, and midx itself is set by the two most extreme vertices -- precisely the ones a re-trace moves.
    #
    # Take the LONGEST interior run: the green's main body, which is what a player is aiming at and
    # putting across. Identical to max/min on every green in the corpus.
    ys.sort()
    runs = [(ys[i+1] - ys[i], ys[i], ys[i+1]) for i in range(0, len(ys) - 1, 2)]
    _len, lo, hi = max(runs)
    return hi, lo, midx                   # approach edge is at the bottom, so front = max


def bank_run_yd(from_y, to_y, midx, cx, cy, theta, slope, my, step=0.01):
    """Yards of the play line, from the mapped edge at `from_y` inward toward `to_y`, that are NOT
    putting surface. ONE walk, called at BOTH ends of every green.

    The depth and the 5-yd ladder both zero at where the OSM green polygon crosses the line of play,
    and at either end that crossing can be on ground steeper than SLOPE_LABEL_MAX_PCT -- which this
    module and the card's own legend both call "bank or bunker face, not putting surface". So the card
    stated "22yd deep", ruled rungs at 5/10/15/20 from that edge, and said nothing about the bank the
    first rung sits on top of. Walked at 0.01 view-unit steps, the leading run over 10%:

        FRONT, 9 of 198 >= 1 yd: micke-grove 2 5.33 of 22 yd (24%), copper-valley 6 3.58 of 24,
        castlewood-valley 16 3.21 of 30, castlewood-hill 10 3.15 of 28, castlewood-valley 12 2.64 of
        40, merion 6 2.32 of 34, philadelphia 18 2.28 of 37, bay-view 13 1.31 of 22, bay-view 5 1.13
        of 27.

        BACK, 14 of 198 >= 1 yd: copper-valley 3 6.51 of 30 (22%), castlewood-valley 5 3.91 of 27,
        bay-view 5 3.06 of 27, copper-valley 6 2.51 of 24, bay-view 16 2.08 of 27, castlewood-hill 14
        2.03 of 24, castlewood-valley 10 1.86 of 39, merion 13 1.68 of 22, castlewood-valley 11 1.55
        of 32, copper-valley 18 1.46 of 18, the-reserve 1 1.45 of 30, castlewood-hill 11 1.12 of 18,
        castlewood-valley 3 1.09 of 34, merion 10 1.06 of 29.

        Median green at either end: 0.00. It is a tail, not a corpus-wide bias.

    THE BACK END IS THE MORE DANGEROUS ONE and it was disclosed second, which is the wrong order. A
    front bank makes the printed depth and the ladder start early -- it OVERSTATES how much green
    there is in front of the pin. A back bank overstates how far BACK the pin can be, and this file
    already names too-long as the dangerous direction: a junior reading "30yd deep" on copper-valley
    3 clubs for a pin up to 30 yd deep when the last 6.51 of those yards are a bank the ball will not
    hold. Two of the 21 affected greens have BOTH (copper-valley 6, bay-view 5).

    THIS DOES NOT MOVE THE DATUM, and that is measured rather than preferred. Re-basing depth on
    S['putt'] -- the obvious fix -- moves all 198 printed depths by a median 2.74 yd and up to 9.64,
    because `putt` is `erode(mask, 3) & (slope <= 10)` and the erosion trims 1.2 m of collar off BOTH
    ends of every green: a device for fitting a plane, not a statement about where the green stops.
    Trimming just the leading steep run moves 12 depths, both ends 28. Either would put the printed
    depth off the drawn OUTLINE, which runs through that same bank because it IS the polygon, and would
    cost the depth its independent check -- tests grade every printed depth against the true WGS84
    geodesic of its own chord to 1e-4 yd, and that only works while depth is a pure function of the
    polygon. The polygon is also what render_hole projects green_front_yd from, so one datum serves the
    hole map and the green card.

    So the geometry is unchanged and the CARD says the bank is there, at both ends, from one walk and
    one phrase (generate.bank_span) so the two editions and the two ends cannot drift into four
    idioms. generate.py prints each end when it rounds to a yard or more; below that it is under the
    resolution the depth is printed at.

    No mask test in the walk. `play_line_span` returns the longest INTERIOR run of the centre line, so
    every sample between the two edges is inside the polygon by construction, while the rasterised
    mask needs a pixel CENTRE inside and so drops pixels along the boundary: testing it made merion 6
    read 0.35 yd instead of 2.32, stopping the run on a rasterisation artifact one third of a yard in.
    """
    H, W = slope.shape
    span = abs(from_y - to_y)
    sgn = 1.0 if to_y > from_y else -1.0        # walk INWARD, whichever edge we started from
    n = max(2, int(span/step))
    run = 0.0
    for i in range(n+1):
        yy = from_y + sgn*span*i/n
        px, py = rot(midx, yy, cx, cy, -theta)
        ri, ci = int(py), int(px)
        if not (0 <= ri < H and 0 <= ci < W):
            break
        if slope[ri, ci] <= SLOPE_LABEL_MAX_PCT:
            break
        run = span*i/n
    return run*my/0.9144


def approach_frame(meta):
    """(theta, cx, cy) that turn a green's PIXEL polygon so the approach is at the bottom of the panel.

    One home for the rotation, because a card that states the same green in two frames is the defect
    this replaces. `_blank_green` drew `poly_to_px(...)` raw -- north-up, no rot() anywhere in it --
    while the depth and width printed beside the drawing came from depth_width_yd, which rotates. The
    outline was byte-identical at every approach bearing while the numbers moved with it (19x34 at 0
    deg against 36x20 at 243 deg on merion 1), and the card still stamped "approach" at the bottom of
    the panel. Over 198 green metas the drawn vertical extent missed the printed depth by a median
    3.25 yd; the-reserve 13 drew 37.7 x 19.8 against a printed 17 x 33, a transpose.
    """
    B = meta['approach_bearing']
    # approach direction as a pixel vector: east=+col, north=-row -> (sinB, -cosB)
    a_ang = math.degrees(math.atan2(-math.cos(math.radians(B)), math.sin(math.radians(B))))
    return -90.0 - a_ang, meta['W'] / 2.0, meta['H'] / 2.0


def depth_width_yd(meta):
    """(depth, width) in yards, measured in the APPROACH frame -- front-to-back is depth.

    Both card paths must use this. _blank_green measured depth from the raw LATITUDE extent, i.e.
    north-to-south, regardless of which way the hole plays; render() measures it after rotating the
    approach to point up. On a hole that plays east-west the two are the depth and the width
    swapped. Corpus-wide the disagreement ran to 18 yards -- two clubs -- with 32 greens off by more
    than 30%, and callippe h6 printing 42 x 29 where the truth is 22 deep x 43 wide.

    Nothing shipped hits it today (no built green is blank), but the whole point of the blank card is
    the case where a course has no usable LiDAR, and then it fires on all 18 holes at once."""
    poly = poly_to_px(meta['polygon'], meta['bbox'], meta['W'], meta['H'])
    W, H = meta['W'], meta['H']
    xmin, ymin, xmax, ymax = meta['bbox']
    clat = meta['green_center'][0]
    theta, cx, cy = approach_frame(meta)
    # per AXIS, never by a scalar mean of the two -- see screen_m_per_unit
    mx, my = screen_m_per_unit(theta, (xmax - xmin) * mlon(clat) / W, (ymax - ymin) * mlat(clat) / H)
    rp = [rot(x, y, cx, cy, theta) for x, y in poly]
    rxs = [p[0] for p in rp]
    fy, by, _midx = play_line_span(rp)
    return ((fy - by) * my / 0.9144, (max(rxs) - min(rxs)) * mx / 0.9144)


def _blank_green(meta, tournament, rebuilt=False):
    """A green we will NOT read. Draw the real outline -- that geometry IS measured, it comes from
    OSM -- with ruled lines to mark your own read, and say plainly why there are no arrows. Printing
    invented or expired contours here would be the one thing this project promises never to do.

    Two reasons, and only the first one currently happens:

    * `rebuilt=False` -- the LiDAR never measured this surface (fetch_dem_hd.py's honesty gate). This
      is the live path.

    * `rebuilt=True` -- the green was rebuilt after the flight, so real measured data describes a
      surface that no longer exists. NOTHING REACHES THIS TODAY, and that is deliberate, not an
      oversight. It is NOT what `greens_possibly_outdated` does: a green whose rebuild is merely
      SUSPECTED still has genuinely measured data, so the policy is to print the map and label it
      "pre-rebuild data" with a warning mark rather than withhold it -- see the comment at the
      `insufficient` check in render(), which is where that decision lives. philadelphia 10-18 are
      the nine greens in that state; the Flynn restoration is phased and whether it has reached the
      back nine is unknown, so a hedged read beats no read.
      This branch is for a green whose rebuild is CONFIRMED, per green. Nothing in the corpus is in
      that state today (the one course awaiting post-rebuild data is built in yardage mode, which
      prints no green panels at all, so this function is never called for it).
      Kept rather than deleted because the capability is real -- a course with some confirmed-rebuilt
      greens and some current ones cannot be handled by yardage mode, which is all-or-nothing -- and
      its behaviour is pinned by test_a_confirmed_rebuild_says_so_rather_than_no_coverage so that it
      works the day it is wired up. An earlier version of this docstring named the rebuild case
      first, which read as though a suspected rebuild were blanked; that is the opposite of the
      policy, in the same module.
    """
    poly = poly_to_px(meta['polygon'], meta['bbox'], meta['W'], meta['H'])
    # ROTATED, like every other statement this card makes. The depth and width printed below come from
    # depth_width_yd, which measures in the approach frame, and the panel stamps "approach" at its
    # bottom edge -- so an unrotated outline made the drawing disagree with both. See approach_frame.
    _theta, _cx, _cy = approach_frame(meta)
    poly = [rot(x, y, _cx, _cy, _theta) for x, y in poly]
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    pad = 8
    VBx, VBy = min(xs)-pad, min(ys)-pad
    VBw, VBh = (max(xs)-min(xs))+2*pad, (max(ys)-min(ys))+2*pad
    d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in poly) + " Z"
    lines = "".join(
        f'<line x1="{VBx+4:.1f}" y1="{VBy+VBh*0.42+i*7:.1f}" x2="{VBx+VBw-4:.1f}" '
        f'y2="{VBy+VBh*0.42+i*7:.1f}" stroke="#cfcfcf" stroke-width="0.5"/>' for i in range(4))
    if tournament:
        # no scale claim is needed (no green image is drawn to scale), so just fit the panel
        grn_w_in = (config.CARD_W_IN - 2*0.07 - 1/96) * (2.4/4.0)
        grn_h_in = config.CARD_H_IN - 2*0.07 - 0.50 - 0.18
        kf = min(grn_w_in/VBw, grn_h_in/VBh)
        wattr, hattr = f'{VBw*kf:.3f}in', f'{VBh*kf:.3f}in'
        wrapopen = ('<div style="display:flex;align-items:center;justify-content:center;'
                    'width:100%;height:100%">'); wrapclose = '</div>'
    else:
        wattr = hattr = '100%'; wrapopen = wrapclose = ''
    msg = "rebuilt after survey" if rebuilt else "no LiDAR coverage"
    svg = (f'{wrapopen}<svg viewBox="{VBx:.1f} {VBy:.1f} {VBw:.1f} {VBh:.1f}" '
           f'style="width:{wattr};height:{hattr}" preserveAspectRatio="xMidYMid meet">'
           f'<path d="{d}" fill="#f4f7f4" stroke="#20402a" stroke-width="1.3"/>{lines}'
           f'<text x="{VBx+VBw/2:.1f}" y="{VBy+VBh*0.30:.1f}" font-size="4.4" text-anchor="middle" '
           f'fill="#b02418">{msg}</text>'
           f'<text x="{VBx+VBw/2:.1f}" y="{VBy+VBh*0.36:.1f}" font-size="3.6" text-anchor="middle" '
           f'fill="#777">mark your own read</text>'
           f'<text x="{VBx+VBw-2.5:.1f}" y="{VBy+VBh-2.5:.1f}" font-size="4" text-anchor="end" '
           f'fill="#333">&#9650; approach</text></svg>{wrapclose}')
    d_yd, w_yd = depth_width_yd(meta)          # approach frame, same as the measured card
    depth_yd = int(round(d_yd)); width_yd = int(round(w_yd))
    return svg, dict(relief_ft=0.0, median_slope=0.0, tilt_pct=0.0,
                     feeds=("rebuilt since survey" if rebuilt else "not surveyed"),
                     undul_ft=0.0, conf="no data", depth_yd=depth_yd, width_yd=width_yd,
                     front_bank_yd=0.0, back_bank_yd=0.0,
                     scale_max_in=None, insufficient=True)


# Render-time gate. Deliberately looser than fetch_dem_hd.py's producer gate (NAN_FRAC_MAX=0.02):
# this is a backstop against an ungated or corrupt surface, not a quality bar, so it must not blank
# a green the sharper producer already accepted.
CINT_M = 0.15                   # contour interval; the card's legend states "15 cm each"
SLOPE_LABEL_MAX_PCT = 10.0      # above this a cell is not putting surface -- colour it, do not number it
NAN_FRAC_MAX_RENDER = 0.25      # >25% of the green interior with no elevation at all
MIN_RELIEF_M = 0.05            # a green flat to within 5 cm is a zero-fill, not a green
MAX_PLAUSIBLE_RELIEF_M = 30.0   # 98 ft of fall inside one green outline is a data artifact
# Sentinel for a green whose fall direction the data does not determine; generate.py prints it
# instead of a compass word, and never inside "feeds ...", which would be a claim.
NO_CLEAR_FALL = "no clear fall"


def green_summary(arr, mask, px_x, px_y, putt=None):
    """Every number the green card prints, derived from a filled elevation grid.

    ONE home on purpose. `tools/cross_flight_check.py` re-derives these figures from a single
    flight's points to prove the printed read does not depend on which survey supplied it; if it
    computed the plane its own way, the check would drift away from the card it claims to verify
    the moment either side changed. Returns (surf, core, dict) -- the smoothed surface and the
    collar-trimmed core as well, because the SVG draws from them.

    `putt` overrides which cells count as putting surface. The card never passes it: it must derive
    that from the surface in front of it. It exists for a controlled comparison of TWO surfaces of
    the same green, where each would otherwise classify slightly different cells as steep and the
    comparison would measure the reclassification instead of the difference in the ground.
    """
    surf = gauss(arr, 3.0)                       # sigma 3 px = 1.20 m at 0.4 m sampling
    core = erode(mask, 3)                        # trim collar: 3 px, 1.20 m at 0.4 m sampling
    if core.sum() < 20: core = mask

    gy, gx = np.gradient(surf, px_y, px_x)       # dz/d(row=south), dz/d(col=east) per meter
    slope = np.hypot(gx, gy)*100.0
    # downhill in PIXEL space (col+ = east/right, row+ = south/down): -gradient
    dcol = -gx; drow = -gy

    # --- robust summary: least-squares plane over the green core ---
    # relief and median slope describe the WHOLE core, because they report the ground as it is.
    zc = surf[core]
    relief_m = float(zc.max()-zc.min()) if core.any() else 0.0
    med_slope = float(np.median(slope[core])) if core.any() else 0.0

    # The plane BEHIND THE PRINTED READ is fitted to putting surface only. Cells steeper than
    # SLOPE_LABEL_MAX_PCT are dropped because that is already this renderer's definition of ground
    # that is not a puttable read -- and the card's own legend says so to the reader: "ground over
    # 10% is shown by colour only". Fitting the headline tilt and feed direction to ground the same
    # card disowns two lines lower was an internal contradiction.
    #
    # It matters because a green outline comes from OpenStreetMap, and one drawn a little generously
    # laps onto the surrounding bank; erode(mask, 3) trims only ~1.2 m of collar, while such a bank
    # reaches 8 m inside the outline. philadelphia 18 is the worked case -- 21% slope, 4.1 cm of
    # surface texture against 1.2 cm over the rest of the green, sitting 0.9 ft above it, which is a
    # bank and not a green -- and including it printed "3.6%, feeds LEFT" where the putting surface
    # alone reads "2.6%, feeds FRONT-LEFT". Corpus-wide this moves 32 printed tilts (the median green
    # not at all, 0.4% of its polygon being steep) and 7 feed directions, which is the figure that
    # tells a player which way the ball rolls.
    #
    # Fall back to the whole core if the exclusion leaves too little to fit: a genuinely steep green
    # must still get a read rather than silently lose one. No green in the corpus needs it today.
    fit = core & (slope <= SLOPE_LABEL_MAX_PCT) if putt is None else (core & putt)
    if fit.sum() < 20:
        fit = core
    rr, cc = np.where(fit)
    Xe = cc*px_x                     # east meters
    Yn = -rr*px_y                    # north meters (row+ is south)
    A = np.c_[Xe, Yn, np.ones(len(Xe))]
    (a, b, d0), *_ = np.linalg.lstsq(A, surf[fit], rcond=None)
    tilt_pct = math.hypot(a, b)*100.0                 # dominant plane tilt
    resid = surf[fit] - A.dot([a, b, d0])
    undul_ft = float((resid.max()-resid.min()))*3.28084 if len(resid) else 0.0
    # plane downhill in pixel space: east=+col -> dcol=-a ; north=-row -> drow=+b
    pdc, pdr = -a, b
    # Confidence, half one: is there enough FALL across the green for the side to be worth playing?
    # tilt_pct is the plane's slope in its OWN downhill direction, so the fall available is that slope
    # times the width of the putting surface ALONG that direction. This used to multiply it by
    # hypot(Xe.ptp(), Yn.ptp()) -- the bounding-box DIAGONAL of the fitted cells, a distance in a
    # direction the green does not fall along -- which overstated the real fall on 198 of 198 greens:
    # median 1.34x, p90 1.75x, worst 2.37x, support along the downhill p50 24.4 m against a bbox
    # diagonal p50 34.1 m. Computed this way it is exactly the fitted plane's own drop between the two
    # most separated cells it was fitted to.
    # The old form also left this test DEAD -- all 6 greens that failed rise_ft >= 0.8 failed
    # tilt_pct >= 1.2 as well, so it changed no label anywhere. Honestly computed it moves two:
    # the-reserve 10 (1.25% tilt, gate saw 1.267 ft where the plane falls 0.730) and valley-hi 14
    # (1.23%, 1.103 against 0.795), both of which printed `clear` against this code's own 0.8 ft bar.
    grad = math.hypot(a, b)
    if grad > 0 and len(Xe):
        along = (Xe*a + Yn*b) / grad     # metres along the plane's own downhill line
        span_m = max(float(along.max() - along.min()), 1.0)
    else:
        span_m = 1.0
    rise_ft = tilt_pct/100.0*span_m*3.28084
    # Tested against the UNROUNDED tilt, while the card prints it to one decimal. When the card marked
    # every green, that showed: six of 198 printed "1.2%", three of them "(firm)" and three "(subtle)",
    # and a reader could not see why -- a true tilt of 1.24 against 1.16, plus the rise test, neither of
    # which the card shows. Only the exception is marked now, and adding the FALL half of the gate
    # widened the band by one step: measured off the shipped books, the ambiguity is confined to
    # whether a 1.2% or 1.3% green carries "(faint)". 1.2% prints three marked (castlewood-valley 14,
    # copper-valley 17, valley-hi 14) against three unmarked (castlewood-valley 8, the-reserve 5,
    # valley-hi 11), and 1.3% one marked (the-reserve 10) against two unmarked (micke-grove 1,
    # monarch-bay 2) -- the-reserve 10 being a green that clears 1.2% of tilt and fails the 0.8 ft
    # fall. Two of the 54 distinct percentages the books print, 9 of 198 greens; the reasoning below
    # is unchanged.
    #
    # Do NOT "fix" that by comparing round(tilt_pct, 1) >= 1.2. It looks like consistency and is a
    # loosening: the effective floor becomes 1.15%. The gate being more precise than the display is the
    # right way round for a book whose rule is never to print a read the data does not support. The
    # qualifier is also not a function of the printed number at all -- it depends on the FALL as well as
    # the tilt -- so tying it to one decimal would make it less informative to look more tidy.
    #
    # 1.2% IS NOT A NOISE FLOOR, and this comment said it was for a long time -- as did legal/09 and,
    # worst, the legend a junior reads. The plane fit is nowhere near the survey's noise at 1.2%:
    # legal/09's worst cross-flight disagreement over 33 twice-surveyed greens is 0.05 pp of tilt and
    # 3.7 degrees of aim, so this threshold stands 24x above the largest tilt disagreement two
    # independent surveys of one green have ever produced here, and the corpus's faintest printed green
    # -- 0.3% -- is still 6x above it. At 3.7 degrees a 45-degree sector is never in doubt, so "trust
    # the side less" was advice against the evidence.
    # What the threshold actually tracks is whether ONE PLANE IS AN ADEQUATE MODEL of the green.
    # Measured over the shipped corpus, R^2 of this fit over the putting surface: `clear` greens p05
    # 0.61, median 0.90; `faint` greens p05 0.02, median 0.44. So a faint green is not badly measured,
    # it is a green a single tilt describes badly -- tiers and hollows one word cannot carry -- which is
    # why the legend now sends the reader to the arrows instead of away from the compass word.
    # The VALUES are "clear"/"faint", not "firm"/"subtle". This gate measures whether one plane is a
    # fair description of the green and whether it drops far enough to matter -- it is a statement about
    # the EVIDENCE. Printed as "(firm)", a golfer reads a statement about the TURF, which is the one
    # thing this module's own docstring says it cannot know: "no elevation model knows grain, FIRMNESS,
    # moisture, mowing direction or a fresh hole location". The book disclaimed firmness in prose and
    # then printed "firm" 220 times beside a slope percentage, on every one of 252 green footers, with
    # no definition in either legend -- and on two of the fourteen books all 18 greens said it, so it
    # carried no information at all while looking like a turf claim. "clear"/"faint" describe what was
    # actually tested, and they join a vocabulary the guide card already explains, ending at
    # NO_CLEAR_FALL: clear fall -> faint -> no clear fall.
    conf = "clear" if (tilt_pct >= 1.2 and rise_ft >= 0.8) else "faint"
    return surf, core, dict(slope=slope, dcol=dcol, drow=drow, relief_m=relief_m,
                            med_slope=med_slope, tilt_pct=tilt_pct, undul_ft=undul_ft,
                            pdc=pdc, pdr=pdr, span_m=span_m, rise_ft=rise_ft, conf=conf,
                            putt=fit)


def render(hole, tournament=False):
    mp = f"{DEM}/hole{hole:02d}.json"
    if not os.path.exists(mp):
        # Every other stage in this pipeline explains itself; this one used to die with a bare
        # FileNotFoundError from json.load, several frames deep, naming a path and nothing else.
        # The situation is ordinary: fetch_dem_hd.py builds only the greens with usable LiDAR
        # ground returns, and the ones it refuses need the 1 m seamless fallback. Monarch Bay has
        # six such holes, so running generate.py without fetch_dem.py hits this every time.
        raise SystemExit(
            f"hole {hole} of {config.SLUG} has no green surface ({os.path.relpath(mp, config.ROOT)}).\n"
            f"  fetch_dem_hd.py builds only greens with usable 0.4 m LiDAR ground returns; the rest\n"
            f"  need the 1 m seamless fallback. Run both, then rebuild:\n"
            f"    COURSE={config.SLUG} python3 fetch_dem_hd.py\n"
            f"    COURSE={config.SLUG} python3 fetch_dem.py\n"
            f"    COURSE={config.SLUG} python3 generate.py")
    meta = json.load(open(mp))
    # Only refuse when there is genuinely NOTHING measured under the green (fetch_dem_hd.py
    # honesty gate) -- then there is no surface to draw at all. A green that was rebuilt AFTER
    # the flight still has real measured data; it is just possibly out of date, so we print the
    # map and label it (see greens_possibly_outdated in generate.py) rather than dropping it.
    if meta.get("insufficient"):
        return _blank_green(meta, tournament)
    raw = np.load(f"{DEM}/hole{hole:02d}.npy")
    arr = raw.astype('float64')
    # THE PAIR MUST AGREE. The array carries no georeference: H,W come from it, but the bbox, the ring
    # and the centre all come from the meta, so an array that is not the one this meta describes is
    # rasterised against ground its pixels do not cover -- and the card then prints a slope for it. That
    # is the shipped monarch-bay defect (mask stretched ~26% past the green, printed tilt inflated 16.6%
    # to 52.5% on six cards), and nothing downstream can catch it: check_scale.py and
    # cross_flight_check.py re-derive metres-per-pixel from this same meta and inherit the error.
    # surface_io.commit_surface stages both files so an interrupted build cannot tear them apart; this
    # is the read-side half, which also covers a pair torn before that existed or restored by hand.
    #
    # TWO checks, because the shape one is shape-blind by construction. commit_surface's two os.replace
    # calls are not one transaction, and the interesting tear is the one where the shapes MATCH and the
    # bbox does not -- reachable because W and H truncate metres to whole pixels, so a green whose
    # polygon moves or resizes by less than one pixel keeps them. That case passed the W,H test and
    # printed a wrong slope in silence. The digest catches it: it is of the array's CONTENT, so it does
    # not care that the shapes agree.
    #
    # A MISSING digest is an error too, and it used to be a silent pass. The test read
    # `meta.get(DIGEST_KEY) not in (None, array_digest(raw))`, so `None` was accepted -- correct while
    # every shipped sidecar predated the digest, and it meant the guard covered 0 of 198 greens.
    # gen_provenance --check disclosed that, which is not the same as protecting it. The 198 sidecars
    # were then stamped from the arrays already beside them (surface_io.stamp_digest), so a meta with no
    # digest can no longer be an old surface -- it was hand-written, restored from an older tree, or
    # truncated, which is the state this guard is for.
    torn = None
    if (meta.get("H"), meta.get("W")) != arr.shape:
        torn = (f"  array is {arr.shape[0]}x{arr.shape[1]} but dem_hd/hole{hole:02d}.json records "
                f"{meta.get('H')}x{meta.get('W')}.")
    elif meta.get(surface_io.DIGEST_KEY) is None:
        torn = (f"  dem_hd/hole{hole:02d}.json records no {surface_io.DIGEST_KEY}, so there is nothing\n"
                f"  to check the array against. Every built sidecar carries one; a missing key means\n"
                f"  this file was hand-written or restored from an older tree. Stamp the corpus with\n"
                f"  `python3 surface_io.py --stamp`, or rebuild this hole.")
    elif meta.get(surface_io.DIGEST_KEY) != surface_io.array_digest(raw):
        torn = (f"  the shapes agree at {arr.shape[0]}x{arr.shape[1]}, but dem_hd/hole{hole:02d}.json\n"
                f"  was committed beside a DIFFERENT array, so its bbox describes other ground.")
    if torn:
        raise SystemExit(
            f"hole {hole} of {config.SLUG}: the green surface and its metadata do not match -- the\n"
            f"{torn}\n"
            f"  One of the two is from a different run, so the green ring would be placed on the wrong\n"
            f"  ground. Rebuild that hole:\n"
            f"    COURSE={config.SLUG} ONLY={hole} OVERWRITE=1 python3 fetch_dem_hd.py\n"
            f"    COURSE={config.SLUG} ONLY={hole} python3 fetch_dem.py")
    # NoData sentinels must die before anything measures this surface. USGS 3DEP ships
    # -3.4028235e38; a single one of those makes the 15 cm contour loop iterate over a 3.4e38
    # range and the process is OOM-killed with no message at all (rc=137, zero output).
    arr[~np.isfinite(arr)] = np.nan
    arr[np.abs(arr) > 1e30] = np.nan
    H, W = arr.shape
    bbox = meta['bbox']; xmin, ymin, xmax, ymax = bbox
    clat = meta['green_center'][0]
    px_x = (xmax-xmin)*mlon(clat)/W        # meters per pixel (E)
    px_y = (ymax-ymin)*mlat(clat)/H        # meters per pixel (N)

    poly = poly_to_px(meta['polygon'], bbox, W, H)
    # rasterize polygon mask
    ys, xs = np.mgrid[0:H, 0:W]
    mask = np.zeros((H, W), bool)
    # scanline point-in-poly (vectorized-ish, fine at this size)
    for r in range(H):
        row = []
        yv = r+0.5
        xints = []
        n = len(poly); j = n-1
        for i in range(n):
            xi, yi = poly[i]; xj, yj = poly[j]
            if (yi > yv) != (yj > yv):
                xints.append((xj-xi)*(yv-yi)/(yj-yi+1e-12)+xi)
            j = i
        xints.sort()
        for k in range(0, len(xints)-1, 2):
            a = int(math.ceil(xints[k]-0.5)); b = int(math.floor(xints[k+1]-0.5))
            if b >= a:
                mask[r, max(0,a):min(W,b+1)] = True
    if mask.sum() < 20:
        mask[:] = False
        for r in range(H):
            for c in range(W):
                if point_in_poly(c+0.5, r+0.5, poly): mask[r,c]=True

    # --- render-time honesty gate -------------------------------------------------------------
    # The producer's gate is not enough on its own. fetch_dem_hd.py writes `insufficient`, but
    # fetch_dem.py -- the 1 m seamless path, which is what a BRAND-NEW course gets -- writes no
    # gate keys at all, so meta.get("insufficient") was None (falsy) for those greens and nothing
    # could stop a bad surface from being printed. This is the last check before a number reaches
    # a card, so verify the surface here too, independently of whoever produced it.
    inside = mask & ~np.isnan(arr)
    n_in = int(mask.sum())
    nan_frac = 1.0 - (int(inside.sum()) / n_in) if n_in else 1.0
    if nan_frac > NAN_FRAC_MAX_RENDER:
        meta = dict(meta, insufficient=True, nan_frac=nan_frac)
        return _blank_green(meta, tournament)
    if inside.any():
        rel = float(np.nanmax(arr[inside]) - np.nanmin(arr[inside]))
        # A putting surface cannot plausibly fall metres within its own outline. This catches a
        # partially-filled NoData patch that survived the fraction test above.
        if rel > MAX_PLAUSIBLE_RELIEF_M:
            meta = dict(meta, insufficient=True, relief_m=rel)
            return _blank_green(meta, tournament)
        # ...and it cannot plausibly be PERFECTLY FLAT either. Out of coverage, 3DEP's exportImage
        # returns a constant raster rather than any NoData marker, so this gate -- which claims in its
        # own comment to verify the surface "independently of whoever produced it" -- was blind to the
        # single failure mode that producer is documented to have. Demonstrated by zeroing a real
        # green: the card printed "feeds back (subtle) - 0.0%", a fabricated read. fetch_dem.py grew
        # a MIN_RELIEF_M check for exactly this; the renderer needs it too, because 8 surfaces on
        # disk predate any producer gate and a future producer may forget again.
        if rel < MIN_RELIEF_M:
            meta = dict(meta, insufficient=True, relief_m=rel)
            return _blank_green(meta, tournament)
    arr = np.where(np.isnan(arr), float(np.nanmedian(arr[inside])) if inside.any() else 0.0, arr)

    surf, core, S = green_summary(arr, mask, px_x, px_y)
    slope, dcol, drow = S['slope'], S['dcol'], S['drow']
    relief_m, med_slope = S['relief_m'], S['med_slope']
    tilt_pct, undul_ft, rise_ft = S['tilt_pct'], S['undul_ft'], S['rise_ft']
    pdc, pdr = S['pdc'], S['pdr']
    conf = S['conf']

    # rotation so approach bearing points UP on screen
    B = meta['approach_bearing']
    # approach direction as pixel vector: east=+col, north=-row -> (sinB, -cosB)
    a_ang = math.degrees(math.atan2(-math.cos(math.radians(B)), math.sin(math.radians(B))))
    theta = -90.0 - a_ang                        # rotate group by theta so approach -> up
    cx, cy = W/2.0, H/2.0

    # dominant break direction, expressed in SCREEN frame (after rotation)
    sdx, sdy = rot(pdc, pdr, 0, 0, theta)        # rotate the plane-downhill vector
    nrm = math.hypot(sdx, sdy) or 1
    sdx, sdy = sdx/nrm, sdy/nrm
    best = max(DIRS, key=lambda d: d[0]*sdx + d[1]*sdy)[2]

    # ---- tight viewBox around the ROTATED green: fills the card, no empty space ----
    rp0 = [rot(x, y, cx, cy, theta) for x, y in poly]
    rxmin = min(p[0] for p in rp0); rxmax = max(p[0] for p in rp0)
    rymin = min(p[1] for p in rp0); rymax = max(p[1] for p in rp0)
    padL, padR, padT, padB = 7, 11, 8, 14    # room: compass(top), grid #s(right), scale+approach(bottom)
    VBx, VBy = rxmin-padL, rymin-padT
    VBw, VBh = (rxmax-rxmin)+padL+padR, (rymax-rymin)+padT+padB
    vb = f"{VBx:.1f} {VBy:.1f} {VBw:.1f} {VBh:.1f}"

    # heat cells
    cells = []
    step = 1
    for r in range(0, H, step):
        for c in range(0, W, step):
            if mask[r, c]:
                cells.append(f'<rect x="{c}" y="{r}" width="1.05" height="1.05" fill="{heat_color(slope[r,c])}"/>')
    heat = f'<g opacity="{HEAT_OPACITY}">{"".join(cells)}</g>'

    # contour lines, fine 0.15 m in BOTH modes. Rule 4.3 limits SCALE + book size,
    # not the presence of contours/arrows/% -- so the tournament book keeps full
    # detail (a conforming coarse-scale book); only the scale is capped below.
    segs = []
    cint = CINT_M
    zmin, zmax = surf[mask].min(), surf[mask].max()
    lvl = math.ceil(zmin/cint)*cint
    levels = []
    while lvl < zmax:
        levels.append(lvl); lvl += cint
    def itp(v1, v2, p1, p2, L):
        t = 0.5 if abs(v2-v1)<1e-9 else (L-v1)/(v2-v1)
        return (p1[0]+(p2[0]-p1[0])*t, p1[1]+(p2[1]-p1[1])*t)
    for L in levels:
        for r in range(H-1):
            for c in range(W-1):
                if not (mask[r,c] or mask[r+1,c] or mask[r,c+1] or mask[r+1,c+1]):
                    continue
                TL,TR,BL,BR = surf[r,c],surf[r,c+1],surf[r+1,c],surf[r+1,c+1]
                # +0.5 because A SAMPLE IS A CELL CENTRE, not a grid corner. fetch_dem_hd.py builds
                # its grid with us=(np.arange(W)+0.5)/W, and poly_to_px maps the bbox EDGES to pixel
                # 0..W, so surf[r,c] is the elevation measured at pixel (c+0.5, r+0.5) -- the algebra
                # is exact, not an approximation. Everything else on this card already knows that: the
                # heat rect for (r,c) spans [c,c+1], the mask tests point_in_poly(c+0.5, r+0.5), the
                # scanline rasteriser uses yv=r+0.5, and fetch_dem.py's own interior stats do the same.
                # Only these corners, the arrow tails/heads below and the slope-label anchors did not,
                # so the contour/arrow/label layer sat half a cell UP AND LEFT of the heat layer and
                # the outline it is drawn over -- 0.284 m of ground at 0.4 m sampling, 0.356 m on the
                # six seamless greens, and 0.30-0.65 mm in print, 54% of the outline's own 1.3-unit
                # stroke. Measured over 74,574 drawn segments: bilerp'd at the coordinate as drawn the
                # elevation landed on a 15 cm level to 0.000 mm, and at the pixel the coordinate
                # CLAIMS to be it was off by a median 7.8 mm and up to 74.9 mm. That is the whole
                # defect: the lines were exact iso-contours of a surface half a cell from where the
                # card drew everything else.
                # Shifted in the COORDINATES rather than with a transform= on the group, because
                # test_nothing_is_drawn_off_the_putting_surface and the two-edition contour count in
                # test_the_contour_interval_is_the_one_the_legend_states match these <g ...> open tags
                # literally, and an added attribute breaks their regexes in either position.
                # No printed NUMBER moves: tilt, feed word, relief, undulation and the plane fit are
                # computed in array space (Xe=cc*px_x, Yn=-rr*px_y), where a uniform +0.5 shifts only
                # the intercept; depth, width, the 5-yd ladder and the pin ring come from the polygon.
                cTL,cTR,cBL,cBR = (c+0.5,r+0.5),(c+1.5,r+0.5),(c+0.5,r+1.5),(c+1.5,r+1.5)
                pts=[]
                if (TL-L)*(TR-L)<0: pts.append(itp(TL,TR,cTL,cTR,L))
                if (TR-L)*(BR-L)<0: pts.append(itp(TR,BR,cTR,cBR,L))
                if (BL-L)*(BR-L)<0: pts.append(itp(BL,BR,cBL,cBR,L))
                if (TL-L)*(BL-L)<0: pts.append(itp(TL,BL,cTL,cBL,L))
                if len(pts)>=2:
                    mx=(pts[0][0]+pts[1][0])/2; my=(pts[0][1]+pts[1][1])/2
                    # int() and not round(): mx,my are now PIXELS, and pixel column ci spans [ci,ci+1),
                    # so int(mx) is both the mask cell the midpoint lies in AND the nearest sample to
                    # it (the sample at column ci sits at x=ci+0.5, and floor(x) == round(x-0.5)).
                    # Needs no +/-0.5 of its own, and correcting the corners above is what made that
                    # true: while they were grid corners, mx ran over [c,c+1] and this reduced to
                    # mask[r,c] -- the TOP-LEFT of the cell's four samples, whichever way the segment
                    # actually ran. It rejected 5,754 segments where the honest question rejects 5,076,
                    # so 678 real contour segments were dropped for sitting in a cell whose top-left
                    # neighbour happened to be off the green.
                    ri,ci=int(my),int(mx)
                    if 0<=ri<H and 0<=ci<W and mask[ri,ci]:
                        segs.append(f'<line x1="{pts[0][0]:.1f}" y1="{pts[0][1]:.1f}" x2="{pts[1][0]:.1f}" y2="{pts[1][1]:.1f}"/>')
    contours = f'<g stroke="#3c5a34" stroke-width="0.5" opacity="0.55">{"".join(segs)}</g>'

    # flow arrows, dense in BOTH modes (allowed within the scale limit)
    # Drawn on PUTTING SURFACE only, the same cells the printed feed word is fitted to. An arrow is a
    # claim about which way a putt runs, so ground the card colours-but-does-not-number is not
    # somewhere to make it -- and because length scales with slope, bank cells produced the LONGEST,
    # most eye-catching arrows on the card ("longer = steeper", says the legend), pulling the reader
    # toward a break that is not a putt. It also keeps the two statements of the same claim honest
    # with each other: word and arrows now describe the same ground.
    arrows = []
    arw_x = arw_y = 0.0
    putt = S['putt']
    smax = max(np.percentile(slope[putt], 92), 1.0) if putt.any() else 5.0
    a_step = 6
    a_min = 0.4
    for r in range(3, H-3, a_step):
        for c in range(3, W-3, a_step):
            if not putt[r, c]: continue
            m = slope[r, c]
            if m < a_min: continue
            L = 2.2 + 3.4*min(m/smax, 1.0)
            vx, vy = dcol[r, c], drow[r, c]
            nn = math.hypot(vx, vy) or 1
            vx, vy = vx/nn*L, vy/nn*L
            ex, ey = c+0.5+vx, r+0.5+vy      # +0.5: the sample is a cell CENTRE -- see the contours
            # keep the whole arrow (tip + a small head allowance) inside the green outline
            # This cull now asks the question it always meant to. It compares against `poly`, which is
            # in pixels, so while the tip was built from a bare (c,r) it was testing a point half a
            # cell up-left of the arrow it was vetting: 24 arrows were kept or dropped on the
            # wrong evidence.
            if not (point_in_poly(ex, ey, poly) and point_in_poly(ex+vx*0.28, ey+vy*0.28, poly)):
                continue
            ang = math.atan2(vy, vx)
            h = 1.7
            arw_x += vx; arw_y += vy      # length-weighted, so steeper arrows count for more
            arrows.append(
                f'<line x1="{c+0.5}" y1="{r+0.5}" x2="{ex:.1f}" y2="{ey:.1f}"/>'
                f'<polygon points="{ex:.1f},{ey:.1f} {ex-h*math.cos(ang-0.5):.1f},{ey-h*math.sin(ang-0.5):.1f} '
                f'{ex-h*math.cos(ang+0.5):.1f},{ey-h*math.sin(ang+0.5):.1f}"/>')
    arrowg = f'<g stroke="#15271b" stroke-width="0.7" fill="#15271b" stroke-linecap="round">{"".join(arrows)}</g>'

    # The card states the fall TWICE: this one word, and the arrows the reader actually looks at. They
    # answer slightly different questions -- a plane over the whole putting surface against every local
    # gradient -- so they are SUPPOSED to differ a little, and across the corpus they run to a median
    # 3.5 deg and a 90th percentile of 13.7, with exactly two greens past 45: monarch-bay 12 at 50.4 and
    # micke-grove 2 at 179.5. (This comment used to quote "median 11, p90 27". Those belong to a
    # different measurement -- the gap between the arrows and the PRINTED WORD, which is snapped to one
    # of eight 45-degree octants and so carries up to 22.5 degrees of quantisation the plane vector does
    # not -- and they made the 90-degree bar below look about three times the typical spread when it is
    # 26x.) But when they point more than 90 degrees apart the card is
    # handing a golfer two different breaks, and the honest reading is that the surface does not
    # determine one. micke-grove 2 is the case that forced this: 0.5% of tilt, plane and arrows 179.5 deg
    # apart, where naming either direction is a coin toss dressed up as a read. So refuse the word and
    # keep the measured percentage, which is still true.
    #
    # Deliberately a self-consistency test and not a tilt floor: it fires on the greens where the two
    # derivations actually conflict, rather than on a number tuned to today's corpus.
    if (arw_x or arw_y) and (pdc or pdr):
        if (pdc*arw_x + pdr*arw_y) / (math.hypot(pdc, pdr)*math.hypot(arw_x, arw_y)) < 0.0:
            best = NO_CLEAR_FALL

    poly_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in poly) + " Z"
    outline = f'<path d="{poly_d}" fill="none" stroke="#20402a" stroke-width="1.3"/>'

    body = (f'<g transform="rotate({theta:.2f} {cx:.1f} {cy:.1f})">'
            f'{heat}{contours}{arrowg}{outline}</g>')

    # ---- depth references: 5-yd front->back grid + F/C/B ----
    # Per AXIS. depth and the ladder run down screen y, width across screen x, and the DEM pixel is not
    # square -- see screen_m_per_unit for the three printed depths this moved.
    mx, my = screen_m_per_unit(theta, px_x, px_y)
    # The SCALE claims below (the printed 5-yd bar and the Rule 4.3 ceiling) stay on the scalar mean
    # deliberately. tools/check_scale.py measures conformance with that same mean, the anisotropy is at
    # most 0.41% against the 4% margin 0.36 keeps under the 0.375 cap, and 0.41% of a 5 yd bar is
    # 0.0015 in on paper -- so splitting them per axis would resize 26 cap-limited greens and move 53
    # coach-edition scale bars for a change no printer can render and no reader can see.
    px_m = (px_x + px_y) / 2.0
    rp = [rot(x, y, cx, cy, theta) for x, y in poly]      # polygon in screen space
    rxs = [p[0] for p in rp]
    # front/back down the LINE OF PLAY, not the corners of the bounding box -- see play_line_span.
    # depth_yd, the grey 5-yd ladder below and the pin ring all hang off these two numbers, so they
    # move together and the printed depth cannot disagree with the top rung.
    front_y, back_y, midx = play_line_span(rp)
    depth_yd = (front_y-back_y)*my/0.9144
    width_yd = (max(rxs)-min(rxs))*mx/0.9144
    # ...and how much of that depth, at EACH end, is bank rather than green. Measured, not trimmed:
    # the datum stays on the polygon so the number still matches the drawing and its own geodesic
    # check, and the CARD discloses the bank instead. Back as well as front, because a back bank is
    # the more dangerous of the two -- it overstates how far back a pin can be. See bank_run_yd.
    fb_yd = bank_run_yd(front_y, back_y, midx, cx, cy, theta, slope, my)
    bb_yd = bank_run_yd(back_y, front_y, midx, cx, cy, theta, slope, my)
    def xspans(yy):
        """The green's x-extent(s) at screen-y yy, as inside/outside PAIRS.

        This returned a single (min, max) span, which draws the rung straight across a concavity --
        over ground the card's own outline excludes. copper-valley 4 had it: one of its six rungs
        bridged a 7.0 yd gap outside the polygon, ruling a putting-depth reference across a notch. That
        instance is GONE -- moving the ladder's zero onto the line of play in the same commit shifted every
        rung, and no green in the corpus now draws a multi-fragment rung. The guard is kept as the correct
        way to draw one, not because a live case remains; do not go looking for copper-valley 4 and
        conclude the code is wrong.
        Sorting the crossings and taking them two at a time draws only the parts that are green, and
        collapses to the old behaviour on the convex greens that are the vast majority.
        """
        xs=[]
        n=len(rp)
        for i in range(n):
            x1,y1=rp[i]; x2,y2=rp[(i+1)%n]
            if (y1>yy)!=(y2>yy):
                xs.append(x1+(x2-x1)*(yy-y1)/(y2-y1))
        xs.sort()
        return [(xs[i], xs[i+1]) for i in range(0, len(xs)-1, 2)]
    step = 4.572/my                                       # 5 yards DOWN THE PLAY LINE, in pixels
    glines=[]; k=1; yy=front_y-step
    while yy>back_y:
        sps=xspans(yy)
        if sps:
            for a, b in sps:
                glines.append(f'<line x1="{a:.1f}" y1="{yy:.1f}" x2="{b:.1f}" y2="{yy:.1f}"/>')
            # one label per rung, at the right-hand edge of the green -- not once per fragment
            glines.append(f'<text x="{sps[-1][1]+1.5:.1f}" y="{yy+1.5:.1f}" font-size="3.4" '
                          f'fill="#8a8a8a" stroke="none">{k*5}</text>')
        yy-=step; k+=1
    gridg=f'<g stroke="#9a9a9a" stroke-width="0.35" stroke-dasharray="2,2" opacity="0.7" fill="#8a8a8a">{"".join(glines)}</g>'
    # (front/center/back yardage tags removed by request -- declutter the green)
    fcb=""
    # pin ring the golfer marks on the day (pin moves daily -> not pre-printed).
    # Small so it never covers the green's slope/bunker detail.
    pin=(f'<circle cx="{midx:.1f}" cy="{(front_y+back_y)/2:.1f}" r="1.4" fill="none" stroke="#c0392b" stroke-width="0.7" stroke-dasharray="1.2,1.2"/>')

    # slope % numbers in steeper zones (kept in BOTH modes -- allowed at this scale)
    chosen=[]
    cand=[]
    for r in range(4,H-4,6):
        for c in range(4,W-4,6):
            # A putting surface is built at roughly 1-4%; a tier face reaches ~8%. Anything above
            # SLOPE_LABEL_MAX_PCT inside the traced outline is a bank, mound or bunker lip, not
            # green -- the OSM golf=green polygon includes the collar and surround. Those cells are
            # MEASURED correctly, but the legend reads "Numbers = slope % there" on a green card,
            # so printing 40 beside 5 tells a reader the green has a 40% putt. It does not.
            # They stay visible through colour and arrows; they just get no putt number.
            # (This loop sorts steepest-first, so without a ceiling it actively PREFERRED the
            # least plausible cells on the card -- merion h2 printed 40, philadelphia 29.)
            if core[r,c] and slope[r,c]>=1.5 and slope[r,c]<=SLOPE_LABEL_MAX_PCT:
                cand.append((float(slope[r,c]),r,c))
    cand.sort(reverse=True)
    for sl,r,c in cand:
        sx,sy=rot(c+0.5,r+0.5,cx,cy,theta)    # +0.5: the sample is a cell CENTRE -- see the contours
        # keep slope numbers inside the frame and off the top-right compass
        sx=min(max(sx, VBx+2.5), VBx+VBw-2.5)
        sy=min(max(sy, VBy+3.0), VBy+VBh-4.0)
        if (sx-(VBx+VBw-5.5))**2 + (sy-(VBy+6.5))**2 < 6.0**2:   # skip compass zone
            continue
        if all((sx-ox)**2+(sy-oy)**2>16**2 for ox,oy,_ in chosen):
            chosen.append((sx,sy,sl))
        if len(chosen)>=7: break
    slabels=("<g>"+"".join(
        f'<text x="{sx:.1f}" y="{sy:.1f}" font-size="4.6" text-anchor="middle" '
        f'paint-order="stroke" stroke="#fff" stroke-width="1.2" fill="#111" font-weight="700">{int(round(sl))}</text>'
        for sx,sy,sl in chosen)+"</g>")

    # scale bar (tournament): a printed 5-yard bar to verify the scale, tucked in the
    # bottom-LEFT of the frame so it never collides with the approach label (bottom-right).
    scalebar = ""
    scale_max_in = round(0.075 * depth_yd, 3)   # legal max on-page height for this green
    if tournament:
        blen = 4.572 / px_m                      # 5 yards in view units
        bx0 = VBx + 2.5; by0 = VBy + VBh - 3.5
        scalebar = (f'<g stroke="#333" stroke-width="0.7">'
                    f'<line x1="{bx0:.1f}" y1="{by0:.1f}" x2="{bx0+blen:.1f}" y2="{by0:.1f}"/>'
                    f'<line x1="{bx0:.1f}" y1="{by0-1.3:.1f}" x2="{bx0:.1f}" y2="{by0+1.3:.1f}"/>'
                    f'<line x1="{bx0+blen:.1f}" y1="{by0-1.3:.1f}" x2="{bx0+blen:.1f}" y2="{by0+1.3:.1f}"/>'
                    f'<text x="{bx0+blen/2:.1f}" y="{by0-2.0:.1f}" font-size="3.6" text-anchor="middle" fill="#333" stroke="none">5 yd</text></g>')

    # compass (true north): small, top-right of the tight frame
    ncx, ncy = VBx+VBw-5.5, VBy+6.5
    nx, ny = rot(0, -1, 0, 0, theta)
    comp = (f'<g stroke="#666" fill="#666">'
            f'<line x1="{ncx:.1f}" y1="{ncy:.1f}" x2="{ncx+nx*4:.1f}" y2="{ncy+ny*4:.1f}" stroke-width="0.7"/>'
            f'<circle cx="{ncx:.1f}" cy="{ncy:.1f}" r="0.7"/>'
            f'<text x="{ncx+nx*6:.1f}" y="{ncy+ny*6+1.3:.1f}" font-size="3.4" text-anchor="middle">N</text></g>')

    # In tournament mode: size the green as large as possible while (a) staying a safe
    # margin UNDER the Rule 4.3 cap (0.36 in : 5 yd, ~4% under 3/8) AND (b) fitting inside
    # its panel so nothing overflows/clips. Whichever is smaller wins -> consistent framing.
    if tournament:
        # 0.36 against a 0.375 limit is a 4% margin, which is a margin against ROUNDING, not against a
        # printer. Scaling a sheet up by 4.1% puts the worst green over the cap while the cover still
        # says "DESIGNED TO CONFORM - RULE 4.3", so every sheet's margin note now reads PRINT AT 100%.
        # Nothing in the book said that before: "fit to page" on A4 happens to shrink a Letter sheet,
        # which is safe, but any deliberate enlargement is not.
        legal_kf = 0.36 * px_m / 4.572                                   # legal ceiling
        # .grn column width must match generate.py's CSS: card minus padding, minus the 1px
        # flex gap, times the .grn share (2.4 of 1.6+2.4). Measured in-browser at 2.010in.
        # Why 2.4/4.0 and not wider. 172 of 198 greens are limited by this 2.010 in column rather than
        # by the Rule 4.3 cap, so a wider share would draw them bigger -- but the hole map pays for it,
        # and measured, the trade is not worth taking:
        #     1.5/2.5 -> green 2.093 in (+4.2%), 101 of 198 hole maps shrink 6%
        #     1.4/2.6 -> green 2.177 in (+8.3%), 119 of 198 hole maps shrink 13%
        # Only the hole maps whose viewBox is SHORTER than 100*LAY_H/LAY_W are affected (108 of 198 are
        # height-limited today and lose nothing), which is why the cost lands on about half of them. And
        # the 26 greens already at the legal cap gain zero from any of this. So the whole exchange buys
        # 0.08 in on a green that is already 2 in across, at the price of shrinking half the hole maps.
        # Left alone deliberately; do not re-open it without re-measuring those two lines.
        grn_w_in = (config.CARD_W_IN - 2*0.07 - 1/96) * (2.4/4.0)        # .grn column width
        # Footer allowance. This was a hardcoded 0.18 in, which assumed a ONE-LINE footer. It can be
        # three: at 7.5pt with normal leading a line is ~0.125 in, and a five-tee course prints "feeds
        # ... %" then "Nyd deep * NB NW * three tees" then the carry/elevation playline. 0.18 in
        # under-reserves by up to 0.32 in, so a green sized against it would be too tall for its panel.
        # Precautionary: measured across the corpus, HEIGHT binds on 0 of 198 greens -- 172 are limited
        # by the 2.01 in column width and 26 by the Rule 4.3 cap -- so this changes no output today. It
        # is fixed because the day a tall narrow green meets a three-line footer, the failure is a green
        # clipped by its own panel, and nothing in the pipeline is watching for that.
        foot_lines_in = 3 * 0.125 + 0.125                                # 3 footer lines + playline
        grn_h_in = config.CARD_H_IN - 2*0.07 - 0.50 - foot_lines_in      # minus header + foot
        fit_kf = min(grn_w_in/VBw, grn_h_in/VBh)                         # fit the whole frame
        kf = min(legal_kf, fit_kf)
        wattr, hattr = f'{VBw*kf:.3f}in', f'{VBh*kf:.3f}in'
        wrapopen = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%">'
        wrapclose = '</div>'
    else:
        wattr = hattr = '100%'
        wrapopen = wrapclose = ''

    # NOTE: the size MUST be emitted as an inline `style` (not width=/height= presentation
    # attributes). A presentation attribute has zero specificity, so the book stylesheet's
    # `.grn svg { width:100%; height:100% }` would override it and re-fit the drawing to the
    # whole column -- silently breaking the Rule 4.3 scale cap computed above.
    svg = (f'{wrapopen}<svg viewBox="{vb}" style="width:{wattr};height:{hattr}" '
           f'preserveAspectRatio="xMidYMid meet">'
           f'{body}{gridg}{slabels}{pin}{fcb}{scalebar}{comp}'
           f'<text x="{VBx+VBw-2.5:.1f}" y="{VBy+VBh-2.5:.1f}" font-size="4" text-anchor="end" fill="#333">&#9650; approach</text>'
           f'</svg>{wrapclose}')


    summary = dict(relief_ft=round(relief_m*3.28084,1), median_slope=round(med_slope,1),
                   source=meta.get('source',''),
                   tilt_pct=round(tilt_pct,1), feeds=best, undul_ft=round(undul_ft,1),
                   conf=conf, depth_yd=int(round(depth_yd)), width_yd=int(round(width_yd)),
                   front_bank_yd=fb_yd, back_bank_yd=bb_yd, scale_max_in=scale_max_in)
    return svg, summary


if __name__ == "__main__":
    for h in range(1, 19):
        try:
            _, s = render(h)
            print(f"hole {h:2d}: feeds {s['feeds']:11s} tilt {s['tilt_pct']:.1f}%  median {s['median_slope']:.1f}%  relief {s['relief_ft']:.1f} ft")
        except Exception as e:
            print(f"hole {h:2d}: ERROR {type(e).__name__}: {e}")
