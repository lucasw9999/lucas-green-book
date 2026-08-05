#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Render a per-hole LAYOUT (tee -> green corridor) from OpenStreetMap geometry.

Orientation: tee at the BOTTOM, green at the TOP (you read it as you play).
Shows: hole centerline, tee boxes, fairway bunkers, water / lateral hazards,
the green (with a hollow 'pin' ring you mark on the day), and yardage.

Data: OpenStreetMap (ODbL) golf features in osm_course.json + osm_geom.json.
"""
import glob
import json, math, os
import config
import geo
from geo import mlat, mlon   # the project's ONE figure of the Earth -- never re-declare these
DIR = config.COURSE_DIR

_LIDAR_TREES = None
def _lidar_trees():
    """LiDAR-derived tree markers per hole (from fetch_trees.py), if available.

    If the course HAS a point cloud but no trees_lidar.json, the map silently fell back to OSM tree
    nodes -- which on Merion means 25 markers instead of 5086, so a tree-lined corridor printed as
    open ground while the legend still promised "trees (dark green)". Nothing said a word. That got
    easier to hit when fetch_trees.py gained hard stops (a course.json missing "location" now aborts
    the tree stage, and generate.py would still produce a clean-looking 18-hole book).

    A missing file when there is no LiDAR at all is fine -- OSM trees are then the honest best
    available. Refusing only when the tiles EXIST keeps that distinction."""
    global _LIDAR_TREES
    if _LIDAR_TREES is None:
        p = os.path.join(config.COURSE_DIR, "trees_lidar.json")
        if not os.path.exists(p) and glob.glob(os.path.join(config.COURSE_DIR, "laz", "*.laz")):
            if not os.environ.get("ALLOW_OSM_TREES"):
                raise SystemExit(
                    "this course has LiDAR tiles but no trees_lidar.json, so the hole maps would\n"
                    "  show only the handful of trees OSM happens to have (25 vs 5086 on Merion)\n"
                    "  while the legend still promises trees. Run:\n"
                    f"    COURSE={config.SLUG} python3 fetch_trees.py\n"
                    "  Set ALLOW_OSM_TREES=1 to draw OSM trees anyway and accept a sparse map.")
            print("  NOTE: ALLOW_OSM_TREES set -- drawing sparse OSM trees, not LiDAR canopy")
        _LIDAR_TREES = json.load(open(p)) if os.path.exists(p) else {}
    return _LIDAR_TREES

def load():
    course = json.load(open(f"{DIR}/osm_course.json"))["elements"]
    geom   = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    return course, geom

def centroid(g):
    la = sum(p['lat'] for p in g['geometry'])/len(g['geometry'])
    lo = sum(p['lon'] for p in g['geometry'])/len(g['geometry']); return la, lo

def match_green(hole_line, greens, label=""):
    """Delegates to geo.match_green, which carries the distance cap. See there for why."""
    return geo.match_green(hole_line, greens, label=label)

def dist_to_poly_m(pt, poly, em):
    """Metres from a projected point to a polygon: 0 when inside, else the nearest edge."""
    P = [em(p['lat'], p['lon']) for p in (poly.get('geometry') or [])]
    if not P:
        return 1e9
    x, y = pt
    inside = False
    for i in range(len(P)):
        x1, y1 = P[i]; x2, y2 = P[(i+1) % len(P)]
        if (y1 > y) != (y2 > y) and x < x1 + (y-y1)*(x2-x1)/((y2-y1) or 1e-12):
            inside = not inside
    if inside:
        return 0.0
    return min(dist_pt_seg(x, y, P[i][0], P[i][1], P[(i+1) % len(P)][0], P[(i+1) % len(P)][1])
               for i in range(len(P)))


DIGIT_EM = 0.556                  # Helvetica/Arial Bold digit advance, in em
PAR3_STRAIGHT_MAX = 1.02          # arc / chord

# A watercourse only belongs on the card if a golfer can SEE it. Two separate exclusions:
#
#  * PIPED. A waterway carrying tunnel=culvert / covered=yes / location=underground runs under the
#    ground. It is not a hazard, it is not visible, and it cannot be played from. Nine holes counted one,
#    and merion 13 printed "1W" whose only blue mark on the page was a 14.7 m culverted section -- a card
#    telling a junior there is water on a hole where none is visible. 27 such features exist in the
#    corpus, on 7 of the 12 courses.
#  * NOT WATER. waterway=dam / weir / lock_gate / sluice_gate are structures beside water, not water.
#    Drawn and counted as water they both overstate the hazard and misplace it: the structure sits where
#    the water is held back, which is exactly where the water is not.
#
# At module scope so it can be tested by truth table rather than through a whole rendered card.
# 'covered' belongs in this tuple because it is a legal VALUE of `tunnel`, not only a key of its
# own. Omitting it let castlewood-valley way 926093107 through -- an 11.5 m `tunnel=covered`
# reach of the Arroyo de la Laguna -- and that hole went 0W to 2W on the strength of 3 mm of blue
# for a buried channel 43.5 m away and 37 m BEHIND the tee. That is merion 13's defect, the one
# this predicate was written to fix, recreated by the fix on a hole that used to print none.
PIPED = ('culvert', 'yes', 'building_passage', 'covered')
NOT_WATER = ('dam', 'weir', 'lock_gate', 'sluice_gate', 'fish_pass')
HIDDEN_LOCATION = ('underground', 'underwater')


def watercourse_identity(feature):
    """A key that is the same for every OSM way belonging to ONE physical watercourse.

    "3W" beside "14B" is read as "there are three waters on this hole", and it was counting OSM WAYS.
    A creek is routinely split into several ways at every road crossing and tag change, so one stream
    printed as several: copper-valley 11 printed 7W where six of the seven ways carry the SAME NHD reach
    code 18040051001111 -- one reach -- and merion 13 printed 2W for two ways both named "Cobbs Creek".
    20 of 198 cards printed a bigger W than there is water.

    The key is already in the data on 137 of the corpus's 179 waterways: the source hydrography's own
    reach identifier, else the name. A way with neither is counted on its own, because nothing available
    says it is the same water as its neighbour -- guessing from shared endpoints would merge a tributary
    into the creek it joins.

    Deduplicates the COUNT only. Every segment is still DRAWN: a golfer looking at the card should see
    all the blue that is there, and the honesty rule that matters is that no counted water lacks ink.
    """
    t = feature.get('tags') or {}
    for k in ('nhd:reach_code', 'pasda:SEGID', 'scvwd:ROUTEID'):
        if t.get(k):
            return (k, t[k])
    if t.get('name'):
        return ('name', t['name'])
    return ('id', feature.get('id'))


def is_visible_watercourse(feature):
    """True when this OSM feature is a watercourse a golfer standing on the hole could see."""
    t = feature.get('tags') or {}
    w = t.get('waterway')
    if not w or w in NOT_WATER:
        return False
    if t.get('tunnel') in PIPED or t.get('covered') in PIPED:
        return False
    return t.get('location') not in HIDDEN_LOCATION


def par3_exact_from_tee(par, arc_m, chord_m):
    """True when a tick's distance FROM THE TEE can be derived exactly as (card - to_green).

    Only a par 3 qualifies. Its played line IS the straight tee-to-green line, so tee, tick and green
    are collinear and the two numbers must sum to the card -- no arc, no proportional scaling, and
    nothing assumed about where a card-vs-line length mismatch lives. That is what lets the from-tee
    number be printed on a par 3 whose OSM centreline stops short of the back tee (4 of the 22 short
    holes), which the proportional model cannot do.

    A par 4 or 5 is excluded because its card yardage follows a played route that can dogleg, so
    (card - to_green) would mix a walked measure with a straight-line one -- up to 42 yd wrong.

    The straightness check refuses a par 3 whose drawn line is NOT straight: a par 3 cannot bend, so
    that means bad data, and collinearity would not hold. Kept as a pure function because the corpus
    cannot exercise this guard -- its one non-straight par 3 (copper-valley 13, arc/chord 1.0237)
    happens to agree with the proportional value within tolerance, so removing the guard changed no
    printed number and no corpus sweep could catch it.
    """
    return par == 3 and arc_m <= PAR3_STRAIGHT_MAX * (chord_m or 1.0)


def line_runs_from_a_forward_tee(arc_yd, back_yd, tee_yds, start_at_tee_m):
    """True when the drawn line is a COMPLETE tee-to-green route that simply starts at a FORWARD tee.

    This is what lets the from-tee number be printed on a hole whose line is shorter than the back-tee
    card. The line is not truncated mid-fairway: it runs from some tee to the green, and the only thing
    missing is the stretch from the back tee up to that forward tee -- which is at the TEE end. So
    (back-tee card - the walk still left to the green) is the distance from the back tee, both terms
    being walked measures, the same one the scorecard uses.

    Two independent things must hold, because neither alone is enough:

      * The line STARTS ON a mapped tee box (start_at_tee_m). Measured against a control: 99% of the
        176 holes whose line does span the back-tee card also start on one, so this is OSM's
        convention, and 17 of the 18 short par 4/5 holes satisfy it. A line starting mid-fairway
        (valley-hi 17, 98.6 m from any tee) fails and is refused.
      * The line's LENGTH matches one of this hole's own published forward-tee yardages. Equivalently,
        the shortfall equals the published tee-to-tee difference: merion 5 runs 397.9 yd against a
        Middle tee of 394 and is short of the 501 Championship card by 103 against a published gap of
        107; merion 8 is short by 23 against a published 21.

    Why BOTH: on its own the yardage match is weak -- it fires on 78% of the real holes but also on
    41% of decoys (the same forward-tee columns of other holes of the same par), because holes of one
    par have similar yardages and the tolerance is wide. The tee-box test is the strong one.

    Observed in the corpus, and the reason two cards carry no from-tee number at all:
    castlewood-valley 10 and 18 start ON a tee box (0 m) yet run 497 and 385 yd against cards of 561 and
    426. Their arc/chord is 1.000 and 1.038 -- the drawn lines are straight, or nearly so, while the
    played route bends -- so OSM has cut the dogleg and the card measures the corner. Their lengths land
    between published tees (497 sits between a 534 and a 460; 385 between a 352 and a 426), so the
    yardage test refuses and the gutter stays empty. That is the right answer: the shortfall is spread
    along the hole rather than sitting at the tee, so nothing here can say where it is.
    Digitizing a TEE would not help -- the tee is already mapped and the line already starts on it. The
    fix is a corrected CENTRELINE, ideally upstream in OSM.

    Residual failure mode, stated rather than hidden: a line that starts at the BACK tee but cuts the
    corner of a dogleg would also satisfy both tests if its length happened to land near a forward-tee
    figure. Then the missing length is spread along the hole, not at the tee, and the from-tee number
    would read high by up to the shortfall at the tick nearest the tee, converging to correct at the
    green. That is the risk this trade accepts; refusing instead left 4 of Merion's 18 cards with an
    empty gutter, which reads as a broken book rather than as a careful one.
    """
    if arc_yd >= back_yd:
        return False          # not short at all, or OVERSHOOTING the card: a line traced PAST the tee
                             # has extra length at the tee end, so subtracting the remaining walk from
                             # the card understates the distance instead of recovering it
    if start_at_tee_m > 20.0:
        return False
    return any(abs(arc_yd - y) <= max(15.0, 0.05*y) for y in tee_yds)

WANDER_MAX = 1.02       # arc / chord above which a line's extra length may be mid-line, not at an end

# A GAP ALONG THE PLAYED LINE TOO SMALL TO BE A PLACE. One number, because it answers one question
# twice. It was a bare `8` inside the carry block, used only to merge sand: a cluster of three bunkers
# 3.8 yd apart is one decision, and printing "213 234 275" spends the card's scarcest resource on
# noise. That is already a judgement about the ground BETWEEN two hazards -- so it is also the bar for
# the ground between the last sand and the green, which is where a player is being invited to land.
# See the landing test in the carry block: a strip of grass too narrow to separate two bunkers is too
# narrow to lay up in, so the green front joins the same merge. That SECOND use is a borrowing, not a
# measurement -- this number was introduced for readability alone -- and the argument for borrowing it,
# with every margin either side of it, is written out there rather than here.
CARRY_MERGE_GAP_YD = 8.0

# THE DRAWING CORRIDOR, one declaration for the whole project.
#
# Every feature class this module draws is selected by how near it comes to the hole's centreline, and
# each class has its own half-width -- a wood is a background fill that may legitimately start 55 m out,
# a fairway is not. Those eight numbers were eleven literals at eleven call sites -- water's 45 spelled
# four times over -- and nothing anywhere said what the WIDEST of them was. tools/check_osm_bbox.py needs
# exactly that figure: it asks whether the
# OSM fetch box covers what the cards draw, and it carried its own `CORRIDOR_M = 45.0` with the comment
# "render_hole.in_corridor's drawing buffer". 45 was never the widest -- OSM tree nodes are taken to
# 68 m -- so the pre-flight could report a box fully covered while the drawn corridor reached 23 m of
# ground the fetch never requested. That is the same two-places defect the earth-model migration just
# removed for the local scales, so it gets the same treatment: named here, derived there, never respelt.
#
# DRAW_CORRIDOR_M is computed from the set rather than written down, so widening any one class widens
# the pre-flight with it. A new class added with a bare literal would slip past that, which is what
# test_the_bbox_preflight_measures_the_widest_corridor_the_engine_draws watches the call sites for --
# along with the defaults, and with both of the counts published in this paragraph.
CORRIDOR_M = {
    "bunker":   40.0,     # edge_within: nearest EDGE of the sand, not its centroid -- see edge_within
    "water":    45.0,     # area hazards AND watercourses, deliberately the same -- see `waters`
    "tee":      38.0,
    "fairway":  34.0,
    "rough":    48.0,
    "wood":     55.0,     # background fill, clipped at the frame edge rather than zooming the hole out
    "treerow":  45.0,
    "treenode": 68.0,     # the WIDEST, and so the figure the fetch box has to cover
}
DRAW_CORRIDOR_M = max(CORRIDOR_M.values())


def line_traced_past_the_tee(arc_yd, back_yd, chord_yd):
    """True when the drawn line runs BEYOND the back tee, so its extra length is at the TEE end.

    The mirror of line_runs_from_a_forward_tee, and it needs no tee evidence at all: the line's green
    end is at the green on all 198 corpus holes, so a line LONGER than the back-tee card must start
    behind that tee. The one alternative is a line that wanders in the middle -- extra length not at
    either end -- and a straight line cannot do that, which is what the chord test rules out. (A
    doglegged overshoot would be ambiguous; none exists in the corpus, and it refuses.)

    Why it matters: without this the two overshoot holes measured every along-line distance from a
    point ~36 yd behind their real tee. castlewood-hill 4 printed "carry 85" for sand that is 49 yd
    off the tee -- not a carry decision at all -- and callippe 3 printed 269 for a real 233.
    """
    if arc_yd <= back_yd:
        return False
    if arc_yd - back_yd <= max(15.0, 0.05*back_yd):
        return False                                  # within tolerance: the line spans, no shift
    return arc_yd <= WANDER_MAX * (chord_yd or 1.0)


def dist_pt_seg(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay; L2=dx*dx+dy*dy
    if L2<1e-9: return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/L2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))


def segs_cross(ax, ay, bx, by, cx, cy, dx, dy):
    """True when segments AB and CD properly cross -- each strictly straddles the other's line."""
    def side(ox, oy, px, py, qx, qy):
        return (px-ox)*(qy-oy) - (py-oy)*(qx-ox)
    d1 = side(cx, cy, dx, dy, ax, ay)
    d2 = side(cx, cy, dx, dy, bx, by)
    d3 = side(ax, ay, bx, by, cx, cy)
    d4 = side(ax, ay, bx, by, dx, dy)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def dist_seg_seg(ax, ay, bx, by, cx, cy, dx, dy):
    """Metres between segment AB and segment CD -- 0 when they cross.

    Where they do not cross the minimum is always attained at an endpoint of one of them, so the
    four point-to-segment distances cover every such case. The CROSSING case is the one they do
    not cover and the one that matters here: a stream can cut a centerline a long way from every
    endpoint, so all four of those distances are large while the true distance is zero.

    At module scope so it can be checked against hand-computed geometry rather than through a whole
    rendered card.
    """
    if segs_cross(ax, ay, bx, by, cx, cy, dx, dy):
        return 0.0
    return min(dist_pt_seg(ax, ay, cx, cy, dx, dy),
               dist_pt_seg(bx, by, cx, cy, dx, dy),
               dist_pt_seg(cx, cy, ax, ay, bx, by),
               dist_pt_seg(dx, dy, ax, ay, bx, by))


