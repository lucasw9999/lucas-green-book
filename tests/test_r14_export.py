#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The PDF export gate, and the two records that say what it earns.

`tools/export_pdf.py` is the only thing standing between the engine's honesty rules and the PRINTED
book, which is the only version that reaches a golf course. legal/06 is a legal record that makes a
claim about what that gate is worth, so an overclaim there is itself the defect. Each test below names
a hole that was measured open on this tree, and drives it on a probe tree under tmp_path -- never on
courses/, which is gitignored, has no copy anywhere, and is what these probes would have to corrupt.

The four helpers below are deliberate local copies of the ones in test_phase1_regressions.py rather
than an import of that module: this file has to stand alone under
`pytest tests/test_r14_export.py`, and importing a 30 000-line sibling to borrow twenty lines of
scaffolding couples the two files' import-time state for nothing. conftest.py's autouse guards apply
here either way -- that is why they live in conftest.
"""
import glob
import hashlib
import importlib.util
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# A whole, tiny PDF: a header and a trailer, which is all is_whole_pdf reads. Used where no real book
# is on disk, so this file's probes run on a fresh clone too.
_MINIMAL_PDF = (b"%PDF-1.4\n"
                b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 252 360]>>endobj\n"
                b"trailer<</Root 1 0 R>>\n%%EOF\n")


def _sha256(data):
    """A digest computed HERE, so a stamp this suite writes is not the tool's own arithmetic echoed back."""
    return hashlib.sha256(data).hexdigest()


def _a_shipped_book_pdf():
    """The bytes of a real shipped book, so a probe damages a real one. None on a fresh clone."""
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        if not os.path.basename(os.path.dirname(p)).startswith("_"):
            with open(p, "rb") as fh:
                return fh.read()
    return None


def _probe_tree(tmp_path, books, html_text=None):
    """A fake repo root holding `books` == {slug: (pdf bytes or None, stamp text or None)}.

    Returns (root, {slug: (html, pdf)}). Never the corpus, and not negotiable: every probe here writes
    a lying stamp or torn bytes beside a book.
    """
    root = tmp_path / "probe-root"
    out = {}
    for slug, (pdf_bytes, stamp) in books.items():
        d = root / "courses" / slug
        d.mkdir(parents=True)
        html = d / "greenbook.html"
        html.write_text(html_text if html_text is not None else f"<html><body>{slug}</body></html>",
                        encoding="utf-8")
        pdf = d / "greenbook.pdf"
        if pdf_bytes is not None:
            pdf.write_bytes(pdf_bytes)
        if stamp is not None:
            (d / "greenbook.pdf.src").write_text(stamp, encoding="utf-8")
        out[slug] = (str(html), str(pdf))
    return root, out


def _export_pdf_bound_to(root, tmp_path, name):
    """A COPY of tools/export_pdf.py, loaded under its own name and pointed at a fake `root`.

    Loaded by spec rather than importlib.import_module so nothing about the real module's identity --
    or sys.modules["export_pdf"], which the rest of the suite imports -- is disturbed.
    """
    with open(os.path.join(ROOT, "tools", "export_pdf.py"), encoding="utf-8") as fh:
        src = fh.read()
    path = tmp_path / f"{name}.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = str(root)
    return mod


def _tags(mod):
    return [t for _h, _p, t, _w in mod.stale()]


def _flowed(text):
    """Markdown reduced to the prose a reader sees: no emphasis, no code ticks, one line, ASCII hyphens."""
    return " ".join(text.replace("*", "").replace("`", "").replace("‑", "-")
                    .replace("–", "-").replace("—", "--").split())


