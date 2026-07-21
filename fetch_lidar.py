#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Download a course's LiDAR point-cloud tiles (USGS, public domain) so the trees
(fetch_trees.py) and high-precision green surfaces (fetch_dem_hd.py) can be built.

Discovery via USGS TNM products API (robust retry — it rate-limits/outages).
Picks the newest project's tiles overlapping the course bbox and downloads the
LAZ into COURSE_DIR/laz/.

Run:  COURSE=<slug> python3 fetch_lidar.py
Then: COURSE=<slug> python3 fetch_dem_hd.py   # precision green surfaces
      COURSE=<slug> python3 fetch_trees.py    # trees from canopy returns
      COURSE=<slug> python3 generate.py
"""
import os, json, time, urllib.request
import config

DIR = config.COURSE_DIR
os.makedirs(f"{DIR}/laz", exist_ok=True)
S, W, N, E = config.COURSE["osm_bbox"]
BBOX = f"{W},{S},{E},{N}"            # TNM wants minx,miny,maxx,maxy

def tnm_items(tries=8):
    url = ("https://tnmaccess.nationalmap.gov/api/v1/products?bbox=" + BBOX +
           "&datasets=Lidar%20Point%20Cloud%20(LPC)&outputFormat=JSON&max=200")
    for a in range(tries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'greenbook/1.0'}), timeout=90).read()
            items = json.loads(data).get('items', [])
            if items:
                return items
            print(f"  TNM try {a+1}: 0 items (service busy), retrying")
        except Exception as e:
            print(f"  TNM try {a+1} failed: {type(e).__name__}, retrying")
        time.sleep(10)
    return []

def _project_of(it):
    """Stable project name for a TNM item. USGS stages LPC under
    .../Projects/<PROJECT>/... so the path segment after 'Projects' groups all
    tiles of one collection; fall back to the title if the URL is unusual."""
    parts = [p for p in (it.get('downloadURL') or '').split('/') if p]
    if 'Projects' in parts:
        i = parts.index('Projects')
        if i + 1 < len(parts):
            return parts[i + 1]
    return it.get('title', '')

def _overlaps(bb):
    """True if a TNM item's boundingBox overlaps the course bbox (S,W,N,E)."""
    if not bb:
        return False
    try:
        return bb['maxY'] > S and bb['minY'] < N and bb['maxX'] > W and bb['minX'] < E
    except (KeyError, TypeError):
        return False

def main():
    items = tnm_items()
    if not items:
        raise SystemExit("USGS TNM returned no tiles after retries (temporary outage). "
                         "Re-run later; point cloud is known to exist for this bbox.")
    # Keep only tiles whose bounding box ACTUALLY overlaps the course. TNM's bbox
    # query returns neighbouring tiles too, and a tile that merely borders the
    # query box can miss every green -- overlap is what matters. (If no item
    # carries a boundingBox, fall back to everything with a download URL.)
    withurl = [it for it in items if it.get('downloadURL')]
    overlapping = [it for it in withurl if _overlaps(it.get('boundingBox'))] or withurl
    # Group the overlapping tiles by project and take the NEWEST project (ties ->
    # the one with the most overlapping tiles). This replaces the old title
    # word-slice grouping, which for non-California projects folded the per-tile
    # ID into the "project" key and so matched only ONE tile -> most greens unfed.
    projects = {}
    for it in overlapping:
        projects.setdefault(_project_of(it), []).append(it)
    def newest(p):
        return max((i.get('publicationDate', '') for i in projects[p]), default='')
    proj = max(projects, key=lambda p: (newest(p), len(projects[p])))
    tiles = projects[proj]
    print(f"project: {proj}  ({len(tiles)} overlapping tiles, {newest(proj)})")
    for it in tiles:
        u = it.get('downloadURL')
        if not u:
            continue
        fn = f"{DIR}/laz/" + os.path.basename(u)
        if os.path.exists(fn) and os.path.getsize(fn) > 1e6:
            print("  cached", os.path.basename(u)); continue
        for a in range(4):
            try:
                urllib.request.urlretrieve(u, fn)
                print("  downloaded", os.path.basename(u), round(os.path.getsize(fn)/1e6), "MB"); break
            except Exception as e:
                print(f"  {os.path.basename(u)} try {a+1} failed: {e}"); time.sleep(3)
    print("done ->", f"{DIR}/laz")

if __name__ == "__main__":
    main()
