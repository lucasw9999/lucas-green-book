#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Republish the two figures this repository states ABOUT ITSELF, so neither is typed by hand again.

Two sentences, in two hand-written documents, each publishing a number that is a property of the
repository rather than of the corpus:

  * legal/10_SOFTWARE_DEPENDENCIES.md -- "ships **N tracked files: ...**", the premise of its
    "Nothing here is redistributed" section. Derived from `git ls-files`.
  * README.md -- "drops modules from `sys.modules` at N sites", which is the evidence for the
    shuffled-order advice standing beside it. Counted across `tests/*.py` off the TOKEN STREAM with
    comments and string literals stripped, so every site counted is one that executes -- a plain
    `grep -c` reads higher, because this suite's own comments discuss the idiom at length.

WHY THIS EXISTS. Both were hand-typed prose audited after the fact by a test, and both went stale
THREE TIMES IN ONE DAY: every round that adds a tracked file moves the first, and every round that
adds a `sys.modules.pop` moves the second, so the pair broke on rounds that had nothing to do with
either document. The two guards -- test_the_software_licence_record_matches_the_repo_it_describes and
test_the_suite_reports_its_own_module_drop_count_correctly -- detected all three, which is the point:
detection was never the gap. Retyping was. This is tools/gen_provenance.py's and
tools/gen_disclaimers.py's arrangement applied to two sentences instead of two whole documents, and
CLAUDE.md's rule spelled out: prefer deriving a published figure over typing it.

ONLY THE NUMBER IS REWRITTEN. Both files are hand-written prose and one of them is a legal record, so
this is deliberately NOT a whole-document generator: it substitutes one integer inside one anchored
sentence per file and leaves every other byte alone. Neither document is marked "generated", because
neither is -- one sentence in each is.

AND IT REFUSES RATHER THAN NO-OPS. If an anchor sentence is not found exactly once, this tool exits 2
instead of writing a file it did not understand. A generator that silently matched nothing would
report "up to date" while the guard above went red, which leaves the next reader exactly where the
hand-typed figure did.

THE TRACKED COUNT IS THE INDEX'S. `git ls-files` reports what git is tracking now, which includes a
staged new file and excludes an unstaged one -- the same question the guard asks. So `git add` a new
file BEFORE republishing, or this writes a count that goes stale the moment you stage it.

Run:  python3 tools/gen_repo_figures.py            # rewrites both figures in place
      python3 tools/gen_repo_figures.py --check    # exits 1 if either is stale (for CI / pre-merge)

Exit codes:  0 both figures on disk are the ones derived here (or they were rewritten)
             1 STALE -- a document publishes a figure this repository does not match, and `--check`
               says so without touching it
             2 nothing could be compared: this is not a git checkout, a document or its anchor
               sentence is gone, a test file does not tokenise, or an argument this tool does not
               understand. AN UNRECOGNISED ARGUMENT IS EXIT 2 AND NOT A REWRITE -- see unknown_args.