def test_a_stamp_naming_two_digests_for_one_key_names_neither_whichever_line_came_last(tmp_path):
    """read_stamp resolved two KEYED lines for one field to whichever came LAST, so a contradictory
    note passed or failed depending on line ORDER.

    A previous round closed this for the legacy BARE form and left the keyed form open, while the
    function's own docstring asserts "A NOTE THAT NAMES TWO DIFFERENT HTML DIGESTS NAMES NEITHER".
    Measured on a probe tree before this test existed:

      html <real> / html <other> / pdf <real>   -> stale() == ['wrong-source']   (caught)
      html <other> / html <real> / pdf <real>   -> stale() == []   *** CLEAN PASS ***
      pdf <wrong> / pdf <real>  (+ html <real>) -> stale() == []       (last line won)
      pdf <real> / pdf <wrong>  (+ html <real>) -> stale() == ['wrong-bytes']

    So a stamp naming two contradictory HTML digests passed the gate, and a stamp naming two
    contradictory PDF digests was resolved to whichever the author happened to append second. Both
    orders of both keys are driven here, and the answers must be IDENTICAL under reordering: an
    order-dependent reading of a self-contradictory note is the defect, not the direction it fell in.

    A field with two different values is dropped, which read_stamp already documents as the "does not
    agree with the html" answer -- a refusal, distinct from "no note at all". The legacy shapes are
    driven too, because every one of the 15 shipped stamps was a single bare line once and a rewrite of
    this rule must not start failing them.
    """
    whole = _a_shipped_book_pdf() or _MINIMAL_PDF
    real = _sha256(b"<html><body>probe-golf-club</body></html>")
    other = _sha256(b"<html><body>a DIFFERENT book</body></html>")
    pdf_real, pdf_other = _sha256(whole), "1" * 64
    assert len({real, other, pdf_real, pdf_other}) == 4, "the probe digests are not four distinct values"

    def drive(label, stamp):
        root, books = _probe_tree(tmp_path / label, {"probe-golf-club": (whole, stamp)})
        mod = _export_pdf_bound_to(root, tmp_path, f"export_pdf_r14_{label}")
        pdf = books["probe-golf-club"][1]
        return mod, mod.read_stamp(pdf), _tags(mod)

    # ---- the html key: keyed/keyed, both orders, and the legacy shapes that must keep working.
    for label, stamp in (("keyed-real-first", f"html {real}\nhtml {other}\npdf {pdf_real}\n"),
                         ("keyed-other-first", f"html {other}\nhtml {real}\npdf {pdf_real}\n"),
                         ("bare-real-first", f"{real}\n{other}\n"),
                         ("bare-other-first", f"{other}\n{real}\n"),
                         ("keyed-and-bare", f"html {real}\n{other}\n")):
        mod, rec, tags = drive(label, stamp)
        assert rec is not None and "html" not in rec, (
            f"[{label}] the stamp names TWO html digests and read_stamp returns {rec}: a note that "
            f"names two htmls is not evidence for either of them, whichever line came last.")
        assert tags == [mod.WRONG_SOURCE], (
            f"[{label}] a book whose stamp contradicts itself about its own source comes back {tags}. "
            f"It is a PROVEN defect: whatever wrote the note recorded two answers and the tool cannot "
            f"pick one. A CLEAN PASS here is a stamp naming another book's html, admitted by order.")

    # ---- the pdf key: same rule, same both-orders requirement. Nothing proves these bytes now, so the
    #      verdict must be a refusal rather than a winner -- and it must not move when the lines swap.
    answers = {}
    for label, stamp in (("pdf-wrong-first", f"html {real}\npdf {pdf_other}\npdf {pdf_real}\n"),
                         ("pdf-real-first", f"html {real}\npdf {pdf_real}\npdf {pdf_other}\n")):
        mod, rec, tags = drive(label, stamp)
        assert rec is not None and "pdf" not in rec, (
            f"[{label}] the stamp names TWO pdf digests and read_stamp returns {rec}: one of them is "
            f"the file on disk, and a note that names both certifies neither.")
        assert tags and set(tags) <= set(mod.REASONS), (
            f"[{label}] a stamp naming two different pdf digests comes back {tags} -- the gate accepted "
            f"a note that contradicts itself about the bytes it is supposed to pin.")
        answers[label] = tags
    assert answers["pdf-wrong-first"] == answers["pdf-real-first"], (
        f"reordering two contradictory pdf lines changes the verdict: {answers}. Which line an author "
        f"appended second is not evidence about the book.")

    # ---- and a note that states the SAME digest twice states ONE digest. Both spellings, because the
    #      union rule above is what would break them. The bare pair is html-only, so it lands in the
    #      unverifiable state the next test is about rather than clean -- what matters here is that it
    #      still reads as the legacy html stamp and is not accused of naming two.
    for label, stamp, html_only in (("repeated-bare", f"{real}\n{real}\n", True),
                                    ("repeated-keyed", f"html {real}\nhtml {real}\npdf {pdf_real}\n"
                                                       f"pdf {pdf_real}\n", False)):
        mod, rec, tags = drive(label, stamp)
        want = [mod.UNSTAMPED] if html_only else []
        assert rec.get("html") == real, (
            f"[{label}] a note repeating one digest no longer reads as that digest ({rec}); every PDF "
            f"in this corpus carried one bare line before write_stamp gained its second field.")
        assert tags == want and mod.WRONG_SOURCE not in tags, (
            f"[{label}] a book whose stamp agrees with itself is reported {tags}, wanted {want}")


