#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Round 14: the TNM reply vocabulary, the bulk tile transfer, and one non-finite gps_time.

Everything here is driven from SYNTHETIC replies and SYNTHETIC LAZ files. The National Map is a
third-party API and rockyweb is a third-party file server; a unit test that asks either of them a
question is a test whose verdict depends on the weather. The shapes stubbed below are the ones this
repo has MEASURED live and recorded in fetch_lidar.py's own docstrings.

Five defects, each watched fail on the unfixed tree first:

  B-1  a NEGATIVE `filteredOut` hard-refused a healthy listing. `_filtered_count` returned the int
       unchanged, so `len(got) + filtered >= total` could never be met and a 14-of-14 reply died on
       "That is a TRUNCATED listing ... with -1 reported removed".
  B-2  the per-page clamp was `min(page_filtered, TNM_PAGE_MAX)`, which ignores the rows the page
       actually served -- so `filteredOut: "200 items have been removed"` beside 5 served rows
       "accounted for" 205 and a truncated listing was accepted in silence.
  B-3  a +inf gps_time raised OverflowError out of cluster_mass WHILE FORMATTING the message that
       explains the refusal, so the user saw a traceback instead of the diagnosis.
  B-5  the bulk tile download used urllib.request.urlretrieve, which accepts no timeout and forwards
       none: the socket inherited socket.getdefaulttimeout() == None and blocked in recv() forever,
       and the `for a in range(4)` retry around it could never fire because nothing raised.
  B-6  the download URL's scheme was never checked, and it is the only request in this project whose
       URL comes out of a reply BODY rather than a module constant.

