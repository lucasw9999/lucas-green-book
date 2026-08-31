#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. All rights reserved.
# "Lucas Green Book" is a trademark of Lucas Wu.
# Published for reference. Not licensed for use, modification or redistribution.
# https://github.com/lucasw9999/lucas-green-book
"""
Download USGS Alameda County 2021 LiDAR (public domain) LAZ tiles covering a course.

This module exists because one county's tiles are named in a scheme nothing else decodes. That is
the ordinary condition of public geospatial data rather than an exception: the survey is free, it is
public domain, and finding the four files that cover a golf course still takes a purpose-built
decoder.

Tile naming: NAD83(2011) / California zone 3. NOTE the projected CRS EPSG:6419 is the METRE
variant -- the US-survey-foot variant is EPSG:6420 -- so the transform below returns metres and
M2FT is required to reach the feet the tile names use. The tile HEADERS are in ftUS. Getting this
backwards silently shifts every tile index by 3.28x, so do not "simplify" M2FT away. The name
..._w{E}n{N}.laz encodes the tile SW-corner easting/northing in *thousands* of
US-feet on a 3000-ft grid. We transform the course bbox -> EPSG:6419, floor to
the grid, enumerate covering tiles, find which of the 3 sub-projects holds each,
and download.

Run:  COURSE=<slug> python3 fetch_lidar_alameda.py
"""
import os, time, urllib.request, urllib.error
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

ABSENT = -1        # the server says this tile is not in this sub-project (HTTP 404/410)
UNKNOWN = -2       # we could not find out -- network error, timeout, 5xx, or a 403 denial


def absence_is_credible(n_candidates, n_absent):
    """Can `n_absent` authoritative 404s out of `n_candidates` honestly be read as the survey's edge?

    False only for a TOTAL sweep, and that one case is the point. A real survey edge clips SOME of a
    course's candidate cells, so a partial absence is ordinary and stays ordinary. But this module is
    only ever run for a course known to be inside this county's survey, so EVERY candidate cell
    answering 404 is not a fact about the survey's footprint: it means these URLs address nothing.

    The three strings the URLs are built from -- BASE, SUBS, PREFIX -- are hardcoded against a
    producer that reorganises staged delivery from time to time, and a stale path 404s uniformly.
    Reading that as "the survey does not cover this course" would leave every green unread for a
    reason that is not real, which is the same false claim this module refuses for a timeout and for a
    denial. Better to fail the fetch than to build on a gap that something other than geography
    invented.
    """
    return not (n_candidates and n_absent >= n_candidates)


def check_paths():
    """[] if the hardcoded USGS paths are self-consistent, else a list of what does not line up.

    Offline and structural -- it cannot tell you the paths are CURRENT, only that they are not
    internally contradictory, which catches the likeliest edit slip. USGS names a tile
    `<PREFIX>_<cell>.laz` where PREFIX is `USGS_LPC_` plus the project directory that ends BASE, and
    the provenance record reads project names back off disk assuming exactly that shape. Editing one
    and not the other 404s every tile, which is the sweep absence_is_credible exists to refuse.
    """
    errs = []
    project = BASE.rstrip("/").rsplit("/", 1)[-1]
    if PREFIX != "USGS_LPC_" + project:
        errs.append(f"PREFIX {PREFIX!r} != 'USGS_LPC_' + {project!r} (the project directory ending BASE)")
    if not SUBS:
        errs.append("SUBS is empty, so no sub-project would ever be probed")
    return errs


