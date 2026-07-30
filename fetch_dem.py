#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
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

NAN_FRAC_MAX = 0.02          # matches fetch_dem_hd.py's gate
MIN_RELIEF_M = 0.05          # 5 cm across a whole green patch: not a green, a zero-fill


def _green_interior_stats(arr, bbox, W, H, polygon):
    """(nan fraction, cells tested, relief in m) over the GREEN INTERIOR only.

    Everything here must be restricted to the interior. The patch carries a 12 m margin, so a
    statistic taken over the whole raster describes mostly surround: a green sitting on the edge of
    3DEP coverage can be entirely zero-filled while the margin outside it holds real elevation, and
    a whole-patch relief test then reports a healthy range and lets the fabricated green through --
    the exact case the test exists to catch."""
    xmin, ymin, xmax, ymax = bbox
    lats = [p[0] for p in polygon]; lons = [p[1] for p in polygon]
    px = [((lo - xmin) / (xmax - xmin) * W, (ymax - la) / (ymax - ymin) * H)
          for la, lo in zip(lats, lons)]
    n_in = 0; n_nan = 0
    lo, hi = float("inf"), float("-inf")
    for r in range(H):
        yv = r + 0.5
        xs = []
        n = len(px); j = n - 1
        for i in range(n):
            xi, yi = px[i]; xj, yj = px[j]
            if (yi > yv) != (yj > yv):
                xs.append((xj - xi) * (yv - yi) / (yj - yi + 1e-12) + xi)
            j = i
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[k] - 0.5))); b = min(W - 1, int(math.floor(xs[k + 1] - 0.5)))
            if b >= a:
                seg = arr[r, a:b + 1]
                n_in += seg.size
                n_nan += int(np.isnan(seg).sum())
                fin = seg[np.isfinite(seg)]
                if fin.size:
                    lo = min(lo, float(fin.min())); hi = max(hi, float(fin.max()))
    relief = (hi - lo) if hi >= lo else 0.0
    return (1.0 if n_in == 0 else n_nan / n_in), n_in, relief


def main():
    # ONLY=14,10 restricts the run to specific holes, so a coarse 1 m fallback can be applied to
    # one green WITHOUT clobbering the sharp 0.4 m point-cloud surfaces of its neighbours.
    only = {int(v) for v in os.environ.get("ONLY", "").replace(" ", "").split(",") if v.isdigit()}
    if only:
        print("ONLY holes:", sorted(only))
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
        if only and int(ref) not in only:
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
               "&format=tiff&pixelType=F32&interpolation=RSP_BilinearInterpolation"
               "&noData=-9999&noDataInterpretation=esriNoDataMatchAny&f=image")
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
        # Honesty gate -- the SAME contract fetch_dem_hd.py writes. This producer used to write no
        # gate keys at all, so render_green's meta.get("insufficient") was None (falsy) and nothing
        # could stop an unusable surface from being printed. This is the path a BRAND-NEW course
        # takes, which made it the least gated and most used producer.
        arr = np.where(np.isfinite(arr) & (np.abs(arr) < 1e30), arr, np.nan)   # NoData sentinels
        arr = np.where(arr <= -9998.0, np.nan, arr)                            # requested noData
        nan_frac, n_in, relief = _green_interior_stats(
            arr, [xmin, ymin, xmax, ymax], W, H, [[p['lat'], p['lon']] for p in geo])
        # Out of coverage, 3DEP's exportImage returns a CONSTANT raster (measured at St Andrews:
        # min 0.0, max 0.0, one unique value) rather than any NoData marker -- so a nan_frac test
        # alone reported insufficient=False for a green with no measurement at all, and the book
        # printed 18 cards of "feeds back (subtle) - 0.0%". A real green is never perfectly flat.
        flat = bool(n_in and nan_frac < 1.0 and relief < MIN_RELIEF_M)
        insufficient = bool(n_in == 0 or nan_frac > NAN_FRAC_MAX or flat)
        if flat:
            print(f"hole {hn}: CONSTANT surface across the green ({relief*100:.1f} cm of relief) -- "
                  f"outside 3DEP coverage, not a flat green; no slope will be printed")
        np.save(f"{OUT}/hole{hn:02d}.npy", arr)
        json.dump(dict(hole=hn, approach_bearing=appr, bbox=[xmin, ymin, xmax, ymax], W=W, H=H,
                       green_id=green['id'], green_center=[clat, clon],
                       polygon=[[p['lat'], p['lon']] for p in geo],
                       source="USGS 3DEP seamless 1 m @0.5m sampling",
                       nan_frac=nan_frac, insufficient=insufficient,
                       # A seamless raster has no point cloud, so there is no measured point
                       # density. Report None rather than inventing a plausible number.
                       density=None),
                  open(f"{OUT}/hole{hn:02d}.json", "w"))
        if insufficient:
            print(f"hole {hn}: INSUFFICIENT -- {nan_frac*100:.0f}% of the green has no elevation; "
                  f"no slope will be printed")
        done += 1
        print(f"hole {hn:2d}: green {green['id']} {arr.shape} approach {appr:.0f}deg")
        time.sleep(0.2)
    print(f"\nWrote {done} greens -> {OUT}")

if __name__ == "__main__":
    main()