No test in this file drops anything from sys.modules -- deliberately, because
test_the_suite_reports_its_own_module_drop_count_correctly counts those sites across every file in
tests/ and pins the total to a figure in README.md. Every stub here is keyed on the argument it is
handed rather than on which course config happens to be bound to, so nothing needs a rebind.
"""
import email.message
import glob
import importlib
import io
import math
import os
import re
import shutil
import socket
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _a_course():
    """One slug config can bind to, or SKIP. courses/ is gitignored, so a fresh clone has none."""
    slugs = sorted(os.path.basename(os.path.dirname(p))
                   for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))
                   if not os.path.basename(os.path.dirname(p)).startswith("_"))
    if not slugs:
        pytest.skip("courses/ is gitignored; no course.json for config to bind to")
    return slugs[0]


def _fetcher(name):
    """fetch_lidar / fetch_lidar_alameda, bound to whatever course is already in play.

    `setdefault`, not an assignment: if an earlier test in this session already imported config,
    rebinding COURSE would not change it anyway, and nothing below cares which course it is -- the
    replies are stubbed per argument. A SystemExit out of config means no course data at all.
    """
    if name == "fetch_lidar_alameda":
        pytest.importorskip("pyproj")
    os.environ.setdefault("COURSE", _a_course())
    try:
        return importlib.import_module(name)
    except SystemExit as e:                     # config refuses when there is no course.json
        pytest.skip(f"{name} cannot bind to a course: {e}")


def _lidar_dates():
    """tools/lidar_dates.py, imported under its own name."""
    pytest.importorskip("laspy")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    return importlib.import_module("lidar_dates")


# ---------------------------------------------------------------------------
# B-1 + B-2 -- what `filteredOut` may and may not excuse
# ---------------------------------------------------------------------------
def _item(i):
    return {"sourceId": f"id{i}", "title": f"t{i}.laz",
            "downloadURL": f"https://x/Projects/CA_Test_2021_B21/LAZ/{i}.laz"}


def _verdict(fl, monkeypatch, total, n_shown, filtered_out):
    """Run the paging walk over a ONE-PAGE listing and report what it decided.

    Returns ("accepted", n_products) or ("refused", message). The page past the end answers the real
    total with an empty item list plus TNM's own over-the-end sentence, which is what the live service
    does -- see _tnm_page.
    """
    import contextlib
    import json as _json
    shown = [_item(i) for i in range(n_shown)]
    page = {"total": total, "items": shown,
            "messages": [f"Retrieved {total} item(s) Retrieved (1 through 200)"]}
    if filtered_out is not None:
        page["filteredOut"] = filtered_out
    pages = {0: page,
             n_shown: {"total": total, "items": [],
                       "messages": ["The offset is greater than the total number of results for "
                                    "this query. No items returned."]}}

    def _open(req, timeout=None):
        off = int(re.search(r"[&?]offset=(\d+)", req.full_url).group(1))
        body = _json.dumps(pages.get(off, {"total": total, "items": []})).encode()

        class _R:
            def read(self_inner):
                return body
        return _R()

    monkeypatch.setattr(fl.urllib.request, "urlopen", _open)
    monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return "accepted", len(fl.tnm_items())
    except SystemExit as e:
        return "refused", str(e)


def test_a_negative_filtered_out_neither_refuses_a_healthy_listing_nor_excuses_a_truncation(
        monkeypatch):
    """`filteredOut` is a THIRD-PARTY count, and both directions of trusting it were wrong.

    `total` is USGS's row count BEFORE its own download-URL filter and `filteredOut` says how many
    that filter removed, so the walk is finished when `len(got) + filtered` reaches `total`. Two ways
    that arithmetic broke on a value the service is free to emit:

      B-1 A NEGATIVE VALUE HARD-REFUSED A HEALTHY LISTING. `_filtered_count` returned any int
          unchanged, so `filteredOut: -1` beside a complete 14-of-14 page made 13 >= 14 false at the
          break AND at the accounting below it, and the course died on "USGS TNM says it holds 14 LPC
          products ... but ran out after serving 14 rows, of which 14 were distinct, with -1 reported
          removed". Fourteen rows served against a stated fourteen is the definition of accounted for.
          This is the SECOND time this class has landed on this function -- see case (c) of
          test_a_product_usgs_filtered_out_is_not_read_as_a_missing_tile, where one sort order away
          from a healthy reply was a refusal.

      B-2 A CRAFTED VALUE EXCUSED A REAL TRUNCATION. The clamp was `min(page_filtered,
          TNM_PAGE_MAX)`, which bounds the claim by the WINDOW but ignores the rows the page actually
          served. So a page serving 5 rows while claiming 200 removed "accounted for" 205 of a stated
          205, broke the walk on page one, and returned 5 products as the whole survey with no
          message of any kind. A short tile list is invisible downstream: the tiles are simply absent,
          coverage measures smaller, and greens fall back to the seamless DEM for a reason that is
          not real.

    THE INTERPRETATION THAT SATISFIES BOTH, stated because clamping alone would satisfy only one:

      * a negative count is NOT A COUNT, and reads as 0 -- the same answer `_filtered_count` already
        gives an unparsable string. 0 is the neutral element of this accounting: it excuses nothing,
        so a truncation cannot hide behind it, and it removes nothing, so a listing whose rows are
        otherwise accounted for is not refused. Clamping to the absolute value or ignoring the sign
        would have been the silent-excuse direction B-2 is about.
      * the per-page bound is the window MINUS THE ROWS SERVED. TNM's own message spells the window
        out -- "Retrieved 14 item(s) Retrieved (1 through 200) 1 items have been removed because they
        don't have a download url" -- so rows considered = served + filtered <= max. Reconciling
        against the rows actually received is what stops a hostile count from paying for rows the
        window never held.

    WHAT IS LEFT, disclosed rather than claimed closed: a page serving 5 rows and claiming 195
    removed is arithmetically consistent with a 200-row window, so if the service also states a total
    of 200 it is accepted. Nothing in the reply distinguishes that from an honest listing of 200
    products with 195 URL-less ones, and refusing it would refuse the live bay-view shape scaled up.
    The bound is the tightest one the vocabulary supports, not a guess.
    """
    fl = _fetcher("fetch_lidar")
    CAP = fl.TNM_PAGE_MAX
    assert fl._filtered_count(-1) == 0, (
        "a NEGATIVE filteredOut is not a count of removed products. Returned unchanged it makes "
        "`len(got) + filtered >= total` unreachable and refuses a listing the service accounted for "
        f"in full; got {fl._filtered_count(-1)!r}")
    assert fl._filtered_count(-999999) == 0 and fl._filtered_count(0) == 0
    assert fl._filtered_count("1 items have been removed because they don't have a download url") == 1

    # total, rows shown, filteredOut          -> expected verdict, why
    CASES = [
        (14, 14, -1,       "accepted", "healthy 14-of-14; a negative count may not refuse it"),
        (14, 14, -999999,  "accepted", "any negative, same reading"),
        (14, 14, 0,        "accepted", "the honest zero, as a control"),
        (14, 14, None,     "accepted", "no filteredOut key at all, as a control"),
        (14, 13, "1 items have been removed because they don't have a download url",
                           "accepted", "the live bay-view shape: 13 shown + 1 removed = 14"),
        (20, 13, None,     "refused",  "7 rows short with nothing claimed removed: truncated"),
        (20, 13, -1,       "refused",  "a negative may not excuse those 7 either"),
        (205, 5, "200 items have been removed because they don't have a download url",
                           "refused",  "crafted: a 200-row window holding 5 served rows cannot have "
                                       "filtered 200"),
        (1000, 5, "999 items have been removed",
                           "refused",  "crafted large: same reconciliation"),
        (CAP, 5, f"{CAP - 5} items have been removed",
                           "accepted", "the disclosed residual: 5 + 195 IS the window, and it "
                                       "accounts for the stated total exactly"),
    ]
    table, bad = [], []
    for total, shown, fo, want, why in CASES:
        got, detail = _verdict(fl, monkeypatch, total, shown, fo)
        table.append(f"filteredOut={fo!r:<70} total={total:<5} shown={shown:<3} -> {got}")
        if got != want:
            bad.append(f"filteredOut={fo!r} total={total} shown={shown}: expected {want} ({why}), "
                       f"got {got} -- {str(detail)[:400]}")
    assert not bad, ("`filteredOut` is still deciding the wrong way:\n  " + "\n  ".join(bad)
                     + "\n\nfull table:\n  " + "\n  ".join(table))

    # ...and the healthy negative case must not cost a REQUEST either. A page that already accounts
    # for the stated total is the end of the listing; asking past it is the retry storm this module
    # measured at ~80 s per fetch on five courses.
    asked = []
    import contextlib
    import json as _json

    def _open(req, timeout=None):
        asked.append(int(re.search(r"[&?]offset=(\d+)", req.full_url).group(1)))
        body = _json.dumps({0: {"total": 14, "items": [_item(i) for i in range(14)],
                                "filteredOut": -1}}.get(asked[-1],
                                                        {"total": 14, "items": []})).encode()

        class _R:
            def read(self_inner):
                return body
        return _R()
    monkeypatch.setattr(fl.urllib.request, "urlopen", _open)
    monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
    with contextlib.redirect_stdout(io.StringIO()):
        got = fl.tnm_items()
    assert len(got) == 14 and asked == [0], (
        f"a listing the first page accounts for in full took {len(asked)} request(s) ({asked}) and "
        f"returned {len(got)} products")


def test_a_stall_is_still_refused_however_the_filtered_count_is_spelled(monkeypatch):
    """The reconciliation must not reopen the defect the stall detector exists for.

    A service that ignores `offset` and re-serves page one is refused after TNM_STALL_PAGES pages,
    and no accounting may excuse it -- accepting page one as the whole survey is the original bug
    this paging was written for. Both spellings of the count are tried here, including the negative
    one B-1 introduces a new reading for, because `filtered` is accumulated inside the same loop the
    stall detector runs in.
    """
    fl = _fetcher("fetch_lidar")
    import contextlib
    import json as _json
    shown = [_item(i) for i in range(13)]
    for fo in ("387 items have been removed", -387, 387, 0):
        pages = {off: {"total": 400, "items": shown, "filteredOut": fo}
                 for off in range(0, 13 * 8, 13)}

        def _open(req, timeout=None, _p=pages):
            off = int(re.search(r"[&?]offset=(\d+)", req.full_url).group(1))
            body = _json.dumps(_p.get(off, {"total": 400, "items": []})).encode()

            class _R:
                def read(self_inner):
                    return body
            return _R()
        monkeypatch.setattr(fl.urllib.request, "urlopen", _open)
        monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
        with pytest.raises(SystemExit) as e:
            with contextlib.redirect_stdout(io.StringIO()):
                fl.tnm_items()
        assert "re-served products it had already listed" in str(e.value), (
            f"filteredOut={fo!r}: a service that ignores `offset` must still be refused as a paging "
            f"failure: {str(e.value)[:400]}")


# ---------------------------------------------------------------------------
# B-5 + B-6 -- the largest fetches in the project
# ---------------------------------------------------------------------------
class _Recorder:
    """A stand-in for urllib.request.urlopen that records the timeout it was handed.

    The discriminator for B-5: `urlretrieve` calls the module-global `urlopen(url, data)` with NO
    timeout, so what arrives here is `socket._GLOBAL_DEFAULT_TIMEOUT` -- and nothing in this project
    calls socket.setdefaulttimeout, so socket.getdefaulttimeout() is None and the socket blocks
    forever on connect and on every read.
    """

    def __init__(self, body):
        self.body = body
        self.calls = []          # [(url, timeout)]

    def __call__(self, req, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kw):
        self.calls.append((getattr(req, "full_url", req), timeout))
        return _FakeResponse(self.body)

    def timeouts(self):
        return [t for _u, t in self.calls]


class _FakeResponse(io.BytesIO):
    """Enough of an http.client.HTTPResponse for urlretrieve AND for copyfileobj."""

    def __init__(self, body):
        super().__init__(body)
        self._headers = email.message.Message()
        self._headers["Content-Length"] = str(len(body))

    def info(self):
        return self._headers


def _tile_body(n=4096):
    return bytes(range(256)) * (n // 256)


def _run_fetch_lidar_main(fl, monkeypatch, tmp_path, urls, rec):
    """fetch_lidar.main() with its DIR pointed at tmp_path and its two network legs stubbed.

    The real main() loop runs: sweep_partials, plan_downloads, the `for a in range(4)` retry, the
    size check against TNM's sizeInBytes, and the .part -> final rename. Only the TNM listing, the
    transfer socket and the coverage report are replaced.
    """
    import lidar_coverage
    body = _tile_body()
    items = [{"downloadURL": u, "sizeInBytes": len(body), "sourceId": f"s{i}",
              "title": os.path.basename(u)} for i, u in enumerate(urls)]
    (tmp_path / "laz").mkdir(exist_ok=True)
    monkeypatch.setattr(fl, "DIR", str(tmp_path))
    monkeypatch.setattr(fl, "tnm_items", lambda *a, **k: items)
    monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(lidar_coverage, "report_or_exit", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen", rec)
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fl.main()
    return buf.getvalue(), body


ALAMEDA_CELL = "w6153n2055"


def _run_alameda_main(fa, monkeypatch, tmp_path, rec, base=None):
    """fetch_lidar_alameda.main() with DIR at tmp_path, HEADs stubbed and the transfer recorded.

    `base` overrides BASE, which is how a non-https URL is driven through the real loop: the project
    directory that ends BASE is left alone, so check_paths() still passes and the only thing that
    changes is the scheme.
    """
    import lidar_coverage
    body = _tile_body()
    (tmp_path / "laz").mkdir(exist_ok=True)
    monkeypatch.setattr(fa, "DIR", str(tmp_path))
    if base is not None:
        monkeypatch.setattr(fa, "BASE", base)
    monkeypatch.setattr(fa, "covering_tiles", lambda *a, **k: [ALAMEDA_CELL])
    monkeypatch.setattr(fa, "head_size",
                        lambda u, tries=3: len(body) if fa.SUBS[0] in u else fa.ABSENT)
    monkeypatch.setattr(fa.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(lidar_coverage, "report_or_exit", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen", rec)
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fa.main()
    return buf.getvalue(), body


def test_the_bulk_tile_download_names_a_read_timeout(monkeypatch, tmp_path):
    """These are the LARGEST fetches in the project and they were the only ones with no timeout.

    `urllib.request.urlretrieve` accepts no timeout parameter and forwards none, so the socket it
    opens inherits `socket.getdefaulttimeout()`, which is None because nothing in this project ever
    calls socket.setdefaulttimeout: blocking on connect and blocking on every read. A connection that
    establishes and then goes quiet mid-transfer sits in recv() forever, and the `for a in range(4)`
    + `time.sleep(3)` retry wrapped around it can never advance, because nothing raises. 78 tiles,
    11.6 GiB, and PIPELINE.md step 4 tells the user to run this unattended.

    Every other network call in this repo names one explicitly: fetch_lidar.tnm_items 90,
    fetch_osm 150, fetch_lidar_alameda's HEAD 30, fetch_dem and tools/verify_elevation 120.

    Recorded rather than asserted about the source text: the recorder below is handed exactly what the
    download path passes, and on the unfixed tree that is the `socket._GLOBAL_DEFAULT_TIMEOUT`
    sentinel. Both fetchers are driven through their real main() loop, with the .part staging and the
    rename that surround the transfer intact -- asserted here too, because a timeout fix that reached
    into that staging would be a different regression.
    """
    body = _tile_body()
    for name, run in (("fetch_lidar", "plain"), ("fetch_lidar_alameda", "alameda")):
        mod = _fetcher(name)
        rec = _Recorder(body)
        d = tmp_path / run
        d.mkdir()
        if run == "plain":
            out, body = _run_fetch_lidar_main(
                mod, monkeypatch, d,
                ["https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
                 "CA_AlamedaCounty_2021_B21/CA_AlamedaCo_1_2021/LAZ/tile_a.laz"], rec)
        else:
            out, body = _run_alameda_main(mod, monkeypatch, d, rec)
        assert rec.calls, f"{name}: the download path opened no connection at all:\n{out}"
        sentinel = [t for t in rec.timeouts() if not isinstance(t, (int, float))]
        assert not sentinel, (
            f"{name}: the tile transfer passed timeout={sentinel[0]!r} -- that is "
            f"socket._GLOBAL_DEFAULT_TIMEOUT, and socket.getdefaulttimeout() is "
            f"{socket.getdefaulttimeout()!r}, so the socket blocks forever on a stalled read and the "
            f"retry loop around it can never fire. Name a timeout on the request.")
        assert all(t > 0 for t in rec.timeouts()), \
            f"{name}: a non-positive timeout is not a deadline: {rec.timeouts()}"
        # the staging behaviour around the transfer is unchanged
        got = sorted(p.name for p in (d / "laz").iterdir())
        assert got and all(g.endswith(".laz") for g in got), (
            f"{name}: laz/ holds {got} after a successful fetch -- the .part must be renamed into "
            f"place and nothing else left behind:\n{out}")
        for g in got:
            assert (d / "laz" / g).read_bytes() == body, f"{name}: {g} is not what was served"


def test_a_transfer_that_goes_quiet_mid_stream_now_reaches_the_retry_loop(monkeypatch, tmp_path):
    """The point of naming a timeout: something has to RAISE for `for a in range(4)` to mean anything.

    The retry loop and the `time.sleep(3)` between its attempts were already there; with no timeout on
    the socket, a connection that established and then stopped sending sat in recv() forever, so the
    loop never advanced and the run never failed -- it simply stopped, unattended, mid-corpus. The
    stand-in below establishes, hands over a few bytes and then raises TimeoutError, which is exactly
    what a socket timeout produces mid-read.

    What must follow is the module's own accounting: four attempts, the tile named in the failure, and
    NO .part left in laz/ -- a staged file that is not a tile is the thing sweep_partials exists to
    clean up after a kill, and this path removes its own.
    """
    fl = _fetcher("fetch_lidar")
    import lidar_coverage
    attempts = []

    class _Stalls(io.BytesIO):
        def __init__(self):
            super().__init__(b"\x00" * 64)
            attempts.append(1)

        def info(self):
            h = email.message.Message()
            h["Content-Length"] = "4096"
            return h

        def read(self, *a, **k):
            raise TimeoutError("timed out")

    def _open(req, data=None, timeout=None, **kw):
        assert isinstance(timeout, (int, float)), f"still no timeout: {timeout!r}"
        return _Stalls()

    url = ("https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
           "CA_AlamedaCounty_2021_B21/CA_AlamedaCo_1_2021/LAZ/tile_b.laz")
    (tmp_path / "laz").mkdir()
    monkeypatch.setattr(fl, "DIR", str(tmp_path))
    monkeypatch.setattr(fl, "tnm_items",
                        lambda *a, **k: [{"downloadURL": url, "sizeInBytes": 4096,
                                          "sourceId": "s0", "title": "tile_b.laz"}])
    monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(lidar_coverage, "report_or_exit", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen", _open)
    import contextlib
    buf = io.StringIO()
    with pytest.raises(SystemExit) as e:
        with contextlib.redirect_stdout(buf):
            fl.main()
    assert "FAILED to download" in str(e.value) and "tile_b.laz" in str(e.value), (
        f"a stalled transfer must end in this module's own refusal, naming the tile: {e.value!r}")
    assert len(attempts) == 4, (
        f"the transfer was attempted {len(attempts)} time(s); the loop around it is "
        f"`for a in range(4)`, and before a timeout existed the first attempt never returned at "
        f"all:\n{buf.getvalue()}")
    assert not list((tmp_path / "laz").iterdir()), (
        f"a failed transfer left {[p.name for p in (tmp_path / 'laz').iterdir()]} behind; a .part in "
        f"laz/ looks like a tile forever")


def test_a_body_shorter_than_the_announced_length_is_still_caught(monkeypatch, tmp_path):
    """urlretrieve raised ContentTooShortError; replacing it must not drop that check.

    It is the ONLY truncation test on the path where TNM reports no `sizeInBytes` -- plan_downloads
    says of that path, in its own comment, that it "still cannot tell a truncated file from a complete
    one" -- and a short tile that still parses is this project's worst case: the file looks fine and
    simply has no points over part of the course. So the transfer compares what it copied against the
    Content-Length the server announced, and raises into the same retry.

    This one is PARITY, not red-then-green: it passes on the unfixed tree too, because urlretrieve did
    it. What it grades is the replacement. Measured three ways on the scenario below -- a body of 100
    bytes against an announced 4,096: old urlretrieve, 4 attempts then FAILED, laz/ empty; the new
    helper with the length check deleted, ONE attempt and `laz/tile_c.laz` accepted as a tile; the
    helper as shipped, 4 attempts then FAILED, laz/ empty.
    """
    fl = _fetcher("fetch_lidar")
    import lidar_coverage
    tries = []

    class _Truncates(io.BytesIO):
        def __init__(self):
            super().__init__(b"\x11" * 100)      # 100 bytes, against an announced 4096
            tries.append(1)

        def info(self):
            h = email.message.Message()
            h["Content-Length"] = "4096"
            return h

    url = ("https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
           "CA_AlamedaCounty_2021_B21/CA_AlamedaCo_1_2021/LAZ/tile_c.laz")
    (tmp_path / "laz").mkdir()
    monkeypatch.setattr(fl, "DIR", str(tmp_path))
    # NO sizeInBytes: the caller's own size check cannot fire, which is the point of this case.
    monkeypatch.setattr(fl, "tnm_items",
                        lambda *a, **k: [{"downloadURL": url, "sourceId": "s0",
                                          "title": "tile_c.laz"}])
    monkeypatch.setattr(fl.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(lidar_coverage, "report_or_exit", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Truncates())
    import contextlib
    buf = io.StringIO()
    with pytest.raises(SystemExit) as e:
        with contextlib.redirect_stdout(buf):
            fl.main()
    assert "FAILED to download" in str(e.value), (
        f"a body 100 bytes long against an announced 4,096 was accepted as a tile: {e.value!r}\n"
        f"{buf.getvalue()}")
    assert len(tries) == 4, f"the short body was not retried like any other transport fault: {tries}"
    assert not list((tmp_path / "laz").iterdir()), "a truncated .part was left in laz/"


def test_the_bulk_tile_download_refuses_a_url_that_is_not_https(monkeypatch, tmp_path):
    """The tile URL is the ONLY request in this project whose address comes out of a reply body.

    `it['downloadURL']` arrives straight from the TNM JSON and was handed to urlretrieve unchecked, so
    an `http://` would have been honoured as a silent TLS downgrade and `file://` would have COPIED A
    LOCAL FILE into laz/ and reported it as a downloaded tile (urlretrieve implements file:// itself).
    Neither README.md nor any legal/ document actually claims the transfer is https -- checked -- so
    this is not a documented-claim failure; it is the one URL in the project that is not https by
    construction, and 78 tiles of public-domain elevation is not worth an unauthenticated channel.

    A refusal, not a retry: a scheme is not a transient, and it names the offending URL so the
    operator can see what the service answered. Nothing may be staged first -- a .part left behind
    would sit in laz/ looking like a tile.
    """
    for name in ("fetch_lidar", "fetch_lidar_alameda"):
        mod = _fetcher(name)
        for scheme in ("http", "ftp", "file"):
            rec = _Recorder(_tile_body())
            d = tmp_path / f"{name}_{scheme}"
            d.mkdir()
            host = ("rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
                    "CA_AlamedaCounty_2021_B21")
            with pytest.raises(SystemExit) as e:
                if name == "fetch_lidar":
                    bad = f"{scheme}://{host}/CA_AlamedaCo_1_2021/LAZ/tile_a.laz"
                    _run_fetch_lidar_main(mod, monkeypatch, d, [bad], rec)
                else:
                    bad = (f"{scheme}://{host}/{mod.SUBS[0]}/LAZ/"
                           f"{mod.PREFIX}_{ALAMEDA_CELL}.laz")
                    _run_alameda_main(mod, monkeypatch, d, rec,
                                      base=f"{scheme}://{host}")
            msg = str(e.value)
            assert bad in msg, (
                f"{name}: a {scheme}:// tile URL was refused without naming it, so the operator "
                f"cannot see what the service answered: {msg!r}")
            assert scheme in msg, f"{name}: the refusal does not say what the scheme was: {msg!r}"
            left = sorted(p.name for p in (d / "laz").iterdir()) if (d / "laz").is_dir() else []
            assert not left, (
                f"{name}: refusing a {scheme}:// URL still left {left} in laz/ -- a staged file that "
                f"is not a tile")


# ---------------------------------------------------------------------------
# B-3 -- the refusal message must be formattable
# ---------------------------------------------------------------------------
def test_an_infinite_gps_time_gets_its_refusal_not_an_overflowerror(tmp_path, capsys):
    """The tool decided correctly and then crashed while explaining itself.

    gps_time is a float64 in the LAS point record, so +inf is storable and a corrupt tile can carry
    one -- laspy round-trips it, asserted below. tile_dates refuses such a tile (the value is
    isolated in time and outside the plausibility window), and then built its refusal message with
    `dating.cluster_mass(raw[1])`, which is `int(np.floor(inf / 3600))` -> OverflowError: cannot
    convert float infinity to integer. So the operator saw an unrelated traceback out of
    tools/lidar_dates.py:234 instead of the diagnosis, on a tool whose whole purpose is that the
    printed date is checkable.

    A non-finite value sits in no bucket at all: `add()` already drops it before it can be counted,
    so its cluster honestly weighs 0, and that is what cluster_mass now answers. The message also has
    to be able to print the raw endpoint, which gps_to_utc cannot turn into a datetime.

    The fixture is deliberately NOT named with "inf" anywhere in it. A prior version of this test
    wrote it to `inf.laz`, and the refusal line opens with `os.path.basename(path)` -- so `"inf" in
    out` passed from the FILENAME alone, whether or not `_stamp` could name the raw +inf value.
    Reverting just the `_stamp` half of the fix (degrading the message back to "...None") left that
    assertion passing. The two assertions below instead key on "no representable date", the exact
    phrase only `_stamp`'s fallback produces, and on "inf" appearing in a message whose file is named
    something else entirely -- so both can only be satisfied by the message itself, not the filename.
    """
    ld = _lidar_dates()
    import datetime as dt
    import laspy
    import numpy as np

    assert ld._Extremes().cluster_mass(float("inf")) == 0, (
        "cluster_mass(+inf) must answer 0 -- add() drops a non-finite value, so nothing is counted "
        "in its bucket -- rather than raising OverflowError out of the refusal message")
    assert ld._Extremes().cluster_mass(float("-inf")) == 0
    assert ld._Extremes().cluster_mass(float("nan")) == 0

    # a real Alameda-2021 acquisition second, plus one +inf
    inst = dt.datetime(2021, 6, 21, 18, 0, 0, tzinfo=dt.timezone.utc)
    clean = (inst - ld.GPS_EPOCH).total_seconds() + ld.LEAP_SECONDS - 1_000_000_000
    n = 1200                              # a pass-like crowd, over MIN_ENDPOINT_CLUSTER_PTS
    h = laspy.LasHeader(version="1.4", point_format=6)
    h.global_encoding.gps_time_type = 1
    las = laspy.LasData(h)
    las.x = np.zeros(n + 1); las.y = np.zeros(n + 1); las.z = np.zeros(n + 1)
    las.gps_time = np.concatenate([clean + np.arange(n) * 0.01, [np.inf]])
    p = tmp_path / "corrupt_endpoint.laz"       # NOT "inf.laz" -- see the docstring above
    las.write(str(p))
    with laspy.open(str(p)) as f:
        assert np.isinf(np.asarray(f.read().gps_time)).any(), \
            "the fixture did not store +inf, so this test would prove nothing"

    capsys.readouterr()
    got = ld.tile_dates(str(p))           # raised OverflowError before the fix
    out = capsys.readouterr().out
    assert got is None, f"a tile carrying +inf must be refused, not dated: {got!r}"
    assert "cannot be defended" in out, (
        f"the refusal printed no explanation, which is the whole point of refusing out loud:\n{out}")
    assert "no representable date" in out, (
        f"the message does not say the refused endpoint has no representable date -- printing "
        f"'None' for it would hide which endpoint was junk and why it was refused:\n{out}")
    assert "inf" in out, (
        f"the message does not name the raw value it refused. The fixture's filename carries no "
        f"'inf' substring, so this can only be satisfied by _stamp printing the raw endpoint's own "
        f"repr, not by os.path.basename(path):\n{out}")


# ---------------------------------------------------------------------------
# B-4 -- the bucket-blowup figures are now derivable
# ---------------------------------------------------------------------------
def test_the_documented_bucket_blowup_figures_are_derived_not_typed():
    """MASS_BUCKETS' comment quotes what one junk gps_time used to allocate, and nothing graded it.

        1e11 -> 27,692,129 buckets (0.22 GB)     1e12 -> 2.2 GB     1e15 -> 2.2 TB

    Every one of those is a consequence of two facts and one constant: the junk magnitude, the base
    bucket the old code offset by, and MAX_ENDPOINT_GAP_S. So recompute all three here and require
    the comment to state them. The base bucket is parsed out of the comment rather than typed in, and
    cross-checked against the real Alameda-2021 adjusted second the comment names, so the figure
    cannot be a number somebody remembered.

    An audit read the 27,692,129 as being 7 buckets behind the live figure. It is not: 7 buckets is
    exactly 7 hours at MAX_ENDPOINT_GAP_S, which is the PDT-vs-UTC offset of the June flight the base
    second comes from -- a re-derivation from a LOCAL clock lands 7 buckets away. This test pins the
    arithmetic so the next reader does not have to re-run that.
    """
    ld = _lidar_dates()
    src = open(os.path.join(ROOT, "tools", "lidar_dates.py"), encoding="utf-8").read()
    m = re.search(r"bucket ([\d,]+) -- a real Alameda-2021 adjusted second, ([\d,]+)", src)
    assert m, ("the MASS_BUCKETS comment no longer says which base bucket its blow-up figures were "
               "measured from, so the figures below cannot be checked against anything")
    base_bucket = int(m.group(1).replace(",", ""))
    base_second = float(m.group(2).replace(",", ""))
    assert int(math.floor(base_second / ld.MAX_ENDPOINT_GAP_S)) == base_bucket, (
        f"the comment names base second {base_second:,.0f} and base bucket {base_bucket:,}, but at "
        f"MAX_ENDPOINT_GAP_S={ld.MAX_ENDPOINT_GAP_S:g} that second is bucket "
        f"{int(math.floor(base_second / ld.MAX_ENDPOINT_GAP_S)):,}")
    # ...and that second really does decode to the 2021 flight the comment claims.
    assert ld.gps_to_utc(base_second).year == 2021

    want = []
    for junk in (1e11, 1e12, 1e15):
        n = int(math.floor(junk / ld.MAX_ENDPOINT_GAP_S)) - base_bucket + 1
        want.append((junk, n, n * 8))
    n11, b11 = want[0][1], want[0][2]
    assert f"{n11:,}" in src, (
        f"the comment no longer states the {n11:,} buckets one junk gps_time of 1e11 used to size "
        f"the counter with")
    assert f"{b11 / 1e9:.2f} GB" in src, f"1e11 is {b11 / 1e9:.2f} GB of int64; the comment disagrees"
    assert f"{want[1][2] / 1e9:.1f} GB" in src, f"1e12 is {want[1][2] / 1e9:.1f} GB of int64"
    assert f"{want[2][2] / 1e12:.1f} TB" in src, f"1e15 is {want[2][2] / 1e12:.1f} TB of int64"
    # and the ceiling that replaced them is still a constant, not a function of the data
    assert ld.MASS_BUCKETS == ld.MASS_BUCKET_HI - ld.MASS_BUCKET_LO + 1
    assert f"{ld.MASS_BUCKETS:,} buckets" in src and f"{ld.MASS_BUCKETS * 8 / 1e6:.1f} MB" in src, (
        f"the comment's ceiling does not match the module's own {ld.MASS_BUCKETS:,} buckets = "
        f"{ld.MASS_BUCKETS * 8 / 1e6:.1f} MB")
