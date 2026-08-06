#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Two more static-analyzer findings, one fixed and one deliberately left alone.

L-2 (tools/check_scale.py:45, ruff F401 -- `import glob` unused): deleted. Every `.glob(` call
left in that file is a pathlib.Path method (`(ROOT / ...).glob("hole*.json")`), not the glob
module's own function, confirmed by an AST walk that found exactly one `Import` node naming
`glob` and zero `Name` nodes referring to a bare `glob` anywhere in the file -- not inside a
nested function, not inside an f-string. The import carried no side effect either: nothing else
in the module's import chain (json, os, pathlib, re, statistics, sys, export_pdf, geo, and the
function-local config/distribution imports inside main()) re-exports `glob` into check_scale's own
namespace, so there is nothing for the deletion to have silently depended on.

Because a genuinely unused import's removal changes no runtime behaviour by definition, there is
no red-then-green to show here. What CAN regress is the pathlib-based globbing this import was
easy to mistake for, so that is what the tests below actually exercise.

L-1 (geo.py:139, vulture -- `utm_epsg(lon)` has zero callers anywhere in the repo, including the
test suite): NOT deleted. `git log -S'utm_epsg' --oneline` returns exactly one commit,
d2b0d1073e259f9cf201d1fc15414fca0bcb58da ("Fix two latent data bugs: vertical units by guesswork,
LiDAR chosen by date") -- the commit that ADDED the function, not one that removed a caller. Its
message frames geo.py as the single shared home for "the same two facts ... previously derived
independently in fetch_dem_hd.py and fetch_trees.py": vertical units, and the UTM zone. That same
diff wired BOTH files to the new `geo.vertical_scale()` for the first fact, but never finished the
second -- fetch_dem_hd.py and fetch_trees.py each kept their own hand-copied
`UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)` instead of calling `geo.utm_epsg(lon)`,
and both still do today (fetch_dem_hd.py:142, fetch_trees.py:46, byte-identical). Commit
777157168ae70e59d77645616bce2c81744d06de ("Cap the hole-to-green binding, and stop fetch_dem_hd
guessing a zone or a Z unit") later touched the three lines around fetch_dem_hd.py's copy --
removing a silent longitude default of -121.0 -- but that diff (`git show 7771571 --
fetch_dem_hd.py`) shows the zone FORMULA itself untouched; it did not migrate the call either.

So this is DROPPED_USE, not harmless dead weight: geo.utm_epsg is exactly the kind of shared
function this module's own top-of-file note says nine OTHER re-declared constants cost two audits
to catch, just never finished for this one fact. Fixing it means editing fetch_dem_hd.py and
fetch_trees.py to call geo.utm_epsg(lon), which is outside this round's owned files (geo.py,
tools/check_scale.py) -- reported here, not fixed.

The tests below for L-1 are tripwires against exactly the divergence the finding describes, not a
red-then-green proof of a change -- none was made to geo.py for this finding.
"""
import ast
import os
import pathlib
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import geo  # noqa: E402


# =================================================================================================
# L-2 -- tools/check_scale.py:45, `import glob` (ruff F401), deleted.
# =================================================================================================

def _load_check_scale():
    """Import tools/check_scale.py fresh. tools/ is not a package, so this mirrors what the
    sys.path.insert above already does for the repo root: add tools/ to sys.path and import the
    bare module name, re-importing so a previous test's monkeypatched ROOT never leaks forward.
    """
    tools_dir = os.path.join(ROOT, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    sys.modules.pop("check_scale", None)
    import check_scale
    return check_scale


def test_check_scale_source_has_no_unused_glob_import():
    """AST-level structural guard, not a behavioural discriminator.

    Deliberately stronger than the discouraged `"glob" not in src` string check this campaign has
    caught being vacuous: it walks the parsed tree for an `Import` node naming `glob` (there must
    be none left) while still allowing every `.glob(` attribute access on a Path object, which is
    a `Name` node for whatever the Path expression is, never for a bare name `glob`. This proves
    the import is gone; it cannot prove behaviour is unchanged, because a dead import changes none
    by definition -- see test_check_scale_pathlib_glob_calls_still_work below for that half.
    """
    src = (pathlib.Path(ROOT) / "tools" / "check_scale.py").read_text()
    tree = ast.parse(src)
    bare_glob_imports = [n for n in ast.walk(tree)
                          if isinstance(n, ast.Import) and any(a.name == "glob" for a in n.names)]
    bare_glob_names = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "glob"]
    assert not bare_glob_imports, "tools/check_scale.py still imports the glob module (ruff F401)"
    assert not bare_glob_names, (
        "tools/check_scale.py references a bare name `glob` somewhere ruff's F401 message did not "
        "expect -- re-check by hand before deleting the import")


def test_check_scale_imports_cleanly_without_glob():
    """The module still loads end to end after the deletion (no ImportError, no NameError at
    import time). Structural, not behavioural: it proves nothing broke at import, not that the
    functions below still compute the right thing -- that is the next test.
    """
    cs = _load_check_scale()
    assert not hasattr(cs, "glob")


def test_check_scale_pathlib_glob_calls_still_work(tmp_path, monkeypatch):
    """Behavioural discriminator for L-2: every `.glob(` left in the file is a pathlib.Path
    method, not the deleted module-level name. Proven by actually calling the two functions that
    use it -- dem_hd_holes() and enlarged_courses() -- against a synthetic tree under tmp_path
    (never courses/) with check_scale.ROOT monkeypatched so nothing real is read or touched.
    """
    cs = _load_check_scale()
    monkeypatch.setattr(cs, "ROOT", tmp_path)

    dem_hd = tmp_path / "courses" / "synth-course" / "dem_hd"
    dem_hd.mkdir(parents=True)
    (dem_hd / "hole01.json").write_text("{}")
    (dem_hd / "hole09.json").write_text("{}")
    (dem_hd / "not_a_hole.json").write_text("{}")     # must NOT match hole(\d+)\.json

    assert cs.dem_hd_holes("synth-course") == {1, 9}

    coach_dir = tmp_path / "courses" / "synth-coach"
    coach_dir.mkdir(parents=True)
    (coach_dir / cs.ENLARGED_BOOK).write_text("<html></html>")
    scratch_dir = tmp_path / "courses" / "_scratch"   # enlarged_courses() filters "_"-prefixed
    scratch_dir.mkdir(parents=True)
    (scratch_dir / cs.ENLARGED_BOOK).write_text("<html></html>")

    assert cs.enlarged_courses(None) == ["synth-coach"]


# =================================================================================================
# L-1 -- geo.py:139, `utm_epsg(lon)`, zero callers anywhere in the repo (vulture). NOT deleted --
# see module docstring above for the DROPPED_USE evidence and the two commit shas.
# =================================================================================================

_DUPLICATED_ZONE_FORMULA = 'UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)'


@pytest.mark.parametrize("relpath", ["fetch_dem_hd.py", "fetch_trees.py"])
def test_utm_epsg_dropped_use_is_still_duplicated_verbatim_in_its_intended_callers(relpath):
    """Pins the exact hand-copied UTM-zone line in both files geo.py's own history names as the
    intended callers of geo.utm_epsg().

    This is a source match, and deliberately so -- unlike the discouraged `"utm_epsg" not in src`
    pattern, it is not standing in for a behavioural proof of a change (there is none to prove
    here: no edit was made to fix the dropped use). It is a tripwire: if this line's text ever
    changes in EITHER file, this fails and says exactly where to look, rather than the two copies
    silently drifting apart -- the specific failure mode geo.py's own module docstring exists to
    prevent, playing out for this one fact anyway.
    """
    src = (pathlib.Path(ROOT) / relpath).read_text()
    assert _DUPLICATED_ZONE_FORMULA in src, (
        f"{relpath} no longer hand-duplicates geo.utm_epsg()'s formula verbatim. If it now calls "
        f"geo.utm_epsg(lon) instead, the DROPPED_USE finding this file documents has been fixed "
        f"and geo.utm_epsg is safe to delete -- update this test and this file's module docstring "
        f"rather than leaving it to fail. If the formula changed by hand instead, that is the "
        f"exact silent-drift bug the finding warned about.")


@pytest.mark.parametrize("lon", [-179.9, -121.0, -122.4, -71.0, 0.0, 34.5, 179.9])
def test_utm_epsg_matches_the_duplicated_inline_formula_numerically(lon):
    """Cross-checks geo.utm_epsg(lon) against the SAME arithmetic the two duplicated copies use,
    evaluated independently here rather than by importing fetch_dem_hd.py/fetch_trees.py (both run
    course-bound code at import time that needs a real course.json to resolve). Paired with the
    verbatim source match above: that one catches the duplicate's TEXT changing, this one would
    additionally catch a change that kept the same textual shape but produced a different number
    (e.g. a stray off-by-one), which a text match alone cannot.
    """
    duplicated = "EPSG:%d" % (26900 + int((lon + 180) / 6) + 1)
    assert geo.utm_epsg(lon) == duplicated


def test_utm_epsg_matches_its_own_docstring_examples():
    """Sanity check on the function itself, since nothing else in the suite calls it -- that
    absence is the whole L-1 finding. Confirms it still computes what its own docstring claims:
    26910 for a California longitude (zone 10), 26919 for a Massachusetts one (zone 19).
    """
    assert geo.utm_epsg(-121.0) == "EPSG:26910"
    assert geo.utm_epsg(-71.0) == "EPSG:26919"