def _lin_interval(c0, cu, lo, hi):
    """{u : lo <= c0 + cu*u <= hi} as (u0, u1), None when empty, unbounded ends allowed."""
    if abs(cu) < 1e-15:                       # constant in u
        return (-math.inf, math.inf) if lo <= c0 <= hi else None
    a, b = (lo - c0) / cu, (hi - c0) / cu
    return (a, b) if a <= b else (b, a)


def _clip(iv, lo, hi):
    """Intersect an interval with [lo, hi]; None when that leaves nothing."""
    if iv is None:
        return None
    a, b = max(iv[0], lo), min(iv[1], hi)
    return (a, b) if a <= b else None


def capsule_interval(ax, ay, dxu, dyu, cx, cy, dx, dy, r):
    """The sub-interval of u in [0,1] where A + u*(dxu,dyu) lies within r of segment C->D.

    {X : dist(X, CD) <= r} is a CAPSULE, and a capsule is convex, so a straight line meets it in at
    most ONE interval. That interval is whatever the two end DISCS and the middle RECTANGLE admit,
    each of which is a quadratic or a pair of linear inequalities -- so the answer is closed form.

    Closed form is the whole point. The alternative, sampling the edge, would make the answer depend
    on the sampling, which is the same class of defect as making it depend on the noding: see
    frac_len_within.

    At module scope so it can be checked against hand-computed geometry rather than through a
    rendered card.
    """
    parts = []
    a = dxu * dxu + dyu * dyu
    if a < 1e-18:
        return None
    for ox, oy in ((cx, cy), (dx, dy)):       # the two end discs
        fx, fy = ax - ox, ay - oy
        b = 2.0 * (fx * dxu + fy * dyu)
        c = fx * fx + fy * fy - r * r
        disc = b * b - 4.0 * a * c
        if disc >= 0.0:
            s = math.sqrt(disc)
            parts.append(((-b - s) / (2.0 * a), (-b + s) / (2.0 * a)))
    ex, ey = dx - cx, dy - cy                 # the rectangle, when CD is not degenerate
    E2 = ex * ex + ey * ey
    if E2 >= 1e-18:
        E = math.sqrt(E2)
        along = _lin_interval(((ax - cx) * ex + (ay - cy) * ey) / E2,
                              (dxu * ex + dyu * ey) / E2, 0.0, 1.0)
        across = _lin_interval(((ax - cx) * ey - (ay - cy) * ex) / E,
                               (dxu * ey - dyu * ex) / E, -r, r)
        if along is not None and across is not None:
            rect = _clip(along, across[0], across[1])
            if rect is not None:
                parts.append(rect)
    parts = [p for p in (_clip(p, 0.0, 1.0) for p in parts) if p is not None]
    if not parts:
        return None
    # convexity guarantees the union is contiguous, so its hull IS the union
    return (min(p[0] for p in parts), max(p[1] for p in parts))


def _union_measure(ivs):
    """Total length of a union of intervals."""
    if not ivs:
        return 0.0
    tot, cur_a, cur_b = 0.0, None, None
    for a, b in sorted(ivs):
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                tot += cur_b - cur_a
            cur_a, cur_b = a, b
        elif b > cur_b:
            cur_b = b
    return tot + (cur_b - cur_a)


def frac_len_within(pts, line, buf):
    """Fraction of `pts`'s own LENGTH lying within buf of the polyline `line`. Both in metres.

    This is "how much of this feature is in the corridor" measured GEOMETRICALLY. The measure it
    replaces counted the fraction of the feature's own VERTICES inside the corridor, and a vertex
    count is not a property of a shape -- it is a property of how someone drew it. Re-noding a corpus
    water polygon (extra points ON its own edges, identical outline) moved the printed water count on
    four cards, and on a DIFFERENT four depending how finely: at the densities the regression test
    uses, bay-view 15 (4W -> 3W, 3 area hazards -> 2), copper-valley 14 (0W -> 1W), copper-valley 18
    (3W -> 4W) and valley-hi 5 (1W -> 0W); insert three points per edge instead and castlewood-valley
    6 joins them while valley-hi 5 drops out. Same water, same shape, different number on the card,
    decided by an OSM editing accident -- and by WHICH editing accident. That is the defect this repo
    had already fixed once for LINEAR watercourses (see _seg_near_played_line) and had left standing
    on the polygon path.

    Boundary LENGTH rather than area: it is the exact continuous limit of the vertex count the
    thresholds were calibrated against (a uniformly noded ring has vertex fraction -> length
    fraction), it is closed form in stdlib arithmetic, and an area measure would need polygon
    clipping against a union of capsules -- a dependency this project does not carry, for a number
    that answers the same question.

    Degenerate input: a feature with no length (one node, or every node identical) has no length
    fraction, so it is judged by the only thing it has -- whether that point is in the corridor.
    """
    if not pts:
        return 0.0
    if len(line) < 2:
        return 0.0
    total = inside = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dxu, dyu = bx - ax, by - ay
        seglen = math.hypot(dxu, dyu)
        if seglen < 1e-9:
            continue
        total += seglen
        ivs = []
        for (cx, cy), (dx, dy) in zip(line, line[1:]):
            iv = capsule_interval(ax, ay, dxu, dyu, cx, cy, dx, dy, buf)
            if iv is not None:
                ivs.append(iv)
        inside += seglen * _union_measure(ivs)
    if total <= 0.0:
        near = min(dist_pt_seg(pts[0][0], pts[0][1], line[i][0], line[i][1],
                               line[i+1][0], line[i+1][1]) for i in range(len(line)-1))
        return 1.0 if near < buf else 0.0
    return inside / total


