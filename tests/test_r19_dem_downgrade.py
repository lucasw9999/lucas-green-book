#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
`fetch_dem.py` could replace a GOOD green surface with a BLANK one, with no flag and no receipt.

THE THIRD DIRECTION. Two of them were already guarded, and each guard is a `keeps_existing_surface`:
fetch_dem's stops this stage swapping a good 0.4 m LiDAR green for the coarse seamless mosaic, and
fetch_dem_hd's stops that stage swapping a working seamless fill for a refused 0.4 m attempt. The
comment above the second one says "Only one direction was guarded", and it was true one level further
down than it looked -- a third trade was open, inside THIS stage alone:

  * `insufficient` was computed by the honesty gate and then only RECORDED in the meta. It never gated
    the commit, and `commit_surface` ran regardless.
  * So a plain `COURSE=<slug> python3 fetch_dem.py` -- no ONLY=, no OVERWRITE= -- re-fetched every
    green this stage owns, and if 3DEP answered WORSE than last time the good pair was replaced by one
    carrying insufficient=True. `render_green.render` returns `_blank_green` for exactly that key, so a
    card that printed a real read printed blank.
  * The retry loop cannot see it: it retries on EXCEPTIONS, and a worse answer is a 200 response
    carrying a perfectly valid GeoTIFF. Out of coverage the service returns a CONSTANT raster rather
    than any NoData marker, which is the reply built below.
  * `keeps_existing_surface` cannot be that guard either, and must not become it: it returns False for
    a seamless meta ON PURPOSE, because re-filling this stage's own greens is the job. The predicate
    the third direction needs is a different question asked at a different moment -- see
    `fetch_dem.keeps_readable_surface`.

Six greens were exposed on disk when this was found (one bayside course's holes 1, 9, 10, 16, 17 and
18: seamless-sourced, readable, insufficient=False), and `courses/` is gitignored, so the run's own
output would have been the only record of what was lost.

