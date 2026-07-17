#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Generic per-green elevation for any course, from the USGS 3DEP seamless 1 m DEM
(public domain) -- no per-course LiDAR tile picking required.

Reads COURSE_DIR/osm_geom.json, matches each green to its hole (for approach
bearing), downloads a small DEM patch per green via the 3DEP exportImage service
sampled at 0.5 m/px, and writes COURSE_DIR/dem_hd/holeNN.{npy,json} -- the same
format render_green.py consumes.

For the sharpest possible result on a specific course you can instead run the
point-cloud path (fetch_dem_hd.py) if dense QL1/QL2 LiDAR is available; this
seamless path is the robust default that works everywhere.

Run:  COURSE=<slug> python3 fetch_dem.py
"""
import urllib.request, json, math, io, time, os
import numpy as np, tifffile
import config

DIR = config.COURSE_DIR
OUT = f"{DIR}/dem_hd"; os.makedirs(OUT, exist_ok=True)
R_LAT = 111320.0
def mlon(lat): return 111320.0 * math.cos(math.radians(lat))

def centroid(g):
    la = sum(p['lat'] for p in g['geometry']) / len(g['geometry'])
    lo = sum(p['lon'] for p in g['geometry']) / len(g['geometry']); return la, lo
def bearing(a_lat, a_lon, b_lat, b_lon):
    dE = (b_lon - a_lon) * mlon((a_lat + b_lat) / 2); dN = (b_lat - a_lat) * R_LAT
    return (math.degrees(math.atan2(dE, dN)) + 360) % 360

def main():
    d = json.load(open(f"{DIR}/osm_geom.json"))
    els = d['elements']
    greens = [e for e in els if e.get('tags', {}).get('golf') == 'green' and e.get('geometry')]
    holes  = [e for e in els if e.get('tags', {}).get('golf') == 'hole'  and e.get('geometry')]
    # keep only the longest centerline per hole ref (OSM sometimes has dup/fragment ways)
    best = {}
    for h in holes:
        ref = h['tags'].get('ref')
        if ref and ref.isdigit() and len(h['geometry']) > len(best.get(ref, {}).get('geometry', [])):
            best[ref] = h
    holes = list(best.values())
    gc = [(g, *centroid(g)) for g in greens]
    done = 0
    for h in holes:
        ref = h['tags'].get('ref')
        if not (ref and ref.isdigit()):
            continue
        hn = int(ref); line = h['geometry']
        def near(pt):
            best = 1e9; bg = None
            for g, la, lo in gc:
                dm = math.hypot((pt['lon']-lo)*mlon(la), (pt['lat']-la)*R_LAT)
                if dm < best: best, bg = dm, g
            return best, bg
        da, ga = near(line[0]); db, gb = near(line[-1])
        if da <= db: green, gend, prev = ga, line[0], line[1]
        else:        green, gend, prev = gb, line[-1], line[-2]
        appr = bearing(prev['lat'], prev['lon'], gend['lat'], gend['lon'])

        geo = green['geometry']; lats = [p['lat'] for p in geo]; lons = [p['lon'] for p in geo]
        clat, clon = centroid(green)
        mrg = 12.0; dlat = mrg/R_LAT; dlon = mrg/mlon(clat)
        xmin, xmax = min(lons)-dlon, max(lons)+dlon
        ymin, ymax = min(lats)-dlat, max(lats)+dlat
        wm = (xmax-xmin)*mlon(clat); hm = (ymax-ymin)*R_LAT
        W = max(48, int(wm/0.5)); H = max(48, int(hm/0.5))
        url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
               f"?bbox={xmin},{ymin},{xmax},{ymax}&bboxSR=4326&imageSR=4326&size={W},{H}"
               "&format=tiff&pixelType=F32&interpolation=RSP_BilinearInterpolation&f=image")
        arr = None
        for attempt in range(4):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'greenbook/1.0'}), timeout=120).read()
                arr = tifffile.imread(io.BytesIO(raw)).astype('float64')
                break
            except Exception as e:
                print(f"hole {hn}: attempt {attempt+1} failed ({e}); retry"); time.sleep(1.5)
        if arr is None:
            print(f"hole {hn}: DEM fetch FAILED"); continue
        np.save(f"{OUT}/hole{hn:02d}.npy", arr)
        json.dump(dict(hole=hn, approach_bearing=appr, bbox=[xmin, ymin, xmax, ymax], W=W, H=H,
                       green_id=green['id'], green_center=[clat, clon],
                       polygon=[[p['lat'], p['lon']] for p in geo],
                       source="USGS 3DEP seamless 1 m @0.5m sampling"),
                  open(f"{OUT}/hole{hn:02d}.json", "w"))
        done += 1
        print(f"hole {hn:2d}: green {green['id']} {arr.shape} approach {appr:.0f}deg")
        time.sleep(0.2)
    print(f"\nWrote {done} greens -> {OUT}")

if __name__ == "__main__":
    main()
