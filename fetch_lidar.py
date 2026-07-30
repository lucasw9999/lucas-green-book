#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
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
import os, re, json, time, urllib.request
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

# Path segments USGS uses as containers, never as a survey name.
_BUCKETS = {'legacy', 'lpc', 'laz', 'metadata', 'projects'}


def _project_of(it):
    """Stable project name for a TNM item. USGS stages LPC under
    .../Projects/<PROJECT>/... so the path segment after 'Projects' groups all tiles of one
    collection.

    There is deliberately NO fallback to the item title. The title carries the per-tile ID
    (USGS_LPC_CA_..._64992142.laz), so grouping by it makes every tile its own "project": coverage
    then collapses to one tile and most greens get no ground returns. That is exactly the bug this
    function was written to fix, so an unexpected URL layout must stop the run, not silently
    reintroduce it."""
    parts = [p for p in (it.get('downloadURL') or '').split('/') if p]
    if 'Projects' in parts:
        i = parts.index('Projects')
        # USGS nests older surveys one level deeper, under a BUCKET rather than a project:
        #   .../Projects/CA_AlamedaCounty_2021_B21/LAZ/...        (modern)
        #   .../Projects/legacy/ARRA_CA_SANFRANCOAST_2010/LAZ/... (older)
        # Taking the segment straight after "Projects" made every legacy survey one pseudo-project
        # called "legacy". Measured live on the Monarch Bay bbox: 19 tiles from ARRA_CA_SANFRANCOAST
        # _2010, CA_ALAMEDACO_2006 and others collapsed into "legacy", whose 19-tile footprint then
        # BEAT the real CA_AlamedaCounty_2021_B21 (5 tiles) on coverage -- so a rebuild would have
        # silently fetched 2006-2010 elevation for a course we hold 2021 data for, and mixed three
        # surveys flown years apart into one green surface.
        j = i + 1
        while j < len(parts) and parts[j].lower() in _BUCKETS:
            j += 1
        if j < len(parts):
            return parts[j]
    raise SystemExit(
        f"cannot determine the LiDAR project for a TNM item: {it.get('downloadURL')!r}\n"
        f"  Expected a .../Projects/<PROJECT>/... URL. Grouping by title instead would make every\n"
        f"  tile its own project, collapsing coverage to a single tile. Inspect the reply and\n"
        f"  extend _project_of rather than falling back.")

def _overlaps(bb):
    """True if a TNM item's boundingBox overlaps the course bbox (S,W,N,E)."""
    if not bb:
        return False
    try:
        return bb['maxY'] > S and bb['minY'] < N and bb['maxX'] > W and bb['minX'] < E
    except (KeyError, TypeError):
        return False

COVERAGE_GOOD = 0.95         # coverage at which a project is "good enough" to prefer recency


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


def survey_year(project):
    """The year the survey was FLOWN, from the project name, or None if the name carries none.

    publicationDate is not the survey epoch and can be a decade out: TNM lists
    ARRA_CA_SANFRANCOAST_2010 with publicationDate 2023-04-13. Ranking recency by that made
    ten-year-old elevation look like the newest data available.

    Many USGS projects date themselves with a FISCAL-YEAR QUARTER CODE rather than a full year --
    PA_17County_D24 is FY2024 quarter D, CA_FEMALevee_D23 is FY2023 -- and matching only 4-digit
    years returned 0 for those. Combined with ranking an unknown year BELOW every dated survey, that
    inverted the whole rule: for Merion, PA_17County_D24 (2024) scored 0 and lost to
    PA_STATEWIDE_S_2006_2008. The fix that was supposed to stop us printing a 2006 green as current
    would have fetched one. So decode both forms, and return None -- not 0 -- when the name says
    nothing, so an undated project is excluded from recency ordering instead of treated as ancient.
    """
    p = project or ''
    yrs = [int(y) for y in re.findall(r'(19\d\d|20\d\d)', p)]
    yrs += [2000 + int(d) for _q, d in re.findall(r'(?:^|_)([A-D])(\d{2})(?:_|$)', p)]
    return max(yrs) if yrs else None


def choose_project(projects):
    """The project whose tiles best cover the course, preferring a RECENT survey.

    Two properties matter and they conflict. Coverage: a survey that merely clips the course corner
    leaves greens with no ground returns at all. Recency: a green surveyed in 2006 may have been
    rebuilt since, and we print its slope as current. So prefer the newest survey that covers the
    course well; only drop to an older one when nothing recent covers enough, and say so out loud.
    """
    if not projects:
        raise SystemExit("no LiDAR projects to choose from for this bbox -- TNM returned nothing "
                         "usable. Re-run later; this is normally a transient outage.")
    scored = {p: _coverage(projects[p]) for p in projects}
    newest = lambda p: max((i.get('publicationDate', '') for i in projects[p]), default='')
    best_cov = max(scored.values())
    good = [p for p in projects if scored[p] >= min(best_cov, COVERAGE_GOOD) - 0.02]
    # Among adequately-covering projects the newest SURVEY wins (not the newest publication). A
    # project whose name carries no year is ranked by coverage alone rather than being treated as the
    # oldest -- "unknown" is not "ancient", and guessing it was would pick genuinely old data.
    dated = [p for p in good if survey_year(p) is not None]
    pool = dated or good
    pick = max(pool, key=lambda p: (survey_year(p) or 0, scored[p], len(projects[p])))
    return pick, scored, newest


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
    pinned = config.COURSE.get("lidar_project")
    if pinned:
        if pinned not in projects:
            raise SystemExit(f'course.json pins "lidar_project": {pinned!r}, which TNM did not '
                             f'return for this bbox. Available: {sorted(projects)}')
        proj, scored, newest = pinned, {p: _coverage(projects[p]) for p in projects}, \
            (lambda p: max((i.get("publicationDate", "") for i in projects[p]), default=""))
        print(f'project: {proj}  (PINNED by course.json)')
    else:
        proj, scored, newest = choose_project(projects)
    tiles = projects[proj]
    yr = survey_year(proj)
    if yr and yr < 2015:
        print(f"  WARNING: {proj} was surveyed around {yr}. Greens rebuilt since then would print\n"
              f"           stale slope. Check for a newer survey, or pin one with \"lidar_project\".")
    if scored[proj] < COVERAGE_GOOD:
        print(f"  WARNING: {proj} covers only {scored[proj]*100:.0f}% of the course bbox; greens\n"
              f"           outside it will have no ground returns and will not be read.")
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
