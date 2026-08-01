#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
High-resolution green surfaces from RAW LiDAR ground returns.

Upgrade over fetch_dem.py (which used the gridded 1 m DEM): here we read the
course's USGS 3DEP point cloud (typically 9-33 pts/m^2 over a green),
keep ONLY ground-classified points (class 2), and interpolate a 0.4 m surface
over each green — sampled on the same lat/lon grid render_green.py expects, so
the renderer is unchanged. Output -> dem_hd/holeNN.{npy,json}.
"""
import json, math, glob, os
import numpy as np, laspy
from pyproj import Transformer
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
import config
import geo

DIR = config.COURSE_DIR
OUT = f"{DIR}/dem_hd"; os.makedirs(OUT, exist_ok=True)
RES = 0.4                                   # target metres/pixel
MARGIN_M = 12.0
R_LAT = 111320.0
# Trust thresholds for a green surface. Above/below these the surface was not really measured,
# so the book must not print a read for it (see the honesty gate in main()).
NAN_FRAC_MAX = 0.02                         # max share of the green interior that may be extrapolated
DENSITY_MIN = 4.0                           # min ground returns per m^2 INSIDE the green ring
COVER_R_M = 1.0                             # a green node is "measured" if a ground return is
                                            # within this radius of it
UNCOVERED_MAX = 0.02                        # max share of the green interior with no return nearby
def mlon(lat): return 111320.0*math.cos(math.radians(lat))
# NAD83 UTM zone chosen from the course longitude (26910 = CA zone 10, 26919 = MA zone 19).
# No default: falling back to -121.0 silently selected California zone 10, so a Pennsylvania course
# (zone 18) would have every green surface projected through the wrong zone with nothing to say so.
# fetch_trees.py was fixed this way; this module -- which actually BUILDS the surfaces -- was missed.
_LOC = config.COURSE.get("location") or {}
if not isinstance(_LOC, dict) or _LOC.get("lon") is None:
    raise SystemExit('course.json needs "location": {"lat": .., "lon": ..} -- it selects the UTM '
                     'zone every green surface is built in. Refusing to guess one.')
_LON = _LOC["lon"]
UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)
TR = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)   # lon/lat -> UTM metres

def laz_to_utm():
    """Transformer from the tiles' native CRS -> the course's UTM zone (metres), plus the
    vertical scale to metres. Auto-read from the LAZ header so State Plane (ftUS) and UTM
    both work; everything downstream then stays in metres."""
    src = config.COURSE.get("lidar_crs")
    if not src:
        for t in sorted(glob.glob(f"{DIR}/laz/*.laz")):
            try:
                with laspy.open(t) as f:
                    src = f.header.parse_crs()
                    if src:
                        break
            except Exception:
                pass
    if src is None:
        # Assuming a CRS-less cloud is already in the course UTM zone with metres for Z is the guess
        # geo.vertical_scale exists to prevent: geo.vertical_scale(UTM) returns 1.0, so a US-survey-
        # foot cloud would go unscaled and EVERY printed slope, contour and arrow would be 3.28x too
        # steep. fetch_trees.py was hard-stopped on this; this module makes the surfaces those numbers
        # come from, so it matters more here.
        raise SystemExit(
            "no CRS in any LAZ tile and no \"lidar_crs\" in course.json.\n"
            "  Refusing to assume the cloud is already in %s with metres for Z: if it is in US\n"
            "  survey feet, every slope would print 3.28x too steep. Set \"lidar_crs\" to a CRS\n"
            "  that carries its units (a compound EPSG code or full WKT), then re-run." % UTM)
    pt = Transformer.from_crs(src, UTM, always_xy=True)
    return pt, geo.vertical_scale(src)      # from the CRS axis unit, never guessed from its name

def centroid(g):
    la=sum(p['lat'] for p in g['geometry'])/len(g['geometry'])
    lo=sum(p['lon'] for p in g['geometry'])/len(g['geometry']); return la,lo

def _polygon_utm(geometry):
    """The green ring as UTM (x, y) arrays."""
    vx, vy = TR.transform([p['lon'] for p in geometry], [p['lat'] for p in geometry])
    return np.asarray(vx), np.asarray(vy)


def _ring_area_m2(geometry):
    """Shoelace area of the green ring in square metres (UTM)."""
    vx, vy = _polygon_utm(geometry)
    return abs(float(np.dot(vx, np.roll(vy, -1)) - np.dot(np.roll(vx, -1), vy))) / 2.0


def _in_polygon(ux, uy, geometry):
    """Mask of sample points (UTM) falling inside a green polygon (lat/lon ring).
    Vectorised ray-cast; the ring is projected to the same UTM frame as the samples."""
    vx, vy = TR.transform([p['lon'] for p in geometry], [p['lat'] for p in geometry])
    vx = np.asarray(vx); vy = np.asarray(vy)
    inside = np.zeros(len(ux), dtype=bool)
    for i in range(len(vx)):
        j = i-1
        x1, y1, x2, y2 = vx[i], vy[i], vx[j], vy[j]
        crosses = (y1 > uy) != (y2 > uy)
        with np.errstate(divide='ignore', invalid='ignore'):
            xint = (x2-x1)*(uy-y1)/np.where(y2 == y1, np.nan, y2-y1) + x1
        inside ^= crosses & (ux < xint)
    return inside

def bearing(a_lat,a_lon,b_lat,b_lon):
    dE=(b_lon-a_lon)*mlon((a_lat+b_lat)/2); dN=(b_lat-a_lat)*R_LAT
    return (math.degrees(math.atan2(dE,dN))+360)%360

def build_targets():
    geom=json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    greens=[e for e in geom if e.get('tags',{}).get('golf')=='green' and e.get('geometry')]
    # ONE hole-line chooser for the whole pipeline. This used to keep the longest way per ref,
    # first-wins on a tie -- the exact heuristic geo.hole_lines was written to replace after it
    # flipped under element reordering on castlewood-valley (two candidates 513 m apart, both
    # 3 vertices). Three fetch scripts still carried their own copy of it, so the tree corridors,
    # the green surfaces and the gap-fill DEM could each have been placed on a DIFFERENT line
    # from the one render_hole draws and fetch_hole_elev measures against. They all agreed on all
    # 198 holes only because the cached element order happened to favour it. geo.hole_lines picks
    # by distance to the course centre and REFUSES a near-tie rather than guessing.
    _loc = config.COURSE.get('location') or {}
    holes = list(geo.hole_lines(geom, _loc.get('lat'), _loc.get('lon')).values())
    gc=[(g,*centroid(g)) for g in greens]
    targets={}
    bound={}          # hole -> green, so a green shared by two holes can be caught (see geo.py)
    for h in holes:
        ref=h['tags'].get('ref')
        if not(ref and ref.isdigit()):continue
        hn=int(ref); line=h['geometry']
        green,gend,_tend = geo.match_green(line, greens, label=f"hole {hn}")
        bound[hn]=green
        prev = line[1] if gend is line[0] else line[-2]
        appr=bearing(prev['lat'],prev['lon'],gend['lat'],gend['lon'])
        gpoly=green['geometry']; lats=[p['lat'] for p in gpoly]; lons=[p['lon'] for p in gpoly]
        clat,clon=centroid(green)
        dlat=MARGIN_M/R_LAT; dlon=MARGIN_M/mlon(clat)
        xmin,xmax=min(lons)-dlon,max(lons)+dlon
        ymin,ymax=min(lats)-dlat,max(lats)+dlat
        wm=(xmax-xmin)*mlon(clat); hm=(ymax-ymin)*R_LAT
        W=max(40,int(wm/RES)); H=max(40,int(hm/RES))
        # grid of cell-centre lon/lat -> UTM (for interpolation) ; store bbox for renderer
        us=(np.arange(W)+0.5)/W; vs=(np.arange(H)+0.5)/H
        lon_g=xmin+us*(xmax-xmin); lat_g=ymax-vs*(ymax-ymin)   # row0=top=ymax
        LON,LAT=np.meshgrid(lon_g,lat_g)
        UX,UY=TR.transform(LON.ravel(),LAT.ravel())
        # UTM bbox of the patch (for point pre-filtering)
        cx,cy=TR.transform([xmin,xmax,xmin,xmax],[ymin,ymin,ymax,ymax])
        targets[hn]=dict(green=green,appr=appr,bbox=[xmin,ymin,xmax,ymax],W=W,H=H,
                         clat=clat,clon=clon,
                         UX=UX,UY=UY,   # target sample points in UTM
                         uxmin=min(cx)-2,uxmax=max(cx)+2,uymin=min(cy)-2,uymax=max(cy)+2,
                         acc_x=[],acc_y=[],acc_z=[])
    geo.assert_one_green_per_hole(bound, label=config.SLUG)
    return targets

def main():
    pt2utm, zscale = laz_to_utm()
    print(f"LiDAR -> {UTM} reproject; vertical scale to m =", zscale)
    targets=build_targets()
    tiles=sorted(glob.glob(f"{DIR}/laz/*.laz"))
    print("tiles:",[os.path.basename(t) for t in tiles])
    for tf in tiles:
        las=laspy.read(tf)
        cls=np.asarray(las.classification)
        g=cls==2
        # reproject ground points to the course UTM zone (metres); scale Z to metres
        x,y = pt2utm.transform(np.asarray(las.x)[g], np.asarray(las.y)[g])
        z = np.asarray(las.z)[g]*zscale
        txmin,txmax=x.min(),x.max(); tymin,tymax=y.min(),y.max()
        used=0
        for hn,t in targets.items():
            if t['uxmax']<txmin or t['uxmin']>txmax or t['uymax']<tymin or t['uymin']>tymax:
                continue
            m=(x>=t['uxmin'])&(x<=t['uxmax'])&(y>=t['uymin'])&(y<=t['uymax'])
            if m.any():
                t['acc_x'].append(x[m]); t['acc_y'].append(y[m]); t['acc_z'].append(z[m]); used+=1
        print(f"  {os.path.basename(tf)}: {g.sum()} ground pts, fed {used} greens")
        del las,cls,x,y,z

    for hn,t in sorted(targets.items()):
        if not t['acc_x']:
            print(f"hole {hn}: NO POINTS"); continue
        px=np.concatenate(t['acc_x']); py=np.concatenate(t['acc_y']); pz=np.concatenate(t['acc_z'])
        pts=np.c_[px,py]
        grid=np.c_[t['UX'],t['UY']]
        zi=griddata(pts,pz,grid,method='linear')
        nan=np.isnan(zi)
        # HONESTY GATE. griddata's linear pass returns NaN for every node OUTSIDE the point
        # cloud's convex hull; the nearest pass below then copies a z value in -- terrain the
        # LiDAR never saw. That is fine for the 12 m margin ring (deliberately outside the
        # green) but NOT on the putting surface itself, so measure the gap where it matters:
        # the fraction of NaN nodes lying INSIDE the green polygon. Recorded in the meta so
        # render_green can refuse to draw a read that was invented rather than measured.
        inside=_in_polygon(t['UX'],t['UY'],t['green']['geometry'])
        n_in=int(inside.sum())
        nan_frac=float((nan & inside).sum())/n_in if n_in else 1.0
        # nan_frac alone answers "is the green inside the point cloud's CONVEX HULL?", which is not
        # the question. griddata's linear pass only returns NaN outside the hull, so an INTERIOR void
        # -- standing water absorbs 1064 nm and returns nothing -- is spanned by the interpolation and
        # counted as measured. A demo deleting the returns in a 6 m circle at each green centre (about
        # a quarter of a 450 m^2 green) still reported nan_frac=0.0000 and insufficient=False, while
        # changing 7 of 18 printed reads. So ALSO measure real coverage: every green node must have a
        # ground return near it. (Measured on the built corpus: the worst uncovered share sits under
        # 1%, well inside the 2% gate, so no existing green is affected -- this closes a blind spot
        # rather than reclassifying anything. Stated as a bound, not an exact figure: the exact worst
        # moves whenever a course is added or re-fetched, and this comment carried a stale 0.87%
        # against an actual 0.71% for exactly that reason.)
        if n_in:
            tree=cKDTree(pts)
            dist,_=tree.query(grid[inside], k=1)
            uncovered=float((dist>COVER_R_M).mean())
        else:
            uncovered=1.0
        if nan.any():
            zi[nan]=griddata(pts,pz,grid[nan],method='nearest')
        arr=zi.reshape(t['H'],t['W'])
        # Density INSIDE the green ring, over the ring's true area. It used to divide the points of a
        # padded prefilter region by the unpadded bbox -- and that bbox includes MARGIN_M=12 m of
        # fairway and bunker, so the published figure was neither a green density nor consistent with
        # its own divisor. gen_provenance publishes this number as density "over N greens".
        g_area=_ring_area_m2(t['green']['geometry'])
        n_pts_in=int(_in_polygon(px,py,t['green']['geometry']).sum())
        dens=round(n_pts_in/g_area,1) if g_area>0 else 0.0
        # A green is only trustworthy if the surface was actually measured under it.
        insufficient = bool(nan_frac > NAN_FRAC_MAX or dens < DENSITY_MIN
                            or uncovered > UNCOVERED_MAX)
        np.save(f"{OUT}/hole{hn:02d}.npy",arr)
        meta=dict(hole=hn,approach_bearing=t['appr'],bbox=t['bbox'],W=t['W'],H=t['H'],
                  green_id=t['green']['id'],green_center=[t['clat'],t['clon']],
                  polygon=[[p['lat'],p['lon']] for p in t['green']['geometry']],
                  source="USGS 3DEP LiDAR ground returns @0.4m",
                  npts=int(len(pz)), density=dens,
                  nan_frac=round(nan_frac,4), uncovered=round(uncovered,4),
                  insufficient=insufficient)
        json.dump(meta,open(f"{OUT}/hole{hn:02d}.json","w"))
        flag=("  *** INSUFFICIENT LiDAR: %.1f%% of the green interior was extrapolated, not "
              "measured -- render blank ***" % (100*nan_frac)) if insufficient else ""
        print(f"hole {hn:2d}: {t['W']}x{t['H']} @0.4m  {len(pz):6d} ground pts "
              f"({dens}/m^2 in-green, {100*nan_frac:.1f}% extrapolated, "
              f"{100*uncovered:.1f}% uncovered){flag}")

if __name__=="__main__":
    main()
