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

L-1 (geo.py:139, vulture -- `utm_epsg(lon)` had zero callers anywhere in the repo, including the
test suite): NOT deleted, and since a5b981a NOT callerless either. `git log -S'utm_epsg' --oneline`
returned exactly one commit when the finding was written,
d2b0d1073e259f9cf201d1fc15414fca0bcb58da ("Fix two latent data bugs: vertical units by guesswork,
LiDAR chosen by date") -- the commit that ADDED the function, not one that removed a caller. Its
message frames geo.py as the single shared home for "the same two facts ... previously derived
independently in fetch_dem_hd.py and fetch_trees.py": vertical units, and the UTM zone. That same
diff wired BOTH files to the new `geo.vertical_scale()` for the first fact, but never finished the
second -- fetch_dem_hd.py and fetch_trees.py each kept their own hand-copied
`UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)` instead of calling `geo.utm_epsg(lon)`.
So it was DROPPED_USE rather than harmless dead weight: geo.utm_epsg is exactly the kind of shared
function this module's own top-of-file note says nine OTHER re-declared constants cost two audits
to catch, just never finished for this one fact.

THE MIGRATION IS FINISHED. a5b981a wired both files to `UTM = geo.utm_epsg(_LON)`, so the fact has
one home at last and the two hand-copies are gone. What the L-1 test below grades therefore flipped
with it: it used to be a tripwire pinning the duplicated line's exact text so the two copies could
not drift apart silently, and it now grades the property that replaced that hazard -- both modules
CALL geo.utm_epsg for the zone their surfaces and tree positions are built in, and neither spells
the zone arithmetic itself. That is the property worth protecting from here on; the duplication it
used to pin cannot come back without failing it.

And geo.utm_epsg is NOT safe to delete, which is what the retired tripwire's own failure message
said would follow from this migration. It said the opposite of what finishing the migration means:
the function now has two real callers, and vulture's original zero-caller reading is what stopped
being true.
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
# L-1 -- geo.py:139, `utm_epsg(lon)`. Zero callers when vulture flagged it (DROPPED_USE, not dead
# weight); two callers since a5b981a finished the migration d2b0d10 started. See the module
# docstring above.
# =================================================================================================

# The arithmetic itself, as the two callers used to spell it inline. Kept only to name what must NOT
# come back, and matched as the false-northing constant in EXECUTABLE code -- both files still quote
# the retired line in a comment, on purpose, and a whole-file substring match would read those
# quotations as the duplication they are recording the end of.
_ZONE_FALSE_NORTHING = 26900


@pytest.mark.parametrize("relpath", ["fetch_dem_hd.py", "fetch_trees.py"])
def test_both_intended_callers_get_their_utm_zone_from_geo_utm_epsg(relpath):
    """Both files geo.py's own history names as the intended callers of geo.utm_epsg() call it, and
    neither derives the zone itself.

    This REPLACES a tripwire that pinned the hand-copied line's exact text in both files. That was
    the right guard while the duplication existed -- it would have caught the two copies drifting
    apart, which is the failure mode geo.py's module docstring exists to prevent -- but a5b981a
    migrated both callers to `UTM = geo.utm_epsg(_LON)`, so pinning the copies became a guard for a
    hazard that no longer exists. Inverted rather than deleted: the duplication cannot return without
    failing this, and the migration cannot be silently backed out either.

    Read off the AST rather than the file text, in both directions. `26900` is the zone formula's
    false-northing constant, and both files QUOTE the retired line in a comment recording why it is
    gone, so a substring match over the source would fail on the very comments that document the fix.
    And the call is graded as the value UTM is BOUND to, not merely as a call appearing somewhere:
    UTM is what every Transformer in each file is constructed with, so a call whose result went
    nowhere would leave the zone as unsourced as the copy did.
    """
    src = (pathlib.Path(ROOT) / relpath).read_text()
    tree = ast.parse(src)

    bound = [n for n in ast.walk(tree)
             if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "UTM" for t in n.targets)
             and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "utm_epsg"
             and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == "geo"]
    assert bound, (
        f"{relpath} no longer binds UTM to geo.utm_epsg(...). Every Transformer in that file is "
        f"built from UTM, so the zone every green surface or tree position is computed in would be "
        f"coming from somewhere other than this project's one home for that fact -- which is the "
        f"DROPPED_USE finding this file documents, reopened.")

    copied = [n for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, int)
              and not isinstance(n.value, bool) and n.value == _ZONE_FALSE_NORTHING]
    assert not copied, (
        f"{relpath} spells the UTM zone formula's own {_ZONE_FALSE_NORTHING} in executable code "
        f"again (line(s) {sorted({n.lineno for n in copied})}). Two copies of the zone arithmetic is "
        f"exactly the silent-drift hazard geo.utm_epsg was added to end, and the zone decides which "
        f"projection every green surface is built in.")


@pytest.mark.parametrize("lon", [-179.9, -121.0, -122.4, -71.0, 0.0, 34.5, 179.9])
def test_utm_epsg_matches_the_zone_arithmetic_derived_independently(lon):
    """Cross-checks geo.utm_epsg(lon) against the SAME arithmetic its two callers used to spell
    inline, evaluated independently here rather than by importing fetch_dem_hd.py/fetch_trees.py
    (both run course-bound code at import time that needs a real course.json to resolve). Paired
    with the structural test above: that one catches the callers going back to deriving the zone
    themselves, this one would catch geo.utm_epsg changing what it computes -- an off-by-one in the
    zone, say -- which no structural check can see now that the callers hold no second copy to
    disagree with.
    """
    duplicated = "EPSG:%d" % (26900 + int((lon + 180) / 6) + 1)
    assert geo.utm_epsg(lon) == duplicated


def test_utm_epsg_matches_its_own_docstring_examples():
    """Sanity check on the function itself. Nothing in the suite called it when L-1 was written --
    that absence was the whole finding -- and fetch_dem_hd.py and fetch_trees.py call it now.
    Confirms it still computes what its own docstring claims: 26910 for a California longitude
    (zone 10), 26919 for a Massachusetts one (zone 19).
    """
    assert geo.utm_epsg(-121.0) == "EPSG:26910"
    assert geo.utm_epsg(-71.0) == "EPSG:26919"
