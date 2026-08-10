#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
ONE grader for the whole escape-hatch class, over a population DERIVED from the engine.

Every refusal in this project has an environment key that lets a human consciously accept a known
gap. Twice now the same defect has been found in that family and closed at the sightings rather than
at the class:

  * bool(os.environ.get(KEY)) makes `KEY=0` and `KEY=false` mean YES. Fixed in five modules, then
    found again in fetch_osm.py's four keys, where `ALLOW_HAZARD_SHRINK=0` ACCEPTED the loss of drawn
    sand and water.
  * The fix that closed those four enumerated three spellings -- "0", "false", "no" -- and stopped.
    Measured on the real helpers before this file existed, driving lidar_coverage._env_on:

        ''  -> False        '0' -> False       'false' -> False      'no' -> False
        '0 ' -> TRUE        ' 0' -> TRUE       '0\\n' -> TRUE
        'off' -> TRUE       'OFF' -> TRUE

    Every one of those TRUEs SPENDS the waiver. `OVERWRITE=off` armed
    `keeps_existing_surface()`'s escape hatch in BOTH surface stages -- the path that replaces a
    0.4 m LiDAR green with the coarse seamless one (fetch_dem) and the path that replaces a working
    seamless fallback with a BLANK GREEN (fetch_dem_hd). `courses/` is gitignored, so those surfaces
    are the only copy there is. `distribution.build_mode` in this same repo already did
    `.strip().lower()` and argues in its docstring that "a trailing space is a realistic typo".

WHY THE GRADER THAT PROVED THE LAST ROUND'S FIX DID NOT CATCH THIS: it hard-codes
`path = os.path.join(ROOT, "fetch_osm.py")` -- a one-file grader for a repo-wide class. So nothing
here is listed. The key population is read out of the engine's own AST -- every `_env_on(...)` call
and every literal-or-module-constant-argument `os.environ.get` / `getenv` across the repo root and
`tools/` -- and each key is then held to three properties:

  (1) an explicit OFF never spends it (the vocabulary, driven over every case-fold and every
      whitespace decoration a shell or a person produces),
  (2) spending it PRINTS something naming it, because `courses/` is gitignored and a build's own
      output is the only record a waiver leaves,
  (3) PIPELINE.md names it, because a key an operator cannot find is a key they cannot set.

WHICH KEYS ARE WAIVERS IS ALSO DERIVED, not listed. A key read through `_env_on` is one by
construction; a key read raw is one when the read's result is used only as a truth value, which is the
shape of the original defect. `COURSE` and `ONLY` carry data and fall out on the other side without an
entry anywhere. That matters more than it looks: two new acknowledgement keys landed in
`tools/check_osm_bbox.py` WHILE this file was being written, and a listed population would have
excused both in silence. The only table here is the EXEMPTIONS -- a key that is read for truth and
waives nothing anyway -- and every entry has to name a reason and still correspond to a live read, so
an excuse cannot outlive the key it was written for.

NOTHING HERE WRITES ANYTHING. Every test is an AST read plus a call to a pure parse function, and no
module in this file is dropped from sys.modules -- see
tests/test_r15_osm_keys.py::test_this_file_drops_no_module_from_sys_modules for why dropping
`lidar_coverage`, whose helper this file drives, would fork the very function being graded.

