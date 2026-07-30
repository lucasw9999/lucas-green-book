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
import os, re, json, time, urllib.parse, urllib.request
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

COVERAGE_GOOD = 0.95         # bbox coverage at which a project is "good enough" (fallback metric)
GREEN_COVERAGE_GOOD = 0.80   # fraction of GREENS a survey must reach to be preferred on recency


def _green_centroids():
    """Green centroids from osm_geom.json, or [] if OSM has not been fetched yet.

    fetch_osm.py runs before this script, so the file is normally there; [] simply means fall back
    to bbox coverage."""
    try:
        els = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    except Exception:
        return []
    out = []
    for e in els:
        g = e.get("geometry") or []
        if g and (e.get("tags") or {}).get("golf") == "green":
            out.append((sum(p["lon"] for p in g) / len(g), sum(p["lat"] for p in g) / len(g)))
    return out


def _green_coverage(items, cents):
    """Fraction of greens whose centroid falls inside the union of these tiles' footprints.

    This, not bbox coverage, is what the choice is really about: the LiDAR exists to build green
    surfaces. Measuring the rectangular bbox instead punished exactly the surveys we want. Monarch
    Bay sits on San Francisco Bay, so about a quarter of its bbox is open water that no land survey
    covers -- CA_AlamedaCounty_2021_B21 scored 74.9% of the bbox and was excluded outright, while
    ARRA_CA_SANFRANCOAST_2010 scored 100% and won. A rebuild would have fetched 2010 elevation for
    a course whose book is built on the 2021 survey. Over the greens the same two projects score
    18/20 and 20/20."""
    boxes = [it["boundingBox"] for it in items if it.get("boundingBox")]
    if not boxes or not cents:
        return None
    inside = sum(1 for x, y in cents
                 if any(b["minX"] <= x <= b["maxX"] and b["minY"] <= y <= b["maxY"] for b in boxes))
    return inside / len(cents)


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
    # Judge coverage over the GREENS when we know where they are, and only fall back to the bbox
    # when OSM has not been fetched yet. See _green_coverage: a bayside course loses a quarter of its
    # bbox to open water, which no land survey covers, so bbox coverage vetoed the recent survey.
    cents = _green_centroids()
    gcov = {p: _green_coverage(projects[p], cents) for p in projects}
    if cents and all(v is not None for v in gcov.values()):
        rank, floor = gcov, GREEN_COVERAGE_GOOD
    else:
        rank, floor = scored, COVERAGE_GOOD
        print("  (no green geometry yet -- ranking projects on bbox coverage)")
    best_cov = max(rank.values())
    # A survey missing some greens is recoverable and disclosed: those greens fall back to the 1 m
    # seamless DEM and the card prints "1 m data". A survey that is a decade stale is not -- it
    # prints slope for a green that may since have been rebuilt. So the bar for preferring the newer
    # survey is a substantial majority of greens, not near-complete coverage.
    good = [p for p in projects if rank[p] >= min(best_cov, floor)]
    # Among adequately-covering projects the newest SURVEY wins (not the newest publication). A
    # project whose name carries no year is ranked by coverage alone rather than being treated as the
    # oldest -- "unknown" is not "ancient", and guessing it was would pick genuinely old data.
    dated = [p for p in good if survey_year(p) is not None]
    pool = dated or good
    pick = max(pool, key=lambda p: (survey_year(p) or 0, scored[p], len(projects[p])))
    return pick, scored, newest


def _sub_project(u):
    """The sub-project directory of a TNM LAZ url: .../Projects/<project>/<SUB>/LAZ/<tile>.laz"""
    parts = [x for x in urllib.parse.urlparse(u).path.split("/") if x]
    for i, x in enumerate(parts):
        if x.upper() == "LAZ" and i:
            return parts[i - 1]
    return parts[-2] if len(parts) > 1 else ""