def render_hole(hnum, HOLES, font_scale=1.0):
    course, geom = load()
    greens=[e for e in geom if e.get('tags',{}).get('golf')=='green' and e.get('geometry')]
    holes =[e for e in geom if e.get('tags',{}).get('golf')=='hole'  and e.get('geometry')]
    _loc = config.COURSE.get('location') or {}
    hole = geo.hole_lines(geom, _loc.get('lat'), _loc.get('lon'))[hnum]   # see geo.hole_lines
    line=hole['geometry']
    green, green_end, tee_end = match_green(line, greens)

    lat0=sum(p['lat'] for p in line)/len(line); lon0=sum(p['lon'] for p in line)/len(line)
    def em(lat,lon): return ((lon-lon0)*mlon(lat0), (lat-lat0)*mlat(lat0))  # east,north meters
    tee=em(tee_end['lat'],tee_end['lon']); grn=em(green_end['lat'],green_end['lon'])
    ux,uy=grn[0]-tee[0],grn[1]-tee[1]; L=math.hypot(ux,uy) or 1; ux,uy=ux/L,uy/L
    perp=(uy,-ux)
    def proj(lat,lon):
        e,n=em(lat,lon); dx,dy=e-tee[0],n-tee[1]
        t=dx*ux+dy*uy; s=dx*perp[0]+dy*perp[1]
        return (s, -t)                       # screen: x=cross, y=-along (green on top)

    # gather features within a corridor of the hole line
    line_em=[em(p['lat'],p['lon']) for p in line]
    def dist_to_line(pe,pn):
        return min(dist_pt_seg(pe,pn,line_em[i][0],line_em[i][1],line_em[i+1][0],line_em[i+1][1])
                   for i in range(len(line_em)-1))
    def in_corridor(g, buf):
        gla,glo=centroid(g); pe,pn=em(gla,glo)
        return dist_to_line(pe,pn) < buf
    def frac_in(g, buf):
        # How much of the feature is within `buf` of THIS hole's centerline -> excludes a
        # neighbouring parallel hole's fairway/rough that only clips the edge (its centroid can be
        # near, but most of it is not).
        #
        # Measured as a fraction of the feature's own LENGTH, in closed form. It used to be the
        # fraction of its own VERTICES, which is not a property of the shape at all: re-noding a
        # water polygon -- extra points ON its own edges, identical outline -- moved the printed water
        # count on four corpus cards, and on a different four at a different density. See
        # frac_len_within.
        #
        # The geometry is taken exactly as OSM gives it, with no closing edge invented. Four of the
        # corpus's 90 water areas are unclosed multipolygon fragments of the Schuylkill (philadelphia
        # ways -1661718201..4); closing those would add a 5.9 km chord of open ground to the boundary
        # of a river and drown the real bank in the denominator.
        #
        # WHAT THIS DOES NOT FIX BY ITSELF, measured rather than guessed: a FRACTION is the wrong
        # shape of rule for a water HAZARD, and correcting the measurement makes that visible instead
        # of hiding it behind noding noise. A big pond mostly elsewhere is excluded however close it
        # comes -- valley-hi 2 printed 0W over a pond 15.8 m from the played line (32.6% of its 330 m
        # bank in the corridor), and copper-valley 18 already did that before this change, at 1.7 m
        # and a margin of 0.001. So the fraction is now only one half of an OR: see `waters`, which
        # also admits area water that REACHES the played line at all, the way the watercourse path
        # does. That reach half costs corpus area water 87 -> 102 on 13 cards.
        pts=[em(p['lat'],p['lon']) for p in (g.get('geometry') or [])]
        if not pts: return 0.0
        return frac_len_within(pts, line_em, buf)
    def edge_within(g, buf):
        """True when the feature's nearest EDGE lies within buf of the centerline, END CAPS INCLUDED.

        The reach test for SAND, and deliberately neither of the other two in this function.

        AGAINST in_corridor, WHICH MEASURES THE CENTROID: a bunker is not its centroid, and the bigger
        the sand the worse that approximation gets. the-reserve 16's way 681278621 is a 3,562 m^2 waste
        bunker -- shoelace on its own closed 75-node ring -- whose nearest edge comes 6.9 m from the
        played line 214 m along a 477 m line, about 234 yd off the tee and in the landing zone, while
        its centroid sits 40.5 m away. At the 40 m bar the centroid test excluded it, so that card
        printed "4B 1W" and drew blank ground over all 3,562 m^2 of that sand; it appeared on NO card in the
        corpus (centroid 40.5/120.9/133.3/176.5 m from holes 16/15/14/12). Water was rescued from
        exactly this defect (see `waters`) and watercourses before it (see _seg_near_played_line); sand
        was the last hazard still selected by one interior point. 40 m is not a new threshold -- it is
        the one this selector already named, and the MEASUREMENT was what was wrong. Measured cost:
        62 of the 198 geometry cards gain at least one bunker, 907 -> 984 drawn bunkers, and no card
        loses one.

        That ring is 61.9 x 129.8 m across, and this docstring published the area of THAT BOUNDING BOX
        -- 8,037 m^2, 2.26x the sand -- as the bunker's area until it was measured on the ring
        (tests: test_every_published_area_for_the_named_bunker_is_its_ring_and_not_its_bounding_box).
        The box is the wrong figure for "of sand" and the right one only where it says box.

        AGAINST any_within, WHICH CLIPS TO THE PLAYED LENGTH: sand past the green is real sand. A
        greenside bunker behind the green projects past t=1 and a bunker beside the tee projects before
        t=0, and both are clipped away whole, so any_within(g,40) would DROP 72 bunkers on 83 shipped
        cards -- bay-view 12 would go 1B -> 0B over way 872811004, whose nearest edge is 8.9 m from the
        line and projects just behind the tee (t=-0.03). Across the corpus 149 bunkers reach within
        40 m but only through those caps: 78 past the green, 71 behind the tee. That clip is right for
        a river whose only near approach is behind the tee and wrong for the class of hazard a junior
        actually finds beside a green. So the metric here is the one in_corridor already used --
        dist_pt_seg per segment, which admits a buf-radius cap at each end -- moved off the centroid
        and onto the boundary.

        Built on frac_len_within rather than a fourth copy of the geometry: a positive in-band LENGTH
        is exactly "some part of this boundary is inside buf", it is closed form, and it does not move
        when a mapper re-nodes the ring. Checked against a direct segment-to-segment minimum over
        every bunker on all 198 cards: the two agree on every one. Degenerate input (one node, or every
        node identical) falls through to frac_len_within's own point test.
        """
        pts=[em(p['lat'],p['lon']) for p in (g.get('geometry') or [])]
        if not pts: return False
        return frac_len_within(pts, line_em, buf) > 0.0
    bunkers=[g for g in course if g.get('tags',{}).get('golf')=='bunker' and g.get('geometry') and edge_within(g, CORRIDOR_M['bunker'])]
    def _seg_near_played_line(pe, pn, qe, qn, buf):
        """True when some point of the SEGMENT p->q comes within buf of the PLAYED line.

        The whole segment, not its endpoints. Testing endpoints only made the answer depend on how
        finely a mapper happened to node the way rather than on where the water is: monarch-bay way
        1135575847 is a 4-node stream whose longest segment is 1396.9 m, and it CROSSES the playing
        lines of holes 12 and 18 (nearest point 0.01 m and 0.10 m) while its nearest vertex is
        273.1 m and 93.5 m away. Both cards printed no water. Re-noding the identical shape to 72
        points made both report it. So distance is measured point-to-SEGMENT.

        PLAYED, not the whole capsule. dist_to_line clamps each segment's projection to [0, 1], so
        the corridor includes a buf-radius half-disc BEHIND the tee and PAST the green. Water sitting
        in those caps is not on the hole at all. Ten counted watercourses on eight cards are reachable
        only through them, and two of those cards would go 0W -> 1W on a river or stream whose nearest
        approach lies behind the tee: castlewood-valley 7, where the Arroyo de la Laguna comes 40.5 m
        from the drawn line but 39.6 m BEHIND the tee (along the tee-to-green chord) and no nearer
        than 260.9 m over the played length, and monarch-bay 9, 42.3 m away and behind the tee, 91.4 m
        over the played length. castlewood-valley 2 is NOT one of them and must not be cited as one:
        the same river's 43.6 m approach there projects at t=0.9151, INSIDE the played length, so that
        hole counts one watercourse with the caps and without them.

        That exclusion survives the change to a segment test because the stretch of p->q projecting
        before the first vertex, or past the last, is CLIPPED OFF this segment before any distance is
        measured -- rather than the segment being judged as a whole by where its nearest point lands.
        Where p projects onto a centerline segment is affine in the position along p->q, so the
        admissible stretch is a sub-interval of it and the clip is exact.
        """
        n = len(line_em) - 1
        for i in range(n):
            ax, ay = line_em[i]; bx, by = line_em[i+1]
            dx, dy = bx-ax, by-ay
            L2 = dx*dx + dy*dy
            if L2 < 1e-9:
                continue
            t0 = ((pe-ax)*dx + (pn-ay)*dy) / L2       # t at p
            te = ((qe-pe)*dx + (qn-pn)*dy) / L2       # dt per unit of u along p->q
            u0, u1 = 0.0, 1.0
            if i == 0:                                # drop what projects BEHIND the tee (t < 0)
                if abs(te) < 1e-12:
                    if t0 < 0.0:
                        continue
                elif te > 0:
                    u0 = max(u0, -t0/te)
                else:
                    u1 = min(u1, -t0/te)
            if i == n-1:                              # drop what projects PAST the green (t > 1)
                if abs(te) < 1e-12:
                    if t0 > 1.0:
                        continue
                elif te > 0:
                    u1 = min(u1, (1.0-t0)/te)
                else:
                    u0 = max(u0, (1.0-t0)/te)
            if u0 > u1:
                continue                              # only an end cap of the line sees this segment
            if dist_seg_seg(pe+(qe-pe)*u0, pn+(qn-pn)*u0,
                            pe+(qe-pe)*u1, pn+(qn-pn)*u1,
                            ax, ay, bx, by) < buf:
                return True
        return False

    def any_within(g, buf):
        """True when part of the feature comes within buf of the PLAYED length of this centerline.

        The only test for a LINE, and one HALF of the test for area WATER. in_corridor tests the
        CENTROID, and a creek is typically long and mostly elsewhere: a stream that crosses this
        fairway has its centroid two holes away, so it was excluded. That hid 49 open watercourses on
        31 holes, one of them passing 0.7 m from the centreline. Meanwhile the same centroid test
        INCLUDED features whose midpoint happens to sit near the line while no part of them is
        visible from it.

        "Part of the feature" means any point of it, so the walk is over its SEGMENTS -- see
        _seg_near_played_line for the node-density defect that iterating its vertices caused. For an
        area feature the walk is over the boundary EXACTLY as OSM gives it, with no closing edge
        invented, which is the same geometry frac_in measures -- see frac_in on the four unclosed
        Schuylkill fragments.
        """
        pts = [em(p['lat'], p['lon']) for p in (g.get('geometry') or [])]
        if len(pts) == 1:                             # a lone node: the degenerate segment p->p
            return _seg_near_played_line(pts[0][0], pts[0][1], pts[0][0], pts[0][1], buf)
        for (ae, an), (be, bn) in zip(pts, pts[1:]):
            if _seg_near_played_line(ae, an, be, bn, buf):
                return True
        return False

    # AREA WATER: mostly-in-the-corridor OR reaches the played line at all.
    #
    # The fraction alone is the wrong shape of rule for a HAZARD, and it omitted water a junior can
    # reach. Two shipped cards proved it: valley-hi 2 printed 0W with NO blue ink at all over way
    # 1229231804, a lateral hazard whose 329.7 m bank comes 15.8 m from the played line (14.2 m
    # unclipped) with 32.6% of that bank in the corridor against the 0.35 threshold; and copper-valley
    # 1 dropped way 775441708, a 688 m lake the drawn playing line CROSSES TWICE (minimum distance
    # 0.00 m), at frac 0.3349. That card still read 2W, because a stream crossing the same line was
    # drawn -- a map showing a hoppable creek where a lake swallows the line. Omitting water is the
    # dangerous direction; over-reporting it is merely noisy, so the gate is an OR, not a re-tuned
    # threshold.
    #
    # The reach half is `any_within` at the SAME 45 m the fraction half uses and the same 45 m the
    # watercourse path uses. Matching rather than picking a third number: a pond is wider than a
    # ditch, so asserting that area water at 45 m is less reachable than a stream at 45 m is
    # backwards, and one corridor half-width for all water keeps the footer's "water (blue)" a single
    # rule. Measured cost of the reach half: corpus area water 87 -> 102 on 13 cards, and no card
    # loses water it printed before -- an OR can only add.
    #
    # ASYMMETRY, noted rather than fixed: `any_within` is clipped to the PLAYED length (nothing behind
    # the tee or past the green counts), while `frac_in` measures against dist_pt_seg, which clamps
    # per segment and so still includes a 45 m half-disc behind the tee and past the green. One corpus
    # card is admitted by the fraction half alone through those caps: copper-valley 15 counts way
    # 775614088, whose nearest approach over the played length is 255.4 m (16.1 m unclipped). That is
    # the over-report direction and it predates this gate.
    waters =[g for g in course if (g.get('tags',{}).get('golf') in ('water_hazard','lateral_water_hazard')
             or g.get('tags',{}).get('natural')=='water') and g.get('geometry')
             and (frac_in(g, CORRIDOR_M['water'])>=0.35 or any_within(g, CORRIDOR_M['water']))]

    creeks =[g for g in course if is_visible_watercourse(g) and g.get('geometry') and any_within(g, CORRIDOR_M['water'])]
    tees   =[g for g in course if g.get('tags',{}).get('golf')=='tee' and g.get('geometry') and in_corridor(g, CORRIDOR_M['tee'])]
    fairways=[g for g in course if g.get('tags',{}).get('golf')=='fairway' and g.get('geometry') and frac_in(g, CORRIDOR_M['fairway'])>=0.40]
    roughs  =[g for g in course if g.get('tags',{}).get('golf')=='rough' and g.get('geometry') and frac_in(g, CORRIDOR_M['rough'])>=0.40]
    woods   =[g for g in course if (g.get('tags',{}).get('natural') in ('wood','scrub') or g.get('tags',{}).get('landuse')=='forest')
              and g.get('geometry') and frac_in(g, CORRIDOR_M['wood'])>=0.35]
    treerows=[g for g in course if g.get('tags',{}).get('natural')=='tree_row' and g.get('geometry') and frac_in(g, CORRIDOR_M['treerow'])>=0.35]
    def in_corr_pt(lat, lon, buf):
        pe, pn = em(lat, lon)
        return min(dist_pt_seg(pe, pn, line_em[i][0], line_em[i][1], line_em[i+1][0], line_em[i+1][1])
                   for i in range(len(line_em)-1)) < buf
    treenodes=[e for e in course if e.get('type')=='node' and e.get('tags',{}).get('natural')=='tree'
               and 'lat' in e and in_corr_pt(e['lat'], e['lon'], CORRIDOR_M['treenode'])]

    # pick the tree markers we will actually DRAW (LiDAR canopy preferred over OSM)
    lt=_lidar_trees().get(str(hnum), [])
    if lt:
        tree_src=lt; r_tree=1.8            # LiDAR canopy: dense -> smaller dots
    else:
        tree_src=[(e['lat'],e['lon']) for e in treenodes]; r_tree=3

    def poly_pts(g): return [proj(p['lat'],p['lon']) for p in g['geometry']]

    def corridor_pts(g, buf):
        """Where g's boundary lies within buf of the centerline, projected. FRAMING, not selection.

        Every other class in the frame is corridor-sized by the way it was selected -- a bunker's
        nearest edge within 40 m, a tee's centroid within 38, a fairway or tree row most of whose own
        length is inside. Sand is selected by REACH, like water and for the same reason (see
        edge_within), and is still framed WHOLE rather than through this function, because a bunker's
        own extent bounds how far that can pull the frame: moving sand onto the edge rule re-framed 44
        of the 198 cards and the worst of them, philadelphia 7, prints its map at 0.0113 in per metre
        where it printed 0.0142 -- 20% smaller, against the 52% of its length copper-valley 10 lost to
        one lake. Nothing is dropped for the room: no yardage row and no from-tee row moves on any card
        of either edition. AREA WATER is the exception: it is selected when it REACHES the hole (see
        `waters`),
        which is right for a hazard and says nothing about how big it is. Framing around all of such a
        feature shrinks the hole to fit water that is not on it: copper-valley 10's way 775614086 is a
        1239.6 m lake whose nearest approach is 40.8 m and which reaches 268 m ACROSS the hole, where
        the centerline itself spans only 148.8 m across. The frame is built on that cross extent, so
        the drawn hole lost 52% of its length; hole 18 lost 72% to that lake and one other. The
        enlarged edition then dropped two yardage rows the pocket book prints, because a compressed
        ladder cannot carry 2x type -- the exact trade the row guard exists to refuse.

        So water is framed to the corridor and drawn whole, clipping at the frame edge the way rough
        and woods and creeks already do. The points returned are the ENDPOINTS of the in-corridor
        sub-intervals of each boundary segment, which is a GEOMETRIC answer: re-noding the ring does
        not move it, so the frame cannot depend on how a mapper clicked -- the same property
        frac_len_within was written for. A straight segment's in-band stretch is bounded by its own
        endpoints, so those points bound its box exactly.

        Degenerate input (a single node, or nothing in the band at all) falls back to the whole
        feature: a water this returns nothing for would otherwise contribute no frame at all, and
        every counted hazard has to have ink on the card.
        """
        gg = g['geometry']
        pts = [em(p['lat'], p['lon']) for p in gg]
        out = []
        for i in range(len(gg) - 1):
            ax, ay = pts[i]
            dxu, dyu = pts[i+1][0] - ax, pts[i+1][1] - ay
            for j in range(len(line_em) - 1):
                iv = capsule_interval(ax, ay, dxu, dyu, line_em[j][0], line_em[j][1],
                                      line_em[j+1][0], line_em[j+1][1], buf)
                if iv is None:
                    continue
                for u in iv:                  # both ends of the in-band stretch bound its box
                    out.append(proj(gg[i]['lat'] + (gg[i+1]['lat'] - gg[i]['lat']) * u,
                                    gg[i]['lon'] + (gg[i+1]['lon'] - gg[i]['lon']) * u))
        return out or poly_pts(g)

    # frame around the corridor + every tree marker so no tree/tee/green is clipped.
    # big background fills (rough, woods) are NOT in the bounds -- they clip cleanly
    # at the frame edge instead of zooming the whole hole out. Water is drawn WHOLE and framed to the
    # corridor, which is the same treatment one step finer -- see corridor_pts.
    allpts=[proj(p['lat'],p['lon']) for p in line]
    for g in bunkers+tees+fairways+treerows+[green]:
        allpts+=poly_pts(g)
    for g in waters:
        allpts+=corridor_pts(g, CORRIDOR_M['water'])
    allpts+=[proj(la,lo) for la,lo in tree_src]
    xs=[p[0] for p in allpts]; ys=[p[1] for p in allpts]
    wx0,wy0=min(xs),min(ys); wW=(max(xs)-wx0) or 1.0; wH=(max(ys)-wy0) or 1.0
    # viewBox hugs the hole; width normalized to 100 units, height follows the hole's
    # aspect. TB = proportional top/bottom breathing room so labels/trees at the ends
    # are never cut. LG = side gutters for the distance numbers.
    CONTENT_W=100.0; LG=12.0
    s=(CONTENT_W-2*LG)/wW
    contentH=wH*s
    TB=max(8.0, 0.06*contentH)
    VBH=contentH+2*TB
    oy=TB-wy0*s
    # Physically CONSISTENT label sizes on every hole: each hole's viewBox is scaled by
    # `fit` (inches per view-unit) to fill the map column, so we size fonts inversely to
    # `fit` -> the printed text is the same size on every hole regardless of its scale.
    #
    # `fit` therefore has to be the meet-fit of the panel THIS render is printed into, and the two
    # editions do not share one. The pocket card gives the map a 1.6/4.0 column beside the green
    # (generate.py `.lay`); the ENLARGED card gives it the WHOLE card width (`.cmap`), at about the
    # same height (4.16 in against 4.18). Computed from the pocket column at BOTH scales, `fit`
    # understated the enlarged card's real scale, which inflated FSN in view units: the enlarged type
    # printed ~2.37x the pocket book's rather than the 2x it promises, and the row-collision guard
    # below -- correctly refusing to overprint that oversized type on an unchanged ladder -- then
    # dropped 12 yardage rows the pocket book prints. Nine 150-yard rows, with three 250-yard rows
    # knocked out behind them, across 9 holes of 4 courses: philadelphia 17 went [100,150,200,250,300]
    # to [100,200,250,300]. That is the same wrong trade already fixed on the HORIZONTAL axis below --
    # the enlarged edition losing data the small one prints -- and it wants the same answer: give the
    # type the room the paper actually has instead of dropping what will not fit in room it does not.
    #
    # Scaled by font_scale rather than switched on an edition flag, and capped at the full card. At
    # font_scale 1 it is bit-identical to before, so the pocket book is untouched; at font_scale 2 it
    # claims 2x a column the enlarged card in fact widens by 2.49x, so the claim is conservative and
    # errs toward a STRICTER row guard, never a looser one. The HEIGHT takes no factor because the
    # enlarged card's map is no taller than the pocket card's -- it is wider, and only wider.
    LAY_COL=min(1.0, (1.6/4.0)*font_scale)            # share of the card width the map is printed at
    LAY_W_IN=(config.CARD_W_IN-2*0.07)*LAY_COL        # map column width (see .lay / .cmap)
    LAY_H_IN=config.CARD_H_IN-2*0.07-0.50-0.18        # minus header + foot
    fit=min(LAY_W_IN/CONTENT_W, LAY_H_IN/VBH)         # in per view-unit after meet-fit
    FS=round(0.100/fit*font_scale,1)        # GRN / BLA  (~7.2 pt printed, consistent; scaled up for enlarged editions)
    FSN=round(0.092/fit*font_scale,1)       # distance numbers (~6.6 pt printed, consistent)
    # The BOX may be wider than the content, because the two gutter numbers have to fit BESIDE the
    # map and the space for them does not otherwise grow with the type. At font_scale 2 the pair
    # stopped fitting between the fixed gutters and the from-tee yardage was dropped rather than
    # overprinted -- 21 numbers on 5 of the enlarged edition's 54 cards, all of them present in the
    # pocket book. The enlarged edition losing data the small one prints is the wrong trade, and it
    # was happening while ~65% of the enlarged card's width sat blank: the map is a tall ribbon that
    # meet-fits by HEIGHT, so widening the box costs nothing at all.
    #
    # Demand-driven, so the pocket book is untouched: at 1x nothing needs more room than the 100
    # units it already has (verified across all 198 holes), so `pad` is 0 and every coordinate,
    # `fit` and font size below is bit-identical to before.
    #
    # The two caps are what keep this honest. `s`, `contentH`, `VBH` and `fit` are all computed from
    # CONTENT_W, never from the widened box, so the drawn map keeps its size and scale -- the box
    # only grows OUTWARD. And the box may not out-grow the panel's own aspect ratio, or meet-fit
    # would start fitting by width and shrink the map to buy room for its labels, which is the same
    # mistake in the other direction.
    need_w = 18.0 + 2*(DIGIT_EM*FSN*3) + 0.24*FSN     # 9-unit gutters + two 3-digit numbers + halos
    box_cap = VBH * (LAY_W_IN/LAY_H_IN)               # widest box that still meet-fits by height
    VBW = max(CONTENT_W, min(need_w, box_cap))
    pad = (VBW-CONTENT_W)/2.0
    ox=LG+pad-wx0*s
    def TX(x): return x*s+ox
    def TY(y): return y*s+oy
    def path(g,close=True):
        d="M "+" L ".join(f"{TX(x):.1f},{TY(y):.1f}" for x,y in poly_pts(g))
        return d+(" Z" if close else "")

    fair_svg ="".join(f'<path d="{path(g)}" fill="#cfe8b2" stroke="#79b356" stroke-width="1.2"/>' for g in fairways)
    rough_svg="".join(f'<path d="{path(g)}" fill="#e9f0da" stroke="#cdd9b4" stroke-width="0.5"/>' for g in roughs)
    wood_svg ="".join(f'<path d="{path(g)}" fill="#9cbf86" fill-opacity="0.6" stroke="#7ea36a" stroke-width="0.5"/>' for g in woods)
    water_svg="".join(f'<path d="{path(g)}" fill="#a9d3ef" stroke="#5b9bd0" stroke-width="1"/>' for g in waters)
    creek_svg="".join('<polyline points="'+" ".join(f"{TX(x):.1f},{TY(y):.1f}" for x,y in poly_pts(g))
                      +'" fill="none" stroke="#5b9bd0" stroke-width="1.8" stroke-linecap="round"/>' for g in creeks)
    bunk_svg ="".join(f'<path d="{path(g)}" fill="#efe3b8" stroke="#c9b477" stroke-width="0.8"/>' for g in bunkers)
    green_svg=f'<path d="{path(green)}" fill="#7cc45a" stroke="#2f5a26" stroke-width="2"/>'
    trow_svg ="".join('<polyline points="'+" ".join(f"{TX(x):.1f},{TY(y):.1f}" for x,y in poly_pts(g))
                      +'" fill="none" stroke="#2f7d32" stroke-width="3" stroke-linecap="round"/>' for g in treerows)
    tdots=[]
    for la,lo in tree_src:
        x,y=proj(la,lo); tdots.append(f'<circle cx="{TX(x):.1f}" cy="{TY(y):.1f}" r="{r_tree}" fill="#2f7d32" stroke="#fff" stroke-width="0.3"/>')
    tdot_svg="".join(tdots)

    lx=[TX(proj(p['lat'],p['lon'])[0]) for p in line]; ly=[TY(proj(p['lat'],p['lon'])[1]) for p in line]
    center=f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in zip(lx,ly))}" fill="none" stroke="#8a8a8a" stroke-width="1.1" stroke-dasharray="5,5"/>'
    tee_svg="".join(f'<path d="{path(g)}" fill="#6aa15a" stroke="#3f6b34" stroke-width="0.7"/>' for g in tees)
    gp=poly_pts(green)
    gcx=sum(TX(x) for x,y in gp)/len(gp); gcy=sum(TY(y) for x,y in gp)/len(gp)
    gtop=min(TY(y) for x,y in gp); gbot=max(TY(y) for x,y in gp)   # green extent (screen y)
    pin=f'<circle cx="{gcx:.1f}" cy="{gcy:.1f}" r="2.6" fill="none" stroke="#c0392b" stroke-width="1.1"/>'
    tx=TX(proj(tee_end['lat'],tee_end['lon'])[0]); ty=TY(proj(tee_end['lat'],tee_end['lon'])[1])
    import config as _cfg
    back_tee = (_cfg.BACK_NAME[:3].upper() if _cfg.BACK_NAME else "TEE")
    def txt(x,y,sn,fill,fs=None):
        fs=FS if fs is None else fs
        hw=fs*0.60*len(sn)/2                       # keep the whole label inside the frame
        x=min(max(x, 3+hw), VBW-3-hw)
        y=min(max(y, fs), VBH-3)
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
                f'paint-order="stroke" stroke="#fff" stroke-width="{fs*0.24:.1f}" fill="{fill}" font-weight="700">{sn}</text>')
    # place labels CLEAR of the features: GRN above the green top, BLA below the tee box,
    # so neither covers the green or the tee.
    grn_y = gtop - FS*0.35 if gtop - FS*0.35 > FS else gbot + FS
    bla_y = ty + FS*1.1 if ty + FS*1.1 < VBH-2 else ty - FS*0.6
    labels=txt(tx, bla_y, back_tee, "#20402a") + txt(gcx, grn_y, "GRN", "#2f5a26")

    # Distance ticks. LEFT number (green) = yds to the GREEN, the straight-line distance a
    # rangefinder reads. RIGHT number (brown) = yds from the BACK tee, measured ALONG the drawn
    # line. Both are drawn in the frame gutters; a row is dropped if it would collide vertically
    # with the row above, and the right number is dropped if the two would overprint horizontally.
    def etxt(x, y, sn, fill, anchor):
        # `:g` on a rounded x, for the same reason the viewBox uses it: the right gutter is now
        # VBW-9 rather than the literal 91, and a bare float would print "91.0" and rewrite every
        # pocket book's bytes without moving a single glyph.
        x = f"{round(x,1):g}"
        return (f'<text x="{x}" y="{y:.1f}" font-size="{FSN:.1f}" text-anchor="{anchor}" '
                f'paint-order="stroke" stroke="#fff" stroke-width="{FSN*0.28:.1f}" fill="{fill}" font-weight="700">{sn}</text>')
    total_yd = HOLES[hnum][_cfg.BACK_I]       # the tee THIS BOOK is built on (config.BACK_I)
    # Geometry of the drawn playing line, tee end first. arc_m is its true walked length, which the
    # from-tee label is derived from -- course yardage follows the line you walk, not the chord.
    same = lambda a, b: abs(a['lat']-b['lat']) < 1e-9 and abs(a['lon']-b['lon']) < 1e-9
    ordered = line if same(line[0], tee_end) else list(reversed(line))
    pts_em = [em(p['lat'], p['lon']) for p in ordered]
    seg = [math.hypot(pts_em[i+1][0]-pts_em[i][0], pts_em[i+1][1]-pts_em[i][1])
           for i in range(len(pts_em)-1)]
    arc_m = sum(seg) or 1.0
    arc_yd = arc_m / 0.9144
    # Does the drawn line actually span the hole? On 21 of 198 holes it does not: 19 stop short of
    # the back tee and 2 OVERSHOOT it (OSM traced past the tee). Was 22/20/2 until valley-hi 17's
    # too-tight osm_bbox was widened on 2026-07-31 and the re-fetch replaced a hand-drawn 220 yd stub
    # with the real 360 yd centreline, moving that hole into the spanning set. Either way no from-tee distance
    # can be derived, so that label is omitted rather than guessed -- the to-green number, which
    # is what you club off, is unaffected. Note the overshoot case still needs the yd < total_yd
    # bound below; suppressing the label alone does not bound the radius.
    tee_ok = abs(arc_yd - total_yd) <= max(15.0, 0.05*total_yd)
    # Where the line is SHORT of the back-tee card, is it a truncated line or a complete route from a
    # forward tee? See line_runs_from_a_forward_tee. Distance from the line's start to the nearest
    # mapped tee box, 1e9 when the course has no tee polygons at all (then this stays refused).
    start_at_tee_m = min((dist_to_poly_m(pts_em[0], t, em) for t in tees), default=1e9)
    fwd_tee = (not tee_ok and line_runs_from_a_forward_tee(
        arc_yd, total_yd,
        # Row length from the ROW, not from len(_cfg.TEES). This function takes HOLES as an argument
        # but reads BACK_I and the tee names from the module-global config, so a caller whose HOLES has
        # fewer tee columns than the bound course crashed with IndexError -- found by running the suite
        # in a shuffled order, where a synthetic 2-tee fixture inherited a real 5-tee binding left
        # behind by an earlier test. Production never hit it because generate.py passes the HOLES of the
        # course it has bound, but nothing said the two must agree, and the argument is the honest
        # source for its own width.
        [HOLES[hnum][i] for i in range(2, len(HOLES[hnum])) if i != _cfg.BACK_I], start_at_tee_m))
    # The mirror case: a line traced PAST the tee. Same conclusion -- the length difference is at the
    # tee end -- so the same signed shift and the same from-tee derivation apply.
    past_tee = not tee_ok and line_traced_past_the_tee(arc_yd, total_yd, L/0.9144)

    # A PAR 3 is the one case where the from-tee distance needs no model at all -- see
    # par3_exact_from_tee for why, and why par 4/5 are excluded. This also CORRECTS the 64 par-3 rows
    # that already printed: the proportional value differed from the exact one by a median 2 yd and
    # up to 11 yd, always because arc_m disagreed with the card.
    par3_straight = par3_exact_from_tee(HOLES[hnum][0], arc_m, L)

    # A golfer clubs off "yards to the green" -- the STRAIGHT-LINE distance a rangefinder reads, not
    # how far there is left to walk. So place each tick where the centerline crosses the circle of
    # that radius about the green centre: the label is then a true to-green distance AND the tick
    # sits on the drawn line. (Walking distance alone printed up to +43 yd over the straight line on
    # a dogleg; positioning along the chord alone put the tick up to 85 m off the drawn line.)
    gcla, gclo = centroid(green)
    gce, gcn = em(gcla, gclo)
    def _dist_to_green(la, lo):
        e, n = em(la, lo)
        return math.hypot(e-gce, n-gcn)

    # How far the drawn line's GREEN END sits from that centroid. Published in `info` because it is
    # what bounds the two gutter numbers against each other: the left number is a radius about the
    # CENTROID while the right one is a walk along the line to its END, so the two are measured from
    # points this far apart and their sum can exceed the hole's length by about this much. A test that
    # wants to bound the pair has to know it, and computing it a second time there would be a copy of
    # this frame's centroid, projection and vertex order -- the drift this module keeps removing.
    green_gap_yd = _dist_to_green(ordered[-1]['lat'], ordered[-1]['lon']) / 0.9144

    def point_at_radius(R_m):
        """(lat, lon, arc_from_tee_m) for the point on the centerline whose straight-line distance
        to the green centre is R_m, taking the crossing nearest the green. None when the line never
        reaches that radius. arc_from_tee_m is that point's walked distance from the tee end, which
        is what the from-tee label needs -- deriving it as (card total - R) would mix two different
        measures and was up to 42 yd wrong on a dogleg (bay-view h10 printed 76 for a point
        33.7 yd from the tee)."""
        prev_pt = ordered[-1]                      # green end
        prev_d = _dist_to_green(prev_pt['lat'], prev_pt['lon'])
        for i in range(len(ordered)-2, -1, -1):    # walk back toward the tee
            cur = ordered[i]
            cur_d = _dist_to_green(cur['lat'], cur['lon'])
            if prev_d <= R_m <= cur_d or cur_d <= R_m <= prev_d:
                lo_f, hi_f = 0.0, 1.0              # bisect between prev_pt (0) and cur (1)
                for _ in range(48):                # ~sub-millimetre, and immune to the
                    mid = (lo_f+hi_f)/2            # quadratic's degenerate cases
                    mla = prev_pt['lat']+(cur['lat']-prev_pt['lat'])*mid
                    mlo = prev_pt['lon']+(cur['lon']-prev_pt['lon'])*mid
                    if (_dist_to_green(mla, mlo) < R_m) == (prev_d < R_m):
                        lo_f = mid
                    else:
                        hi_f = mid
                f = (lo_f+hi_f)/2
                # the crossing lies on segment i, a fraction (1-f) along it from ordered[i]
                arc_from_tee = sum(seg[:i]) + seg[i]*(1.0-f)
                return (prev_pt['lat']+(cur['lat']-prev_pt['lat'])*f,
                        prev_pt['lon']+(cur['lon']-prev_pt['lon'])*f,
                        arc_from_tee)
            prev_pt, prev_d = cur, cur_d
        return None

    # A from-tee figure is worth printing down to 30 yd -- but 30 yd is noise on a 500-yd hole and a
    # fifth of a 128-yd one, where "28 from the tee" is real information. Scale it, which only loosens
    # below 150 yd. ONE spelling, hoisted out of the tick loop: it is also published in `info` so a
    # test can grade the gate, and a second copy there would be the drift this repo keeps fixing.
    ft_floor = min(30.0, 0.20*total_yd)
    cands=[]
    for yd in (100,150,200,250,300):
        # A tick can never be further from the green than the hole is long. This bound must NOT
        # depend on tee_ok: where the drawn centerline OVERSHOOTS the card (2 of 198 holes -- OSM
        # traced past the back tee) the from-tee label is suppressed, so a gate on that value alone
        # never fires and castlewood-hill h4 printed a "200 to green" tick on a 182-yd hole.
        # Bound on the card yardage itself, not (total_yd - 30), which would drop legitimate rows
        # on short holes (the-reserve h15 card 179 keeps its 150 tick).
        if yd >= total_yd:
            continue
        hit = point_at_radius(yd*0.9144)
        if hit is None:                            # the line never gets that far from the green
            continue
        la, lo, arc_from_tee = hit
        # A tick sitting essentially AT the tee is clutter, not information: the hole's full
        # yardage is already the headline number on the card. Judge that GEOMETRICALLY, by how far
        # along the line the tick actually is -- not by whether its from-tee label is printable,
        # which is what previously discarded perfectly good to-green numbers on holes whose
        # centerline does not span the card.
        if par3_straight:
            # The exact from-tee distance is known here, so ONE threshold governs the row: keep it
            # only if its from-tee number is printable. Judging the row on the drawn line instead
            # left merion 13 with no gutter numbers at all (its only tick sits 18 yd along a line
            # 10 yd shy of the card, though it is 28 yd from the real tee); judging the row and the
            # number by DIFFERENT thresholds instead added a to-green tick on philadelphia 15 whose
            # brown partner was then suppressed, i.e. a new half-empty row.
            if total_yd - yd < ft_floor:
                continue
        elif arc_from_tee / 0.9144 < 25.0:
            continue
        # From-tee label: on a straight par 3 it is exact (see par3_straight above). Otherwise scale
        # the card yardage by how far along the drawn line this point is -- only meaningful when the
        # line spans the hole; otherwise print the to-green number alone.
        if par3_straight:
            ft_exact = float(total_yd - yd)
        elif tee_ok:
            ft_exact = total_yd * arc_from_tee / arc_m
        elif fwd_tee or past_tee:
            # Complete route from a forward tee, or traced past the back tee: either way the length
            # difference sits at the tee end, so the back-tee distance is the card minus the walk left.
            # Both are walked measures, so this does not mix a straight-line radius into a route
            # length -- the mistake that made (card - to_green) up to 42 yd wrong on a dogleg.
            ft_exact = total_yd - (arc_m - arc_from_tee)/0.9144
        else:
            ft_exact = None
        # ROUND AFTER THE GATE, never before. `round(ft) < ft_floor` let a measurement in
        # [floor-0.5, floor) round UP onto the floor and print: castlewood-valley h8, a 344-yd par 4
        # whose 100-to-green tick measures 29.634 yd from the tee, printed "30" against a 30.0 floor
        # because `30 < 30.0` is false. It was the corpus's only instance, and nothing could see it --
        # the test grading this floor compared the PRINTED INTEGER too.
        # This is the third publish threshold in this engine to compare a rounded figure against its
        # own limit (a 3 ft elevation floor and a LiDAR density gate comparing round(n/area, 1) were
        # the first two). Suppression keeps the row: its to-green number is still true and is the one a
        # golfer clubs off -- only the from-tee figure is not worth printing.
        ft = None if (ft_exact is None or ft_exact < ft_floor) else round(ft_exact)
        sx, sy = proj(la, lo)
        cands.append((TY(sy), TX(sx), yd, ft, ft_exact))
    cands.sort()                              # by screen y (green side first)
    rings=""; lastY=-999
    # Every row this loop DRAWS, as (to_green_yd, printed_from_tee_or_None, unrounded_from_tee_or_None).
    # Published so a test can grade the from-tee floor against the MEASUREMENT rather than against the
    # integer it prints; the floor comparison itself was made on the rounded figure for a long time and
    # no test could see it -- see the ft_floor note above.
    ft_rows = []
    # Vertical guard: one printed row needs ~0.998*FSN of baseline separation (0.718 cap height +
    # two 0.14 halo strokes), so 1.35 clears it with margin while not needlessly dropping the
    # radius-spaced ticks.
    # It is NON-BINDING on the present corpus: it drops no row on any of the 198 cards at either
    # scale, and disabling it leaves every SVG byte-identical -- 830 rows printed per scale with and
    # without it. Measured tightest realised gaps: 1.4869*FSN at the coach scale (valley-hi h18) and
    # 2.1765*FSN in the pocket book (philadelphia h17), both clear of the 1.35 threshold.
    #
    # RE-MEASURE THIS COMMENT WHENEVER THE FRAME CHANGES. The gaps are in view units and the frame
    # sets the scale, so a change to what the frame contains moves every number here -- and both
    # figures have already gone stale that way. The 1.365*FSN / bay-view h9 pair predates the coach
    # edition's `fit` correction (bay-view h9's tightest is now 1.7156*FSN), and the pocket figure was
    # wrong for the whole of bd768a1: a water polygon that had entered the frame compressed
    # copper-valley h11's ladder to 1.6618*FSN while this comment still named philadelphia h17.
    # Framing water to the corridor (corridor_pts) restored it. castlewood-valley h16, the coach
    # holder until now, sits at 1.5966*FSN.
    #
    # So this is a floor kept against geometry the corpus does not yet contain, not a rule shaping the
    # printed ladder -- do not attribute a missing row to it without measuring.
    for Y0,Xc,yd,ft,ft_exact in cands:
        if Y0-lastY < FSN*1.35:
            continue
        lastY=Y0
        # Horizontal budget. The gutters sit at x=9 (start-anchored) and x=VBW-9 (end-anchored), and
        # VBW is only 100 when the numbers fit inside it -- see the box-widening note above, which
        # exists because these two used to be pinned at 9 and 91 no matter how big the type got.
        # FSN scales with font_scale, so at the 2x coach scale the numbers ran into each other
        # -- the brown one paints second WITH a white halo, so it erased digits of the to-green
        # yardage (monarch-bay h16 printed "1(498"). Budget the glyph advance plus the halo's
        # 0.14-em reach.
        wl = DIGIT_EM*FSN*len(str(yd))
        wr = DIGIT_EM*FSN*len(str(ft)) if ft is not None else 0.0
        left_end  = 9 + wl + 0.12*FSN
        right_beg = (VBW-9 - wr - 0.12*FSN) if ft is not None else VBW
        show_ft = ft is not None and left_end <= right_beg
        ft_rows.append((yd, ft if show_ft else None, ft_exact))
        # The tick MARK must not sit under a number either: at 2x the labels reach far enough in
        # that the mark was drawn beneath their halos (67 of 814 rows). Clip it to the clear band,
        # and drop it entirely if nothing legible is left -- the two numbers already mark the row.
        # The row is a LEADER, not a tick. It used to be clipped to +-4 units either side of the line,
        # which is fine when the line sits mid-frame -- but the frame is sized to hold every drawn
        # feature, so a lake or a tree belt on one side pushes the line off-centre while the numbers
        # stay pinned in the gutters at x=9 and x=VBW-9. On valley-hi 16 that left "110" and "60"
        # floating in white space ~40% of the panel from anything, with no mark reaching them. Span
        # the whole clear band between the two numbers instead, dashed and light so five of them
        # crossing a long hole read as guides rather than as fairway features.
        mx0 = left_end
        mx1 = right_beg if show_ft else VBW
        if mx1 - mx0 >= 2.0:
            rings += (f'<line x1="{mx0:.1f}" y1="{Y0:.1f}" x2="{mx1:.1f}" y2="{Y0:.1f}" '
                      f'stroke="#b4b4b4" stroke-width="0.45" stroke-dasharray="1.6,1.6"/>')
        rings += etxt(9, Y0+FSN*0.35, str(yd), "#2f5a26", "start")      # LEFT = to green
        if show_ft:
            rings += etxt(VBW-9, Y0+FSN*0.35, str(ft), "#7a4a12", "end")   # RIGHT = from back tee

    # --- CARRY DISTANCES to the bunkers a tee shot has to deal with ---------------------------
    # Standard yardage-book content the card was missing. proj() already gives along-line distance
    # from the tee, so a bunker's near and far edges are its carry window. Three filters keep this
    # honest and useful:
    #   * only bunkers inside the tee CORRIDOR (they are already, by construction of `bunkers`)
    #   * only those the tee shot can reach and must clear -- past CARRY_MIN_YD, and short of the
    #     green, so a GREENSIDE bunker is not printed as a tee carry (Merion 18's greenside pair sits
    #     at 401-429 yd and would otherwise read as a driving carry)
    #   * only those near enough to the line to be in play, not a neighbouring hole's sand
    # A bunker straddling the line (offset ~0) is the one that matters most, so offset is not used to
    # rank -- distance is, because that is what a player is choosing a club against.
    # The window is what a TEE SHOT is clubbed against. Below 80 yd nobody is carrying anything off
    # the tee; past 300 yd nobody is reaching it, and that upper bound is also what stops a genuine
    # fairway bunker far up a long hole from reading as a driving decision (Merion 18's pair at
    # 401-429 on a 502 yd hole). Both ends chosen for the reader, not the data.
    CARRY_MIN_YD, CARRY_MAX_YD = 80.0, 300.0
    # Offset is measured from the straight tee-to-green CHORD, not from the drawn polyline that the
    # sand's own drawing corridor uses (CORRIDOR_M['bunker'], 40 m off the polyline). That INCONSISTENCY
    # is deliberate, and it is conservative: 68 bunkers
    # across 43 holes lie within 30 m of the drawn line yet more than 30 m off the chord, so they are
    # drawn on the map but not quantified in the footer. Switching the test to the polyline was
    # prototyped and rejected -- it moves the printed carries on 37 holes in BOTH directions (merion 7
    # loses its only one, monarch-bay 5 goes from 85 to 254), because chord and polyline diverge each
    # way on a dogleg, and the bunkers it admits sit 40-100 m off the chord where the along-chord
    # projection understates the real carry. Doing it properly means also redefining the printed number
    # as the straight-line tee-to-edge distance. Until that is measured and validated, under-reporting a
    # hazard the map still shows beats printing a distance that is wrong as a carry.
    CARRY_OFF_M  = 30.0        # further off the CHORD than this is not quantified
    # SAND ONLY, and that is a decision rather than an oversight. Applying this same test to water
    # finds 62 features in the tee-shot corridor corpus-wide, but 41 of them span 300-1300 yd ALONG
    # the line: they are streams running WITH the hole, where a single "carry N" is meaningless. Of the
    # 21 that genuinely cross (under 60 yd of along-line extent), 10 straddle the chord, and only 4 of
    # those carry a golf water tag -- bay-view 11 and 16, merion 9, philadelphia 5. The rest are
    # `waterway=drain` or `stream`, which in OSM covers culverted and seasonally dry channels that are
    # not a hazard anyone carries.
    #
    # So quantifying water would mean inventing a crosses-versus-runs-along heuristic and trusting OSM
    # to distinguish a real hazard from a storm drain, on four holes. Printing "carry 86" for a culverted
    # drain is precisely the confident-but-unsupported number this book exists not to print, and the
    # failure is worse than the omission: the map already draws every one of these in blue and the
    # footer counts them ("1W"), so the reader is told the water is there, just not measured.
    #
    # The card says so rather than leaving it to be inferred -- the legend reads "carry N = yd ... to
    # where fairway SAND starts" (see generate.py), which is why that wording is asserted by a test.
    # Revisit only with something better than the tag to go on.
    # Every along-line distance here is measured from where the LINE starts, and on a forward-tee hole
    # that is not the back tee. Left unshifted, merion 5 printed "carry 173" for sand that is nearer
    # 276 from the Championship tee -- a 103 yd understatement of the one number a player actually
    # clubs against, and worse than the empty gutter it sat beside. Shift by the same tee-to-tee gap
    # the from-tee gutter numbers are derived through, BEFORE the filters, so the 80-300 yd window and
    # the greenside test judge back-tee distances too. That also fixes two spurious carries: merion 9's
    # greenside bunker lands at 215 on a 231 yd hole and is correctly dropped, and valley-hi 6's at 303
    # is past anyone's tee shot.
    # Signed, and correct in both directions: positive where the line starts at a forward tee, negative
    # where it was traced past the back tee.
    tee_shift_yd = (total_yd - arc_yd) if (fwd_tee or past_tee) else 0.0
    # Where the GREEN starts, along the same chord and through the same shift as every carry below.
    # min() over the whole ring rather than only its near-the-chord part: a green offset from the chord
    # projects SHORT, which understates the landing area and so refuses more carries, not fewer. That is
    # the safe direction for a number a junior clubs against. Published in `info` for the same reason
    # green_gap_yd is -- a test that grades the landing decision needs it, and computing it there would
    # be a second copy of this frame's projection, chord basis and tee shift.
    green_front_yd = min(((em(p['lat'], p['lon'])[0]-tee[0])*ux
                          + (em(p['lat'], p['lon'])[1]-tee[1])*uy) / 0.9144 + tee_shift_yd
                         for p in green['geometry'])
    carries = []
    # ...and the sand the greenside filter drops, kept rather than thrown away. It is not a tee carry,
    # which is all `near_yd > total_yd - 40` establishes, but it is still ground a lay-up has to land
    # short of. See the landing block below for what it is used for and why it is not simply excluded.
    greenside = []
    for g in bunkers:
        alongs, offs = [], []
        for p in (g.get('geometry') or []):
            e, n = em(p['lat'], p['lon'])
            dx, dy = e - tee[0], n - tee[1]
            alongs.append(dx*ux + dy*uy)
            offs.append(abs(dx*perp[0] + dy*perp[1]))
        if not alongs:
            continue
        near_yd = min(alongs)/0.9144 + tee_shift_yd
        far_yd  = max(alongs)/0.9144 + tee_shift_yd
        # The shift is only trustworthy for sand well UP the hole, where the direction from the back
        # tee is nearly the chord direction. Close to the tee the back tee's unknown lateral offset
        # dominates, and shifting swept in bunkers lying BEHIND the forward tee: merion 5 grew a
        # "carry 81" and "105" from sand at -22 and +2 yd along its own line. So the reach test must
        # also pass on the UNSHIFTED distance -- a carry has to be a real carry from the mapped tee too.
        if min(alongs)/0.9144 < CARRY_MIN_YD:
            continue
        if not (CARRY_MIN_YD <= near_yd <= CARRY_MAX_YD) or min(offs) > CARRY_OFF_M:
            continue
        if near_yd > total_yd - 40:        # greenside sand: not a tee carry, still sand
            greenside.append((near_yd, far_yd))
            continue
        carries.append((near_yd, far_yd))
    # Merge windows that overlap or nearly touch: a cluster of three bunkers spanning 149-187 is one
    # decision, and printing "149 163 167" spends the card's scarcest resource on noise.
    carries.sort()
    merged = []
    for a, b in carries:
        if merged and a - merged[-1][1] <= CARRY_MERGE_GAP_YD:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # A CARRY IS AN INVITATION TO LAND SHORT OF THE GREEN, AND SOME HOLES HAVE NOWHERE TO LAND. The
    # figure answers "how far must I fly to clear the sand and land on fairway short of the green". Where
    # the sand runs ON to the green there is no answer: flying the near edge puts the ball in sand, and
    # the distance that would clear it is the FAR edge, which the card does not print. So the near edge
    # becomes the one number on that card a player could act on and be wrong about.
    #
    # That argument was already written down here -- see the par-3 note below, on the-reserve 8 (sand
    # ending 2.24 yd short of its green) and merion 13 (sand ending PAST its green front). It was
    # keyed on PAR, and none of it is a property of par. Re-measured over the 198 geometry cards after
    # the WGS84 per-axis migration, seven windows on seven PAR 4s had no landing area either:
    #
    #     merion 10        carry 227, sand to 284.1, green front 253.4  ->  -30.7 yd
    #     micke-grove 3    carry 294, sand to 309.3, green front 296.8  ->  -12.5
    #     philadelphia 1   carry 212, sand to 307.0, green front 299.4  ->   -7.6
    #     callippe 12      carry 272, sand to 293.3, green front 293.6  ->    0.3
    #     castlewood-v 8   carry 287, sand to 309.7, green front 311.6  ->    1.9
    #     copper-valley 3  carry 294, sand to 312.4, green front 315.7  ->    3.3
    #     monarch-bay 14   carry 273, sand to 283.4, green front 286.8  ->    3.4
    #
    # Three of those are NEGATIVE: on merion 10 the sand ends 30 yd past the green front, because the
    # card (306 yd) and the mapped green disagree by 53 yd, so a greenside pair straddling the green
    # slipped past the `total_yd - 40` greenside test. philadelphia 1 is the case that motivated this:
    # three bunkers 3.8 yd apart merging into 212 -> 307 on a 325 yd hole whose green front is at 299.
    #
    # THE BAR IS CARRY_MERGE_GAP_YD, not a new threshold -- picking one would have been a guess. That
    # constant already declares a gap this small along the played line to be one obstacle rather than two
    # decisions, which is a judgement about the ground BETWEEN hazards; the ground between the last sand
    # and the green is the same kind of ground, so the green front simply joins the merge.
    #
    # THE MARGIN, AND WHICH MEASURE EACH FIGURE BELONGS TO. This note used to read "the corpus leaves a
    # clean break either side of it: worst KEPT landing area 8.7 yd (micke-grove 13), best DROPPED 3.4
    # (monarch-bay 14)". Both figures were right and the sentence still misled, because two measures are
    # in play and it named neither:
    #
    #   * by the RULE'S OWN measure -- `beyond = min(next merged window, greenside sand, green front)`,
    #     unrounded edges -- worst KEPT that the rule can decide 8.8428 (castlewood-hill 10, bounded by
    #     greenside sand), best DROPPED 6.1489 (micke-grove 13, likewise). Margin over the bound: 0.8428,
    #     and that is the thinnest real margin, so it is the honest headline for a bound governing 118
    #     printed figures.
    #   * by the SUPPRESSION TEST's measure -- last PRINTED window only, `reach` seeded from the ROUNDED
    #     far edge and then chained across any strip of grass narrower than CARRY_MERGE_GAP_YD, which is
    #     the whole obstacle rather than the part the carry filters admitted -- worst kept 17.1187
    #     (callippe 8), a margin of 9.1187.
    #
    # Both headline figures used to be micke-grove 13's: 8.7456 by the rule's own measure and 8.4352 by
    # the suppression test's, because rounding 289.69 up to 290 costs 0.31 yd. That card no longer prints
    # a carry at all -- see the greenside paragraph below -- so both figures are history, and it is the
    # thinner of the two measures that changed hands: it is now the rule's own.
    #
    # "worst KEPT" also needed qualifying: 3 kept windows are tighter than 8.8428 -- copper-valley 17 at
    # 8.2538, merion 5 at 8.5073, monarch-bay 2 at 8.5827. Every one is bounded
    # by the NEXT MERGED WINDOW, and the merge guarantees a gap above CARRY_MERGE_GAP_YD between two
    # merged windows by construction, so those are TAUTOLOGICAL and can never be dropped. 8.8428 is
    # the worst of the 82 KEPT windows the rule decides, and 8.2538 the worst of all 124 kept;
    # 95 of the corpus's 137 windows are decidable at all. (That list said FOUR,
    # naming micke-grove 11 at 8.5031, and the counts said 86 and 132. All three came from a test that
    # re-derived the rule over every golf=bunker way on the course, skipping the corridor pre-filter
    # `bunkers` is built with -- so micke-grove 11's second window is sand this engine never selects,
    # and 86 and 132 were counts of KEPT windows wearing the words "decide" and "all". The tautology
    # needed narrowing too: it holds for the next MERGED window, which the merge spaced, and not for
    # greenside sand, which never entered the merge.)
    #
    # And the value is inherited rather than measured ON PURPOSE. The physical question -- "is N yards a
    # landing area for a junior's tee shot" -- needs dispersion data this project does not have, so a
    # measured replacement would be a guess in charge of 118 figures. What the corpus can say is that the
    # decision is insensitive to the value: every window the rule decides is at 6.1489 or below or 8.8428
    # or above, so any bound inside that 2.6940 yd gap gives the identical outcome. That gap USED to be
    # 5.3205 yd wide, so counting the greenside sand has made the bound more load-bearing, not less --
    # honest either way, and 8.0 still decides no card. All of the above is
    # re-derived and graded by test_the_landing_bound_publishes_the_metric_each_of_its_margins_belongs_to,
    # which also fails if a re-fetch closes the gap and makes the value start deciding cards.
    #
    # PER WINDOW, bounded by the next sand or the green, whichever comes first -- so a hole keeps the
    # carries that DO have somewhere to land. merion 10 keeps 95 and 164 (57 and 41 yd of fairway beyond
    # them) and loses only 227.
    #
    # AND EVERY KEPT WINDOW IS PRINTED. This list used to end at `[:3]`, an unargued cap on a card whose
    # carry row has room: merion 15 keeps FOUR windows and printed three, dropping 299.15-308.40 -- a
    # reachable fairway bunker with 51.89 yd of fairway beyond it and the green front 52 yd further on.
    # Nothing marked the omission, and nothing could: `sand_to_green` would have been a false claim,
    # because that sand does not run to the green. So the cap went instead. It fired on ONE card in 198,
    # the fourth figure costs merion 15's playline 25.96 px (pocket) / 27.66 px (enlarged) against 146.02
    # and 132.36 px of slack, and a re-fetch that made a row too long fails loudly in
    # test_the_playline_is_never_clipped_by_its_own_nowrap rather than truncating in silence.
    #
    # "THE NEXT SAND" HAS TO MEAN THE NEXT SAND, INCLUDING THE GREENSIDE SAND `total_yd - 40` DROPS. That
    # filter answers "is this a tee carry worth printing?", and its answer was being reused to decide
    # "is this ground you can land on?" -- two different questions about one bunker. micke-grove 13 is
    # what that cost: printed window 206.71-289.69 on a 330 yd hole, green front 298.4352, and way
    # 1315241589 is sand from 295.84 to 306.14, INSIDE the engine's own carry corridor (13/13 ring points
    # within CARRY_OFF_M, six within 15 m) and starting BEFORE the green front. Measured to the green
    # alone the window had 8.7456 yd of landing area and kept its "carry 207"; measured to the next sand
    # it has 6.1489 and cannot. Flying 207 lands in the second bunker.
    #
    # The same asymmetry was already visible two paragraphs down: `sand_to_green` is worded FROM the
    # greenside sand this filter drops, on the eight windows the rule refused -- so that sand was
    # trusted to describe a refusal and not to decide one.
    #
    # SAND THE 80-300 REACH WINDOW DROPS IS DELIBERATELY NOT A BOUND, and monarch-bay 18 is the corpus
    # case. Its printed window is 289.97-308.13 and way 689151365 runs 313.25-323.26, dropped because
    # 313.25 is past CARRY_MAX_YD. Counting it as a bound would refuse "carry 290" over a 5.12 yd gap --
    # but CARRY_MERGE_GAP_YD already declares a gap that small to be ONE obstacle rather than two
    # decisions, so that sand is part of the same complex, and beyond the whole complex there are 57.83
    # yd of fairway before the 381.09 green front. The card's legend already says sand can run well past
    # N (the-reserve 16 prints "carry 177" for sand reaching 322). Refusing there would withdraw a
    # correct carry, which is the one thing this rule must not do.
    #
    # Cost: 8 figures across 8 of 198 cards, 128 -> 119; four cards lose their only carry row
    # (philadelphia 1, micke-grove 3 and 13, callippe 12) and no course loses all of them. Nothing is
    # hidden -- the bunkers stay drawn and stay counted in the footer's "NB". Only the false invitation
    # goes.
    #
    # AND THE CARD SAYS SO, because withdrawing the figure silently left a different fault. Nine windows
    # in this corpus have no landing area: merion 1 is one of them and it cost no printed
    # figure only because that hole's fourth merged window is the refused one, so the three it prints are
    # the three it keeps. On five of the nine (merion 1 and 10, castlewood-valley 8, copper-valley 3,
    # monarch-bay 14) an EARLIER carry survives, so the printed list just ended before the sand did and
    # nothing distinguished "no more sand" from "sand we declined to number".
    #
    # `sand_to_green` is that statement, and it carries no digit ON PURPOSE. Both edges are supported
    # numbers and both are wrong to print: the near edge is the lay-up invitation this rule exists to
    # withdraw, and the far edge is at or past the green front on all nine -- merion 10's is 284 with the
    # front at 253, philadelphia 1's is 307 with the front at 299 -- so clubbing to "clear" it flies the
    # green. Too long is the direction this file already calls the dangerous one (see the par3_straight
    # note below). Measured with the greenside sand the `total_yd - 40` filter drops, and across a strip of
    # grass narrower than CARRY_MERGE_GAP_YD where there is one (micke-grove 13's 6.15 yd), every one of
    # the nine reaches AT OR PAST the green front, which makes the wording true rather than a hedge.
    kept, no_landing = [], []
    for i, (a, b) in enumerate(merged):
        nxt = ([merged[i+1][0]] if i+1 < len(merged) else []) + [n for n, f in greenside if f > b]
        beyond = min(nxt + [green_front_yd])
        (kept if beyond - b > CARRY_MERGE_GAP_YD else no_landing).append((a, b))
    carries = [(round(a), round(b)) for a, b in kept]
    # A CARRY NEEDS AN ORIGIN THE GEOMETRY CORROBORATES. Every distance above is measured along the line
    # from where the line STARTS, shifted by tee_shift_yd. That shift only exists when tee_ok, fwd_tee or
    # past_tee established where the back tee is. Two holes printed carries with no such evidence:
    #
    #  * castlewood-valley 10 -- the from-tee gutter is BLANK on all five rows precisely because the code
    #    cannot say where the line's 64 yd shortfall lives. The carries were printed anyway, from the
    #    line's start, which asserts that start is the Black tee -- the very assumption the empty gutter
    #    refuses to make. The mapped Black tee is 51-66 yd further back, so "carry 139" understated by
    #    ~51-64 yd, and "carry 277" is 328-341 yd from the real tee, past CARRY_MAX_YD: a second-shot
    #    bunker printed as a driving carry on a 561 yd par 5. A shift cannot rescue it -- the shortfall is
    #    a cut dogleg spread along the hole, not a gap at the tee.
    #
    #  * merion 3 -- par3_exact supplies the gutter by asserting the tee sits `card` (250 yd) from the
    #    green centre, but that assertion has no geometric backing: the furthest vertex of ANY mapped tee
    #    polygon is 229.4 yd out, and tee_shift_yd stays 0, so the card printed gutters from a 250 yd
    #    origin and "carry 170" from a 215 yd one -- two origins 35 yd apart on one card.
    #
    # par3_straight is deliberately NOT in this list, and that is the whole decision. Propagating its
    # card-derived origin to the carries was the obvious fix and it is the wrong one: on merion 3 it would
    # print 205 for sand the mapped geometry puts at 184, trading a 14 yd understatement for a 21 yd
    # OVERSTATEMENT. Too long is the dangerous direction -- it tells a player they have room they do not
    # have -- which is what test_a_printed_carry_never_overstates_what_it_clears exists to forbid. On the
    # seven other par-3-exact holes the shift IS corroborated by a mapped tee box, but they all satisfy
    # tee_ok as well, so they keep their numbers either way.
    #
    # Refusing is the only move that adds no wrong number: it drops 3 figures across 2 of 198 holes and
    # changes nothing else. The map still draws the sand, and the footer still counts it as "NB".
    origin_known = bool(tee_ok or fwd_tee or past_tee)
    if not origin_known:
        carries = []
        no_landing = []          # the same frame the mark would be measured in is the untrustworthy one

    # A CARRY IS A TEE-SHOT DECISION, AND A PAR 3 DOES NOT HAVE ONE. The figure answers "how far must
    # I fly to clear the sand and land on fairway short of the green" -- which is a real question on a
    # par 4 or 5 and no question at all on a par 3, where the shot is to the green. Nobody lays up at
    # 90 yd on a 237 yd hole. All six par-3 carries in the corpus printed a number far short of the
    # card, and on two of them the near edge was actively misleading:
    #
    #   * the-reserve 8 printed "carry 90" for a 128-vertex waste complex running from 90 to 216 yd on
    #     a 237 yd hole -- sand ending 2.24 yd short of the green front (218.03 - 215.79). Flying 90
    #     clears nothing; the distance that matters is ~215. A 126 yd gap, eight or nine clubs, and the
    #     near edge is the one number on that card a player could act on and be wrong about. (The figure
    #     read "four yd" until the WGS84 per-axis migration re-measured it, and travelled into a NEW
    #     comment afterwards, so it is graded now -- see
    #     test_the_reserve_8s_published_shortfall_is_the_figure_that_was_measured.)
    #   * merion 13 printed "carry 82" on a 128 yd hole for a bunker running 82 to 113, where the green
    #     front is at 107 -- again no landing area beyond it.
    #
    # This is the concept's own boundary, not a tuning parameter: CARRY_MIN_YD/CARRY_MAX_YD (80/300)
    # and "greenside sand, not a tee carry" were written for a driving hole. Suppressing on par 3 drops
    # 6 figures across 6 of 198 holes and adds no wrong number. The map still draws every bunker and
    # the footer still counts it, so nothing is hidden -- only the false invitation to lay up is.
    #
    # KEPT ALONGSIDE the landing test above, not replaced by it, and the two are not the same claim.
    # The landing test says "this sand leaves nowhere to land"; this says "on a par 3 there is no
    # lay-up shot at all, whatever the ground looks like". Measured: the landing test catches 3 of the
    # 6 par-3 carries on geometry alone -- merion 13 (-5.8 yd), monarch-bay 7 (1.9), the-reserve 8
    # (2.2) -- and would hand back the other 3, which have real fairway beyond the sand and still no
    # shot to play to it: copper-valley 5 (19.9 yd), philadelphia 15 (21.1), micke-grove 6 (40.1).
    # Nobody lays up at 94 yd on a 179 yd hole because the gap is 40 yd wide.
    par = config.HOLES[hnum][0] if hnum in config.HOLES else None
    if par == 3:
        carries = []
        # ...and no mark either. The mark says "a carry was measured and refused for want of a landing
        # area"; on a par 3 there was no carry decision to refuse, so it would answer a question the
        # card does not raise. Four par-3 windows have no landing area (merion 3 and 13, monarch-bay 7,
        # the-reserve 8) and all four are silent for this reason, not by oversight.
        no_landing = []

    # `:g` on a rounded value, not `:.1f`: an un-widened box must print as the bare "100" it always
    # did, or all 12 pocket books change bytes for a purely cosmetic reason.
    vb=f"0 0 {round(VBW,1):g} {VBH:.1f}"
    svg=(f'<svg viewBox="{vb}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">'
         f'{wood_svg}{rough_svg}{fair_svg}{water_svg}{creek_svg}{bunk_svg}{center}{tee_svg}{green_svg}{pin}'
         f'{trow_svg}{tdot_svg}{rings}{labels}</svg>')
    # COUNT WHAT THIS CARD DRAWS. An earlier attempt counted "features whose nearest hole is this
    # one, within 90 m" so that the per-hole numbers would sum to no more than the course holds
    # (they had reached 168 bunkers on a 122-bunker course at Merion, 35 on 25 at bay-view, while
    # Philadelphia's corridor MISSED some at 119 of 131) --
    # but drawing still uses the 40 m corridor, so the footer stopped matching its own map on 115 of
    # 198 cards: Merion hole 3 printed "2B" beside eight drawn bunkers, 23 cards printed a ZERO with
    # the feature drawn, and 15 printed more than the map showed. The sum is something nobody
    # computes; the footer sitting under the map is something a 12-year-old reads directly. So the
    # footer describes the map, and a bunker between two parallel holes legitimately appears on both
    # cards -- it is in play on both.
    # The footer's water count must cover every blue mark the map DRAWS, not just the polygons OSM
    # tagged golf=water_hazard. A stream or ditch inside the corridor is drawn in the same blue and
    # is just as wet, but it was excluded: 17 cards printed "0W" over a map showing blue, and merion 5
    # printed it over five separate lines of Cobbs Creek. The guide's legend calls all of it "water
    # (blue)", so the footer was contradicting both the map beside it and the legend that explains it.
    info=dict(bunkers=len(bunkers),
              # distinct PHYSICAL waters: the area hazards plus the deduplicated watercourses. See
              # watercourse_identity -- counting OSM ways made one split creek read as several.
              waters=len(waters)+len({watercourse_identity(g) for g in creeks}),
              water_hazards=len(waters), watercourses=len(creeks),
              tees=len(tees),
              trees=len(treenodes)+len(woods)+len(treerows),length_m=round(L),aspect=round(VBW/VBH,3),
              arc_yd=round(arc_yd), card_yd=total_yd, green_gap_yd=round(green_gap_yd, 2),
              green_front_yd=round(green_front_yd, 2),
              tee_ticks=tee_ok or par3_straight or fwd_tee or past_tee,
              line_spans=tee_ok, par3_straight=par3_straight, fwd_tee=fwd_tee, past_tee=past_tee,
              carry_origin_known=origin_known,
              start_at_tee_m=round(start_at_tee_m, 1),
              from_tee_rows=ft_rows,
              from_tee_floor_yd=ft_floor,
              carries=carries,
              # "a further sand window was measured and refused" -- see the no_landing block above.
              sand_to_green=bool(no_landing))
    return svg, info

if __name__=="__main__":
    HOLES={1:(4,15,348,348,325,298,265),2:(5,1,575,548,523,499,434),3:(4,5,452,431,400,370,327),
           4:(3,17,180,180,159,135,106),5:(4,7,433,413,383,352,308),6:(5,9,537,537,515,490,419),
           7:(4,3,437,437,406,371,313),8:(3,13,237,201,182,162,141),9:(4,11,403,403,390,364,323),
           10:(4,12,415,386,366,343,311),11:(5,4,538,517,495,471,417),12:(4,8,422,376,350,321,283),
           13:(3,16,163,162,147,116,103),14:(4,6,455,418,397,370,304),15:(3,18,179,179,166,150,129),
           16:(5,10,530,530,510,484,420),17:(4,2,475,439,409,367,335),18:(4,14,394,394,374,352,308)}
    for h in range(1,19):
        try:
            _,i=render_hole(h,HOLES)
            print(f"hole {h:2d}: {i['bunkers']} bunkers, {i['waters']} water, {i['tees']} tees, line {i['length_m']}m")
        except Exception as e:
            print(f"hole {h:2d}: ERROR {type(e).__name__}: {e}")
