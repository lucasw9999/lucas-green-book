#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Export greenbook.html -> greenbook.pdf, in the repo, reproducibly.

Why this exists: nothing in the pipeline produced the PDF. PIPELINE.md said "headless Chrome
--print-to-pdf, or Cmd+P", so every shipped PDF was made by hand at an unknown time from an unknown
HTML -- and they drifted. Measured on 2026-07-29: all 12 PDFs were exported at 12:02 while the HTML
they claim to represent was rebuilt at 15:16, so the printed books still carried slope labels of
40%, 29% and 21% that the engine had already stopped emitting. The honesty rule was satisfied in the
HTML and violated on the paper, which is the only version that reaches a golf course.

A generated artifact that no tool generates will always drift. So: one command, and a test that
fails when a PDF was not exported from the HTML beside it. (It says CONTENT, not mtime, and it always
did -- see stale(). The promise here read "a test that fails when a PDF is older than its HTML" for
the 338 commits between `2b5e4e3`, which introduced this tool, and `2b0e248`, which corrected it, and
the test was named for that comparison too, while no age comparison existed anywhere: a PDF thirty
days older than its HTML passed. That span was published as "96 commits", a figure nothing in this
tree measured and one that reached a commit message too; it is derived from git now, by
test_the_export_tools_account_of_its_own_history_is_the_one_git_records.)

WHAT --check PROVES, exactly, because two records overstated it once each: beside every book it
records the digest of the HTML and the digest of the exported PDF, and at check time it re-derives
BOTH from the files on disk. So it proves the PDF beside a book is byte-for-byte the file this tool
exported, and that the export was recorded against the HTML now sitting beside it. It does not
re-render anything, so it cannot prove the bytes were PRODUCED from that HTML -- a stamp is a record,
not a re-derivation of the rendering, and a hand-written stamp naming both current digests passes.
A PDF with no stamp is reported as provenance UNKNOWN rather than as stale; a file with no trailer is
refused whatever its stamp says.

Run:  python3 tools/export_pdf.py                 # every built course (and coach edition)
      python3 tools/export_pdf.py merion-golf-club
      python3 tools/export_pdf.py --check          # exit 1 if any PDF is stale; exports nothing
