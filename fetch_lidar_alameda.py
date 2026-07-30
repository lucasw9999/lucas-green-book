#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Download USGS Alameda County 2021 LiDAR (public domain) LAZ tiles covering a
course, into COURSE_DIR/laz/. Solves the w####n#### tile-naming for the
CA_AlamedaCounty_2021_B21 project (see memory: alameda-2021-lidar-tile-index).

Tile naming: NAD83(2011) / California zone 3. NOTE the projected CRS EPSG:6419 is the METRE
variant -- the US-survey-foot variant is EPSG:6420 -- so the transform below returns metres and
M2FT is required to reach the feet the tile names use. The tile HEADERS are in ftUS. Getting this
backwards silently shifts every tile index by 3.28x, so do not "simplify" M2FT away. The name
..._w{E}n{N}.laz encodes the tile SW-corner easting/northing in *thousands* of
US-feet on a 3000-ft grid. We transform the course bbox -> EPSG:6419, floor to
the grid, enumerate covering tiles, find which of the 3 sub-projects holds each,
and download.

Run:  COURSE=<slug> python3 fetch_lidar_alameda.py
Then: COURSE=<slug> python3 fetch_dem_hd.py   # 0.4 m green surfaces
      COURSE=<slug> python3 fetch_trees.py    # canopy trees
"""
import os, re, time, urllib.request, urllib.error
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

ABSENT = -1        # the server says this tile is not in this sub-project (HTTP 404/403)
UNKNOWN = -2       # we could not find out -- network error, timeout, 5xx


def head_size(url, tries=3):
    """Content-Length of a tile; ABSENT if the server says it is not there, UNKNOWN if we could not
    ask.

    The distinction is the whole point. This used to swallow every exception and return -1, so a
    transient timeout looked exactly like "this tile is not in this sub-project" -- the caller then
    reported "edge of coverage, skip" and main() exited 0 having downloaded half a course. A green
    with no ground returns under it is what the honesty gate now has to catch; better to fail the
    fetch than to build on a gap that a network wobble invented.
    """
    last = None
    for attempt in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30)
            return int(r.headers.get("Content-Length", 0))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                return ABSENT          # an authoritative "no such tile"
            last = f"HTTP {e.code}"
        except Exception as e:
            last = type(e).__name__
        if attempt < tries - 1:
            time.sleep(4)
    print(f"    HEAD failed for {os.path.basename(url)} after {tries} tries ({last})")
    return UNKNOWN

def tile_copies(t, unknown):
    """All sub-project copies of a geographic tile. The 3 Alameda sub-projects were
    flown separately, so a tile straddling a project boundary appears in MORE THAN
    ONE sub-project, each holding only the points collected in its own footprint —
    the copies are COMPLEMENTARY, not duplicates. Download them all (distinct names)
    and let the downstream glob+merge combine coverage. Taking just the biggest copy
    silently leaves the other strip's greens with almost no ground points."""
    out = []
    for sub in SUBS:
        u = f"{BASE}/{sub}/LAZ/{PREFIX}_{t}.laz"
        sz = head_size(u)
        if sz == UNKNOWN:
            unknown.append(f"{t} [{sub[-9:]}]")
        elif sz > 0:
            out.append((sub, u, sz))
    return out

def main():
    tiles = covering_tiles(config.COURSE["osm_bbox"])
    print(f"{len(tiles)} candidate tiles for {config.SLUG}")
    got = 0
    failed = []
    absent = []
    unknown = []
    for t in tiles:
        copies = tile_copies(t, unknown)
        if not copies:
            # Genuinely absent: every sub-project answered an authoritative 404. A HEAD that
            # merely FAILED landed in `unknown` instead and aborts the run below, so reaching here
            # really does mean the edge of the survey.
            absent.append(t)
            print(f"  {t}: not in any sub-project (404) -- edge of coverage, skip")
            continue
        for i, (sub, url, sz) in enumerate(copies):
            # First copy keeps the plain name; extra sub-project copies get a `__Co<n>` suffix taken
            # from the sub-project number. The suffix MUST end in digits: tools/gen_provenance.py
            # reads the LiDAR project name off these filenames for the legal record and strips
            # `__Co\d+$`. The previous suffix was the sub-project's last 9 characters
            # (`__Co_3_2021`), which that strip does not match, so the generator published
            # "CA_AlamedaCounty_2021_B21_w6162n2049__Co_3" as the project a book was built from.
            m = re.search(r"Co_?(\d+)", sub)
            tok = m.group(1) if m else str(50 + i)
            fn = f"{DIR}/laz/{PREFIX}_{t}.laz" if i == 0 else f"{DIR}/laz/{PREFIX}_{t}__Co{tok}.laz"
            if os.path.exists(fn) and os.path.getsize(fn) >= sz - 1024:
                print(f"  cached {t} [{sub[-9:]}]"); got += 1; continue
            ok = False
            for a in range(4):
                try:
                    # stage as .part and rename, so an interrupted transfer cannot be mistaken for a
                    # complete tile by the size check above on the next run. fetch_lidar.py was fixed
                    # this way; this module still wrote straight to the final name.
                    urllib.request.urlretrieve(url, fn + ".part")
                    os.replace(fn + ".part", fn)
                    print(f"  downloaded {t} [{sub[-9:]}] ({round(os.path.getsize(fn)/1e6)} MB)")
                    got += 1; ok = True; break
                except Exception as e:
                    print(f"  {t} [{sub[-9:]}] try {a+1} failed: {type(e).__name__}; retry"); time.sleep(3)
            if not ok:
                failed.append(f"{t} [{sub[-9:]}]")
                if os.path.exists(fn + ".part"):
                    os.remove(fn + ".part")
    print(f"done -> {DIR}/laz  ({got} tile copies)")
    if absent:
        print(f"  NOTE {len(absent)} candidate tile(s) are not on the server (authoritative 404): "
              f"{', '.join(absent)}\n"
              f"       That is the edge of the survey. Greens there will have no ground returns and\n"
              f"       the honesty gate will leave them unread rather than invent a surface.")
    if unknown:
        # This is the case that used to masquerade as "edge of coverage".
        raise SystemExit(
            f"could not determine whether {len(unknown)} tile(s) exist: {', '.join(unknown)}\n"
            f"  These are network failures, not 404s, so the survey may well cover them. Building now\n"
            f"  would leave greens with no ground returns for a reason that is not real. Re-run.")
    if failed:
        # Exiting 0 here would leave PARTIAL coverage. fetch_lidar.py raises for exactly this reason:
        # a green with no ground returns under it is what produced the fabricated-terrain cards the
        # honesty gate now has to catch.
        raise SystemExit(f"FAILED to download {len(failed)} tile copy(ies): {', '.join(failed)}\n"
                         f"  Coverage would be incomplete -- re-run rather than building on this.")
    if got == 0:
        raise SystemExit("no tiles downloaded")

if __name__ == "__main__":
    main()
