# Lucas Green Book — Legal & Copyright File

This folder is the **provenance and clearance record** for the Lucas Green Book project.
Its purpose: if anyone ever claims "you copied someone's data / you don't have the rights,"
you can hand them this folder and show, source by source, that every distributed book is
built only from **open** and **public‑domain** data plus **facts**, independently created.

> **Not legal advice.** This is an internal risk assessment prepared with an adversarial
> review. For absolute certainty before wide distribution, a ~15‑minute review by a licensed
> IP attorney is cheap insurance. Nothing here creates an attorney–client relationship.

## What's in here
| File | What it covers |
|---|---|
| `00_SUMMARY_AND_VERDICT.md` | The bottom line: what's clean, what's flagged |
| `01_DATA_SOURCES_AND_LICENSES.md` | Every data source, its license, and how we comply |
| `02_ATTRIBUTIONS.md` | The exact attribution notices we use |
| `03_PROVENANCE_BY_COURSE.md` | Per‑course: exactly what data built each book |
| `04_INDEPENDENT_CREATION_DEFENSE.md` | The hand‑to‑a‑challenger statement + why it holds — **local‑only, not in git** |
| `05_DISCLAIMER_TEXT.md` | The full "About & legal" text printed in every book — **generated** |
| `06_RULE_4.3_CONFORMANCE.md` | Why the "Designed to conform · Rule 4.3" claim is honest |
| `07_POPPY_RIDGE_ESRI_IMAGERY.md` | The ONE flagged item and the decision on it |
| `08_AUDIT_2026-07-13.md` | The full audit + adversarial findings + action checklist — **local‑only, not in git** |
| `09_GREEN_SURFACE_REPEATABILITY.md` | What the printed slope numbers are worth, measured across
repeat LiDAR flights and flight-line overlap |
| `10_SOFTWARE_DEPENDENCIES.md` | Every library the build uses and its licence |
| `11_HORIZONTAL_EARTH_MODEL.md` | The WGS84 local ground scales every printed distance is computed on, the
measured offset against WGS84, and the four cards whose printed depth it rounds the other way |

**Two of the records above are local‑only and deliberately not in git**, so a copy of this folder
will have twelve entries and ten files. `04` is argument rather than fact, and it asserted
patent non‑infringement that no freedom‑to‑operate search supports; `08` is a dated internal audit
snapshot carrying this project's own severity ratings of where it is weakest. Both of their factual
outcomes are in `01`–`03` and `07`, which stay public — what is withheld is the self‑assessment, not
the evidence. The reasoning is recorded at `.gitignore:58‑68` and under **Risk review** in
`00_SUMMARY_AND_VERDICT.md`. Nothing else in the index is missing.

## One‑line verdict
**All eleven distributed courses — fourteen books to give away (eleven pocket, three enlarged)**, are clean, and Poppy Ridge (yardage‑mode, personal)
is clean too. The project contains **no Esri/Maxar, Google, Apple or Bing imagery anywhere** — the
one such file, the Poppy Ridge aerial, was **rebuilt from public‑domain USDA NAIP on 2026‑07‑13**
and the Esri‑derived originals were deleted (see `07_...`). Every book is built only from
OpenStreetMap geometry (ODbL), slope computed by us from public‑domain USGS 3DEP LiDAR, scorecard
**facts**, and public‑domain NAIP where an aerial or a missing green was needed.

Per‑course detail lives in `03_PROVENANCE_BY_COURSE.md`, which is **generated** from the build
artifacts (`python3 tools/gen_provenance.py`) so it cannot drift from what was actually built.

`05_DISCLAIMER_TEXT.md` is generated the same way, by `python3 tools/gen_disclaimers.py`, which
extracts the printed words straight out of the built books. It had drifted badly while
hand-maintained — describing six books when there were twelve, and omitting the trademark and
CC BY-NC-ND lines that every book actually prints — and a "verbatim" legal record that is not
verbatim is worse than none. Both generators take `--check`, which the test suite runs.