The last test is about `distribution.py` rather than the environment: it is the same class one layer
over -- a fail-closed guard whose "uncertain input" test recognised ONE spelling of uncertainty, so
four others walked through it -- and it belongs beside the sweep rather than in a file of its own.
"""
import ast
import contextlib
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import lidar_coverage                                                            # noqa: E402

PIPELINE = os.path.join(ROOT, "PIPELINE.md")

# THE VOCABULARY, stated once. This is the specification, not a sample of it: the off side is CLOSED
# and everything outside it is on, which is why an arbitrary word is driven on the on side below.
#
# "off" is in it because a person writing OVERWRITE=off means it, and because the three modules'
# docstrings already claimed "ON only if it is not an explicit off" while `off` turned the hatch ON.
OFF_WORDS = ("", "0", "false", "no", "off")
# `maybe` is deliberate: it is not an affirmative, and it must still read as ON. The rule is "not in
# the off vocabulary", never "in a list of yes words" -- a hatch that only recognised `1`/`true` would
# read a typo'd affirmative as a refusal to waive, and then the refusal is the surprise.
ON_WORDS = ("1", "true", "yes", "on", "2", "maybe")


def _decorations(word):
    """Every spelling of `word` a shell, an editor or a person can hand to the process.

    Case folds because these keys are typed by hand, and whitespace because `OVERWRITE=0 ` out of a
    heredoc, a shell variable or a copied line is the same intent as `OVERWRITE=0`. Both were live:
    the helpers case-folded and did NOT strip, so `' 0'` and `'0\\n'` spent the waiver.
    """
    out = set()
    for base in {word, word.lower(), word.upper(), word.capitalize()}:
        out |= {base, base + " ", " " + base, " " + base + " ",
                base + "\n", base + "\r\n", "\t" + base, base + "\t"}
    return sorted(out)


OFF_SPELLINGS = [(w, s) for w in OFF_WORDS for s in _decorations(w)]
ON_SPELLINGS = [(w, s) for w in ON_WORDS for s in _decorations(w)]


# ---------------------------------------------------------------------------------------------------
# The population, derived.

def _engine_sources():
    """Every first-party source an operator's environment can reach. Tests are not the engine."""
    return (sorted(glob.glob(os.path.join(ROOT, "*.py")))
            + sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))))


def _module_string_constants(tree):
    """{NAME: value} for module-level `NAME = "literal"`.

    Load-bearing, not a nicety: three keys are passed to the helper as constants
    (`lidar_coverage.COVERAGE_GAPS_ACK`, `UNCHECKED_ACK`, `verify_elevation.UNVERIFIED_ACK`), so a
    literal-only scan silently derives a population three keys short -- and two of those three guard
    the coverage verdict.
    """
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _calls_inside_env_on(tree):
    """The Call nodes that live inside a `def _env_on` body.

    The helper's own `os.environ.get(name, "")` is the READER, not a read site; counting it derives a
    key named by a local variable and then reports the population as unresolvable.
    """
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_env_on":
            inside |= {id(n) for n in ast.walk(node) if isinstance(n, ast.Call)}
    return inside


def _env_call_kind(func):
    """"_env_on", "bare" (a raw environment read), or None."""
    if isinstance(func, ast.Name):
        if func.id == "_env_on":
            return "_env_on"
        if func.id == "getenv":
            return "bare"
        return None
    if isinstance(func, ast.Attribute):
        if func.attr == "_env_on":
            return "_env_on"
        if func.attr == "getenv":
            return "bare"
        if func.attr == "get" and "environ" in ast.unparse(func.value):
            return "bare"
    return None


def read_sites():
    """{KEY: [(relpath, lineno, kind)]} and the sites whose key could not be resolved.

    Derived, never listed. The last grader for this class named ONE file, which is why a class that
    had been closed in five modules was still live in three.
    """
    sites, unresolved = {}, []
    for path in _engine_sources():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        consts = _module_string_constants(tree)
        skip = _calls_inside_env_on(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in skip:
                continue
            kind = _env_call_kind(node.func)
            if kind is None or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                key = arg.value
            elif isinstance(arg, ast.Name) and arg.id in consts:
                key = consts[arg.id]
            else:
                unresolved.append((rel, node.lineno, ast.unparse(arg)))
                continue
            sites.setdefault(key, []).append((rel, node.lineno, kind))
    return sites, unresolved


def _module_level_imports_the_helper(rel):
    """Does `rel` hold `from lidar_coverage import _env_on` AT MODULE LEVEL?

    Module level matters: a function-local import re-resolves out of sys.modules on every call, which
    is fine for correctness but invisible to a reader asking "whose vocabulary does this file use?".
    """
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=rel)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and not node.level and node.module == "lidar_coverage" \
                and any(a.name == "_env_on" for a in node.names):
            return True
    return False


def _helper_definers():
    """Every engine module that spells `def _env_on` itself, discovered rather than listed."""
    out = []
    for path in _engine_sources():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        if any(isinstance(n, ast.FunctionDef) and n.name == "_env_on" for n in ast.walk(tree)):
            out.append(os.path.relpath(path, ROOT))
    return sorted(out)


