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
import glob, os, re, json, time, urllib.parse, urllib.request
import config

DIR = config.COURSE_DIR
os.makedirs(f"{DIR}/laz", exist_ok=True)
S, W, N, E = config.COURSE["osm_bbox"]
BBOX = f"{W},{S},{E},{N}"            # TNM wants minx,miny,maxx,maxy

TNM_PAGE_MAX = 200      # products per request. The API's own cap on this endpoint -- ask for it, then PAGE.


def _tnm_page(offset, tries):
    """One page of TNM LPC products for the course bbox: (items, total, note).

    `total` is what the service says the whole query holds, or None when it did not say. `note` is any
    message or error field it carried, so a caller can report what was actually said.

    Retries on a transport error or an empty reply, which is how this endpoint expresses being busy. But
    an empty reply CARRYING a total of 0 is an answer, not a wobble, and comes straight back: "0 items
    (service busy), retrying" was the sole diagnosis this module printed for every cause of an empty
    list -- a real outage, a bbox over open water, and a renamed `datasets=` string all read the same.
    """
    url = ("https://tnmaccess.nationalmap.gov/api/v1/products?bbox=" + BBOX +
           "&datasets=Lidar%20Point%20Cloud%20(LPC)&outputFormat=JSON"
           f"&max={TNM_PAGE_MAX}&offset={offset}")
    for a in range(tries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(
                url, headers={'User-Agent': 'greenbook/1.0'}), timeout=90).read()
            reply = json.loads(data)
            items = reply.get('items') or []
            total = reply.get('total')
            note = reply.get('message') or reply.get('errors') or reply.get('error')
            if isinstance(total, str) and total.isdigit():
                total = int(total)          # the endpoint has been seen to quote it
            if items:
                return items, (total if isinstance(total, int) else None), note
            if total == 0:
                print(f"  TNM answered: it lists 0 LPC products for this bbox"
                      + (f" -- {note}" if note else ""))
                return [], 0, note
            print(f"  TNM try {a+1}: 0 items and no total (service busy), retrying")
        except Exception as e:
            print(f"  TNM try {a+1} failed: {type(e).__name__}, retrying")
        time.sleep(10)
    return [], None, None


def tnm_items(tries=8):
    """Every LPC product TNM lists for this course bbox, following the API's paging.

    THIS USED TO BE ONE REQUEST FOR `&max=200`, read as the whole world. A course needing more than 200
    products would have got a silently TRUNCATED tile list: the missing tiles are not an error anywhere
    downstream, they are simply absent, so lidar_coverage measures a smaller footprint, choose_project
    ranks surveys on it, and greens fall back to the 1 m DEM or to nothing for a reason that is not real.
    There was a `print("WARNING: hit the 200-item TNM cap")`, which is a line in a long log rather than a
    refusal, and everything else in this pipeline refuses.

    Latent on this corpus -- 4 to 14 tiles are kept per course, nowhere near the cap -- so the fix is for
    the course that is not in it yet.

    TWO REFUSALS, because paging can fail in two ways that both end in a short list:
      * a page exactly at the cap with NO total. That is the one state where a complete list and a
        truncated one are indistinguishable, which is precisely what the old code could not tell apart,
        so it must stop rather than guess.
      * a service that ignores `offset` and re-serves page one. Following that forever, or accepting the
        first page as everything, are both wrong; deduplicating by sourceId makes the lack of progress
        visible and it stops there.

    A list that ends SHORT of a total the service stated is the truncation this function exists to
    prevent, so that stops too. Getting nothing at all is the old outage path and still returns [], which
    main() turns into its own "re-run later" stop.
    """
    got, ids, offset, total = [], set(), 0, None
    while True:
        items, page_total, note = _tnm_page(offset, tries)
        if page_total is not None:
            total = page_total
        if not items:
            break
        new = 0
        for it in items:
            key = it.get('sourceId') or it.get('downloadURL') or it.get('title')
            if key in ids:
                continue
            ids.add(key)
            got.append(it)
            new += 1
        if new == 0:
            raise SystemExit(
                f"USGS TNM re-served the same {len(items)} products at offset={offset}, so it is not\n"
                f"  honouring `offset` and the listing cannot be paged. Refusing to treat the first\n"
                f"  {len(got)} products as the whole survey: a short tile list is invisible downstream --\n"
                f"  the tiles are simply absent, coverage measures smaller, and greens fall back to the\n"
                f"  1 m DEM for a reason that is not real. Check the products API before re-running."
                + (f"\n  The service said: {note}" if note else ""))
        offset += len(items)
        if total is None:
            if len(items) < TNM_PAGE_MAX:
                break                       # a short page ends the list whatever the service does not say
            raise SystemExit(
                f"USGS TNM returned exactly {TNM_PAGE_MAX} products -- this request's cap -- and no\n"
                f"  `total`, so a complete listing and a truncated one look identical. Refusing to\n"
                f"  guess: if it is truncated, the missing tiles are not an error anywhere downstream,\n"
                f"  they are just absent, and greens lose their 0.4 m surface for a reason that is not\n"
                f"  real. Check what the products API now returns and extend the paging here."
                + (f"\n  The service said: {note}" if note else ""))
        if len(got) >= total:
            break
    if total and got and len(got) < total:
        raise SystemExit(
            f"USGS TNM says it holds {total} LPC products for this bbox but only {len(got)} could be\n"
            f"  listed. Refusing to build on a partial tile list -- see this function's docstring for\n"
            f"  why a short list is invisible downstream. Re-run when the service is healthy.")
    return got

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


