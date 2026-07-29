#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Extract TREES from the LiDAR point cloud (high-vegetation returns, class 5) for a
course, so trees appear at real locations even where OpenStreetMap has none.

Reads COURSE_DIR/laz/*.laz + osm_geom.json (hole centerlines), keeps class-5
points within a corridor of each hole, thins them to a grid so each clump gives a
few markers, and writes COURSE_DIR/trees_lidar.json = {hole: [[lat,lon],...]}.

Run:  COURSE=<slug> python3 fetch_trees.py
"""
import glob, os, json, math
import numpy as np, laspy
from pyproj import Transformer
import config
import geo

DIR = config.COURSE_DIR
R_LAT = 111320.0
def mlon(lat): return 111320.0*math.cos(math.radians(lat))
# NAD83 UTM zone chosen from the course longitude (26910 = CA zone 10, 26919 = MA zone 19)
# No default. A course.json without "location" used to fall back to -121.0, i.e. silently pick
# California UTM zone 10 -- for a Pennsylvania course (zone 18) every tree would be projected
# through the wrong zone, and nothing would say so.
_LOC = config.COURSE.get("location") or {}
if not isinstance(_LOC, dict) or _LOC.get("lon") is None:
    raise SystemExit('course.json needs "location": {"lat": .., "lon": ..} -- it selects the UTM '
                     'zone for every tree position. Refusing to guess one.')
_LON = _LOC["lon"]
UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)
FWD = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)   # lon/lat -> UTM m
INV = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)

def laz_to_utm():
    """Transformer from the tiles' native CRS -> the course's UTM zone (metres) + vertical scale to m."""
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
        # Assuming the tiles are already in the course's UTM zone with metres for Z is exactly the
        # guess geo.vertical_scale exists to prevent: a US-survey-foot cloud would go unscaled and
        # every slope, contour and arrow would print 3.28x too steep, with nothing to reveal it.
        raise SystemExit(
            "no CRS in any LAZ tile and no \"lidar_crs\" in course.json.\n"
            "  Refusing to assume the cloud is already in %s with metres for Z: if it is in US\n"
            "  survey feet, every slope would print 3.28x too steep. Set \"lidar_crs\" to a CRS\n"
            "  that carries its units (a compound EPSG code or full WKT), then re-run." % UTM)
    # vertical unit from the CRS axis, never guessed from its name (see geo.vertical_scale)
    return Transformer.from_crs(src, UTM, always_xy=True), geo.vertical_scale(src)

def dist_pt_seg(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay; L2=dx*dx+dy*dy
    if L2<1e-9: return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/L2)); return math.hypot(px-(ax+t*dx),py-(ay+t*dy))

def _pip(x, y, poly):
    """point-in-polygon (ray cast); poly is a list of (lon,lat)."""
    inside=False; n=len(poly); j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>y)!=(yj>y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-15)+xi):
            inside=not inside
        j=i
    return inside

def load_playing_surfaces():
    """Polygons where a tree marker must be a false positive, with bboxes:
      * fairway / green / tee / bunker -- trees never grow on a playing surface, so a marker
        there is an edge-tree clipped in or a non-vegetation elevated return (cart, mower,
        person, flagstick).
      * BUILDINGS -- a roof is 2.5-35 m above ground and reads exactly like canopy. On tiles
        that carry class 6 we drop those points upstream, but most of our tiles are
        unclassified, so a clubhouse roof arrives as class 1 and only its FOOTPRINT can
        identify it (53 markers sat on Merion's clubhouse before this)."""
    els=[]; seen=set()
    for fn in ("osm_course.json","osm_geom.json"):
        p=f"{DIR}/{fn}"
        if os.path.exists(p):
            j=json.load(open(p))
            for e in (j.get("elements",j) if isinstance(j,dict) else j):
                # the two files overlap (greens appear in both), so de-dup by id or the polygon
                # itself -- otherwise the same green is tested twice and the log over-counts.
                k=e.get('id') if e.get('id') is not None else id(e)
                if k in seen: continue
                seen.add(k); els.append(e)
    surfaces=[]
    for e in els:
        t=e.get('tags',{})
        is_surface = (t.get('golf') in ('fairway','green','tee','bunker')
                      or t.get('building') not in (None, 'no'))
        if is_surface and e.get('geometry'):
            poly=[(p['lon'],p['lat']) for p in e['geometry']]
            xs=[c[0] for c in poly]; ys=[c[1] for c in poly]
            # building='no' means NOT a building -- must not be treated as a surface at all
            kind='building' if t.get('building') not in (None,'no') else 'golf'
            surfaces.append((min(xs),min(ys),max(xs),max(ys),poly,kind))
    return surfaces

def on_playing_surface(lon,lat,surfaces):
    """'golf' | 'building' | False -- which kind of surface this marker falls on (counted
    separately, because reporting a building drop as a 'green/fairway/tee/bunker' drop
    overstated that number by 16x on valley-hi)."""
    for x0,y0,x1,y1,poly,kind in surfaces:
        if x0<=lon<=x1 and y0<=lat<=y1 and _pip(lon,lat,poly):
            return kind
    return False

def main():
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        raise SystemExit("no LAZ tiles in "+DIR+"/laz  (download the course point cloud first)")
    pt2utm, zscale = laz_to_utm()
    surfaces = load_playing_surfaces()
    n_golf=sum(1 for s in surfaces if s[5]=='golf'); n_bld=len(surfaces)-n_golf
    _allow = os.environ.get("ALLOW_NO_BUILDINGS", "").lower() not in ("", "0", "false", "no")
    if n_bld == 0 and not _allow:
        # A cache fetched before way[building] was added silently disables the footprint test, and
        # clubhouse roofs come back as trees (53 of them at Merion). Fail loudly instead.
        raise SystemExit("no building polygons in osm_course.json -- this cache predates the "
                         "way[building] query, so roofs would be drawn as trees.\n"
                         "  Re-run: COURSE=%s python3 fetch_osm.py   "
                         "(or set ALLOW_NO_BUILDINGS=1 if this course genuinely has none)"
                         % config.SLUG)
    if n_bld == 0:
        print("WARNING: ALLOW_NO_BUILDINGS set -- building footprint test DISABLED; "
              "roofs may be drawn as trees")
    geom = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    holes = [e for e in geom if e.get('tags',{}).get('golf')=='hole' and e.get('geometry')]
    # hole centerlines as UTM segment lists -- keep the LONGEST way per ref (OSM has
    # dup/fragment ways where a neighbouring course pokes into the bbox); matches
    # render_hole / fetch_dem so trees are collected around the correct hole.
    best={}
    for h in holes:
        ref=h['tags'].get('ref')
        if ref and ref.isdigit() and len(h['geometry'])>len(best.get(ref,{}).get('geometry',[])):
            best[ref]=h
    hlines={}
    for ref,h in best.items():
        hlines[int(ref)]=[FWD.transform(p['lon'],p['lat']) for p in h['geometry']]
    BUF=42.0                      # metres either side of the centerline
    CELL=5.0                      # thinning grid (m) -> ~one marker per clump
    GC=4.0                        # ground grid cell (m) for height-above-ground
    acc={hn:{} for hn in hlines}  # hole -> {cell:(x,y)}
    for tf in tiles:
        las=laspy.read(tf)
        cls=np.asarray(las.classification)
        # reproject XY to the course UTM zone (metres), scale Z to metres (State Plane ftUS -> m)
        x,y = pt2utm.transform(np.asarray(las.x), np.asarray(las.y))
        z = np.asarray(las.z)*zscale
        # bare-earth grid from ground returns (class 2): min z per GC-metre cell
        gnd=cls==2
        if not gnd.any():
            print(os.path.basename(tf),"no ground"); continue
        gx0,gy0=x[gnd].min(),y[gnd].min()
        nx=int((x[gnd].max()-gx0)/GC)+2; ny=int((y[gnd].max()-gy0)/GC)+2
        grd=np.full((nx,ny), np.inf)
        gi=((x[gnd]-gx0)/GC).astype(int); gj=((y[gnd]-gy0)/GC).astype(int)
        np.minimum.at(grd, (gi,gj), z[gnd])
        # Candidate canopy points: NON-ground, 2.5-35 m above local ground.
        # Excluded classes: 2 ground, 6 BUILDING, 7 noise, 9 water, 17 bridge deck, 18 high noise.
        # We must NOT restrict to class 5 (high vegetation): 10 of 11 courses have ZERO class-5
        # points (their tiles are unclassified, class 1 + 2 only), so vegetation arrives as class
        # 1/3/4 and a class-5 filter would yield no trees at all on almost every course.
        cand=(cls!=2)&(cls!=6)&(cls!=7)&(cls!=9)&(cls!=17)&(cls!=18)
        cx=x[cand]; cy=y[cand]; cz=z[cand]
        ci=np.clip(((cx-gx0)/GC).astype(int),0,nx-1); cj=np.clip(((cy-gy0)/GC).astype(int),0,ny-1)
        hgt=cz-grd[ci,cj]
        tree=np.isfinite(hgt)&(hgt>2.5)&(hgt<35)
        tx=cx[tree]; ty=cy[tree]
        for hn,line in hlines.items():
            xs=[p[0] for p in line]; ys=[p[1] for p in line]
            bx0,bx1,by0,by1=min(xs)-BUF,max(xs)+BUF,min(ys)-BUF,max(ys)+BUF
            sel=(tx>=bx0)&(tx<=bx1)&(ty>=by0)&(ty<=by1)
            if not sel.any(): continue
            xx=tx[sel]; yy=ty[sel]
            for i in range(len(xx)):
                px,py=xx[i],yy[i]
                near=min(dist_pt_seg(px,py,line[j][0],line[j][1],line[j+1][0],line[j+1][1])
                         for j in range(len(line)-1))
                if near<BUF:
                    acc[hn][(round(px/CELL),round(py/CELL))]=(px,py)
        print(os.path.basename(tf),f"processed ({int(tree.sum())} canopy pts)")
    out={}
    dropped_surface=0; dropped_building=0
    for hn,cells in acc.items():
        pts=[]
        for (ux,uy) in cells.values():
            lon,lat=INV.transform(ux,uy)
            lat=round(lat,6); lon=round(lon,6)          # round FIRST so stored==tested
            hit=on_playing_surface(lon,lat,surfaces)   # golf surface OR building footprint
            if hit:
                if hit=='building': dropped_building+=1
                else: dropped_surface+=1
                continue
            pts.append([lat,lon])
        out[str(hn)]=pts
    json.dump(out,open(f"{DIR}/trees_lidar.json","w"))
    tot=sum(len(v) for v in out.values())
    print(f"wrote trees_lidar.json: {tot} tree markers across {len(out)} holes "
          f"(dropped {dropped_surface} on green/fairway/tee/bunker, {dropped_building} on buildings; "
          f"{n_golf} golf + {n_bld} building polygons; e.g. hole1={len(out.get('1',[]))})")

if __name__=="__main__":
    main()