def test_a_stamp_that_never_recorded_the_pdfs_own_digest_is_not_reported_as_verified(tmp_path):
    """stale() skipped the PDF check entirely when the stamp had no `pdf` field, so legal/06's
    "byte-for-byte" sentence held only because today's corpus happens to be fully re-stamped.

    Measured before this test existed, on a book with an html-only stamp -- legacy bare line OR keyed --
    whose PDF bytes were ENTIRELY REPLACED with different bytes, trailer left intact:

      stale() == []      i.e. the gate reported nothing at all about a book it cannot verify.

    Nothing in this project required the shipped stamps to carry both fields, so restoring one older
    PDF+stamp pair from a backup would have made the legal record silently overclaim again. `--check` on
    a book whose note records the HTML alone cannot say the bytes are the export, and the honest answer
    is to SAY so: the state is unverifiable (the "cannot know" half of the verdicts, alongside a PDF
    with no note at all), never a silent pass. The companion of this test is
    test_every_shipped_stamp_records_both_digests_because_legal_06_rests_on_it, which is what makes the
    record's sentence true of the books actually on disk.
    """
    whole = _a_shipped_book_pdf() or _MINIMAL_PDF
    real = _sha256(b"<html><body>probe-golf-club</body></html>")
    replaced = b"%PDF-1.4\nnot the exported book at all\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    assert replaced != whole and replaced.startswith(b"%PDF-") and replaced.endswith(b"%%EOF\n")

    sentences = {}
    for label, stamp in (("legacy-bare-html-only", f"{real}\n"), ("keyed-html-only", f"html {real}\n")):
        for what, body in (("bytes untouched", whole), ("bytes ENTIRELY REPLACED", replaced)):
            root, books = _probe_tree(tmp_path / f"{label}-{what.split()[1]}",
                                      {"probe-golf-club": (body, stamp)})
            mod = _export_pdf_bound_to(root, tmp_path, f"export_pdf_r14_{label}_{what.split()[1]}")
            bad = mod.stale()
            tags = [t for _h, _p, t, _w in bad]
            assert tags == [mod.UNSTAMPED], (
                f"[{label}, {what}] a book whose note records the HTML alone comes back {tags}. "
                f"Nothing on disk pins its bytes, so the gate cannot verify it -- and legal/06 tells a "
                f"reader every shipped PDF is byte-for-byte the file the tool exported.")
            assert mod.WRONG_BYTES not in tags and mod.WRONG_SOURCE not in tags, (
                f"[{label}, {what}] reported as a PROVEN defect ({tags}) on a stamp that records no pdf "
                f"digest: nothing here proves anything about the bytes, which is the whole point.")
            sentences[(label, what)] = bad[0][3]

    why = sentences[("keyed-html-only", "bytes untouched")]
    assert re.search(r"digest of the PDF|PDF['’]s own digest|HTML digest alone|html alone", why,
                     re.I), (
        f"the reason reads {why!r}, which does not tell the reader WHAT is missing. A note recording "
        f"the html alone is a different state from no note at all, and the sentence is the only place "
        f"the two are told apart -- the tag they share is the coarse fact that neither can be judged.")

    # ...and the gate DOES verify when the stamp lets it: this is the state the corpus is in, and it is
    # what the html-only verdict above is measured against.
    root, books = _probe_tree(tmp_path / "fully-stamped", {"probe-golf-club": (whole, None)})
    mod = _export_pdf_bound_to(root, tmp_path, "export_pdf_r14_fully_stamped")
    html, pdf = books["probe-golf-club"]
    mod.write_stamp(pdf, html)
    assert sorted(mod.read_stamp(pdf)) == ["html", "pdf"] and _tags(mod) == [], (
        f"a book this tool just exported is not clean: {mod.stale()}")
    with open(pdf, "wb") as fh:
        fh.write(replaced)
    assert _tags(mod) == [mod.WRONG_BYTES], (
        f"the same byte replacement beside a FULL stamp comes back {_tags(mod)}; if this is not "
        f"WRONG_BYTES then the html-only verdict above is not measuring what it claims to")