def choose_project(projects, cents=None):
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
    # cents may be supplied so the caller reads osm_geom.json once; None means read it here. Passing
    # it also lets the tests hand in synthetic greens instead of monkeypatching a module attribute.
    if cents is None:
        cents = _green_centroids()
    gcov = {p: _green_coverage(projects[p], cents) for p in projects}
    if cents and all(v is not None for v in gcov.values()):
        rank, floor = gcov, GREEN_COVERAGE_GOOD
    else:
        rank, floor = scored, COVERAGE_GOOD
        # Name the ACTUAL reason. This used to say "no green geometry yet" unconditionally, which is
        # wrong when the greens are known and it is a project's tiles that carry no boundingBox --
        # blaming the wrong input sends you looking in the wrong place.
        why = ("no green geometry yet" if not cents
               else "some project's tiles carry no boundingBox")
        print(f"  ({why} -- ranking projects on bbox coverage instead of greens)")
    best_cov = max(rank.values())
    # A survey missing some greens is recoverable and disclosed: those greens fall back to the 1 m
    # seamless DEM and the card prints "1 m data". A survey that is a decade stale is not -- it
    # prints slope for a green that may since have been rebuilt. So the bar for preferring the newer
    # survey is a substantial majority of greens, not near-complete coverage.
    # The 2% slack is deliberate and predates the green-coverage change (d2b0d10: "recency only
    # among projects within 2% of the best"). Dropping it made the pool collapse to the single
    # best-covering project whenever NOTHING reaches the floor, so recency could no longer break a
    # near-tie -- replaying both rules on synthetic shapes, greens 0.71 (2011) vs 0.70 (2021) picked
    # the 2011 survey, inverting this function's own stated principle that a small gap is preferable
    # to a decade of staleness. Latent today (the worst real green coverage is Monarch Bay at 0.90,
    # above the floor) but restored rather than left as an accident.
    good = [p for p in projects if rank[p] >= min(best_cov, floor) - 0.02]
    # Among adequately-covering projects the newest SURVEY wins (not the newest publication). A
    # project whose name carries no year is ranked by coverage alone rather than being treated as the
    # oldest -- "unknown" is not "ancient", and guessing it was would pick genuinely old data.
    dated = [p for p in good if survey_year(p) is not None]
    pool = dated or good
    # Tie-break on the metric we actually RANKED by, not on bbox coverage. With two surveys from the
    # same year both above the floor, using scored[] here picked the one that feeds FEWER greens:
    # measured, greens 1.00 / bbox 0.62 lost to greens 0.90 / bbox 0.95. That is the same
    # bbox-over-greens mistake the ranking itself was changed to stop making.
    pick = max(pool, key=lambda p: (survey_year(p) or 0, rank[p], scored[p], len(projects[p])))
    return pick, scored, newest


def sweep_partials(laz_dir):
    """Remove stale .part files. Shared by both fetchers -- it was written twice, byte-identical.

    A transfer killed outright (SIGKILL, a closed laptop, power) leaves one behind that no exception
    handler ever runs to remove, and it then sits in laz/ looking like a tile forever. It is never a
    complete tile: both callers only rename a .part into place after the transfer returns, and this
    one additionally checks its size against TNM first.
    """
    for stale in sorted(glob.glob(os.path.join(laz_dir, "*.part"))):
        print(f"  removing stale partial download {os.path.basename(stale)} "
              f"({os.path.getsize(stale)/1e6:.0f} MB)")
        os.remove(stale)


