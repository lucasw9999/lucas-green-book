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
fails when a PDF is older than its HTML.

Run:  python3 tools/export_pdf.py                 # every built course (and coach edition)
      python3 tools/export_pdf.py merion-golf-club
      python3 tools/export_pdf.py --check          # exit 1 if any PDF is stale; exports nothing
"""
import glob
import hashlib
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _headless_shell():
    """The bundled chrome-headless-shell that matches the installed Playwright build."""
    hits = sorted(glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/"
        "chrome-headless-shell")))
    return hits[-1] if hits else None


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


def src_hash(html):
    return hashlib.sha256(open(html, "rb").read()).hexdigest()


def stamp_path(pdf):
    return pdf + ".src"


def stale(only=None):
    """Books whose PDF is missing, or was not exported from the CURRENT html.

    Compares a recorded content hash of the source HTML rather than mtimes. mtime is a proxy that
    false-positives on any copied or freshly checked-out tree (cp/rsync/git touch the html), and a
    gate that cries wolf gets ignored -- which is how the PDFs drifted three commits behind in the
    first place."""
    bad = []
    for h, p in pairs(only):
        if not os.path.exists(p):
            bad.append((h, p, "not exported")); continue
        sp = stamp_path(p)
        rec = open(sp).read().strip() if os.path.exists(sp) else None
        if rec is None:
            # No stamp: this PDF was produced by something other than this tool, so its provenance
            # is UNKNOWN, not proven stale. Falling back to mtime looked rigorous but false-positived
            # on any copied or checked-out tree (cp/rsync/git rewrite the html mtime), and a gate
            # that cries wolf is a gate people switch off.
            bad.append((h, p, "unverifiable (exported by hand; no source hash)"))
        elif rec != src_hash(h):
            bad.append((h, p, "exported from a DIFFERENT html"))
    return bad


def export(items):
    from playwright.sync_api import sync_playwright
    exe = _headless_shell()
    done = []
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
            # prefer_css_page_size honours the book's own @page rule, so the sheet size and the
            # imposition come from the stylesheet rather than from whoever hit Cmd+P.
            pg.pdf(path=p, prefer_css_page_size=True, print_background=True)
            # record WHICH html this pdf came from, so staleness is a fact rather than a guess
            with open(stamp_path(p), "w") as f:
                f.write(src_hash(h) + "\n")
            print(f"  {os.path.relpath(p, ROOT)}  {os.path.getsize(p)/1e6:.1f} MB")
            done.append(p)
        b.close()
    return done


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    check = "--check" in sys.argv
    items = pairs(set(args) or None)
    if not items:
        print("no built books found (build one first: COURSE=<slug> python3 generate.py)")
        return 1
    if check:
        bad = stale(set(args) or None)
        if bad:
            print(f"STALE: {len(bad)} of {len(items)} PDF(s) do not match their HTML -- the PRINTED "
                  f"book does not match the engine:")
            for _h, p, why in bad:
                print(f"   {os.path.relpath(p, ROOT)}  ({why})")
            print("  Re-run: python3 tools/export_pdf.py")
            return 1
        print(f"all {len(items)} PDF(s) match the HTML they were exported from")
        return 0
    print(f"exporting {len(items)} book(s)")
    return 0 if export(items) is not None else 1


if __name__ == "__main__":
    sys.exit(main())
