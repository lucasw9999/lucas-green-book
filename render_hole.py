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
DIR = config.COURSE_DIR
R_LAT = 111320.0

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
def mlon(lat): return 111320.0*math.cos(math.radians(lat))

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

def render_hole(hnum, HOLES, font_scale=1.0):
    course, geom = load()
    greens=[e for e in geom if e.get('tags',{}).get('golf')=='green' and e.get('geometry')]
    holes =[e for e in geom if e.get('tags',{}).get('golf')=='hole'  and e.get('geometry')]
    _loc = config.COURSE.get('location') or {}
    hole = geo.hole_lines(geom, _loc.get('lat'), _loc.get('lon'))[hnum]   # see geo.hole_lines
    line=hole['geometry']
    green, green_end, tee_end = match_green(line, greens)

    lat0=sum(p['lat'] for p in line)/len(line); lon0=sum(p['lon'] for p in line)/len(line)
    def em(lat,lon): return ((lon-lon0)*mlon(lat0), (lat-lat0)*R_LAT)   # east,north meters
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
    def in_corridor(g, buf=45):
        gla,glo=centroid(g); pe,pn=em(gla,glo)
        return dist_to_line(pe,pn) < buf
    def frac_in(g, buf):
        # fraction of the feature's own vertices that lie within `buf` of THIS hole's
        # centerline -> excludes a neighbouring parallel hole's fairway/rough that only
        # clips the edge (its centroid can be near, but most of it is not).
        pts=g.get('geometry') or []
        if not pts: return 0.0
        c=sum(1 for p in pts if dist_to_line(*em(p['lat'],p['lon'])) < buf)
        return c/len(pts)
    bunkers=[g for g in course if g.get('tags',{}).get('golf')=='bunker' and g.get('geometry') and in_corridor(g,40)]
    waters =[g for g in course if (g.get('tags',{}).get('golf') in ('water_hazard','lateral_water_hazard')
             or g.get('tags',{}).get('natural')=='water') and g.get('geometry') and frac_in(g,45)>=0.35]
    creeks =[g for g in course if g.get('tags',{}).get('waterway') and g.get('geometry') and in_corridor(g,45)]
    tees   =[g for g in course if g.get('tags',{}).get('golf')=='tee' and g.get('geometry') and in_corridor(g,38)]
    fairways=[g for g in course if g.get('tags',{}).get('golf')=='fairway' and g.get('geometry') and frac_in(g,34)>=0.40]
    roughs  =[g for g in course if g.get('tags',{}).get('golf')=='rough' and g.get('geometry') and frac_in(g,48)>=0.40]
    woods   =[g for g in course if (g.get('tags',{}).get('natural') in ('wood','scrub') or g.get('tags',{}).get('landuse')=='forest')
              and g.get('geometry') and frac_in(g,55)>=0.35]
    treerows=[g for g in course if g.get('tags',{}).get('natural')=='tree_row' and g.get('geometry') and frac_in(g,45)>=0.35]
    def in_corr_pt(lat, lon, buf=48):
        pe, pn = em(lat, lon)
        return min(dist_pt_seg(pe, pn, line_em[i][0], line_em[i][1], line_em[i+1][0], line_em[i+1][1])
                   for i in range(len(line_em)-1)) < buf
    treenodes=[e for e in course if e.get('type')=='node' and e.get('tags',{}).get('natural')=='tree'
               and 'lat' in e and in_corr_pt(e['lat'], e['lon'], 68)]

    # pick the tree markers we will actually DRAW (LiDAR canopy preferred over OSM)
    lt=_lidar_trees().get(str(hnum), [])
    if lt:
        tree_src=lt; r_tree=1.8            # LiDAR canopy: dense -> smaller dots
    else:
        tree_src=[(e['lat'],e['lon']) for e in treenodes]; r_tree=3

    def poly_pts(g): return [proj(p['lat'],p['lon']) for p in g['geometry']]
    # frame around the corridor + every tree marker so no tree/tee/green is clipped.
    # big background fills (rough, woods) are NOT in the bounds -- they clip cleanly
    # at the frame edge instead of zooming the whole hole out.
    allpts=[proj(p['lat'],p['lon']) for p in line]
    for g in bunkers+waters+tees+fairways+treerows+[green]:
        allpts+=poly_pts(g)
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
    LAY_W_IN=(config.CARD_W_IN-2*0.07)*(1.6/4.0)      # map column width (see .lay flex)
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
    # Does the drawn line actually span the hole? On 22 of 198 holes it does not: 20 stop short of
    # the back tee and 2 OVERSHOOT it (OSM traced past the tee). Either way no from-tee distance
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
        # A from-tee figure is worth printing down to 30 yd -- but 30 yd is noise on a 500-yd hole
        # and a fifth of a 128-yd one, where "28 from the tee" is real information. Scale it, which
        # only loosens below 150 yd.
        ft_floor = min(30.0, 0.20*total_yd)
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
            ft = round(total_yd - yd)
        elif tee_ok:
            ft = round(total_yd * arc_from_tee / arc_m)
        elif fwd_tee or past_tee:
            # Complete route from a forward tee, or traced past the back tee: either way the length
            # difference sits at the tee end, so the back-tee distance is the card minus the walk left.
            # Both are walked measures, so this does not mix a straight-line radius into a route
            # length -- the mistake that made (card - to_green) up to 42 yd wrong on a dogleg.
            ft = round(total_yd - (arc_m - arc_from_tee)/0.9144)
        else:
            ft = None
        if ft is not None and ft < ft_floor:
            ft = None          # keep the row: its to-green number is still true and is the one a
                               # golfer clubs off -- only the from-tee figure is not worth printing
        sx, sy = proj(la, lo)
        cands.append((TY(sy), TX(sx), yd, ft))
    cands.sort()                              # by screen y (green side first)
    rings=""; lastY=-999
    # Vertical guard: one printed row needs ~0.998*FSN of baseline separation (0.718 cap height +
    # two 0.14 halo strokes), so 1.35 clears it with margin while not needlessly dropping the
    # radius-spaced ticks. Measured tightest realised gap: 1.365*FSN (coach edition, bay-view h9).
    for Y0,Xc,yd,ft in cands:
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
    # 45 m drawing corridor uses. That INCONSISTENCY is deliberate, and it is conservative: 68 bunkers
    # across 43 holes lie within 30 m of the drawn line yet more than 30 m off the chord, so they are
    # drawn on the map but not quantified in the footer. Switching the test to the polyline was
    # prototyped and rejected -- it moves the printed carries on 37 holes in BOTH directions (merion 7
    # loses its only one, monarch-bay 5 goes from 85 to 254), because chord and polyline diverge each
    # way on a dogleg, and the bunkers it admits sit 40-100 m off the chord where the along-chord
    # projection understates the real carry. Doing it properly means also redefining the printed number
    # as the straight-line tee-to-edge distance. Until that is measured and validated, under-reporting a
    # hazard the map still shows beats printing a distance that is wrong as a carry.
    CARRY_OFF_M  = 30.0        # further off the CHORD than this is not quantified
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
    carries = []
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
        if near_yd > total_yd - 40:        # greenside sand, not a tee carry
            continue
        carries.append((near_yd, far_yd))
    # Merge windows that overlap or nearly touch: a cluster of three bunkers spanning 149-187 is one
    # decision, and printing "149 163 167" spends the card's scarcest resource on noise.
    carries.sort()
    merged = []
    for a, b in carries:
        if merged and a - merged[-1][1] <= 8:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    carries = [(round(a), round(b)) for a, b in merged][:3]

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
              waters=len(waters)+len(creeks),
              water_hazards=len(waters), watercourses=len(creeks),
              tees=len(tees),
              trees=len(treenodes)+len(woods)+len(treerows),length_m=round(L),aspect=round(VBW/VBH,3),
              arc_yd=round(arc_yd), card_yd=total_yd,
              tee_ticks=tee_ok or par3_straight or fwd_tee or past_tee,
              line_spans=tee_ok, par3_straight=par3_straight, fwd_tee=fwd_tee, past_tee=past_tee,
              start_at_tee_m=round(start_at_tee_m, 1),
              carries=carries)
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
