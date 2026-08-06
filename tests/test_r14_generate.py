#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
generate.py: the two books it writes, and the two claims it prints.

Three things this file holds the line on, all of them about the LAST step of a build -- the step after
which every other gate in the pipeline starts calling the artifact correct:

  * the books are STAGED and renamed, like every other artifact under courses/<slug>/. They were the
    only two written in place, and `with open(out, "w") as f: f.write(doc(...))` truncates the previous
    good book before doc() has even been called.
  * the yardage card claims a rebuild only where that course's own record states one. The year was
    hardcoded, and it is latent only because exactly one course is built in yardage mode today.
  * the printed refusal reason and distribution.py's reason for the same refusal cannot drift.

EVERY BUILD IN THIS FILE WRITES TO tmp_path. courses/ is gitignored -- no copy in history, none on a
remote -- so the destination is redirected to a throwaway directory and the real books are only ever
READ. See _run_build().
"""
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import distribution  # noqa: E402  (after the sys.path insert above)

GEN_PY = os.path.join(ROOT, "generate.py")


# ---------------------------------------------------------------------------
# course selection -- read-only, and skips rather than fails on a fresh clone
# ---------------------------------------------------------------------------
def _record(slug):
    with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _slug_where(pred, what):
    for slug in distribution.course_slugs(ROOT):
        try:
            if pred(slug):
                return slug
        except (OSError, ValueError):
            continue
    pytest.skip(f"per-course data is gitignored; no course here {what}")


def _yardage_slug():
    """The cheapest real course to build: yardage mode renders no greens and no hole layouts."""
    return _slug_where(lambda s: distribution.is_yardage(_record(s)), "is built in yardage mode")


def _coach_slug():
    """A course whose ENLARGED edition was actually built, so this suite knows the data supports one."""
    return _slug_where(
        lambda s: os.path.exists(os.path.join(ROOT, "courses", s, "greenbook_coach.html")),
        "has an enlarged edition")


# ---------------------------------------------------------------------------
# a build whose destination is a throwaway directory
# ---------------------------------------------------------------------------
# generate binds config, DISTRIBUTABLE and HOLE_ELEV at IMPORT time, so a build runs in its own
# interpreter: that is also what keeps a course-bound generate out of this session's sys.modules for
# the tests that follow. COURSE_DIR is rebound to `dest` before main() runs -- reads still come from
# the real (read-only) course, and the only thing written is the book, into tmp_path.
#
# `fail_after` characters are accepted by the book's destination and then it raises ENOSPC. 0 is the
# window where the old writer had truncated the previous book without doc() having been called at all;
# 2000 is a torn write part-way through the 4.24-6.80 MB a real book takes.
_BUILD = r'''
import builtins, os, sys
root, dest, slug, edition, fail_after = sys.argv[1:6]
sys.path.insert(0, root)
os.environ["COURSE"] = slug
import generate
generate.COURSE_DIR = dest

_real_open = builtins.open
_n = int(fail_after)


class _FullDisk:
    def __init__(self, fh):
        self.fh = fh

    def write(self, s):
        if _n:
            self.fh.write(s[:_n])
            self.fh.flush()
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.fh.close()
        return False


def _open(file, mode="r", *a, **k):
    if "w" in mode and "greenbook" in os.path.basename(str(file)):
        sys.stderr.write("THE-WRITE-THAT-FAILS %s\n" % file)
        return _FullDisk(_real_open(file, mode, *a, **k))
    return _real_open(file, mode, *a, **k)


if _n >= 0:
    builtins.open = _open
if edition == "pocket":
    generate.main()
else:
    generate.build_coach("")
'''


def _run_build(dest, slug, edition, fail_after):
    """Build one edition of `slug` into `dest`. fail_after < 0 means "let it succeed"."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("COACH", None)
    return subprocess.run(
        [sys.executable, "-c", _BUILD, ROOT, str(dest), slug, edition, str(fail_after)],
        capture_output=True, text=True, env=env, cwd=str(dest))


