# Software Dependencies & Their Licences

Every Python package this project asks you to install, its licence, and whether it constrains how
this project's own code may be licensed. Verified from each package's installed metadata
(`importlib.metadata`), not from memory.

This file exists because `legal/` was thorough about **data** licences and silent about **software**
licences — and that asymmetry is exactly how an AGPL dependency sat in `requirements.txt` unnoticed.

## Nothing here is redistributed

This repository ships **70 tracked files: source, docs, one original banner image and one 3D-print model.** No dependency
is vendored, bundled, or re-published. The binary-attribution duties in BSD/MIT/Apache attach to
*redistribution*, so they are not triggered. The list below is hygiene and, for one entry, a real
compatibility question.

## Default install (`pip install -r requirements.txt`)

| Package | Version verified | Licence | Copyleft? |
|---|---|---|---|
| numpy | 2.4.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | no |
| scipy | 1.17.1 | BSD-3-Clause | no |
| laspy | 2.7.0 | BSD-2-Clause | no |
| lazrs | 0.8.1 | MIT | no |
| pyproj | 3.7.2 | MIT | no |
| playwright | 1.59.0 | Apache-2.0 | no |
| rasterio | 1.4.4 | BSD-3-Clause | no |
| pytest | 9.0.3 | MIT | no |

All permissive. None restricts how this project's own code is licensed.

Note that `playwright` the Python package is Apache-2.0, but the **Chromium** it drives is not
pip-installed — `python3 -m playwright install chromium` fetches it separately, under Chromium's own
BSD-3-Clause-and-others terms. Chromium is used as a *tool* that prints a PDF; nothing of it is
embedded in a book.

## Optional, and deliberately excluded from the default install

| Package | Version verified | Licence | Copyleft? |
|---|---|---|---|
| **PyMuPDF** | 1.27.2.2 | **"Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"** | **yes — AGPL-3.0** |

That string is PyMuPDF's own installed metadata, verbatim.

**Why it is separated out.** AGPL-3.0 requires a work based on the program to be conveyed under
AGPL-3.0, and forbids imposing further restrictions (§7, §10). This project's code is **PolyForm
Noncommercial 1.0.0**, which restricts commercial use — that is exactly such a further restriction.
The two do not compose for a combined work. Artifex dual-licenses MuPDF specifically to monetise this
and has enforced it (*Artifex v. Hancom*), so the licensor is not theoretical.

**What is and is not affected.**

- **No book is built with it.** PyMuPDF is used only by verification tooling
  (`tools/check_scale.py`) and by the test suite. The books and every figure in them are produced
  without it.
- **Nothing AGPL-licensed is redistributed here.** It is not vendored; this repo conveys only its own
  source.
- **The import is guarded.** `tools/check_scale.py` wraps it in `try/except ImportError` and returns a
  stated reason when absent, so the engine and the layout half of the Rule 4.3 gate run without it.
- **What you lose without it:** the *printed-artifact* half of the scale check — measuring the text
  spans and vector scale bar inside the exported PDF, as opposed to measuring the rendered HTML
  layout. Both halves existed because a book can conform in layout and still print wrong; if you want
  that second measurement, install PyMuPDF yourself and accept its terms.

It was previously an unconditional line in `requirements.txt`, which told every user to install it and
put an AGPL library on the critical path of this project's headline conformance claim.

**If the printed-artifact measurement should be part of the default gate again**, the replacement is
`pypdf` (BSD-3-Clause) or `pdfplumber` (MIT) — `check_scale.py` needs only text spans with positions
and vector line rectangles, which both provide. That would remove the only copyleft exposure in the
dependency set entirely.

## How to re-verify this file

```bash
python3 - <<'EOF'
import importlib.metadata as md
for p in ("numpy","scipy","laspy","lazrs","pyproj","rasterio","playwright",
          "pytest","pymupdf"):
    try:
        m = md.metadata(p)
        expr = (m.get("License-Expression") or "").strip()
        cls = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or [])
               if "License ::" in c]
        print(f"{p:12s} {m['Version']:12s} {expr or cls or m['License']}")
    except Exception:
        print(f"{p:12s} not installed")
EOF
```

Re-run it when pinning or bumping anything. A licence can change between releases — PyMuPDF's did not,
but `rasterio` moved maintainers, and a permissive-to-copyleft change in any of these would matter.

The tracked-file count in *Nothing here is redistributed* is not re-verified by hand at all: it is
generated from `git ls-files` by `python3 tools/gen_repo_figures.py`, and `--check` fails while it is
stale. That one sentence is the only generated thing in this file; everything else here is authored.

Every version in the tables above must also be one `requirements.txt` actually permits. The two files
are separate accounts of the same dependency set — this one records what was verified, that one records
what a stranger is told to install — so a bump that moves a version outside its declared range makes the
pair contradict itself. `test_no_declared_version_floor_is_one_the_rest_of_the_declared_set_rejects`
asserts that, and the stronger property behind it: no floor `requirements.txt` declares may sit outside
what another declared package requires of it. `lazrs` is declared `>=0.8,<0.9` for exactly that reason —
the range is `laspy`'s own, carried in an extra (`laspy[lazrs]`) that this project does not request, so
no resolver ever reads it and the requirement line is the only place it can live. It was `>=0.6`, which
told a stranger to install a `lazrs` that the `laspy` beside it does not support.
