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
# Consecutive pages that add no new product before the walk gives up. A service that ignores `offset`
# re-serves page one forever, and following that is unbounded; a service whose ORDER is merely unstable
# adds nothing on the odd page and progresses on the next. One page cannot tell those apart, three can,
# and the accounting at the end of tnm_items decides what the stall meant.
TNM_STALL_PAGES = 3


def _filtered_count(v):
    """How many products USGS says it dropped from a reply, from its own `filteredOut` field.

    Live it is either the int 0 or a SENTENCE -- "1 items have been removed because they don't have a
    download url" -- so the count has to be read out of the prose. Anything unrecognised reads as 0,
    which is the safe direction: an unparsed value then shows up as an unaccounted-for row and gets
    reported, rather than silently excusing a shortfall.
    """
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r"\d+", v)
        return int(m.group(0)) if m else 0
    return 0


def _tnm_page(offset, tries):
    """One page of TNM LPC products for the course bbox: (items, total, note, filtered).

    `total` is what the service says the whole query holds, or None when it did not say. `note` is any
    message or error field it carried, so a caller can report what was actually said. `filtered` is how
    many products the service says it removed from THIS reply before sending it.

    THE MESSAGE KEY IS `messages`, PLURAL, and a LIST. This read `reply.get('message')`, which is
    absent from every live reply, so USGS's own explanation of a short page was never read -- and the
    caller then invented one. Live on the bay-view bbox the reply carries
    `messages: ["Retrieved 14 item(s) Retrieved (1 through 200) 1 items have been removed because they
    don't have a download url"]` and `message: None`. Both spellings are read now; the singular is kept
    because it costs nothing and this endpoint's shape has changed before.

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
            msgs = reply.get('messages')
            if isinstance(msgs, (list, tuple)):
                msgs = "; ".join(str(m) for m in msgs if m)
            note = msgs or reply.get('message') or reply.get('errors') or reply.get('error')
            filtered = _filtered_count(reply.get('filteredOut'))
            if isinstance(total, str) and total.isdigit():
                total = int(total)          # the endpoint has been seen to quote it
            total = total if isinstance(total, int) else None
            if items:
                return items, total, note, filtered
            if total == 0:
                print(f"  TNM answered: it lists 0 LPC products for this bbox"
                      + (f" -- {note}" if note else ""))
                return [], 0, note, filtered
            # AN EMPTY REPLY THAT STATES A TOTAL IS AN ANSWER TOO, not a wobble: a service too busy to
            # serve any rows does not also report an accurate count of them. Live, the reply for an
            # offset past the end carries the REAL total (bay-view 14, micke-grove 6) plus "The offset
            # is greater than the total number of results for this query. No items returned." -- so the
            # `total == 0` case above never matched it and the walk's own terminating page was retried
            # `tries` times at 10 s each. Measured on the bay-view bbox: 8 rounds of "service busy"
            # against a service that had just answered the question precisely.
            # A transient empty page carrying a total would now end the walk instead of being retried,
            # and the accounting below then REFUSES rather than returning a short list -- which is the
            # direction this module chooses everywhere else.
            if total is not None:
                return [], total, note, filtered
            print(f"  TNM try {a+1}: 0 items and no total (service busy), retrying")
        except Exception as e:
            print(f"  TNM try {a+1} failed: {type(e).__name__}, retrying")
        time.sleep(10)
    return [], None, None, 0


def tnm_items(tries=8):
    """Every LPC product TNM lists for this course bbox, following the API's paging.

    THIS USED TO BE ONE REQUEST FOR `&max=200`, read as the whole world. A course needing more than 200
    products would have got a silently TRUNCATED tile list: the missing tiles are not an error anywhere
    downstream, they are simply absent, so lidar_coverage measures a smaller footprint, choose_project
    ranks surveys on it, and greens fall back to the seamless DEM or to nothing for a reason that is
    not real.
    There was a `print("WARNING: hit the 200-item TNM cap")`, which is a line in a long log rather than a
    refusal, and everything else in this pipeline refuses.

    Latent on this corpus -- 4 to 14 tiles are kept per course, nowhere near the cap -- so the fix is for
    the course that is not in it yet.

    WHAT A SHORT LIST MEANS DEPENDS ON WHY IT IS SHORT, and the first version of this paging did not ask.
    It advanced with `offset += len(items)` and then refused whenever `len(got) < total`. Both halves
    assume `offset` is item-indexed over a STABLE ordering, and this API guarantees neither -- so a
    reordering between two requests makes one page overlap the last, dedup drops the repeats, and the run
    dies telling the user to re-run a service that is working perfectly. Every one of these semantics was
    reasoned about against a monkeypatched stub, never observed live, which is exactly why the failure
    modes now have to distinguish "the service said something I cannot interpret" from "the service is
    broken".

    The fact that separates them is how many ROWS the service accounts for against the number it claims.
    Two terms, not one: `total` is USGS's count BEFORE its own download-URL filter, and `filteredOut`
    says how many that filter removed. Measured live on all twelve course bboxes, five of them list a
    product with no downloadURL -- bay-view 14/13, callippe 41/40, castlewood-hill 11/10,
    castlewood-valley 7/6, monarch-bay 25/24 -- so `len(got) < total` is the NORMAL state there and
    means nothing is wrong.

      * WALKED TO THE END and accounted for at least `total` rows, but fewer DISTINCT products came
        back. Every offset in the range was asked, so `got` already holds every product the service was
        willing to show; the deficit is repeated rows or filtered ones, not missing tiles. That is
        reported and returned best effort rather than stopping a build that has everything.
      * RAN OUT of rows before accounting for `total`. The listing really is short, nothing can say which
        products are missing, and a missing tile is invisible downstream. That still REFUSES.

    Two refusals are unchanged, because neither is a thing a healthy service does:
      * a page exactly at the cap with NO total. That is the one state where a complete list and a
        truncated one are indistinguishable, which is precisely what the old code could not tell apart.
      * a service that ignores `offset` and re-serves page one. It is followed for TNM_STALL_PAGES pages
        and then abandoned -- but abandoning the walk is NOT walking to the end, so such a run can never
        reach the best-effort path however many rows it was handed. Accepting page one as the whole survey
        is the defect this function was written for.

    AND THE STATED TOTAL IS TAKEN FROM THE FIRST PAGE THAT GIVES ONE. It used to be overwritten by every
    page, which erased the real figure and made the shortfall check a no-op. The shape it was written
    against is not the one this service sends: an over-the-end reply answers the REAL total (bay-view
    14, micke-grove 6) plus "The offset is greater than the total number of results for this query. No
    items returned." The latch is kept because it is free and correct either way, but it defends against
    a reply TNM does not produce.

    WHAT ENDS THE WALK is an empty page, a `total` that has been accounted for, or the stall detector --
    NOT a page that came back under `max`. `max` is a ceiling, not a quota, and an HTTP API may
    under-fill any page and keep serving on the next. Treating a sub-cap page as the end regardless
    refused a healthy service: a stated 500 served as 200 + 150 + 150 stopped at 350 rows and reported
    that the producer "ran out", naming an offset the walk had never requested. A short page still ends
    the walk when NO total was stated -- which measured over all twelve course bboxes at every offset
    regime NEVER HAPPENS. `total` is a top-level int on page one, mid-listing and past the end alike, 0
    of 12 times absent. That path is real but live-unreachable on this corpus, and it is kept because
    the shape of this endpoint's reply has changed before.

    AND EVERY REFUSAL NAMES AN OFFSET THAT WAS ACTUALLY REQUESTED, from `last_asked`. The stall refusal
    computed it as `offset - TNM_PAGE_MAX`, which is the last request only while every page arrives
    cap-sized -- true until the paragraph above made sub-cap pages reachable mid-walk, and false after: a
    service ignoring `offset` at 150 rows a page against a stated 500 is asked at 0/150/300/450 and that
    subtraction blames 400. The offset is in the message so an operator can replay the request that
    stalled; one that was never made replays as something else.

    Getting nothing at all is the old outage path and still returns [], which main() turns into its own
    "re-run later" stop.
    """
    got, ids, offset, total = [], set(), 0, None
    served = 0              # ROWS the service handed over, before dedup. The other half of the accounting.
    filtered = 0            # products USGS says it REMOVED from the replies -- see `filteredOut`
    last_asked = 0          # the offset of the most recent REQUEST. NOT `offset - TNM_PAGE_MAX`: pages
                            # come back under the cap, so that subtraction names a request never made.
    stalled = 0             # CONSECUTIVE pages that added no new product
    stalls_seen = 0         # pages that added nothing, consecutive or not -- see the refusals below
    walked_to_end = False   # the listing ran out, as opposed to this loop giving up on it
    notes = []
    while True:
        last_asked = offset
        items, page_total, note, page_filtered = _tnm_page(offset, tries)
        if note and str(note) not in notes:
            notes.append(str(note))
        # FIRST stated total wins -- see the docstring. An over-the-end page answers the real total, and
        # taking the latest was written against a `total: 0` this service does not actually send.
        if page_total is not None and total is None:
            total = page_total
        if not items:
            walked_to_end = True
            break
        served += len(items)
        new = 0
        for it in items:
            key = it.get('sourceId') or it.get('downloadURL') or it.get('title')
            if key in ids:
                continue
            ids.add(key)
            got.append(it)
            new += 1
        offset += len(items)
        stalled = stalled + 1 if new == 0 else 0
        stalls_seen += 1 if new == 0 else 0
        # A FILTERED COUNT MAY NEVER EXCUSE A STALL, so it is accumulated under two bounds. Caught by
        # this function's own regression test: a service re-serving page one while reporting
        # "387 items have been removed" made `len(got) + filtered` meet a stated 400 on the FIRST page,
        # which broke the walk and returned page one as the whole survey -- exactly the defect the stall
        # detector exists for, re-entered through the new accounting.
        #   * PER PAGE, no page can have filtered more products than the window it was asked for holds;
        #   * ONLY ON PROGRESS, because a page that repeated its rows repeated its filtered count too,
        #     and summing those double-counts without bound.
        if new:
            filtered += min(page_filtered, TNM_PAGE_MAX)
        if stalled >= TNM_STALL_PAGES:
            break                   # not honouring `offset`; the accounting below says what that cost
        # Its position relative to the sub-cap block below is NOT load-bearing, and saying so beats
        # leaving the next reader to assume it is: past page one `total` is never None -- a cap-sized
        # page with no total raises and a sub-cap page with no total breaks -- so the only thing that
        # block does (`if total is None: break`) cannot fire on a page where a stall could have built up.
        # Measured: swapping the two leaves all eleven stubbed scenarios byte-identical.
        if len(items) < TNM_PAGE_MAX:
            # A SUB-CAP PAGE IS THE END ONLY WHEN NOTHING SAYS OTHERWISE. `max` is a ceiling, not a
            # quota: an HTTP API may under-fill any page and keep serving on the next. Reading a short
            # page as the end WHILE A STATED `total` IS STILL UNMET refused a healthy service --
            # 500 served as 200 + 150 + 150 stopped at 350 and blamed the producer for "running out"
            # at an offset that had never been requested. With a `total` in hand, keep paging; the
            # empty page, the stall detector, or `total` itself ends the walk.
            if total is None:
                walked_to_end = True
                break
        elif total is None:
            raise SystemExit(
                f"USGS TNM returned exactly {TNM_PAGE_MAX} products -- this request's cap -- and no\n"
                f"  `total`, so a complete listing and a truncated one look identical. Refusing to\n"
                f"  guess: if it is truncated, the missing tiles are not an error anywhere downstream,\n"
                f"  they are just absent, and greens lose their 0.4 m surface for a reason that is not\n"
                f"  real. Check what the products API now returns and extend the paging here."
                + (f"\n  The service said: {'; '.join(notes)}" if notes else ""))
        # `total` counts products BEFORE the service's own download-URL filter, so the walk is done when
        # what it has plus what USGS says it dropped accounts for the stated total. Without the second
        # term this asked for one page past the end of every listing holding a URL-less product -- five
        # of the twelve courses in this corpus -- and then blamed the service for the difference.
        if len(got) + filtered >= total:
            break

    said = f"\n  The service said: {'; '.join(notes)}" if notes else ""
    if stalled >= TNM_STALL_PAGES and not walked_to_end:
        raise SystemExit(
            f"USGS TNM re-served products it had already listed for {stalled} pages running, the last at\n"
            f"  offset={last_asked}, so it is not honouring `offset` and the listing cannot be\n"
            f"  paged. Refusing to treat the {len(got)} products seen so far as the whole survey"
            + (f" of {total}" if total else "") + ": a short\n"
            f"  tile list is invisible downstream -- the tiles are simply absent, coverage measures\n"
            f"  smaller, and greens fall back to the seamless DEM for a reason that is not real. Check\n"
            f"  products API before re-running." + said)
    if total and got and len(got) + filtered < total:
        if walked_to_end and served + filtered >= total:
            # NOT a refusal. The walk reached the end of the listing and the service accounted for at
            # least as many rows as it claims to hold, so every product it was willing to show is in
            # `got` and the gap is rows it repeated -- an unstable ordering under an item-indexed
            # offset, which this API does not promise not to do. Loud, because it is still a surprise.
            #
            # DELIBERATELY NOT A DIAGNOSIS. This used to assert the cause was "an unstable listing
            # order" and advise "re-run -- a different ordering will page differently", and on the five
            # courses whose listing holds a URL-less product both halves were false: USGS had said in
            # `filteredOut` exactly what happened, and that product has no downloadURL on any run, so
            # re-running changes nothing. The accounting is reported instead and the cause is left to
            # whatever the service said, because a page that repeats one row per page is genuinely
            # ambiguous here and refusing would refuse the reordering case this branch exists for.
            print(f"  NOTE: TNM says it holds {total} LPC products for this bbox. {len(got)} distinct "
                  f"came back"
                  + (f" and it reports removing {filtered} for having no download URL" if filtered
                     else "")
                  + f"; {total - len(got) - filtered} row(s) are unaccounted for.")
            print(f"  Every offset from 0 to {offset} was requested and the end of the listing was "
                  f"reached, so these {len(got)} are every product the service was willing to show; "
                  f"{served} rows were served in total, so the difference is rows it repeated."
                  + said.replace("\n  ", " "))
        else:
            # A repeated page and a short listing are different faults and can arrive together, so the
            # refusal reports both: a walk that saw repeats cannot even claim `offset` was advancing over
            # a stable order, which changes what the operator should go and look at.
            repeats = ("" if not stalls_seen else
                       f"\n  {stalls_seen} page(s) repeated products already listed, so `offset` may not\n"
                       f"  be advancing over a stable order either -- the shortfall may be either fault.")
            raise SystemExit(
                f"USGS TNM says it holds {total} LPC products for this bbox but ran out after serving\n"
                f"  {served} rows, of which {len(got)} were distinct"
                + (f", with {filtered} reported removed for\n  having no download URL" if filtered
                   else "") + ". That is a TRUNCATED listing, not a\n"
                f"  reordered one: a service whose order merely shifted would still have handed over\n"
                f"  {total} rows. Refusing to build on a partial tile list -- see this function's\n"
                f"  docstring for why a short list is invisible downstream. Re-run when the service is\n"
                f"  healthy." + repeats + said)
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
    # A survey missing some greens is recoverable and disclosed: those greens fall back to the 3DEP
    # seamless mosaic and the card carries a coarse-data caveat naming the source cell measured off
    # that green's own array. A survey that is a decade stale is not -- it
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
              f"({round(gc*ngreens)}/{ngreens}); the rest fall back to the 3DEP seamless mosaic and\n"
              f"       their cards are labelled with the source cell measured off their own arrays.")
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
    # report_or_exit, not report: this was a bare expression statement that DISCARDED the verdict, so
    # a fetch ending "!! 1 green(s) are NOT fully covered by the point data on disk" exited 0 and
    # PIPELINE.md's "what an agent does each time" read that as success. The stop names the key that
    # clears it, because monarch-bay's bayside holes make its verdict permanently unclean.
    import lidar_coverage
    lidar_coverage.report_or_exit(config.COURSE_DIR)

if __name__ == "__main__":
    main()
