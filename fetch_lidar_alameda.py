#!/usr/bin/env python3
"""
Download USGS Alameda County 2021 LiDAR (public domain) LAZ tiles covering a
course, into COURSE_DIR/laz/. Solves the w####n#### tile-naming for the
CA_AlamedaCounty_2021_B21 project (see memory: alameda-2021-lidar-tile-index).

Tile naming: NAD83(2011) / California zone 3, US feet (EPSG:6419). The name
..._w{E}n{N}.laz encodes the tile SW-corner easting/northing in *thousands* of
US-feet on a 3000-ft grid. We transform the course bbox -> EPSG:6419, floor to
the grid, enumerate covering tiles, find which of the 3 sub-projects holds each,
and download.

Run:  COURSE=<slug> python3 fetch_lidar_alameda.py
Then: COURSE=<slug> python3 fetch_dem_hd.py   # 0.4 m green surfaces
      COURSE=<slug> python3 fetch_trees.py    # canopy trees
"""
import os, time, urllib.request
from pyproj import Transformer
import config

DIR = config.COURSE_DIR
os.makedirs(f"{DIR}/laz", exist_ok=True)
BASE = ("https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/"
        "Projects/CA_AlamedaCounty_2021_B21")
SUBS = ["CA_AlamedaCo_1_2021", "CA_AlamedaCo_2_2021", "CA_AlamedaCo_3_2021"]
PREFIX = "USGS_LPC_CA_AlamedaCounty_2021_B21"
T = Transformer.from_crs("EPSG:4326", "EPSG:6419", always_xy=True)   # lon/lat -> CA zone3 ftUS
M2FT = 1 / 0.3048006096012192

def covering_tiles(bbox, pad_ft=300):
    S, W, N, E = bbox
    es, ns = [], []
    for la in (S, N):
        for lo in (W, E):
            x, y = T.transform(lo, la)
            es.append(x * M2FT); ns.append(y * M2FT)
    e0 = int((min(es) - pad_ft) // 3000 * 3); e1 = int((max(es) + pad_ft) // 3000 * 3)
    n0 = int((min(ns) - pad_ft) // 3000 * 3); n1 = int((max(ns) + pad_ft) // 3000 * 3)
    return [f"w{e}n{n}" for e in range(e0, e1 + 1, 3) for n in range(n0, n1 + 1, 3)]

def head_ok(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30)
        return True
    except Exception:
        return False

def main():
    tiles = covering_tiles(config.COURSE["osm_bbox"])
    print(f"{len(tiles)} candidate tiles for {config.SLUG}")
    got = 0
    for t in tiles:
        fn = f"{DIR}/laz/{PREFIX}_{t}.laz"
        if os.path.exists(fn) and os.path.getsize(fn) > 1e6:
            print("  cached", t); got += 1; continue
        url = None
        for sub in SUBS:
            u = f"{BASE}/{sub}/LAZ/{PREFIX}_{t}.laz"
            if head_ok(u):
                url = u; break
        if not url:
            print(f"  {t}: no tile on server (edge of coverage) -- skip"); continue
        for a in range(4):
            try:
                urllib.request.urlretrieve(url, fn)
                print(f"  downloaded {t} ({round(os.path.getsize(fn)/1e6)} MB)"); got += 1; break
            except Exception as e:
                print(f"  {t} try {a+1} failed: {type(e).__name__}; retry"); time.sleep(3)
    print(f"done -> {DIR}/laz  ({got} tiles)")
    if got == 0:
        raise SystemExit("no tiles downloaded")

if __name__ == "__main__":
    main()
