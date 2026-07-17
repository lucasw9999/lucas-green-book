#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Render a per-hole LAYOUT (tee -> green corridor) from OpenStreetMap geometry.

Orientation: tee at the BOTTOM, green at the TOP (you read it as you play).
Shows: hole centerline, tee boxes, fairway bunkers, water / lateral hazards,
the green (with a hollow 'pin' ring you mark on the day), and yardage.

Data: OpenStreetMap (ODbL) golf features in osm_course.json + osm_geom.json.
"""
import json, math, os
import config
DIR = config.COURSE_DIR
R_LAT = 111320.0

_LIDAR_TREES = None
def _lidar_trees():
    """LiDAR-derived tree markers per hole (from fetch_trees.py), if available."""
    global _LIDAR_TREES
    if _LIDAR_TREES is None:
        p = os.path.join(config.COURSE_DIR, "trees_lidar.json")
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

def match_green(hole_line, greens):
    def near(pt):
        best=1e9; bg=None
        for g in greens:
            gla,glo=centroid(g)
            dm=math.hypot((pt['lon']-glo)*mlon(gla),(pt['lat']-gla)*R_LAT)
            if dm<best: best,bg=dm,g
        return best,bg
    da,ga=near(hole_line[0]); db,gb=near(hole_line[-1])
    return (ga, hole_line[0], hole_line[-1]) if da<=db else (gb, hole_line[-1], hole_line[0])

def dist_pt_seg(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay; L2=dx*dx+dy*dy
    if L2<1e-9: return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/L2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

def render_hole(hnum, HOLES, font_scale=1.0):
    course, geom = load()
    greens=[e for e in geom if e.get('tags',{}).get('golf')=='green' and e.get('geometry')]
    holes =[e for e in geom if e.get('tags',{}).get('golf')=='hole'  and e.get('geometry')]
    hole=max((h for h in holes if h['tags'].get('ref')==str(hnum)),
             key=lambda h: len(h.get('geometry') or []))   # longest centerline if dup refs
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
    VBW=100.0; LG=12.0
    s=(VBW-2*LG)/wW
    contentH=wH*s
    TB=max(8.0, 0.06*contentH)
    VBH=contentH+2*TB
    ox=LG-wx0*s; oy=TB-wy0*s
    def TX(x): return x*s+ox
    def TY(y): return y*s+oy
    # Physically CONSISTENT label sizes on every hole: each hole's viewBox is scaled by
    # `fit` (inches per view-unit) to fill the map column, so we size fonts inversely to
    # `fit` -> the printed text is the same size on every hole regardless of its scale.
    LAY_W_IN=(config.CARD_W_IN-2*0.07)*(1.6/4.0)      # map column width (see .lay flex)
    LAY_H_IN=config.CARD_H_IN-2*0.07-0.50-0.18        # minus header + foot
    fit=min(LAY_W_IN/VBW, LAY_H_IN/VBH)               # in per view-unit after meet-fit
    FS=round(0.100/fit*font_scale,1)        # GRN / BLA  (~7.2 pt printed, consistent; scaled up for enlarged editions)
    FSN=round(0.092/fit*font_scale,1)       # distance numbers (~6.6 pt printed, consistent)
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
    back_tee = (_cfg.TEES[0][:3].upper() if _cfg.TEES else "TEE")
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

    # Distance ticks. LEFT number = yds to GREEN (green). RIGHT number = yds from
    # the BLACK (back) tee (brown). Placed at the frame edges and spaced apart so
    # numbers never overlap; points too near the tee or green are skipped.
    def etxt(x, y, sn, fill, anchor):
        return (f'<text x="{x}" y="{y:.1f}" font-size="{FSN:.1f}" text-anchor="{anchor}" '
                f'paint-order="stroke" stroke="#fff" stroke-width="{FSN*0.28:.1f}" fill="{fill}" font-weight="700">{sn}</text>')
    total_yd = HOLES[hnum][2]                 # BLACK (back) tee scorecard yardage
    cands=[]
    for yd in (100,150,200,250,300):
        ft = total_yd - yd
        if ft < 30 or yd < 40:                # skip points too near the tee/green
            continue
        t=L-yd*0.9144
        if t<=2: continue
        e=tee[0]+ux*t; n=tee[1]+uy*t
        dx,dy=e-tee[0],n-tee[1]; sx=dx*perp[0]+dy*perp[1]; sy=-(dx*ux+dy*uy)
        cands.append((TY(sy), TX(sx), yd, ft))
    cands.sort()                              # by screen y (green side first)
    rings=""; lastY=-999
    for Y0,Xc,yd,ft in cands:
        if Y0-lastY < FSN*2.6:                # keep the numbers from stacking
            continue
        lastY=Y0
        rings+=(f'<line x1="{Xc-4:.1f}" y1="{Y0:.1f}" x2="{Xc+4:.1f}" y2="{Y0:.1f}" stroke="#9a9a9a" stroke-width="0.7"/>'
                + etxt(9,  Y0+FSN*0.35, str(yd), "#2f5a26", "start")   # LEFT  = to green
                + etxt(91, Y0+FSN*0.35, str(ft), "#7a4a12", "end"))    # RIGHT = from black tee

    vb=f"0 0 100 {VBH:.1f}"
    svg=(f'<svg viewBox="{vb}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">'
         f'{wood_svg}{rough_svg}{fair_svg}{water_svg}{creek_svg}{bunk_svg}{center}{tee_svg}{green_svg}{pin}'
         f'{trow_svg}{tdot_svg}{rings}{labels}</svg>')
    info=dict(bunkers=len(bunkers),waters=len(waters),tees=len(tees),
              trees=len(treenodes)+len(woods)+len(treerows),length_m=round(L),aspect=round(VBW/VBH,3))
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