The end-to-end tests here drive `fetch_dem.main()` against a synthetic one-hole course under
`tmp_path` with a stubbed reply, so they measure the WRITE DECISION rather than files written days ago
-- an artifact assertion cannot fail until after the data is already gone.
"""
import io
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# A GOOD surface, as this stage itself records one. Both fields matter: `source` is what every reader
# in the engine tests, and `insufficient` is what render_green blanks on.
GOOD_SEAMLESS = "USGS 3DEP seamless mosaic, 2.72 m E-W x 3.43 m N-S source cell @0.5m sampling"
GOOD_LIDAR = "USGS 3DEP LiDAR ground returns @0.4m"


def _code_only(src):
    """`src` with comments and string literals removed, so a source assertion cannot read prose.

    A LOCAL COPY ON PURPOSE, and the duplication is the lesser evil twice over: importing another test
    module would execute its whole body and make this file's answers a re-statement of that one's, and
    `_sys_modules_pop_names` already lives in two test modules here for the same reason. The helper it
    mirrors records why it must exist at all -- this codebase writes long comments that quote the very
    names its guards check for, and a grep-based version of the assertion below was satisfied by a
    comment in fetch_dem.py naming `keeps_existing_surface` while the live call was replaced by
    `if False:`.

    Raises rather than falling back to the raw source: a silent fallback in a helper whose whole job is
    to strip prose would hand the caller prose to assert on, which is the fault it exists to prevent.
    """
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        raise AssertionError(
            "_code_only() was handed source that does not tokenise, so the caller's assertion would be "
            f"checking prose. First 60 chars: {src[:60]!r}")
    return " ".join(out)


def _fetch_dem():
    """fetch_dem, imported against whatever course conftest bound. Its COURSE_DIR is never written.

    Every test below repoints `DIR` and `OUT` at tmp_path, so the bound course supplies nothing but an
    importable config. conftest's `_bind_a_course` drops this module in teardown, so each test re-reads
    the environment; nothing here pops sys.modules itself, because that count is published in README
    and re-derived across tests/*.py.
    """
    import fetch_dem
    return fetch_dem


def _one_hole_course(tmp_path):
    """A synthetic course under tmp_path: one green, one hole line reaching it. Returns (dir, ring)."""
    d = tmp_path / "course"
    (d / "dem_hd").mkdir(parents=True)
    clat, clon = 37.7000, -121.5000
    dla, dlo = 15 / 111_000.0, 15 / 88_000.0          # a green about 30 m across
    ring = [(clat - dla, clon - dlo), (clat - dla, clon + dlo),
            (clat + dla, clon + dlo), (clat + dla, clon - dlo)]
    green = dict(type="way", id=901, tags={"golf": "green"},
                 geometry=[{"lat": la, "lon": lo} for la, lo in ring])
    hole = dict(type="way", id=801, tags={"golf": "hole", "ref": "1", "par": "4"},
                geometry=[{"lat": 37.6970, "lon": clon},
                          {"lat": 37.6985, "lon": clon},
                          {"lat": clat - dla, "lon": clon}])
    (d / "osm_geom.json").write_text(json.dumps({"elements": [hole, green]}), encoding="utf-8")
    return d, ring


def _plant(d, ring, source=GOOD_SEAMLESS, insufficient=False):
    """Commit a surface into the synthetic course's dem_hd/, through the real writer.

    Written with surface_io.commit_surface rather than by hand so the planted pair carries a real
    array digest and reads exactly like one this stage produced -- including to the reader that
    would blank it.
    """
    import surface_io
    H = W = 108
    arr = np.tile(np.linspace(30.0, 31.4, W), (H, 1))     # 1.4 m of fall: plainly not a zero-fill
    lats = [p[0] for p in ring]
    lons = [p[1] for p in ring]
    mla, mlo = 12 / 111_000.0, 12 / 88_000.0
    bbox = [min(lons) - mlo, min(lats) - mla, max(lons) + mlo, max(lats) + mla]
    surface_io.commit_surface(
        str(d / "dem_hd" / "hole01"), arr,
        dict(hole=1, approach_bearing=0.0, bbox=bbox, W=W, H=H, green_id=901,
             green_center=[sum(lats) / 4, sum(lons) / 4],
             polygon=[[la, lo] for la, lo in ring], source=source,
             nan_frac=0.0, insufficient=insufficient, density=None))


def _reply(url, values):
    """A 200 reply carrying a real, georeferenced GeoTIFF whose pixels are `values(W, H)`.

    Georeferenced deliberately: `_served_patch` refuses a raster with no transform, and a refusal is
    not the failure under test here. What is under test is a reply this stage ACCEPTS as a raster and
    then measures as unusable -- which is what out-of-coverage ground looks like.
    """
    import urllib.parse

    import rasterio
    from rasterio.transform import from_bounds
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    xmin, ymin, xmax, ymax = [float(v) for v in q["bbox"][0].split(",")]
    W, H = [int(v) for v in q["size"][0].split(",")]
    buf = io.BytesIO()
    with rasterio.io.MemoryFile() as mem:
        with mem.open(driver="GTiff", width=W, height=H, count=1, dtype="float32", crs="EPSG:4326",
                      transform=from_bounds(xmin, ymin, xmax, ymax, W, H)) as ds:
            ds.write(values(W, H), 1)
        buf.write(mem.read())
    return buf.getvalue()


def _constant(W, H):
    """Out of coverage, 3DEP answers with a CONSTANT raster -- measured at St Andrews, min 0.0, max
    0.0, one unique value -- rather than with any NoData marker."""
    return np.zeros((H, W), dtype="float32")


def _sloping(W, H):
    """A usable green: 3 m of fall across the patch, so the honesty gate passes it."""
    return (np.tile(np.linspace(0.0, 3.0, W), (H, 1))
            + np.tile(np.linspace(0.0, 0.4, H), (W, 1)).T).astype("float32")


def _run(monkeypatch, fd, d, values):
    """Drive fetch_dem.main() over the synthetic course with a stubbed reply. No network, no corpus."""
    monkeypatch.setattr(fd, "DIR", str(d))
    monkeypatch.setattr(fd, "OUT", str(d / "dem_hd"))
    monkeypatch.setattr(fd, "OVERWRITE", False)          # the plain, no-flag run
    monkeypatch.delenv("ONLY", raising=False)

    class _R:
        def __init__(self, raw):
            self._raw = raw

        def read(self):
            return self._raw

    monkeypatch.setattr(fd.urllib.request, "urlopen",
                        lambda req, timeout=None: _R(_reply(req.full_url, values)))
    fd.main()


def _meta(d):
    p = d / "dem_hd" / "hole01.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_a_worse_seamless_reply_cannot_blank_a_green_that_already_reads(tmp_path, monkeypatch, capsys):
    """THE FAULT. A good surface, a worse answer, no flag set -- and the card must not go blank.

    Reproduced on a copy of the affected course before the fix: one no-flag run turned a
    seamless-sourced, insufficient=False green into insufficient=True, which `render_green.render`
    answers with `_blank_green`. Nothing printed the name of the surface it discarded, and `courses/`
    has no other copy of it.
    """
    fd = _fetch_dem()
    d, ring = _one_hole_course(tmp_path)
    _plant(d, ring)
    before = _meta(d)
    assert before["insufficient"] is False, "the planted surface must start out GOOD, or this proves nothing"

    _run(monkeypatch, fd, d, _constant)
    after = _meta(d)

    assert after["insufficient"] is False and after["source"] == before["source"], (
        "a refused seamless reply replaced a green that already read, so that card now prints blank "
        f"(source {after['source']!r}, insufficient={after['insufficient']!r}). No OVERWRITE was set.")
    assert after["array_sha256"] == before["array_sha256"], (
        "the meta survived but the ARRAY was rewritten, so the surface a card measures is the refused "
        "one -- the pair is what has to be kept, not the sidecar")
    out = capsys.readouterr().out
    assert "KEEPING the existing surface" in out and "OVERWRITE=1" in out, (
        "the refusal has to say so on its way past: the discarded surface has no other copy, so a run "
        f"that silently keeps or silently replaces are the same output. Got:\n{out}")


def test_the_downgrade_guard_still_lets_the_seamless_stage_fill_a_gap(tmp_path, monkeypatch):
    """WHAT IT MUST STILL PERMIT (1): a gap gets filled even when the reply is refused.

    This stage exists to fill gaps, so an empty dem_hd/ must be written whatever the reply measures --
    a refused surface recorded AS refused is the honest outcome there, and it is what makes the card
    print blank rather than a read of nothing. A guard that read "keep whatever exists" would look
    correct and would quietly turn this stage off.
    """
    fd = _fetch_dem()
    d, _ring = _one_hole_course(tmp_path)
    assert _meta(d) is None
    _run(monkeypatch, fd, d, _constant)
    got = _meta(d)
    assert got is not None and got["insufficient"] is True, (
        "the gap-fill stage wrote nothing into an EMPTY dem_hd/, so the guard is refusing the case this "
        f"stage exists for: {got!r}")


def test_the_downgrade_guard_still_lets_a_good_reply_replace_a_good_surface(tmp_path, monkeypatch):
    """WHAT IT MUST STILL PERMIT (2): a good surface replaced by a different GOOD one.

    Only a REFUSED reply is a downgrade. Re-fetching a seamless green that is already fine -- after a
    green is re-traced in OSM, or the service improves its coverage -- has to keep working, which is
    also why `keeps_existing_surface` above it returns False for a seamless meta.
    """
    fd = _fetch_dem()
    d, ring = _one_hole_course(tmp_path)
    _plant(d, ring)
    before = _meta(d)
    _run(monkeypatch, fd, d, _sloping)
    after = _meta(d)
    assert after["insufficient"] is False, "a good reply must not be recorded as a refusal"
    assert after["array_sha256"] != before["array_sha256"], (
        "a GOOD seamless reply did not replace the surface on disk, so the guard has stopped this "
        "stage refreshing its own greens -- that is a wall, not a safety net")


def test_a_record_already_marked_insufficient_is_rebuilt_rather_than_protected(tmp_path, monkeypatch):
    """WHAT IT MUST STILL PERMIT (3): a refusal already on disk IS the gap; re-fetching it is the repair.

    The same reading of `insufficient` both `keeps_existing_surface` predicates make. Protecting a
    refusal would freeze a green that a later flight or a wider mosaic could fix.
    """
    fd = _fetch_dem()
    d, ring = _one_hole_course(tmp_path)
    _plant(d, ring, insufficient=True)
    before = _meta(d)
    _run(monkeypatch, fd, d, _sloping)
    after = _meta(d)
    assert after["array_sha256"] != before["array_sha256"] and after["insufficient"] is False, (
        "a surface already marked insufficient was protected from a GOOD reply, so a green that could "
        "now be read stays blank forever")


def test_keeps_readable_surface_truth_table(tmp_path):
    """The predicate itself, by TRUTH TABLE, in the shape its mirror in fetch_dem_hd.py is graded in.

    A predicate rather than an inline boolean for exactly this reason: `main()` cannot be exercised
    without a course and a reply, and the two assertions that once stood in for the sibling's guard
    were greps over module source that BOTH matched outside the guard -- deleting the whole thing left
    them green.

    The row that separates this predicate from `keeps_existing_surface` in the same file is the
    SEAMLESS one: that predicate answers False there on purpose (this stage re-fills its own greens),
    and this one must answer True, because a working seamless read beats a blank green.
    """
    fd = _fetch_dem()

    def keeps(rec, overwrite=False):
        if rec is None:
            return fd.keeps_readable_surface(str(tmp_path / "absent.json"), overwrite)
        p = tmp_path / "prev.json"
        p.write_text(rec if isinstance(rec, str) else json.dumps(rec), encoding="utf-8")
        return fd.keeps_readable_surface(str(p), overwrite)

    seamless = {"source": GOOD_SEAMLESS, "insufficient": False}
    lidar = {"source": GOOD_LIDAR, "insufficient": False}
    cases = [
        (seamless, False, True,
         "a working seamless read -- the six exposed greens, and the case keeps_existing_surface "
         "must go on answering False for"),
        (lidar, False, True,
         "a good 0.4 m LiDAR surface: this stage should have skipped it earlier, and under OVERWRITE "
         "it reaches here, where a refused reply is still a downgrade"),
        ({**seamless, "insufficient": True}, False, False,
         "a record that was ALREADY a refusal is the gap this stage fills; rebuilding it is the repair"),
        ({"insufficient": False}, False, False,
         "no source field at all: unknown provenance, so leave it fillable rather than protect it on a "
         "guess -- the same rule both keeps_existing_surface predicates keep"),
        ({"source": "   ", "insufficient": False}, False, False,
         "a blank source is not a positive source"),
        ("{not json", False, False, "an unreadable file must be rebuilt, not protected"),
        (None, False, False, "nothing on disk yet: the gap-fill case"),
        (seamless, True, False,
         "OVERWRITE=1 must still be able to do it on purpose, or the guard is a wall rather than a "
         "safety net"),
    ]
    for rec, ow, want, why in cases:
        got = keeps(rec, ow)
        assert got is want, (
            f"fetch_dem.keeps_readable_surface returned {got}, expected {want}: {why}")


def test_fetch_dem_main_still_calls_the_downgrade_guard():
    """A guard nothing calls is decoration -- the sibling has this test for the same reason.

    Checked as CODE, not as text: this module's comments name both predicates repeatedly, so a grep
    would pass with the live call deleted. That is not hypothetical here -- it is recorded as having
    happened to the assertion covering `keeps_existing_surface` in this very file.
    """
    with open(os.path.join(ROOT, "fetch_dem.py"), encoding="utf-8") as f:
        src = f.read()
    # keep "def main(" attached so the fragment tokenises on its own
    body = "def main(" + src.split("def main(", 1)[1]
    code = _code_only(body)
    assert "keeps_readable_surface" in code, (
        "fetch_dem.main() no longer calls keeps_readable_surface, so a worse 3DEP reply can overwrite "
        "a green that already reads and blank its card again")
    assert "keeps_existing_surface" in code, (
        "fetch_dem.main() no longer calls keeps_existing_surface either -- the gap-fill skip that keeps "
        "0.4 m LiDAR greens off the coarse mosaic is gone")


def test_the_two_surface_stages_answer_the_downgrade_question_the_same_way():
    """ONE IDIOM for "do not replace a good surface with a worse one", so the two cannot drift apart.

    fetch_dem.keeps_readable_surface and fetch_dem_hd.keeps_existing_surface are the same rule seen
    from the two producers of dem_hd/: any positively-sourced record that is not itself a refusal is
    worth more than a blank green, whatever built it. They are separate functions because each module
    is standalone -- fetch_dem must not import laspy, pyproj and scipy to answer a question about a
    JSON file -- so the thing that keeps them one rule is this test.

    Graded by BEHAVIOUR over a shared truth table rather than by comparing source text: the two are
    written in the same shape today, and a reformatting of either must not fail while a changed
    ANSWER must.
    """
    import fetch_dem_hd
    fd = _fetch_dem()
    rows = [
        {"source": GOOD_SEAMLESS, "insufficient": False},
        {"source": GOOD_LIDAR, "insufficient": False},
        {"source": GOOD_LIDAR, "insufficient": True},
        {"insufficient": False},
        {"source": "", "insufficient": False},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "prev.json")
        for rec in rows:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            mine = fd.keeps_readable_surface(p)
            theirs = fetch_dem_hd.keeps_existing_surface(p)
            assert mine is theirs, (
                f"the two stages disagree about {rec!r}: fetch_dem says {mine}, fetch_dem_hd says "
                f"{theirs}. One of them will trade a surface the other would have kept, and the loss "
                f"has no other copy.")
        missing = os.path.join(td, "absent.json")
        assert fd.keeps_readable_surface(missing) is fetch_dem_hd.keeps_existing_surface(missing) is False


if __name__ == "__main__":     # pragma: no cover - pytest is the entry point
    raise SystemExit(pytest.main([__file__, "-q"]))