def head_size(url, tries=3):
    """Content-Length of a tile; ABSENT if the server says it is not there, UNKNOWN if we could not
    ask.

    The distinction is the whole point, and collapsing it is the classic fault here. Swallow every
    exception and a transient timeout looks exactly like "this tile is not in this sub-project": the
    caller reports the edge of coverage and the run exits successfully having downloaded half a
    course. A green with no ground returns under it must never be produced by a network wobble.

    403 is UNKNOWN, not ABSENT, and that is deliberate. The server does not answer 403 for a tile it
    does not hold, so a 403 comes from an intermediary -- a proxy, a WAF, a rate limiter -- and says
    nothing whatever about the survey's footprint. Counting it as authoritative would publish a denied
    request as a geographic fact.
    """
    last = None
    for attempt in range(tries):
        try:
            # Identify the client, as every request this project makes does. An anonymous HEAD is one
            # of the reasons an intermediary answers 403, and a 403 must never reach the caller as the
            # edge of the LiDAR survey.
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "greenbook/1.0"})
            r = urllib.request.urlopen(req, timeout=30)
            n = int(r.headers.get("Content-Length", 0))
            if n > 0:
                return n
            # A 200 that carries no Content-Length is not an absence. Returning 0 would make the
            # caller drop the copy exactly like an authoritative 404 -- the false "edge of coverage"
            # claim this function exists to stop. We could not learn the size, so say so and let the
            # run abort rather than invent a gap.
            last = "HTTP 200 with no Content-Length"
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
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
        # Once one HEAD is UNKNOWN the run is already doomed -- main() raises on any unknown -- so
        # stop asking. A course probes every candidate cell against every sub-project, and with
        # retries and backoff a network outage would otherwise cost hours before printing the same
        # "re-run" message. The verdict is unchanged; only the waiting is gone.
        if unknown:
            break
        sz = head_size(u)
        if sz == UNKNOWN:
            unknown.append(f"{t} [{sub[-9:]}]")
        elif sz > 0:
            out.append((sub, u, sz))
    return out