def test_every_shipped_stamp_records_both_digests_because_legal_06_rests_on_it(tmp_path):
    """legal/06 tells a reader every shipped PDF is byte-for-byte the file the tool exported. That is
    only true of a book whose stamp records the PDF's OWN digest -- an html-only stamp is unverifiable
    (see the test above), and nothing but this assertion requires the shipped stamps to carry both.

    So the corpus is the claim's precondition, and it is checked here rather than assumed. Skips
    cleanly where no book is built, the way the other corpus tests in this suite do: courses/ is
    gitignored, and a skip is visibly not a pass.

    Parsed here rather than through read_stamp, so a bug in the reader cannot certify the stamps it
    reads -- then cross-checked against read_stamp, because a stamp the tool reads differently from
    this test is a stamp neither of us understands.
    """
    import export_pdf
    books = export_pdf.pairs()
    if not books:
        pytest.skip("no book is built here, so there is no stamp to read (build one: COURSE=<slug> "
                    "python3 generate.py, then python3 tools/export_pdf.py)")
    missing, partial = [], []
    for _h, pdf in books:
        sp = export_pdf.stamp_path(pdf)
        if not os.path.exists(sp):
            missing.append(os.path.relpath(pdf, ROOT))
            continue
        with open(sp, encoding="utf-8") as fh:
            fields = {ln.split()[0] for ln in fh.read().splitlines() if len(ln.split()) == 2}
        if fields != {"html", "pdf"}:
            partial.append(f"{os.path.relpath(sp, ROOT)} records {sorted(fields)}")
        assert sorted(export_pdf.read_stamp(pdf)) == sorted(fields), (
            f"{os.path.relpath(sp, ROOT)}: this test reads the fields {sorted(fields)} and read_stamp "
            f"returns {sorted(export_pdf.read_stamp(pdf))} -- one of the two is misreading the stamp")
    assert not missing and not partial, (
        f"legal/06 says every shipped PDF is byte-for-byte the file tools/export_pdf.py exported, and "
        f"that is unverifiable for {len(missing) + len(partial)} of {len(books)} book(s):\n  "
        + "\n  ".join(missing + partial)
        + "\n  Re-export those books (python3 tools/export_pdf.py <slug>) so the record is earned "
          "rather than assumed.")


def test_the_records_say_which_step_writes_the_stamp_and_which_only_re_derives_it(tmp_path):
    """legal/06 and README both attributed the RECORDING to `--check`, which records nothing.

    Both read "beside each book `tools/export_pdf.py --check` records a digest of the HTML and a digest
    of the exported PDF, then re-derives both from the files on disk" -- one step doing two jobs, one of
    which it cannot do. Measured here: `--check` is the read-only half (it is the branch that "exports
    nothing", and a read-only gate must not write), and write_stamp is called from export() alone.
    A reader who believes the check writes the stamp believes the gate certifies itself.

    The prose is graded by LOCALITY, because that is what the defect was: the words naming who records
    sit next to the verb, so `--check` inside the 90 characters before "records a digest of the HTML"
    is the misattribution, and `--check` must be what the doc names beside "re-derives". Locality is a
    heuristic about English and is stated as one; the behaviour it is grading is measured above it.
    """
    import export_pdf
    src = open(os.path.join(ROOT, "tools", "export_pdf.py"), encoding="utf-8").read()
    check_branch = src.split("if check:", 1)[1].split("\n    print(f\"exporting", 1)[0]
    assert "write_stamp" not in check_branch and "stale(" in check_branch, (
        "the --check branch of main() now writes stamps, so these two records would be right and this "
        "test is the thing that is wrong")
    export_body = src.split("def export(", 1)[1].split("\ndef ", 1)[0]
    callers = [ln.strip() for ln in src.splitlines()
               if "write_stamp(" in ln and not ln.strip().startswith("def ")]
    assert callers and all(ln in export_body for ln in callers), (
        f"the stamp is written from somewhere other than export(), so 'the export records it' is not "
        f"the whole truth: {[ln for ln in callers if ln not in export_body]}")

    # ...and that the gate really re-derives rather than trusting the note is measured by
    # test_legal_06s_account_of_the_pdf_export_gate_is_the_one_the_gate_earns; here we only grade WHO.
    for rel in ("legal/06_RULE_4.3_CONFORMANCE.md", "README.md"):
        with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as fh:
            flowed = _flowed(fh.read())
        rec = re.search(r"record(?:s|ing)? a digest of the HTML", flowed)
        assert rec, (
            f"{rel} no longer says the tool records a digest of the HTML, which is where it tells a "
            f"reader what the stamp beside each book is")
        subject = flowed[max(0, rec.start() - 90):rec.start()]
        assert "--check" not in subject, (
            f"{rel} attributes the RECORDING to --check, which records nothing -- the export writes the "
            f"stamp and --check only re-derives it and compares. It reads:\n  ...{subject}"
            f"{flowed[rec.start():rec.end() + 60]}...")
        derives = list(re.finditer(r"re-deriv(?:es|ed|ing)", flowed))
        assert derives, f"{rel} no longer says anything is re-derived from the files on disk"
        assert any("--check" in flowed[max(0, m.start() - 90):m.start()] for m in derives), (
            f"{rel} says something re-derives the digests but never names --check as the step that "
            f"does it, so the reader is left with the tool as one undivided action:\n  "
            + " | ".join(f"...{flowed[max(0, m.start() - 90):m.end()]}..." for m in derives))