def _previous_book(dest, name):
    """A throwaway `dest` holding a stand-in for the last good book, and its bytes."""
    keep = ("<!DOCTYPE html><html><!-- the previous good book: 12 of these are the only copy -->"
            + "<div class='sheet'>." * 4000 + "</html>\n")
    p = os.path.join(str(dest), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(keep)
    return p, keep


# ---------------------------------------------------------------------------
# M-1: the two books were the only artifacts written under courses/ in place
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("edition,name", [("pocket", "greenbook.html"),
                                          ("coach", "greenbook_coach.html")])
@pytest.mark.parametrize("fail_after", [0, 2000])
def test_an_interrupted_book_write_leaves_the_previous_book_intact(tmp_path, edition, name,
                                                                  fail_after):
    """An interrupted build must not destroy the book it was replacing -- and it did, both editions.

    `with open(out, "w", encoding="utf-8") as _f: _f.write(doc(...))` evaluates open() FIRST, so the
    previous greenbook.html was truncated to 0 bytes before doc() had been called, and then stayed
    incomplete for the whole 4.24-6.80 MB write. Measured here at both ends of that window: nothing
    written at all (fail_after=0) and a torn write part-way through (fail_after=2000).

    The reason this is worse than lost work is what happens NEXT. tools/export_pdf.py --check reports
    WRONG_SOURCE and prints "Re-run: python3 tools/export_pdf.py"; Chromium parses truncated HTML
    happily and prints whatever sheets it got; write_stamp records the wreck's digest beside the short
    PDF; the next --check prints "all N PDF(s) match the HTML they were exported from". The sheets a
    torn write loses are the LAST ones -- the back cover, which is where the copyright, trademark and
    licence block lives. So a book missing its licence passes every gate in the pipeline.

    export_pdf.py argues exactly this for the PDF it prints FROM these files ("writing in place
    truncates a good book first: interrupt it and the printable artifact is gone") and stages for it.
    """
    slug = _yardage_slug() if edition == "pocket" else _coach_slug()
    dest = tmp_path / "throwaway-course"
    dest.mkdir()
    book, keep = _previous_book(dest, name)

    p = _run_build(dest, slug, edition, fail_after)
    assert p.returncode != 0 and "No space left on device" in p.stderr, (
        f"the build was supposed to die in the book write and did not:\n{p.stdout}\n{p.stderr}")

    with open(book, encoding="utf-8") as fh:
        after = fh.read()
    assert after == keep, (
        f"an interrupted {edition} build destroyed the book it was replacing: {len(keep)} bytes "
        f"became {len(after)}. courses/ is gitignored -- there is no other copy of it anywhere -- and "
        f"the rest of the pipeline then certifies the wreck as correct.")
    assert sorted(os.listdir(str(dest))) == [name], (
        f"a failed {edition} build left litter in the course directory: {sorted(os.listdir(str(dest)))}. "
        f"courses/<slug>/ is the one directory nothing sweeps.")


def test_a_failed_book_write_sweeps_up_its_own_stage(tmp_path, monkeypatch):
    """generate.write_book: the stage takes the wreck, the previous book is untouched, no litter stays.

    The same three properties the other eight staged writers under courses/ are held to
    (test_no_staged_write_leaves_its_part_file_behind, whose census lists eight staged writers and does
    NOT include these two books) -- driven directly here rather than through a whole build:

      * a payload that cannot be written at all never opens the destination;
      * a write that dies part-way leaves the wreck in the STAGE, not in the book;
      * the stage is DOT-PREFIXED, so the suite's `courses/*/*` snapshot and export_pdf's own sweep
        read it as a stage rather than as course data nothing has ever seen;
      * and a successful write still lands the book with nothing left beside it.
    """
    import builtins

    gen = _fresh_generate(_yardage_slug())
    try:
        assert hasattr(gen, "write_book"), (
            "generate.py has no staged book writer. Both books are written with a bare "
            "`open(out, \"w\")`, which truncates the previous good book before the document it is "
            "replacing it with has even been rendered.")
        book, keep = _previous_book(tmp_path, "greenbook.html")

        # (1) a payload that cannot be written at all: nothing is opened, nothing is staged
        with pytest.raises(TypeError):
            gen.write_book(book, 1234)
        assert open(book, encoding="utf-8").read() == keep, \
            "a book write that could not even start destroyed the previous book"
        assert sorted(os.listdir(str(tmp_path))) == ["greenbook.html"], \
            f"litter after a payload that never wrote: {sorted(os.listdir(str(tmp_path)))}"

        # (2) a write that dies part-way through -- the ENOSPC case, on the file the book lands in
        real_open = builtins.open
        staged = []

        class _FullDisk:
            def __init__(self, fh):
                self.fh = fh

            def write(self, s):
                self.fh.write(s[:2000])
                self.fh.flush()
                raise OSError(28, "No space left on device")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.fh.close()
                return False

        def flaky(file, mode="r", *a, **k):
            if "w" in mode and "greenbook" in os.path.basename(str(file)):
                staged.append(os.path.basename(str(file)))
                return _FullDisk(real_open(file, mode, *a, **k))
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr(builtins, "open", flaky)
        with pytest.raises(OSError):
            gen.write_book(book, "<html>" + "y" * 100000 + "</html>")
        monkeypatch.undo()

        assert open(book, encoding="utf-8").read() == keep, \
            "a torn book write landed in the book itself instead of in its stage"
        assert staged == [".greenbook.html.part"], (
            f"the book was not written to a dot-prefixed stage beside itself: {staged}. Dot-prefixed "
            f"is the convention export_pdf.staged_pdf and surface_io.staged_names state: the suite's "
            f"`courses/*/*` snapshot exempts a leading dot, so `greenbook.html.part` would read as "
            f"course data nothing has ever seen.")
        assert sorted(os.listdir(str(tmp_path))) == ["greenbook.html"], (
            f"a torn book write left its stage behind: {sorted(os.listdir(str(tmp_path)))}. A stray "
            f"stage under courses/<slug>/ is indistinguishable from an interrupted build, and nothing "
            f"sweeps that directory.")

        # (3) ...and a successful write still lands the book, with nothing staged beside it
        gen.write_book(book, "<html>the new book</html>")
        assert open(book, encoding="utf-8").read() == "<html>the new book</html>"
        assert sorted(os.listdir(str(tmp_path))) == ["greenbook.html"], \
            f"a successful book write left a stage behind: {sorted(os.listdir(str(tmp_path)))}"
    finally:
        _drop_generate()


def test_neither_edition_is_written_into_the_course_directory_in_place():
    """No writer in generate.py may open a book destination for writing directly.

    The behavioural tests above prove the two known writers stage; this one is the census, so a THIRD
    output added later cannot quietly go back to writing in place. It is also the assertion that
    belongs in test_no_staged_write_leaves_its_part_file_behind's census -- that docstring enumerates
    eight staged writers under courses/ and these two books are not among them.
    """
    with open(GEN_PY, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()

    bodies = {}
    starts = [(i, m.group(1)) for i, ln in enumerate(lines)
              for m in [re.match(r"def (\w+)\(", ln)] if m]
    for k, (i, name) in enumerate(starts):
        bodies[name] = (i, starts[k + 1][0] if k + 1 < len(starts) else len(lines))
    assert "write_book" in bodies, "generate.py has no staged book writer"

    lo, hi = bodies["write_book"]
    writes = [(i + 1, ln.strip()) for i, ln in enumerate(lines)
              if re.search(r"""\bopen\([^)]*['"][wa]""", ln) and not lo <= i < hi]
    assert writes == [], (
        "generate.py opens a file for writing outside write_book(), so an interrupted build can "
        f"destroy what it was replacing: {writes}")

    body = "\n".join(lines[lo:hi])
    assert 'f".{os.path.basename(out)}.part"' in body and "os.replace(tmp, out)" in body, (
        "write_book() no longer stages a DOT-PREFIXED .part and renames it into place:\n" + body)
    assert "finally:" in body and "os.remove(tmp)" in body, \
        "write_book() no longer sweeps its stage on the failure path:\n" + body
    for writer in ("main", "build_coach"):
        w_lo, w_hi = bodies[writer]
        assert any("write_book(" in ln for ln in lines[w_lo:w_hi]), \
            f"{writer}() does not write its book through write_book()"


# ---------------------------------------------------------------------------
# generate, imported bound to ONE course (it reads COURSE at import time)
# ---------------------------------------------------------------------------
_SAVED_COURSE = []


def _fresh_generate(slug):
    _SAVED_COURSE.append(os.environ.get("COURSE"))
    os.environ["COURSE"] = slug
    for m in ("config", "render_hole", "render_green", "fetch_trees", "generate"):
        sys.modules.pop(m, None)
    import generate
    return generate


def _drop_generate():
    prev = _SAVED_COURSE.pop() if _SAVED_COURSE else None
    if prev is None:
        os.environ.pop("COURSE", None)
    else:
        os.environ["COURSE"] = prev
    for m in ("config", "render_hole", "render_green", "fetch_trees", "generate"):
        sys.modules.pop(m, None)


# ---------------------------------------------------------------------------
# M-2: the yardage card's rebuild claim
# ---------------------------------------------------------------------------
def test_the_yardage_card_claims_a_rebuild_only_where_the_course_record_states_one():
    """"This course was rebuilt in 2025 with new greens" was hardcoded into yardage_guide_panel().

    It prints on the shipped book of the one course built in yardage mode, where it is TRUE and where
    that course's own record states it -- and it would print, unchanged, on the next yardage-mode
    course, about a course nothing in the project says was rebuilt at all. Latent only because there is
    exactly one such course today (11 of 12 records carry no build_mode).

    The claim is gated on a fact read from that course's own record now. The wording for a course whose
    record DOES state a rebuild is unchanged to the byte: the sentence is quoted verbatim in
    legal/05_DISCLAIMER_TEXT.md, which is generated from what the books print, and the book and its PDF
    are already exported.
    """
    slug = _yardage_slug()
    gen = _fresh_generate(slug)
    try:
        stated = gen.yardage_guide_panel()
        year = str(gen._rebuild_year())
        assert re.search(r"[12]\d{3}", year), (
            f"{slug}'s own record states a rebuild year and generate.py cannot find it: {year!r}")
        assert f"rebuilt in\n      {year} with new greens" in stated, (
            f"the About text no longer names the rebuild year {year} that {slug}'s record states")
        assert f"rebuilt in {year})" in stated.replace("\n    ", " "), \
            "the no-arrows line no longer names the rebuild year"

        # The shipped book carries this card verbatim: that is the byte-identity this fix had to keep.
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if os.path.exists(book):
            with open(book, encoding="utf-8") as fh:
                html = fh.read()
            assert stated in html, (
                "the yardage guide card this build produces is no longer the one in the shipped book, "
                "so the book and the PDF beside it would have to be rebuilt -- and "
                "legal/05_DISCLAIMER_TEXT.md quotes this card's About text verbatim")

        # A SECOND yardage-mode course, whose record states no rebuild: no rebuild may be claimed.
        saved = dict(gen.config.COURSE)
        try:
            gen.config.COURSE.update({
                "name": "A Second Yardage Course",
                "_status": "AWAITING ELEVATION DATA -- no public LiDAR covers this site.",
                "dem_source": "PENDING: no public LiDAR or survey covers this site.",
                "sources": {"scorecard": "Official published scorecard",
                            "aerial": "USDA NAIP (public domain)",
                            "elevation": "NONE available (verified via USGS TNM)"},
            })
            gen.config.COURSE.pop("rebuilt", None)
            assert gen._rebuild_year() is None, \
                "generate.py found a rebuild year in a record that states none"
            bare = gen.yardage_guide_panel()
        finally:
            gen.config.COURSE.clear()
            gen.config.COURSE.update(saved)

        assert "rebuil" not in bare.lower(), (
            "a yardage-mode course whose own record states no rebuild still prints a rebuild claim on "
            "its guide card:\n  " + " ".join(
                s for s in re.split(r"(?<=[.)])\s+", re.sub(r"<[^>]+>", "", bare))
                if "rebuil" in s.lower()))
        # Everything before the copyright notice: the card's own claims, not the (c) year in the licence.
        claims = re.sub(r"<[^>]+>", "", bare).split("&copy;")[0]
        assert not re.search(r"\b(19|20)\d{2}\b", claims), \
            f"a year is printed on a card whose course record states no rebuild year: {claims[-300:]}"
        # ...and the reason the greens are blank, which IS what build_mode: yardage means, survives
        for supported in ("post-construction green-surface data", "blank\n      to mark your own read"):
            assert supported in bare, (
                f"the yardage card dropped {supported!r} -- the part of the sentence every "
                f"yardage-mode book supports")
        assert "{" not in re.sub(r"<[^>]+>", "", bare), \
            f"a literal brace reached the card, so a splice demoted an f-string: {bare[:400]}"
    finally:
        _drop_generate()


# ---------------------------------------------------------------------------
# M-3: two records, one reason
# ---------------------------------------------------------------------------
def test_the_printed_refusal_reason_cannot_drift_from_distribution_pys_own(monkeypatch):
    """The reason a book may not be shared is stated in two places and nothing tied them together.

    sharing_line() spells its own sentences; distribution.distribution_status() holds its own reason
    strings, and legal/03_PROVENANCE_BY_COURSE.md is generated from those. An earlier fix keyed the
    printed sentence on the right DATA fact (distribution.is_yardage), which is why the two verdicts
    agree -- but the two TEXTS could still drift into giving different reasons for the same verdict,
    which is the failure sharing_line()'s own docstring says it exists to end.

    So each printed refusal now names the claim distribution.py's reason for the same refusal has to
    carry, and a build stops rather than printing a reason the shared rule no longer gives.
    """
    slug = _yardage_slug()
    gen = _fresh_generate(slug)
    try:
        real = gen.DISTRIBUTABLE
        try:
            gen.DISTRIBUTABLE = False
            blank = gen.sharing_line()
            assert "its greens are blank for want of trustworthy survey data" in blank, \
                "the yardage refusal lost the reason legal/05 quotes verbatim"

            # (1) distribution.py stops claiming blank greens for a yardage course -> the build stops
            monkeypatch.setattr(
                gen.distribution, "distribution_status",
                lambda course: (False, "Personal", "built in yardage mode: personal-use only"))
            with pytest.raises(SystemExit) as e:
                gen.sharing_line()
            assert "blank greens" in str(e.value), (
                "the card claims the greens are blank while distribution.py's reason for the same "
                f"refusal no longer says so, and the build did not say which claim drifted: {e.value}")
            monkeypatch.undo()

            # (2) the same for the other refusal, the one that must NOT claim blank greens
            gen.config.COURSE["build_mode"] = "yardge"          # the typo, fails closed upstream
            typo = gen.sharing_line()
            assert "greens are blank" not in typo and "personal use only" in typo.lower(), \
                "the unrecognised-build_mode refusal states a reason its book contradicts"
            monkeypatch.setattr(
                gen.distribution, "distribution_status",
                lambda course: (False, "Personal", "this course is personal-use only"))
            with pytest.raises(SystemExit) as e2:
                gen.sharing_line()
            assert "build_mode" in str(e2.value), \
                f"the drift in the unrecognised-mode reason was not reported: {e2.value}"
            monkeypatch.undo()
        finally:
            gen.DISTRIBUTABLE = real
            if distribution.is_yardage(_record(slug)):
                gen.config.COURSE["build_mode"] = "yardage"
            else:
                gen.config.COURSE.pop("build_mode", None)
    finally:
        _drop_generate()