def copy_suffix(sub, i, stem, ext, used):
    """Filename for an extra sub-project copy of one cell: `<stem>__Co<n><ext>`.

    The suffix MUST end in digits -- tools/gen_provenance.py reads the LiDAR project name off these
    filenames for the legal record and strips `__Co<digits>` -- and it was encoded twice, with two
    different token regexes, one of which had no collision handling. Shared so a third spelling
    cannot appear.
    """
    m = re.search(r"Co_?(\d+)", sub) or re.search(r"(\d+)", sub)
    token = m.group(1) if m else str(50 + i)
    fn = f"{stem}__Co{token}{ext}"
    while fn in used:                # two sub-projects reducing to the same token
        token += "0"
        fn = f"{stem}__Co{token}{ext}"
    return fn


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

    # Deduplicate by URL first. Two entries for the SAME url are the same file, but the grouping
    # below would see two copies of one cell and give the second a __CoN name -- downloading the
    # identical tile twice and doubling its points, which inflates the pts/m2 the legal provenance
    # table publishes. Live TNM returns no duplicates today (checked: 10/40/9 urls, 0 repeats across
    # three courses), but it is a third-party API that has already surprised us with a 200-item cap,
    # fiscal-year project codes and surveys nested under buckets.
    seen_url, deduped = set(), []
    for it in tiles:
        u = it["downloadURL"]
        if u in seen_url:
            continue
        seen_url.add(u)
        deduped.append(it)
    if len(deduped) != len(tiles):
        print(f"  ({len(tiles) - len(deduped)} duplicate url(s) in the TNM listing, ignored)")
    by_base = {}
    for it in deduped:
        by_base.setdefault(os.path.basename(it["downloadURL"]), []).append(it)

    todo, cached, used = [], 0, set()
    for base in sorted(by_base):
        group = sorted(by_base[base], key=lambda t: t["downloadURL"])
        stem, ext = os.path.splitext(base)
        for i, it in enumerate(group):
            if i == 0:
                # the first copy keeps the plain name: every existing cache on disk uses it
                fn = base
            else:
                fn = copy_suffix(_sub_project(it["downloadURL"]), i, stem, ext, used)
            used.add(fn)
            want = it.get("sizeInBytes") or 0
            if want and have.get(want):
                got = have[want].pop(0)
                # A size match across DIFFERENT cells would mean we skip a tile we actually need. It
                # does not happen in practice -- every size within a course's laz/ is distinct, the
                # only duplicates being the same tile shared by two neighbouring courses -- but the
                # failure would be missing coverage, so say it out loud rather than assume.
                cell = lambda n: re.sub(r"__Co\d+$", "", os.path.splitext(n)[0])
                if cell(got) != cell(fn):
                    print(f"  WARNING cached {got} matches {fn} by size ({want:,} bytes) but is a\n"
                          f"          different tile. Treating it as {fn} would hide a real gap; "
                          f"downloading.")
                    have[want].insert(0, got)
                    todo.append((it, fn))
                    continue
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
    # Read the green centroids ONCE here: choose_project ranks on them and the NOTE below reports
    # against them, and each used to re-read osm_geom.json for itself.
    cents_now = _green_centroids()
    pinned = config.COURSE.get("lidar_project")
    if pinned:
        if pinned not in projects:
            raise SystemExit(f'course.json pins "lidar_project": {pinned!r}, which TNM did not '
                             f'return for this bbox. Available: {sorted(projects)}')
        proj, scored, newest = pinned, {p: _coverage(projects[p]) for p in projects}, \
            (lambda p: max((i.get("publicationDate", "") for i in projects[p]), default=""))
        print(f'project: {proj}  (PINNED by course.json)')
    else:
        proj, scored, newest = choose_project(projects, cents_now)
    tiles = projects[proj]
    yr = survey_year(proj)
    if yr and yr < 2015:
        print(f"  WARNING: {proj} was surveyed around {yr}. Greens rebuilt since then would print\n"
              f"           stale slope. Check for a newer survey, or pin one with \"lidar_project\".")
    ngreens = len(cents_now)
    gc = _green_coverage(tiles, cents_now)
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
    # Sweep stale .part files first. A transfer killed outright (SIGKILL, laptop asleep, power) leaves
    # one behind that no exception handler ever runs to remove, and it then sits in laz/ looking like
    # a tile forever. It is never valid data: the code below only renames a .part into place after
    # checking its size against TNM.
    sweep_partials(f"{DIR}/laz")
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
    # Check the DATA, not just the filenames: a tile can be present and correctly named and still
    # hold no points where a green is. See lidar_coverage.py for the two greens this cost us.
    import lidar_coverage
    lidar_coverage.report(config.COURSE_DIR)

if __name__ == "__main__":
    main()