def test_is_whole_pdfs_account_of_why_it_still_exists_matches_the_stamps_on_disk(tmp_path):
    """is_whole_pdf's docstring justified itself with "the stamps already on disk record the HTML alone:
    for those books a trailer is the only evidence the file is whole". That is no longer true of any of
    the 15 stamps -- every one of them records the PDF's own digest (the test above measures that), so a
    tear in a stamped book would also come back as a byte mismatch.

    The check still has to exist, for reasons that ARE live and are driven here rather than asserted:
    a book with no note beside it, or one recording the HTML alone, is unverifiable, and the trailer is
    then the only evidence it is whole; and because it runs first, a tear is named as a tear rather than
    as a generic byte mismatch. A docstring resting on a fact the tree has moved past is the defect --
    the next reader deletes the check, or trusts a claim about the corpus that stopped holding.
    """
    whole = _a_shipped_book_pdf() or _MINIMAL_PDF
    import export_pdf

    doc = export_pdf.is_whole_pdf.__doc__
    stale_claims = [s.strip() for s in re.split(r"(?<=[.;:])\s+", " ".join(doc.split()))
                    if re.search(r"stamps?\b[^.;:]*\bon disk", s)
                    and re.search(r"\b(?:HTML|html)\b[^.;:]*\b(?:alone|only)\b", s)]
    assert not stale_claims, (
        "is_whole_pdf still rests on the stamps recording the HTML alone:\n  "
        + "\n  ".join(stale_claims)
        + "\n  Every stamp on disk records the PDF's own digest now (see "
          "test_every_shipped_stamp_records_both_digests_because_legal_06_rests_on_it), so that is not "
          "why this check exists. Say what is.")

    # The reasons that ARE live, driven on a probe tree.
    torn = whole[:max(8, len(whole) // 10)]
    assert not torn.endswith(b"%%EOF\n"), "the torn probe still has a trailer"
    root, books = _probe_tree(tmp_path / "torn-unstamped", {"probe-golf-club": (torn, None)})
    mod = _export_pdf_bound_to(root, tmp_path, "export_pdf_r14_torn_unstamped")
    assert _tags(mod) == [mod.TRUNCATED], (
        f"a torn book with NO stamp beside it comes back {_tags(mod)}; there is no recorded digest to "
        f"catch it with, so the trailer is the only evidence, which is why this check exists")

    root, books = _probe_tree(tmp_path / "torn-stamped", {"probe-golf-club": (whole, None)})
    mod = _export_pdf_bound_to(root, tmp_path, "export_pdf_r14_torn_stamped")
    html, pdf = books["probe-golf-club"]
    mod.write_stamp(pdf, html)
    assert sorted(mod.read_stamp(pdf)) == ["html", "pdf"], (
        f"write_stamp records {sorted(mod.read_stamp(pdf))}, so the docstring's old account of the "
        f"stamps on disk may be true again and this test is asking the wrong thing")
    with open(pdf, "wb") as fh:
        fh.write(torn)
    assert _tags(mod) == [mod.TRUNCATED], (
        f"a torn book beside a FULL stamp comes back {_tags(mod)} -- the recorded digest would also "
        f"disagree, and naming it a byte mismatch tells the reader the file changed rather than that "
        f"it is the wreck of an interrupted write")


def _course_restoring_autouse_fixtures():
    """[(file, fixture name)] for every autouse fixture in tests/ that BINDS and RESTORES `COURSE`.

    Found by AST, so a comment or docstring discussing the fixture cannot stand in for it -- which is
    the failure mode `_code_only` exists for one level up, and the reason this walks the tree rather
    than grepping for a name. "Restores" means an operation on COURSE that runs AFTER the yield: the
    property README claims is teardown, and a fixture that binds without restoring is exactly the
    order-dependent suite the shuffle advice is about.
    """
    import ast
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            autouse = any(isinstance(d, ast.Call) and "fixture" in ast.unparse(d.func)
                          and any(k.arg == "autouse" and getattr(k.value, "value", None) is True
                                  for k in d.keywords)
                          for d in node.decorator_list)
            if not autouse:
                continue
            yields = [n.lineno for n in ast.walk(node) if isinstance(n, (ast.Yield, ast.YieldFrom))]
            if not yields:
                continue
            binds, restores = [], []
            for n in ast.walk(node):
                touches = False
                if isinstance(n, ast.Assign):
                    touches = any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                                  and t.slice.value == "COURSE"
                                  and ast.unparse(t.value).endswith("environ") for t in n.targets)
                elif isinstance(n, ast.Call):
                    touches = (ast.unparse(n.func).endswith("environ.pop") and n.args
                               and getattr(n.args[0], "value", None) == "COURSE")
                if touches:
                    (restores if n.lineno > min(yields) else binds).append(n.lineno)
            if binds and restores:
                out.append((os.path.relpath(path, ROOT), node.name))
    return out


def test_the_readmes_shuffled_order_advice_still_describes_this_suite(tmp_path):
    """README claims a safety property -- "leakage should be structurally impossible" -- and nothing
    graded the claim, only the count beside it.

    The property rests on ONE autouse fixture that binds `COURSE` before each test and restores it
    afterwards. Delete the restore, or move the fixture, and the README goes on promising isolation the
    suite no longer has: every test after a synthetic 2-tee fixture would run against that binding, which
    is how a real `IndexError` in render_hole stayed hidden for its whole life. That is a worse defect
    than a wrong count, because a reader trusts the shuffle less, not more.

    So the fixture is found by AST and the README's account of WHERE it lives is graded against where it
    was found. It is currently in the suite file rather than in conftest.py, which means a second test
    module -- this one -- does not inherit it, and README has to say so: conftest.py is the only file
    pytest loads for every module in the directory, which is the argument its own docstring makes for
    the deletion guard living there.
    """
    found = _course_restoring_autouse_fixtures()
    assert found, (
        "no autouse fixture in tests/ binds COURSE and restores it after the yield, so README's "
        '"leakage should be structurally impossible" is a property the suite does not have. Either the '
        "fixture was removed or its teardown was, and the shuffled-order advice is now the only thing "
        "standing between a rebinding test and the next one.")
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    para = re.search(r"Run the suite in a \*\*shuffled order\*\*.+?you find out it still is\.",
                     readme, re.S)
    assert para, "README no longer carries the shuffled-order paragraph this test grades"
    said = para.group(0)
    for rel, name in found:
        assert name in said and rel.replace(os.sep, "/") in said, (
            f"README's shuffled-order advice does not name {name} in {rel}, which is the fixture the "
            f"claim rests on. A reader who cannot find it cannot check whether the property still "
            f"holds -- and if the fixture MOVED (to tests/conftest.py, say, where every test module "
            f"would inherit it) the paragraph's scope sentence is now wrong.")
    assert "conftest" in said, (
        "README does not say how the fixture's location bounds the claim. It is not in tests/conftest.py, "
        "so tests in a second module do not inherit it -- state that, or the promise reads as covering "
        "the whole directory.")