def _off_vocabulary_of(rel):
    """The off-vocabulary `rel`'s `_env_on` actually implements, and whether it strips first.

    Read off the comparison, not off the prose: the prose is what was wrong.
    """
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=rel)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_env_on"]:
        for cmp_node in [n for n in ast.walk(fn) if isinstance(n, ast.Compare)]:
            right = cmp_node.comparators[0] if cmp_node.comparators else None
            if not isinstance(right, (ast.Tuple, ast.List, ast.Set)):
                continue
            vocab = {e.value for e in right.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if not vocab:
                continue
            left = ast.unparse(cmp_node.left)
            return vocab, ".strip()" in left, ast.unparse(fn.body[-1])
    return None, False, ""


@contextlib.contextmanager
def _bound(key, raw):
    """Bind one key to one raw value and put back exactly what was there."""
    held = os.environ.get(key)
    try:
        os.environ[key] = raw
        yield
    finally:
        if held is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = held


# ---------------------------------------------------------------------------------------------------
# The classification, DERIVED. Nothing here lists the waivers.
#
# A waiver is a key read for YES/NO -- its value never reaches a number, a path or a page, it only
# decides whether the build goes on. That is exactly what the AST can see, so it is asked rather than
# transcribed: a list of key names in a test file is one more copy of the thing that keeps
# rotting, and a new hatch landing while this file was being written would have had to be typed in
# before anything graded it. Two of them did land, twice.

def _boolean_context(tree):
    """The Call nodes whose RESULT is only ever used as a truth value.

    `if _env_on(K)`, `not os.environ.get(K)`, `assert os.environ.get(K)` -- versus
    `slug = os.environ.get("COURSE")`, whose value goes on to name a directory. This is the whole
    difference between a waiver and a key that carries data, and it is a property of the read, not of
    the key's spelling: `ALLOW_` is a naming convention and `OVERWRITE` and `QUIET_TEE_CHECK` do not
    follow it.

    A BARE `and`/`or` IS NOT A TRUTH CONTEXT, and getting that wrong classified COURSE as a hatch:
    `os.environ.get("COURSE") or sys.exit(...)` yields the slug, it does not test it. Inside an `if`
    test the whole expression is walked anyway, so `if x and os.environ.get(K):` is still caught.
    """
    out = set()
    for node in ast.walk(tree):
        tests = []
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            tests = [node.test]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            tests = [node.operand]
        elif isinstance(node, ast.Assert):
            tests = [node.test]
        elif isinstance(node, ast.comprehension):
            tests = list(node.ifs)
        for t in tests:
            out |= {id(n) for n in ast.walk(t) if isinstance(n, ast.Call)}
    return out


def classify():
    """(waivers, value_keys) over the derived population.

    A key read through `_env_on` is a waiver by construction -- that helper returns nothing but a bool.
    A key read raw is a waiver when its result is used only as a truth value; that is the shape of the
    original defect (`if not os.environ.get("ALLOW_OSM_TREES")`), so it has to be caught by shape and
    not by a list, or the next one arrives unpinned.
    """
    waivers, values = set(), set()
    for path in _engine_sources():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        consts = _module_string_constants(tree)
        skip = _calls_inside_env_on(tree)
        truthy = _boolean_context(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in skip or not node.args:
                continue
            kind = _env_call_kind(node.func)
            if kind is None:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                key = arg.value
            elif isinstance(arg, ast.Name) and arg.id in consts:
                key = consts[arg.id]
            else:
                continue
            (waivers if kind == "_env_on" or id(node) in truthy else values).add(key)
    return waivers - set(NOT_WAIVERS), values - waivers


# The ONLY table here, and it is the EXEMPTIONS -- the half that has to be argued. A key whose read
# LOOKS like a waiver (used for truth, nothing else) but waives nothing, with the reason. Kept short on
# purpose: every entry is a hole in the three properties below.
NOT_WAIVERS = {
    "COACH": "selects the enlarged large-print edition. Both editions are built from the same data by "
             "the same code, so no value of this key waives a refusal, hides a gap or destroys a "
             "surface -- the worst a surprising parse can do here is build a book nobody asked for. It "
             "is read for truth (`if os.environ.get(\"COACH\")`) and so would otherwise be graded as a "
             "hatch that must be routed through the shared helper",
}

# A silencer cannot announce itself: printing "the note you asked me to suppress is suppressed" is the
# note. Nothing is waived here either -- the shorter-tee condition stays derivable from the scorecard,
# and this key hides an advisory, never a data gap.
CANNOT_ANNOUNCE_ITSELF = {
    "QUIET_TEE_CHECK": "it exists to make output quiet; a waiver notice would defeat it",
}


def _enumeration_window(doc, words):
    """The tightest span of `doc` that names every one of `words`, or None.

    ONE SPAN, not "each word appears somewhere". Graded per-word first, and that version passed with
    `off` deleted from the enumeration: the docstring's HISTORY paragraph mentions `off` too ("the fix
    that added `off` and a `.strip()`"), so a prose reference to the value satisfied a check meant to
    ask whether the vocabulary is stated. What a reader needs is the list, in one place.
    """
    hits = []
    for word in words:
        pat = (r"(?<![A-Za-z0-9_])empty(?![A-Za-z0-9_])" if word == ""
               else "`%s`" % re.escape(word))
        found = [m.start() for m in re.finditer(pat, doc)]
        if not found:
            return None
        hits.extend((p, word) for p in found)
    hits.sort()
    need, best = len(words), None
    seen, left = {}, 0
    for right, (pos, word) in enumerate(hits):
        seen[word] = seen.get(word, 0) + 1
        while len(seen) == need:
            span = pos - hits[left][0]
            best = span if best is None else min(best, span)
            drop = hits[left][1]
            seen[drop] -= 1
            if not seen[drop]:
                del seen[drop]
            left += 1
    return best


def test_every_environment_key_the_engine_reads_is_classified():
    """The population AND the split are read off the engine, so a new hatch is graded on arrival.

    Written first with a hand-typed list of the waiver names, which is how this defect keeps
    coming back: two new acknowledgement keys landed in `tools/check_osm_bbox.py` WHILE this file was
    being written, and a listed population would have silently excused both. The list is gone; what is
    checked instead is that the derived split is non-degenerate and that every exemption is real.
    """
    sites, unresolved = read_sites()
    assert not unresolved, (
        "these environment reads name their key with something this grader cannot resolve, so the key "
        "is outside the population every property below is asserted over: %s. Spell the key as a "
        "literal or as a module-level constant." % (unresolved,))

    waivers, values = classify()
    assert waivers and values, (
        "the derived split is degenerate (%d waiver(s), %d value key(s)), so the classifier has "
        "stopped telling a hatch from a slug and every property below is being asserted over the "
        "wrong set" % (len(waivers), len(values)))
    assert waivers | values | set(NOT_WAIVERS) == set(sites), (
        "the split does not cover the derived population: %s classified nowhere"
        % sorted(set(sites) - (waivers | values | set(NOT_WAIVERS))))

    for table, name in ((NOT_WAIVERS, "NOT_WAIVERS"), (CANNOT_ANNOUNCE_ITSELF, "CANNOT_ANNOUNCE_ITSELF")):
        for key, why in sorted(table.items()):
            assert key in sites, (
                "%s excuses %s, which the engine no longer reads -- delete the entry rather than "
                "leaving an excuse behind for a key that does not exist" % (name, key))
            assert why and len(why) > 20, (
                "%s excuses %s with no stated reason. The exemption is the dangerous half of this "
                "file; it has to be argued." % (name, key))
    for key in sorted(CANNOT_ANNOUNCE_ITSELF):
        assert key in waivers, \
            "%s is excused from announcing itself but is not derived as a waiver at all" % key


def test_the_off_vocabulary_is_one_vocabulary_and_every_copy_obeys_it():
    """An explicit off must never spend a waiver -- in every spelling, from every copy of the helper.

    RED BEFORE THE FIX, measured on the real helpers:
        lidar_coverage._env_on('0 ')   -> True      (the waiver is SPENT)
        lidar_coverage._env_on(' 0')   -> True
        lidar_coverage._env_on('0\\n')  -> True
        lidar_coverage._env_on('off')  -> True
        lidar_coverage._env_on('OFF')  -> True
    and identically for fetch_trees, fetch_hole_elev and both OVERWRITE constants, because all five
    were the same hand-copied expression.

    The vocabulary is graded THREE ways, because each alone has been satisfied by something wrong:
    the implemented tuple (a narrowed copy is the failure mode the last grader was written for), the
    parse itself over every decoration, and the docstring beside it -- a comment claiming "ON only if
    it is not an explicit off" while `off` means ON is a false claim about a safety property, and this
    repo has already shipped a false printed claim that hid inside an interpolation (f067f28).
    """
    definers = _helper_definers()
    assert definers, "no engine module defines `_env_on` any more -- this whole grader is aimed at it"

    for rel in definers:
        vocab, strips, tail = _off_vocabulary_of(rel)
        assert vocab is not None, \
            "%s defines _env_on but this grader cannot find the vocabulary it compares against" % rel
        assert vocab == set(OFF_WORDS), (
            "%s's _env_on implements the off-vocabulary %s; the one this project specifies is %s. "
            "Copies of a vocabulary are only safe while they are the SAME vocabulary -- narrowing one "
            "turns an explicit off into a waiver in one module and nowhere else.\n  %s"
            % (rel, sorted(vocab), sorted(OFF_WORDS), tail))
        assert strips, (
            "%s's _env_on case-folds but does not strip, so `KEY=0 ` and `KEY=0\\n` SPEND the waiver. "
            "distribution.build_mode in this repo already strips and argues why: 'a trailing space is "
            "a realistic typo'.\n  %s" % (rel, tail))

        doc = ast.get_docstring(
            [n for n in ast.walk(ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read()))
             if isinstance(n, ast.FunctionDef) and n.name == "_env_on"][0]) or ""
        span = _enumeration_window(doc, OFF_WORDS)
        assert span is not None and span <= 200, (
            "%s's _env_on does not state its off-vocabulary %s in one place -- tightest span naming all "
            "of them: %s. The summary sentence 'ON only if it is not an explicit off' is not a "
            "specification: it read as true while `off` turned the hatch ON, and every ALLOW_* key in "
            "the repo copied that claim. Enumerate the values, backtick-quoted, and write \"empty\" for "
            "the empty string." % (rel, sorted(OFF_WORDS),
                                   "none" if span is None else "%d chars" % span))

    waivers, _values = classify()
    routed = {k for k, v in read_sites()[0].items()
              if k in waivers and all(kind == "_env_on" for _rel, _ln, kind in v)}
    assert routed, "no waiver is read through _env_on at all"

    for rel in definers:
        mod = sys.modules.get(os.path.basename(rel)[:-3]) or lidar_coverage
        env_on = mod._env_on if hasattr(mod, "_env_on") else lidar_coverage._env_on
        for key in sorted(routed):
            for word, raw in OFF_SPELLINGS:
                with _bound(key, raw):
                    assert env_on(key) is False, (
                        "%s: %s=%r parsed to ON, so an explicit off SPENDS this waiver. %r is in this "
                        "project's off-vocabulary." % (rel, key, raw, word))
            for word, raw in ON_SPELLINGS:
                with _bound(key, raw):
                    assert env_on(key) is True, (
                        "%s: %s=%r parsed to OFF. Only the off-vocabulary %s turns a hatch off; "
                        "everything else is on, or a typo'd yes becomes a silent refusal."
                        % (rel, key, raw, sorted(OFF_WORDS)))
            os.environ.pop(key, None)
            assert env_on(key) is False, "%s: an UNSET %s must be off" % (rel, key)


def test_no_waiver_is_read_for_bare_truthiness():
    """Every waiver goes through the shared helper, so the vocabulary above is the ONLY vocabulary.

    This is the property the previous grader asserted for ONE file. `bool(os.environ.get(KEY))` is the
    original defect in this family and it has now been introduced three separate times, so the shape
    is pinned across the whole engine rather than per module -- and over a population the engine
    supplies, so a hatch added tomorrow is held to it without an edit here.
    """
    sites, _ = read_sites()
    waivers, _values = classify()
    bare = {k: [(r, ln) for r, ln, kind in sites[k] if kind == "bare"] for k in waivers}
    bare = {k: v for k, v in bare.items() if v}

    assert not bare, (
        "these waivers are read as a raw environment value, so every spelling a person reaches for to "
        "DISABLE one -- `=0`, `=false`, `=no`, `=off` -- is a non-empty string, therefore truthy, "
        "therefore SPENDS the waiver: %s. Route them through lidar_coverage._env_on, as fetch_osm.py "
        "and tools/verify_elevation.py do." % {k: bare[k] for k in sorted(bare)})

    for key in sorted(waivers):
        for rel, _ln, _kind in sites[key]:
            if rel not in _helper_definers():
                assert _module_level_imports_the_helper(rel), (
                    "%s reads %s through a name called `_env_on` that it does not import from "
                    "lidar_coverage at module level, so which off-vocabulary it uses is unknowable "
                    "from the file." % (rel, key))


def _announcements(rel):
    """Every printed text in `rel`, with module-level string constants resolved into it.

    Constant-resolved because the four keys whose notice is spelled `f"WARNING: {UNCHECKED_ACK} set"`
    would otherwise read as unannounced, and brace-stripped so an interpolated key reads the same as a
    literal one. Interpolation is exactly where a false printed claim hid in this repo once already.
    """
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=rel)
    consts = _module_string_constants(tree)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "print"):
            continue
        text = ast.unparse(node)
        for name, value in consts.items():
            text = re.sub(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), value, text)
        out.append(text.replace("{", "").replace("}", ""))
    return out