def main():
    # Sweep stale .part files first -- a transfer killed outright leaves one that no handler removes.
    import fetch_lidar
    fetch_lidar.sweep_partials(f"{DIR}/laz")
    tiles = covering_tiles(config.COURSE["osm_bbox"])
    print(f"{len(tiles)} candidate tiles for {config.SLUG}")
    # Say up front whether the hardcoded paths are even self-consistent. Cheap, offline, and it names
    # the suspect before 75 HEADs go out rather than after they have all 404'd.
    _path_errs = check_paths()
    if _path_errs:
        raise SystemExit("the hardcoded USGS paths in this module are inconsistent:\n  "
                         + "\n  ".join(_path_errs)
                         + "\n  Fix BASE / SUBS / PREFIX; every HEAD would 404 and no tile could be "
                           "found.")
    items = []        # every sub-project copy that exists, as a TNM-shaped record
    absent = []
    unknown = []
    for t in tiles:
        if unknown:
            break          # already doomed; see tile_copies
        copies = tile_copies(t, unknown)
        if not copies and unknown:
            # We stopped probing mid-cell because a HEAD was unresolvable, so this cell's emptiness
            # proves nothing. Saying "404, edge of coverage" here would be the same false claim in a
            # new costume: the early exit means one failing sub-project can empty `copies` where
            # previously all three had to answer 404.
            print(f"  {t}: not probed -- a HEAD was unresolvable (see below); NOT treated as absent")
            continue
        if not copies:
            # Absent as far as the server is concerned: every sub-project answered an authoritative
            # 404. A HEAD that merely FAILED landed in `unknown` instead and aborts the run below. That
            # makes this cell's emptiness real, but it does NOT by itself make it the survey's edge --
            # see absence_is_credible, and the total-sweep check after the loop.
            absent.append(t)
            print(f"  {t}: not in any sub-project (404) -- absent from these URLs, skip")
            continue
        for sub, url, sz in copies:
            items.append({"downloadURL": url, "sizeInBytes": sz})
    if unknown:
        # The case that most easily masquerades as "edge of coverage". Raised BEFORE anything is
        # downloaded: the coverage is already known to be incomplete, so there is nothing to buy by
        # fetching part of it first.
        raise SystemExit(
            f"could not determine whether {len(unknown)} tile(s) exist: {', '.join(unknown)}\n"
            f"  These are network failures, not 404s, so the survey may well cover them. Building now\n"
            f"  would leave greens with no ground returns for a reason that is not real. Re-run.")
    if not absence_is_credible(len(tiles), len(absent)):
        # A TOTAL sweep. Every HEAD was authoritative, so this is not a network story -- and it is not
        # a footprint story either, because this module is only run for a course known to be inside
        # this survey. What it means is that these URLs address nothing. Raised here, so the "edge of
        # the survey" note below can never be reached with all of a course behind it.
        raise SystemExit(
            f"all {len(tiles)} candidate tile(s) answered 404. That is NOT the edge of the survey:\n"
            f"  this module is only run for a course known to be inside the Alameda County 2021\n"
            f"  survey, so a course lying entirely outside it is not the explanation. The likely cause\n"
            f"  is that the hardcoded paths are stale -- USGS has reorganised staged delivery before.\n"
            f"  Check these three against the producer, none of which is verified anywhere:\n"
            f"    BASE   = {BASE}\n"
            f"    SUBS   = {', '.join(SUBS)}\n"
            f"    PREFIX = {PREFIX}\n"
            f"  Publishing this as a survey gap would leave every green unread for a reason that is\n"
            f"  not real -- the same false claim this module already refuses for a timeout and a 403.")
    # WHICH LOCAL FILE HOLDS WHICH COPY is plan_downloads' job, not this module's. Deciding it in
    # both places is the same rule written twice, and the two answers diverged in the way that costs
    # ground returns: a one-sided size check ("on disk and at least as big as expected") is satisfied
    # by a file LARGER than the expectation, so where one geographic cell exists in two sub-projects
    # at very different sizes, a re-run can report the small copy cached against the large one and
    # then download the large copy again under a second name. The surface builder concatenates every
    # tile in the directory with no de-duplication, so that cell's ground returns would be counted
    # twice and the reported point density for every green fed by it would be inflated.
    #
    # plan_downloads matches the cache BY SIZE across the whole directory, consuming each file as it
    # is matched, so it finds a copy whatever it is called and cannot spend one file on two
    # expectations. It also owns the per-sub-project naming and the cross-cell size-collision warning.
    todo, got = fetch_lidar.plan_downloads(items, f"{DIR}/laz")
    print(f"  {got} tile copy(ies) already on disk, {len(todo)} to download")
    failed = []
    for it, name in todo:
        url, fn, sz = it["downloadURL"], f"{DIR}/laz/{name}", it.get("sizeInBytes") or 0
        ok = False
        for a in range(4):
            try:
                # Stage as .part and rename, so an interrupted transfer cannot be mistaken for a
                # complete tile by the size check on the next run.
                #
                # download_tile rather than urlretrieve: it sets a READ timeout and refuses a non-https
                # URL. urlretrieve accepts no timeout and forwards none, so a stalled transfer blocks
                # the socket indefinitely and a retry loop like this one can never fire.
                fetch_lidar.download_tile(url, fn + ".part")
                n = os.path.getsize(fn + ".part")
                if sz and n != sz:
                    # A short read that still parses is the worst case: the tile looks fine and simply
                    # has no points over part of the course. Checked here, on this run, rather than
                    # left for the next one to notice after this one reported success.
                    raise IOError(f"got {n:,} bytes, the server says {sz:,}")
                os.replace(fn + ".part", fn)
                print(f"  downloaded {name} ({round(n/1e6)} MB)")
                got += 1; ok = True; break
            except Exception as e:
                print(f"  {name} try {a+1} failed: {e}; retry"); time.sleep(3)
        if not ok:
            failed.append(name)
            if os.path.exists(fn + ".part"):
                os.remove(fn + ".part")
    print(f"done -> {DIR}/laz  ({got} tile copies)")
    if absent:
        print(f"  NOTE {len(absent)} candidate tile(s) are not on the server (authoritative 404): "
              f"{', '.join(absent)}\n"
              f"       That is the edge of the survey. Greens there will have no ground returns and\n"
              f"       the honesty gate will leave them unread rather than invent a surface.")
    if failed:
        # Exiting 0 here would leave PARTIAL coverage, and a green with no ground returns under it is
        # exactly what must never reach a card as terrain.
        raise SystemExit(f"FAILED to download {len(failed)} tile copy(ies): {', '.join(failed)}\n"
                         f"  Coverage would be incomplete -- re-run rather than building on this.")
    if got == 0:
        raise SystemExit("no tiles downloaded")
    # Check the DATA, not just the filenames: a tile can be present, correctly named, the right size,
    # and still hold no points where a green is -- a sub-project's copy of a cell covers only the strip
    # it flew, which can be a small fraction of the cell. Filenames cannot see that; only the points
    # can. See lidar_coverage.py.
    #
    # report_or_exit, not report: a bare call would DISCARD the verdict, so a fetch whose own check
    # said "coverage NOT CHECKED" would still exit 0.
    import lidar_coverage
    lidar_coverage.report_or_exit(config.COURSE_DIR)

if __name__ == "__main__":
    main()
