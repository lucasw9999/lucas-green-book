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
    course's candidate cells -- most courses here have none clipped, Castlewood Hill has a cell whose
    copy covers a 470-ft strip -- so a partial absence is ordinary and stays ordinary. But this module
    is only ever run for a course known to be in Alameda County, so EVERY candidate cell 404ing is not
    a fact about the survey's footprint: it means these URLs address nothing.

    The three strings they are built from -- BASE, SUBS, PREFIX -- have never been verified against the
    producer, and a USGS reorganisation is not hypothetical: fetch_lidar._BUCKETS exists only because
    surveys moved under a `legacy/` bucket. Measured on the pre-fix module with every HEAD answered 404,
    a 9-cell course printed "edge of coverage, skip" nine times and then "That is the edge of the
    survey" about 100% of itself, before exiting with the unrelated "no tiles downloaded".

    This is the same false claim 08cb08d removed for a timeout and a later fix removed for a 403,
    reached through a third status code. head_size's own docstring is the argument: "better to fail the
    fetch than to build on a gap that a network wobble invented" is exactly as true of a gap a stale
    URL invented.
    """
    return not (n_candidates and n_absent >= n_candidates)


def check_paths():
    """[] if the hardcoded USGS paths are self-consistent, else a list of what does not line up.

    Offline and structural -- it cannot tell you the paths are CURRENT, only that they are not
    internally contradictory, which catches the likeliest edit slip. USGS names a tile
    `<PREFIX>_<cell>.laz` where PREFIX is `USGS_LPC_` plus the project directory that ends BASE, and
    tools/gen_provenance.py reads project names back off disk assuming exactly that shape. Editing one
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

    The distinction is the whole point. This used to swallow every exception and return -1, so a
    transient timeout looked exactly like "this tile is not in this sub-project" -- the caller then
    reported "edge of coverage, skip" and main() exited 0 having downloaded half a course. A green
    with no ground returns under it is what the honesty gate now has to catch; better to fail the
    fetch than to build on a gap that a network wobble invented.

    403 is UNKNOWN, not ABSENT. It was counted as authoritative alongside 404/410 and never retried,
    which reopened this exact false claim through a different status code: rockyweb does not answer 403
    for a tile it does not hold, so a 403 comes from an intermediary -- a proxy, a WAF, a rate limiter
    -- and says nothing about the survey's footprint. Reproduced with every HEAD answered 403: four
    tiles printed as "not in any sub-project (404) -- edge of coverage, skip", then "authoritative
    404 ... That is the edge of the survey", about requests that were DENIED.
    """
    last = None
    for attempt in range(tries):
        try:
            # identify the client, like every other request this project makes (fetch_lidar.tnm_items,
            # fetch_dem, fetch_osm). An anonymous HEAD is one of the reasons an intermediary answers
            # 403, and a 403 here used to be published as the edge of the LiDAR survey.
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "greenbook/1.0"})
            r = urllib.request.urlopen(req, timeout=30)
            n = int(r.headers.get("Content-Length", 0))
            if n > 0:
                return n
            # A 200 that carries no Content-Length is not an absence. Returning 0 here made the
            # caller drop the copy exactly like an authoritative 404, which is the false "edge of
            # coverage" claim this function was written to stop. We could not learn the size, so say
            # so and let the run abort rather than invent a gap.
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
        # stop asking. Callippe probes 25 cells x 3 sub-projects = 75 HEADs, and with 3 tries and two
        # 4 s sleeps each a network outage cost up to two hours before printing the same "re-run"
        # message. The verdict is unchanged; only the waiting is gone.
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
            # proves nothing. Saying "404, edge of coverage" here would be the exact false claim
            # 08cb08d removed -- and the early exit added for speed had reintroduced it, since one
            # failing sub-project now empties `copies` where previously all three had to 404.
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
        # This is the case that used to masquerade as "edge of coverage". Raised BEFORE anything is
        # downloaded: the coverage is already known to be incomplete, so there is nothing to buy by
        # fetching part of it first.
        raise SystemExit(
            f"could not determine whether {len(unknown)} tile(s) exist: {', '.join(unknown)}\n"
            f"  These are network failures, not 404s, so the survey may well cover them. Building now\n"
            f"  would leave greens with no ground returns for a reason that is not real. Re-run.")
    if not absence_is_credible(len(tiles), len(absent)):
        # A TOTAL sweep. Every HEAD was authoritative, so this is not a network story -- and it is not
        # a footprint story either, because this module is only run for a course known to be in Alameda
        # County. What it means is that these URLs address nothing. Raised here, so the "That is the
        # edge of the survey" note below is never reached with 100% of a course behind it.
        raise SystemExit(
            f"all {len(tiles)} candidate tile(s) answered 404. That is NOT the edge of the survey:\n"
            f"  this module is only run for a course known to be inside the Alameda County 2021\n"
            f"  survey, so a course lying entirely outside it is not the explanation. The likely cause\n"
            f"  is that the hardcoded paths are stale -- USGS has reorganised staged delivery before\n"
            f"  (fetch_lidar._BUCKETS exists because surveys moved under a `legacy/` bucket).\n"
            f"  Check these three against the producer, none of which is verified anywhere:\n"
            f"    BASE   = {BASE}\n"
            f"    SUBS   = {', '.join(SUBS)}\n"
            f"    PREFIX = {PREFIX}\n"
            f"  Publishing this as a survey gap would leave every green unread for a reason that is\n"
            f"  not real -- the same false claim this module already refuses for a timeout and a 403.")
    # WHICH LOCAL FILE HOLDS WHICH COPY is fetch_lidar.plan_downloads' job, not ours. It was decided
    # here too, and the two answers disagreed in the way that costs ground returns: this module
    # tested `os.path.exists(fn) and os.path.getsize(fn) >= sz - 1024`, which is ONE-SIDED, so a file
    # LARGER than expected satisfied a smaller expectation. Measured at Callippe, where cell
    # w6165n2052 exists in two sub-projects -- CA_AlamedaCo_1_2021 at 21,981,521 bytes and
    # CA_AlamedaCo_3_2021 at 244,776,088 (both confirmed by HEAD) -- and the 245 MB copy is on disk
    # under the PLAIN name while the 22 MB copy sits under `__Co1`, a name this module can never
    # generate (sub-project 1 is always probed first, so it always takes the plain name). A re-run
    # therefore reported the Co_1 copy "cached" against the 245 MB file, then downloaded the Co_3
    # copy again as `__Co3.laz`. fetch_dem_hd.py globs laz/*.laz and concatenates with NO
    # de-duplication, so that cell's ground returns would be counted twice. Measured per green:
    # 10 of Callippe's 18 (holes 1, 7, 10, 11, 12, 13, 14, 15, 17, 18) take their in-green points
    # from that cell alone and their published density would be EXACTLY doubled -- 13.0-15.8 pts/m2
    # becoming 26.0-31.6 -- which tools/gen_provenance.py prints into legal/03, where the Callippe row
    # currently reads "12.4-16.1 pts/m2 over 18 greens @0.4 m". Hole 9 is the one green in the cell
    # fed only by the Co_1 strip, so it alone would be unaffected.
    #
    # plan_downloads matches the cache BY SIZE over the whole directory, consuming each file as it is
    # matched, so it finds a copy whatever it is called and cannot spend one file on two expectations.
    # It also owns the `__Co<n>` naming (fetch_lidar.copy_suffix) and the cross-cell size-collision
    # warning. Reusing it is the point: this module already imports fetch_lidar, and the previous
    # arrangement was the same rule written twice with one copy wrong.
    todo, got = fetch_lidar.plan_downloads(items, f"{DIR}/laz")
    print(f"  {got} tile copy(ies) already on disk, {len(todo)} to download")
    failed = []
    for it, name in todo:
        url, fn, sz = it["downloadURL"], f"{DIR}/laz/{name}", it.get("sizeInBytes") or 0
        ok = False
        for a in range(4):
            try:
                # stage as .part and rename, so an interrupted transfer cannot be mistaken for a
                # complete tile by the size check on the next run. fetch_lidar.py was fixed this way;
                # this module still wrote straight to the final name.
                urllib.request.urlretrieve(url, fn + ".part")
                n = os.path.getsize(fn + ".part")
                if sz and n != sz:
                    # A short read that still parses is the worst case: the tile looks fine and simply
                    # has no points over part of the course. fetch_lidar.py already checked this; here
                    # the only test was the one-sided size comparison above, which a truncated file
                    # would fail on the NEXT run rather than this one -- after the run had reported
                    # success.
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
        # Exiting 0 here would leave PARTIAL coverage. fetch_lidar.py raises for exactly this reason:
        # a green with no ground returns under it is what produced the fabricated-terrain cards the
        # honesty gate now has to catch.
        raise SystemExit(f"FAILED to download {len(failed)} tile copy(ies): {', '.join(failed)}\n"
                         f"  Coverage would be incomplete -- re-run rather than building on this.")
    if got == 0:
        raise SystemExit("no tiles downloaded")
    # Check the DATA, not just the filenames: a tile can be present and correctly named and still
    # hold no points where a green is. This is the module's own worst case -- Castlewood Hill's
    # w6153n2055 copy on disk covers a 470-ft strip of a 3000-ft cell, and two greens fell in the
    # gap. See lidar_coverage.py.
    import lidar_coverage
    lidar_coverage.report(config.COURSE_DIR)

if __name__ == "__main__":
    main()