def test_a_spent_waiver_says_so():
    """A waiver changes the exit code; it must never hide the finding.

    `courses/` is gitignored and a fetch overwrites the cache it was compared against, so the build's
    own output is the ONLY record that a loss was accepted. Every other key in this family already
    prints `KEY set -- <what it accepted>`; OVERWRITE printed nothing at all, and both stages
    that read it mention `OVERWRITE=1` only as ADVICE on the path where it is NOT set -- which is why
    the token graded here is "KEY set" and not the bare key name. A suggestion is not a receipt.

    PER READING MODULE, not per key. OVERWRITE is read by both surface stages and the two losses are
    DIFFERENT -- fetch_dem discards a 0.4 m LiDAR green for the coarse mosaic, fetch_dem_hd turns a
    working card blank -- so one stage's notice cannot stand in for the other's. Written key-wise first,
    this test passed with fetch_dem's notice deleted, because fetch_dem_hd still had one.
    """
    sites, _ = read_sites()
    waivers, _values = classify()
    missing = {}
    for key in sorted(waivers):
        if key in CANNOT_ANNOUNCE_ITSELF:
            continue
        for rel in sorted({rel for rel, _ln, _kind in sites[key]}):
            if not any("%s set" % key in text for text in _announcements(rel)):
                missing.setdefault(key, []).append(rel)
    assert not missing, (
        "spending these waivers prints nothing that names them, so a build that accepted a real loss "
        "leaves no trace in its own output: %s. Print `WARNING: KEY set -- <what was accepted>`, the "
        "shape the other keys in this family already use." % missing)

    for key, why in sorted(CANNOT_ANNOUNCE_ITSELF.items()):
        assert why and len(why) > 20, \
            "%s is excused from announcing itself with no stated reason" % key
        assert not any("%s set" % key in text
                       for rel, _ln, _kind in sites[key] for text in _announcements(rel)), (
            "%s is excused from announcing itself but announces itself anyway -- delete the "
            "exemption." % key)