def plan_downloads(tiles, laz_dir):
    """[(item, filename)] still to fetch, plus the number already on disk.

    Two things this has to get right, both of which cost real ground returns when wrong.

    DISTINCT NAMES FOR DISTINCT COPIES. One geographic cell can appear in several sub-projects of the
    same USGS project, flown separately, each holding only the points collected in its own footprint.
    Their download urls differ *only* in the sub-project directory, so naming a file by url basename
    gave both copies the same local name: the first was downloaded, and the second matched
    `os.path.exists(fn)` and was reported "cached" -- a distinct file silently discarded. Measured
    live at Callippe: 8 of 20 cells have two copies, and the two copies of w6168n2055 have different
    bounding boxes -- CA_AlamedaCo_3_2021 reaches west to -121.85963, CA_AlamedaCo_1_2021 east to
    -121.84912 -- so they are COMPLEMENTARY strips, not duplicates. Extra copies now take a
    `__Co<n>` suffix from the sub-project name; tools/gen_provenance.py strips it when it reads
    project names off disk.

    MATCH THE CACHE BY SIZE, NOT BY NAME. Existing courses were fetched under an older naming scheme,
    so a cell's copies can be on disk under names this function would not choose. Treating "no file
    of that name" as "not downloaded" would fetch a copy that is already present under another name
    and store it TWICE, and duplicate points inflate the pts/m2 that the legal provenance table
    publishes. TNM reports sizeInBytes per copy and the copies differ by millions of bytes, so an
    exact size match identifies a copy whatever it is called. Files are consumed as they are matched,
    so two copies that happen to be byte-identical still require two files on disk.
    """
    have = {}
    for f in sorted(os.listdir(laz_dir)) if os.path.isdir(laz_dir) else []:
        if f.lower().endswith(".laz"):
            have.setdefault(os.path.getsize(os.path.join(laz_dir, f)), []).append(f)

    by_base = {}
    for it in tiles:
        by_base.setdefault(os.path.basename(it["downloadURL"]), []).append(it)

    todo, cached, used = [], 0, set()
    for base in sorted(by_base):
        group = sorted(by_base[base], key=lambda t: t["downloadURL"])
        stem, ext = os.path.splitext(base)
        for i, it in enumerate(group):
            if len(group) == 1 or i == 0:
                fn = base                      # keep the plain name: every existing cache uses it
            else:
                sub = _sub_project(it["downloadURL"])
                m = re.search(r"(\d+)", sub)
                token = m.group(1) if m else str(50 + i)
                fn = f"{stem}__Co{token}{ext}"
                while fn in used:              # two sub-projects reducing to the same token
                    token += "0"
                    fn = f"{stem}__Co{token}{ext}"
            used.add(fn)
            want = it.get("sizeInBytes") or 0
            if want and have.get(want):
                got = have[want].pop(0)
                print(f"  cached {got}" + (f"  (holds {fn})" if got != fn else ""))
                cached += 1
                continue
            if not want:
                # No size from TNM: fall back to the old name-and-nonempty test, and say so, because
                # this is the one path that still cannot tell a truncated file from a complete one.
                pth = os.path.join(laz_dir, fn)
                if os.path.exists(pth) and os.path.getsize(pth) > 1e6:
                    print(f"  cached {fn}  (TNM reported no size; accepted on name alone)")
                    cached += 1
                    continue
            todo.append((it, fn))
    return todo, cached


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
    ngreens = len(_green_centroids())
    gc = _green_coverage(tiles, _green_centroids())
    if gc is not None and gc < 1.0:
        print(f"  NOTE {proj} reaches {gc*100:.0f}% of the {ngreens} greens "
              f"({round(gc*ngreens)}/{ngreens}); the rest fall back to the 1 m seamless DEM and\n"
              f"       their cards are labelled '1 m data'.")
    elif gc is None and scored[proj] < COVERAGE_GOOD:
        print(f"  WARNING: {proj} covers only {scored[proj]*100:.0f}% of the course bbox; greens\n"
              f"           outside it will have no ground returns and will not be read.")
    print(f"project: {proj}  ({len(tiles)} overlapping tiles, {newest(proj)}, "
          f"{scored[proj]*100:.0f}% bbox coverage)")
    for p in sorted(projects, key=lambda p: -scored[p]):
        if p != proj:
            print(f"  (not chosen: {p} — {scored[p]*100:.0f}% coverage, {newest(p)})")
    failed = []
    todo, ncached = plan_downloads([t for t in tiles if t.get('downloadURL')], f"{DIR}/laz")
    print(f"  {ncached} tile copy(ies) already on disk, {len(todo)} to download")
    for it, name in todo:
        u, fn = it['downloadURL'], f"{DIR}/laz/{name}"
        want = it.get('sizeInBytes') or 0
        ok = False
        for a in range(4):
            try:
                # download to .part and rename, so an interrupted transfer cannot be mistaken
                # for a complete tile by the size check above on the next run
                urllib.request.urlretrieve(u, fn + ".part")
                got = os.path.getsize(fn + ".part")
                if want and got != want:
                    # A short read that still parses is the worst case: the tile looks fine and
                    # simply has no points over part of the course.
                    raise IOError(f"got {got:,} bytes, TNM says {want:,}")
                os.replace(fn + ".part", fn)
                print(f"  downloaded {name} {round(got/1e6)} MB")
                ok = True
                break
            except Exception as e:
                print(f"  {name} try {a+1} failed: {e}"); time.sleep(3)
        if not ok:
            failed.append(name)
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