"""
import glob
import hashlib
import json
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# THE VERDICTS, as values. stale() used to return only a sentence, and the test that gates the
# printed book classified on the sentence -- `why.startswith("exported from")`. Proven by a two-step
# mutation: corrupting a stamp so the recorded hash genuinely disagreed made that test fail with the
# right message, and then REWORDING the sentence below, nothing else, made the same corrupted stamp
# SKIP instead, under a skip message that was itself false. A proven-stale printed book became a
# green run because a message had been edited. The tag is the fact; the sentence is a courtesy.
NOT_EXPORTED = "not-exported"     # no PDF beside the html: nothing to judge
UNSTAMPED = "no-source-hash"      # a PDF with no record of where it came from: provenance unknown
WRONG_SOURCE = "wrong-source"     # the recorded source digest is not this html: PROVEN stale
TRUNCATED = "truncated"           # the file on disk is not a whole PDF: PROVEN unprintable
WRONG_BYTES = "wrong-bytes"       # the recorded PDF digest is not this file: PROVEN not the export

# The whole vocabulary, so a test can require that every verdict it might meet is one it classifies
# rather than let an unrecognised one fall into "we cannot know" and skip.
REASONS = (NOT_EXPORTED, UNSTAMPED, WRONG_SOURCE, TRUNCATED, WRONG_BYTES)


def _headless_shell():
    """The cached chrome-headless-shell for the revision the installed Playwright declares.

    It claimed to match the installed build and consulted nothing: it returned the LEXICOGRAPHICALLY
    greatest cached directory, which is wrong at every digit-count boundary -- with revisions 999,
    1000 and 1208 cached it picked 999. Which binary prints the book is not an implementation detail
    here, because /Creator and the Skia/PDF milestone are how the suite and PIPELINE.md tell a
    tool-exported book from a hand-printed one.

    So the revision comes from playwright's own browsers.json (the `chromium-headless-shell` entry),
    and that exact directory is globbed for. Where it is not cached -- or where playwright is not
    importable at all, which is a bare `--check` on a machine that never exports -- the newest cached
    revision is the honest answer, newest by REVISION NUMBER rather than as text.
    """
    hits = glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/"
        "chrome-headless-shell"))
    if not hits:
        return None
    want = _declared_revision()

    def revision(path):
        tag = path.split("chromium_headless_shell-", 1)[1].split(os.sep, 1)[0]
        return (1, int(tag)) if tag.isdigit() else (0, 0)

    if want is not None:
        exact = sorted(p for p in hits if revision(p) == (1, want))
        if exact:
            return exact[0]
    return sorted(hits, key=lambda p: (revision(p), p))[-1]


def _declared_revision():
    """The chrome-headless-shell revision the INSTALLED playwright drives, or None if it cannot say."""
    try:
        import playwright
    except ImportError:
        return None
    manifest = os.path.join(os.path.dirname(playwright.__file__), "driver", "package",
                            "browsers.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            for b in json.load(fh).get("browsers") or ():
                if b.get("name") == "chromium-headless-shell":
                    return int(b["revision"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def pairs(only=None):
    """[(html, pdf)] for every built book, pocket and coach."""
    out = []
    for h in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        slug = os.path.basename(os.path.dirname(h))
        if slug.startswith("_"):
            continue                      # scratch/staging dirs are not books
        if only and slug not in only:
            continue
        out.append((h, os.path.splitext(h)[0] + ".pdf"))
    return out


def file_hash(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def src_hash(html):
    return file_hash(html)


def stamp_path(pdf):
    return pdf + ".src"


def staged_pdf(pdf):
    """Where export() writes a book before renaming it into place. One spelling, so a sweep matches it.

    Dot-prefixed, exactly like surface_io.staged_names' `.holeNN.json.part`, and for the same reason
    on the other side: `courses/*/*` is what the suite's read-only snapshot watches and what its
    coverage walk requires to be watched, and both of them exempt a dot-prefixed name as either OS
    litter or a stage. A leftover `greenbook.pdf.part` would read as course data nothing has ever
    seen; a leftover `.greenbook.pdf.part` reads as what it is.
    """
    d, n = os.path.dirname(pdf), os.path.basename(pdf)
    return os.path.join(d, f".{n}.part")


def is_whole_pdf(pdf, tail=4096):
    """Does this file begin and end like a PDF? Not a parse -- a TORN WRITE is what it has to catch.

    Playwright's writer opens the destination "wb", so a run interrupted partway through leaves the
    printable book truncated in place while its stamp -- never rewritten, because it already agreed --
    still names the current HTML. Measured on a real shipped book: the remains opened with ZERO pages
    and PyMuPDF's is_repaired set, and --check called it fresh and exited 0.

    export() stages and renames now, so it cannot produce one of these itself. This still has to exist
    because the stamps already on disk record the HTML alone: for those books a trailer is the only
    evidence the file is whole, and it costs a 4 KiB read.
    """
    try:
        size = os.path.getsize(pdf)
        with open(pdf, "rb") as fh:
            if fh.read(5) != b"%PDF-":
                return False
            fh.seek(max(0, size - tail))
            return b"%%EOF" in fh.read()
    except OSError:
        return False


def read_stamp(pdf):
    """{field: digest} from a PDF's .src note, or None when there is no note at all.

    Two formats, because the stamps already on disk carry one bare line. A single line is the html
    digest and nothing else; the current form is `<field> <digest>` per line, so the PDF's own digest
    travels beside it. None and {} are different answers on purpose: no note means provenance is
    unknown, whereas a note that yields no html digest is a note that does not agree with the html,
    which is a proven defect and was one before this function existed.

    A NOTE THAT NAMES TWO DIFFERENT HTML DIGESTS NAMES NEITHER. `setdefault` resolved that to whichever
    line came first and said nothing, so appending a second, contradicting digest to a legacy stamp read
    as a clean match -- and the reader whose html matched the OTHER line would have been told the same.
    A self-contradictory note is not evidence, so the field is dropped: that is the "does not agree with
    the html" answer, a PROVEN defect, and not the "no note at all" answer.
    """
    sp = stamp_path(pdf)
    if not os.path.exists(sp):
        return None
    out = {}
    try:
        with open(sp, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return out
    bare = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 1:
            bare.append(parts[0])                 # legacy: one bare line IS the html digest
        elif len(parts) == 2:
            out[parts[0]] = parts[1]
    for digest in bare:
        out.setdefault("html", digest)
    if len({d for d in bare} | ({out["html"]} if "html" in out else set())) > 1:
        out.pop("html", None)
    return out


def write_stamp(pdf, html):
    """Record WHICH html this pdf came from AND what the pdf itself is, so staleness is a fact.

    The html digest alone proved that a NOTE beside the book named the current HTML -- not that the
    book on disk was the one exported from it. README claimed the stronger thing; the PDF's own digest
    is what earns it.
    """
    with open(stamp_path(pdf), "w", encoding="utf-8") as f:
        f.write(f"html {src_hash(html)}\npdf {file_hash(pdf)}\n")


def stale(only=None):
    """[(html, pdf, tag, why)] for every book whose PDF is missing, torn, or not the current export.

    Compares recorded content digests rather than mtimes. mtime is a proxy that false-positives on any
    copied or freshly checked-out tree (cp/rsync/git touch the html), and a gate that cries wolf gets
    ignored -- which is how the PDFs drifted three commits behind in the first place.

    `tag` is one of REASONS and is the verdict; `why` is the sentence for a human. They are separate
    because the gating test used to classify on the sentence, and rewording one turned a proven-stale
    printed book into a green run.
    """
    bad = []
    for h, p in pairs(only):
        if not os.path.exists(p):
            bad.append((h, p, NOT_EXPORTED, "not exported")); continue
        if not is_whole_pdf(p):
            bad.append((h, p, TRUNCATED,
                        "not a whole PDF -- no trailer, so this is the wreck of an interrupted write"))
            continue
        rec = read_stamp(p)
        if rec is None:
            # No note: this PDF was produced by something other than this tool, or by this tool
            # interrupted between writing the book and writing the note. Its provenance is UNKNOWN,
            # not proven stale. Falling back to mtime looked rigorous but false-positived on any
            # copied or checked-out tree, and a gate that cries wolf is a gate people switch off.
            # It said "exported by hand" until this line, which asserts a cause the tool cannot know
            # and is FALSE in the one case the tool causes itself -- one Ctrl-C during a 15-book run,
            # and --check told the user to do the thing they were doing.
            bad.append((h, p, UNSTAMPED,
                        "unverifiable: no source hash recorded beside it, so it was either printed by "
                        "hand or left by a run interrupted before its stamp was written"))
        elif rec.get("html") != src_hash(h):
            bad.append((h, p, WRONG_SOURCE, "exported from a DIFFERENT html"))
        elif "pdf" in rec and rec["pdf"] != file_hash(p):
            bad.append((h, p, WRONG_BYTES,
                        "not the PDF that was exported -- the file has changed since"))
    return bad


def sweep_staged(items):
    """Remove any `.greenbook*.pdf.part` left beside the books in `items`. -> [paths removed]

    The convention this repo states five times for exactly this class, and the one place that had the
    stage without the sweep: fetch_lidar.py sweeps laz/, fetch_dem.py and fetch_dem_hd.py call
    surface_io.sweep_staged, lidar_dates.py sweeps its own course.json.part. export()'s `finally`
    covers every failure short of a KILL -- SIGKILL, a closed lid, power -- and a run killed there
    leaves a staged book in courses/<slug>/, which is the one directory nothing else sweeps.

    Harmless to lose: a `.part` is only renamed into place after `pg.pdf()` returns, so it is never a
    whole book and never the only copy of anything. Swept before exporting rather than in `--check`,
    because `--check` exports nothing and a read-only gate must not write.
    """
    gone = []
    for _h, p in items:
        tmp = staged_pdf(p)
        if os.path.exists(tmp):
            os.remove(tmp)
            gone.append(tmp)
    return gone


def export(items):
    from playwright.sync_api import sync_playwright
    exe = _headless_shell()
    done = []
    for tmp in sweep_staged(items):
        print(f"  swept a staged book left by an interrupted run: {os.path.relpath(tmp, ROOT)}")
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception as e:
            print(f"no browser available ({type(e).__name__}): cannot export")
            return None
        pg = b.new_page()
        for h, p in items:
            pg.goto(pathlib.Path(h).resolve().as_uri())
            pg.emulate_media(media="print")
            # STAGE AND RENAME -- the convention this repo states four times for exactly this class
            # (fetch_lidar.py's laz/ downloads, fetch_hole_elev.py, surface_io.commit_surface,
            # fetch_trees.py). Playwright's writer opens its destination "wb", and a re-export rewrites
            # ALL the books including the ones whose stamps already match, so writing in place
            # truncates a good book first: interrupt it and the printable artifact is gone while its
            # stamp still names the current HTML. The rename is the only moment the book changes.
            #
            # prefer_css_page_size honours the book's own @page rule, so the sheet size and the
            # imposition come from the stylesheet rather than from whoever hit Cmd+P.
            tmp = staged_pdf(p)
            try:
                pg.pdf(path=tmp, prefer_css_page_size=True, print_background=True)
                os.replace(tmp, p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            # record WHICH html this pdf came from, and what the pdf is, so staleness is a fact
            write_stamp(p, h)
            print(f"  {os.path.relpath(p, ROOT)}  {os.path.getsize(p)/1e6:.1f} MB")
            done.append(p)
        b.close()
    return done


def main():
    argv = sys.argv[1:]
    flags = [a for a in argv if a.startswith("-")]
    slugs = [a for a in argv if not a.startswith("-")]
    # REFUSE AN OPTION THIS TOOL DOES NOT UNDERSTAND. `check = "--check" in sys.argv` was exact
    # membership and every other dash-argument was silently discarded, so `-check`, `--chek`,
    # `--verify` and `-n` all fell through to the branch that REWRITES all 15 books. Measured on a
    # genuinely stale book: `-check` exported it and exited 0, and the `--check` that followed then
    # returned 0 too. The gate did not check; it made itself true and said nothing.
    unknown = [f for f in flags if f != "--check"]
    if unknown:
        print(f"unknown option(s): {' '.join(unknown)}\n"
              f"usage: export_pdf.py [--check] [<course-slug> ...]")
        return 2
    check = "--check" in flags
    built = pairs()
    if not built:
        print("no built books found (build one first: COURSE=<slug> python3 generate.py)")
        return 1
    items = pairs(set(slugs) or None)
    if not items:
        # The message above is right for an empty tree and WRONG here: books are built and only the
        # slug matched nothing (`--check merion` for merion-golf-club). It sent the reader off to
        # rebuild a corpus that was already on disk, at up to 4.1 GB of LiDAR a course -- the worst of
        # the twelve here is callippe-preserve-golf-course. It quoted "~300 MB", which is the SMALLEST
        # non-zero course in this corpus offered as the typical one, the same median-quoted-as-worst
        # shape 8869583 fixed at the tee-pad end. Both figures are derived by
        # test_the_export_tools_account_of_what_a_rebuild_costs_is_the_corpus_on_disk.
        #
        # And it counted BOOKS while listing COURSES: `len(built)` is 15, the deduplicated list under it
        # is 12, and the two read as a mismatch. Each number now names what it counts.
        courses = sorted({os.path.basename(os.path.dirname(h)) for h, _p in built})
        print(f"no book matches {' '.join(sorted(slugs))} -- {len(courses)} course(s) are built here, "
              f"{len(built)} book(s) counting enlarged editions:\n  " + "\n  ".join(courses))
        return 1
    if check:
        bad = stale(set(slugs) or None)
        if bad:
            print(f"STALE: {len(bad)} of {len(items)} PDF(s) do not match their HTML -- the PRINTED "
                  f"book does not match the engine:")
            for _h, p, tag, why in bad:
                print(f"   {os.path.relpath(p, ROOT)}  [{tag}] ({why})")
            print("  Re-run: python3 tools/export_pdf.py")
            return 1
        print(f"all {len(items)} PDF(s) match the HTML they were exported from")
        return 0
    print(f"exporting {len(items)} book(s)")
    return 0 if export(items) is not None else 1


if __name__ == "__main__":
    sys.exit(main())