def test_every_environment_key_is_documented_in_the_pipeline():
    """A key an operator cannot find in the recipe is a key they cannot consciously set.

    RED before the fix for two of them: `QUIET_TEE_CHECK` -- which suppresses the note behind the
    defect that printed "376 Gold" beside a BLA marker on 10 of 18 holes, up to 46 yd wrong on the
    number a junior reads as how far they hit it -- and `COACH_NAME` appeared nowhere in PIPELINE.md.
    """
    with open(PIPELINE, encoding="utf-8") as fh:
        doc = fh.read()
    sites, _ = read_sites()
    absent = {}
    for key in sorted(sites):
        if not re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(key), doc):
            absent[key] = sorted({rel for rel, _ln, _kind in sites[key]})
    assert not absent, (
        "PIPELINE.md is the recipe an operator follows and it names none of these keys: %s" % absent)


def test_the_pipeline_does_not_claim_a_vocabulary_the_code_does_not_have():
    """PIPELINE.md said one family of keys used "the same vocabulary every other `ALLOW_*` key here
    uses". ELEVEN LINES LATER it documents `ALLOW_OSM_TREES`, which used none of it.

    An operator reads that sentence, concludes `=0` is the safe way to leave a waiver off, and spends
    it. So the universal claim is refused while any ALLOW_ key is still read bare, and each such key
    has to be documented as the exception it is -- next to the thing that actually bites, which is
    that any non-empty value turns it on.
    """
    with open(PIPELINE, encoding="utf-8") as fh:
        doc = fh.read()
    sites, _ = read_sites()
    waivers, _values = classify()
    bare = sorted(k for k in waivers if any(kind == "bare" for _r, _l, kind in sites[k]))

    if bare:
        for phrase in ("every other `ALLOW_*` key", "every other ALLOW_* key"):
            assert phrase not in doc, (
                "PIPELINE.md claims %r shares one vocabulary while %s is still read as a raw "
                "environment value. The claim is false in the direction that spends a waiver."
                % (phrase, ", ".join(bare)))
        for key in bare:
            near = [doc[max(0, m.start() - 500):m.end() + 500] for m in
                    re.finditer(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(key), doc)]
            assert any("non-empty" in chunk for chunk in near), (
                "%s is read as a raw environment value -- `=0` turns it ON -- and PIPELINE.md "
                "describes it without saying so. An operator reading only the recipe cannot know "
                "which of these keys the off-vocabulary covers." % key)