"""
import glob
import io
import os
import re
import subprocess
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# THE ONLY ARGUMENT THIS TOOL UNDERSTANDS, for tools/gen_disclaimers.py's reason: the no-flag branch
# REWRITES two tracked documents, one of them a legal record, so `-check`, `--chek`, `--verify` and a
# bare `check` must never be read as a request to verify. Held to the shared truth table by
# tests/test_r16_gates.py, which discovers every tool defining unknown_args rather than listing them.
KNOWN_FLAGS = ("--check",)


def unknown_args(argv):
    """The arguments this tool does not understand -- EXACT membership, never a prefix or a substring.

    Spelled the same way in tools/gen_provenance.py, tools/gen_disclaimers.py and
    tools/check_osm_bbox.py, and all four are held to ONE truth table by tests/test_r16_gates.py.
    This tool takes no positional argument at all, so a bare word is unknown too.
    """
    return [a for a in argv if a not in KNOWN_FLAGS]


class Undecidable(Exception):
    """A figure could not be derived here at all, which is a REFUSAL and never a staleness verdict."""


# A drop site, in every spacing the suite writes it in. The same pattern the guard in
# tests/test_phase1_regressions.py counts with, applied to the same stripped token stream, because two
# implementations of one figure that disagree would leave `--check` green while the suite went red.
# That agreement is asserted, not assumed: the guard calls drop_sites() and requires it to equal the
# number it counted for itself.
POP_SITE = re.compile(r"sys\s*\.\s*modules\s*\.\s*pop")


def code_only(src):
    """`src` with comments and string literals removed, so a mention in prose is not counted as a site.

    This suite explains the `sys.modules.pop` idiom in its own comments and docstrings -- the reason
    README says the figure is counted with comments and strings stripped, and the reason a plain
    `grep -c` reads higher than the number published. Refuses rather than falling back to the raw
    source: counting prose would inflate the figure a legal-adjacent claim about cross-test state
    rests on.
    """
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError) as e:
        raise Undecidable(f"a test file does not tokenise ({type(e).__name__}), so comments and "
                          f"strings cannot be stripped and the count would include prose")
    return " ".join(out)


def drop_sites():
    """How many places in `tests/*.py` drop a module from `sys.modules`, counted as EXECUTABLE code."""
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
        with open(p, encoding="utf-8") as fh:
            n += len(POP_SITE.findall(code_only(fh.read())))
    return n


def tracked_files():
    """How many files git is tracking, or None when that cannot be asked here.

    None means "not a git checkout": a source tarball, a vendored copy, or the corpus-less temp tree
    the fresh-clone gate builds out of the tracked files -- that tree has no `.git` at all. None is a
    REFUSAL and not a count, because 0 tracked files would otherwise be published as a fact about a
    repository that ships forty-odd source files.
    """
    try:
        r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return len([p for p in r.stdout.split("\0") if p]) or None


# (document, the sentence that carries the figure, what the figure counts, how it is derived). The
# anchor is the SAME regex each guard pins with, so the tool and the guard read one sentence: the
# number is group 2 and the words around it are put back untouched.
FIGURES = (
    ("legal/10_SOFTWARE_DEPENDENCIES.md",
     re.compile(r"(ships \*\*)(\d+)( tracked files)"),
     "tracked files", tracked_files),
    ("README.md",
     re.compile(r"(drops modules from `sys\.modules` at )(\d+)( sites)"),
     "sys.modules drop sites", drop_sites),
)


def figures():
    """[(relpath, sentence pattern, what it counts, the number derived here)] for every figure.

    Raises Undecidable when a figure cannot be derived in this tree, so a caller cannot mistake a
    refusal for a verdict -- see main(), which reports it and exits 2 before comparing anything.
    """
    out = []
    for rel, pat, what, how in FIGURES:
        n = how()
        if n is None:
            raise Undecidable(f"the {what} count cannot be derived here: `git ls-files` in {ROOT} "
                              f"reported nothing, so this is not a git checkout")
        out.append((rel, pat, what, n))
    return out


def _one_site(rel, pat, what, text):
    """The single match of `pat` in `text`, or Undecidable naming what it was looking for."""
    hits = pat.finditer(text)
    first = next(hits, None)
    if first is None:
        raise Undecidable(f"{rel} no longer contains the sentence that publishes the {what} count "
                          f"({pat.pattern!r}), so there is nothing to republish. Restore the sentence "
                          f"or update FIGURES -- the guard that pins it reads the same words.")
    if next(hits, None) is not None:
        raise Undecidable(f"{rel} publishes the {what} count in more than one place, so rewriting "
                          f"one of them would leave the others behind. Keep it to one sentence.")
    return first


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # REFUSED BEFORE A SINGLE FILE IS READ, so this message cannot be confused with a verdict about
    # the documents: the refusals below answer 2 as well, and a reader who mistyped the flag needs to
    # know which of them stopped the run.
    stray = unknown_args(argv)
    if stray:
        print(f"unknown argument(s): {' '.join(stray)}\n"
              f"usage: gen_repo_figures.py [--check]\n"
              f"  with no argument this REWRITES the published figure in "
              f"{' and '.join(rel for rel, _p, _w, _h in FIGURES)}, so an argument this tool does "
              f"not recognise is refused rather than treated as one it does.")
        return 2
    # DERIVED FIRST, and every refusal reported before any comparison, so no run can print a
    # staleness verdict about a figure it could not derive.
    try:
        wanted = figures()
    except Undecidable as e:
        print(f"nothing to compare: {e}")
        return 2
    stale, current = [], []
    for rel, pat, what, n in wanted:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"nothing to compare: {rel} is not in this tree, and it is the document that "
                  f"publishes the {what} count")
            return 2
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            at = _one_site(rel, pat, what, text)
        except Undecidable as e:
            print(f"nothing to compare: {e}")
            return 2
        said = int(at.group(2))
        row = (rel, path, text, at, what, said, n)
        (current if said == n else stale).append(row)
    if "--check" in argv:
        for rel, _p, _t, _a, what, said, n in stale:
            print(f"{rel} is STALE: it publishes {said} {what}; this repository has {n}")
        if stale:
            print("run: python3 tools/gen_repo_figures.py")
            return 1
        for rel, _p, _t, _a, what, _said, n in current:
            print(f"{rel} is up to date ({n} {what})")
        return 0
    for rel, path, text, at, what, said, n in stale:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text[:at.start()] + at.group(1) + str(n) + at.group(3) + text[at.end():])
        print(f"wrote {rel}: {what} {said} -> {n}")
    for rel, _p, _t, _a, what, _said, n in current:
        print(f"{rel} already publishes {n} {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
