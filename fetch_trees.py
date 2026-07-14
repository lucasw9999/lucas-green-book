#!/usr/bin/env python3
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

DIR = config.COURSE_DIR
R_LAT = 111320.0
def mlon(lat): return 111320.0*math.cos(math.radians(lat))
FWD = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True)   # lon/lat -> UTM10N m
INV = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True)

def laz_to_utm():
    """Transformer from the tiles' native CRS -> UTM10N metres + vertical scale to m."""
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
        src = "EPSG:26910"
    name = str(src).lower()
    zscale = 0.3048006096012192 if ("ftus" in name or "us survey foot" in name
                                    or "foot" in name or "feet" in name) else 1.0
    return Transformer.from_crs(src, "EPSG:26910", always_xy=True), zscale

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
    """Fairway / green / tee / bunker polygons (lon,lat) with bboxes. Trees never
    grow on these, so any marker inside one is a false positive (edge-tree clipped
    in, or a non-vegetation elevated return: cart, mower, person, flagstick) and is
    dropped. Correct by definition -- keeps only rough/out-of-play trees."""
    els=[]
    for fn in ("osm_course.json","osm_geom.json"):
        p=f"{DIR}/{fn}"
        if os.path.exists(p):
            j=json.load(open(p)); els+=j.get("elements",j) if isinstance(j,dict) else j
    surfaces=[]
    for e in els:
        if e.get('tags',{}).get('golf') in ('fairway','green','tee','bunker') and e.get('geometry'):
            poly=[(p['lon'],p['lat']) for p in e['geometry']]
            xs=[c[0] for c in poly]; ys=[c[1] for c in poly]
            surfaces.append((min(xs),min(ys),max(xs),max(ys),poly))
    return surfaces

def on_playing_surface(lon,lat,surfaces):
    for x0,y0,x1,y1,poly in surfaces:
        if x0<=lon<=x1 and y0<=lat<=y1 and _pip(lon,lat,poly):
            return True
    return False

def main():
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        raise SystemExit("no LAZ tiles in "+DIR+"/laz  (download the course point cloud first)")
    pt2utm, zscale = laz_to_utm()
    surfaces = load_playing_surfaces()
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
        # reproject XY to UTM10N metres, scale Z to metres (State Plane ftUS -> m)
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
        # candidate canopy points: NON-ground, 2.5-35 m above local ground
        cand=(cls!=2)&(cls!=7)&(cls!=9)      # drop ground/noise/water
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
    dropped=0
    for hn,cells in acc.items():
        pts=[]
        for (ux,uy) in cells.values():
            lon,lat=INV.transform(ux,uy)
            lat=round(lat,6); lon=round(lon,6)          # round FIRST so stored==tested
            if on_playing_surface(lon,lat,surfaces):    # no trees on green/fairway/tee/bunker
                dropped+=1; continue
            pts.append([lat,lon])
        out[str(hn)]=pts
    json.dump(out,open(f"{DIR}/trees_lidar.json","w"))
    tot=sum(len(v) for v in out.values())
    print(f"wrote trees_lidar.json: {tot} tree markers across {len(out)} holes "
          f"(dropped {dropped} on green/fairway/tee/bunker; e.g. hole1={len(out.get('1',[]))})")

if __name__=="__main__":
    main()