# ---------------------------------------------------------------------------------------------------
# The same defect one layer over: a guard whose "uncertain input" test recognises ONE spelling of
# uncertainty. Here because it is the same class as everything above -- a refusal that a falsy value
# walks straight through -- and because the fix belongs beside the vocabulary sweep, not in a file of
# its own.

# Every record that is NOT a parsed course.json, and what each one is in practice. `{}` is deliberately
# absent: tests/test_phase1_regressions.py:19087 pins it as distributable, documenting "an ordinary
# course with no build_mode", and that is the DEFAULT 11 corpus courses rely on.
UNREADABLE_RECORDS = (
    (None, "json.load never ran, or the file is missing"),
    ([], "course.json holds a LIST -- a truncated or wrongly-rooted document"),
    ((), "the same, as a tuple"),
    (0, "course.json holds a bare number"),
    (False, "course.json holds `false`"),
    ("", "course.json is empty, or a reader handed back the empty string"),
    ("yardage", "someone passed the MODE where the record goes -- and this raised AttributeError"),
    (0.0, "course.json holds a bare float"),
    (set(), "not JSON at all, but reachable from Python"),
)


def test_the_distribution_rule_fails_closed_on_a_record_it_cannot_read():
    """"Every uncertain input has to resolve to no" -- its own docstring. Four other spellings of an
    unreadable record answered *publishable*, and a fifth crashed.

    RED before the fix, measured:
        None       -> (False, 'Personal', ...)     the only one that was right
        []         -> (True, 'Distributed', '')
        0          -> (True, 'Distributed', '')
        False      -> (True, 'Distributed', '')
        ''         -> (True, 'Distributed', '')
        'yardage'  -> AttributeError: 'str' object has no attribute 'get'

    `(course or {})` laundered every falsy non-dict into an empty course and the only unknown-record
    test was `if course is None`. This is the shared rule for ANY publisher: tools/gen_provenance.py
    hands it JSON it loaded itself and writes the answer into the Status column of
    legal/03_PROVENANCE_BY_COURSE.md, whose legend reads *"Distributed" = safe to hand out*.

    An AttributeError is not the safe failure either -- gen_provenance catches broadly enough that a
    crash inside one course's row is not the same as a refusal, and a decision this file exists to make
    must be MADE, not raised.
    """
    import distribution

    for record, what in UNREADABLE_RECORDS:
        ok, label, why = distribution.distribution_status(record)
        assert ok is False and label == "Personal", (
            "distribution_status(%r) answered (%r, %r) -- %s. This decides whether a book may be "
            "handed out; an input it cannot read has to resolve to no."
            % (record, ok, label, what))
        assert why, "a Personal verdict needs a stated reason; %r got none" % (record,)
        assert distribution.is_distributable(record) is False, \
            "is_distributable(%r) disagrees with distribution_status" % (record,)
        # ...and no reader of the same record may crash instead of answering.
        assert distribution.build_mode(record) == "", \
            "build_mode(%r) must answer, not raise or invent a mode" % (record,)
        assert distribution.is_yardage(record) is False, \
            "is_yardage(%r) must answer, not raise" % (record,)

    # The documented default is untouched: an absent build_mode means full, and 11 of 12 corpus
    # records carry no build_mode at all.
    assert distribution.distribution_status({}) == (True, "Distributed", ""), \
        "an ordinary course record with no build_mode is distributable -- this is the documented default"
    assert distribution.distribution_status({"slug": "x"}) == (True, "Distributed", "")
    assert distribution.distribution_status({"build_mode": "yardage"})[1] == "Personal"
