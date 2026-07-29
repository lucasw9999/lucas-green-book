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

def _coverage(items):
    """Fraction of the course bbox covered by the union of these tiles' bounding boxes.

    Approximated on a 40x40 sample grid, which is ample: we are choosing between projects, not
    measuring area. Picking by DATE alone is not safe -- a newer project that merely clips the
    corner of the course beats an older one that covers all of it, and the greens outside the
    clip then get no ground returns at all. Observed live for one bbox:
    CA_SanJoaquin_2021_A21 (2023, 90% coverage) outranked
    CA_UpperSouthAmerican_Eldorado_2019_B19 (2021, 100%).
    """
    boxes = [it['boundingBox'] for it in items if it.get('boundingBox')]
    if not boxes:
        return 0.0
    n = 40
    hit = 0
    for i in range(n):
        y = S + (N - S) * (i + 0.5) / n
        for j in range(n):
            x = W + (E - W) * (j + 0.5) / n
            if any(b['minX'] <= x <= b['maxX'] and b['minY'] <= y <= b['maxY'] for b in boxes):
                hit += 1
    return hit / (n * n)


def main():
    items = tnm_items()
    if not items:
        raise SystemExit("USGS TNM returned no tiles after retries (temporary outage). "
                         "Re-run later; point cloud is known to exist for this bbox.")
    if len(items) >= 200:
        print("  WARNING: hit the 200-item TNM cap; some tiles may be missing from this listing")
    # Keep only tiles whose bounding box ACTUALLY overlaps the course. TNM's bbox
    # query returns neighbouring tiles too, and a tile that merely borders the
    # query box can miss every green -- overlap is what matters. (If no item
    # carries a boundingBox, fall back to everything with a download URL.)
    withurl = [it for it in items if it.get('downloadURL')]
    overlapping = [it for it in withurl if _overlaps(it.get('boundingBox'))] or withurl
    # Group by project, then choose on COVERAGE first and recency second. The old title
    # word-slice grouping folded the per-tile ID into the "project" key for non-California
    # projects and so matched only ONE tile -> most greens unfed.
    projects = {}
    for it in overlapping:
        projects.setdefault(_project_of(it), []).append(it)
    def newest(p):
        return max((i.get('publicationDate', '') for i in projects[p]), default='')
    scored = {p: _coverage(projects[p]) for p in projects}
    # Prefer full coverage; among projects that cover the course equally well (within 2%), take the
    # newest. A newer partial project is only chosen when nothing older covers more.
    best_cov = max(scored.values())
    finalists = [p for p in projects if scored[p] >= best_cov - 0.02]
    proj = max(finalists, key=lambda p: (newest(p), len(projects[p])))
    tiles = projects[proj]
    print(f"project: {proj}  ({len(tiles)} overlapping tiles, {newest(proj)}, "
          f"{scored[proj]*100:.0f}% bbox coverage)")
    for p in sorted(projects, key=lambda p: -scored[p]):
        if p != proj:
            print(f"  (not chosen: {p} — {scored[p]*100:.0f}% coverage, {newest(p)})")
    failed = []
    for it in tiles:
        u = it.get('downloadURL')
        if not u:
            continue
        fn = f"{DIR}/laz/" + os.path.basename(u)
        if os.path.exists(fn) and os.path.getsize(fn) > 1e6:
            print("  cached", os.path.basename(u)); continue
        ok = False
        for a in range(4):
            try:
                # download to .part and rename, so an interrupted transfer cannot be mistaken
                # for a complete tile by the size check above on the next run
                urllib.request.urlretrieve(u, fn + ".part")
                os.replace(fn + ".part", fn)
                print("  downloaded", os.path.basename(u), round(os.path.getsize(fn)/1e6), "MB")
                ok = True
                break
            except Exception as e:
                print(f"  {os.path.basename(u)} try {a+1} failed: {e}"); time.sleep(3)
        if not ok:
            failed.append(os.path.basename(u))
            if os.path.exists(fn + ".part"):
                os.remove(fn + ".part")
    if failed:
        # Exiting 0 here would leave PARTIAL coverage, and a green with no ground returns under it
        # is exactly what produced the fabricated-terrain cards the honesty gate now blocks.
        raise SystemExit(f"FAILED to download {len(failed)} tile(s): {', '.join(failed)}\n"
                         f"  Coverage would be incomplete -- re-run rather than building on this.")
    print("done ->", f"{DIR}/laz")

if __name__ == "__main__":
    main()
