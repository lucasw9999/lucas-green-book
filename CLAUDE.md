# Lucas Green Book — build rules

These rules govern every build. They are not style preferences; two of them are what the
project's legal position rests on, and one is what its promise to a junior golfer rests on.

## 1. Two rules that never bend

- **Never print a number the data does not support.** Refusing to print is always safer than
  printing a wrong number. If a figure cannot be derived from the sources below, the book leaves
  it out and says so.
- **Never omit a hazard the golfer can reach.** When in doubt, over-warn. A kid aims at what the
  book shows as safe.

## 2. Everything the book prints is generated from open and public-domain data

| What | Source | Licence |
|---|---|---|
| Hole & green geometry | OpenStreetMap contributors | ODbL 1.0 |
| Slope, contours, arrows, elevation | USGS 3DEP LiDAR — **computed here**, never copied | U.S. public domain |
| Par, yardage, handicap, rating/slope | Facts from the published scorecard | facts, not copyrightable |
| Aerial tracing, where OSM lacks a green | USDA NAIP | U.S. public domain |

Nothing else generates anything a book prints. No commercial green-reading product's data,
imagery, artwork, layout or trade dress is used, copied or referenced — see `legal/`.

## 3. Provenance recorded in this repository is open-data provenance only

Everything written down here — `legal/**`, code, comments, docstrings, variable and test names,
commit messages, PRs, issues, docs, and the books themselves — records **only** how a figure was
generated from the sources in §2. State the open source a number came from:

> "computed from public-domain USGS 3DEP LiDAR" · "measured from the OSM centreline and the mapped
> tee polygons" · "facts from the published scorecard"

Do **not** record a figure as having been sourced from, checked against, or verified against any
third-party or commercial compilation of course data. If a figure's provenance cannot be
stated in open-data terms, say plainly that it is single-source or unresolved — an honest gap in
writing is worth more than a citation that muddies §2.

`tests/test_r17_clean.py` enforces this and fails the build when a tracked file breaks it.

**This is separate from, and does not weaken, the protective statements in `legal/` that name
commercial products in order to disclaim using them.** Those must stay. The distinction:
*"we never used X" belongs here; "we checked against X" does not.* References to the USGA also
stay — it is the body that publishes course ratings and authors Rule 4.3, not a directory.

## 4. `courses/` is gitignored and is the only copy of the corpus

It holds every built book, every derived 0.4 m green surface, the OSM caches and the
hand-transcribed scorecards. **It is not in git. There is no undo.** Treat it as read-only unless
a build stage owns the file, back up before editing a `course.json`, and never commit anything
under `courses/`, `outreach/` or `app/`. Only `laz/` is re-downloadable.

## 5. Working rules

- Never work on `main`; branch first. Stage files explicitly by path — never `git add -A`.
- Never `git commit --amend` or `git stash` without a pathspec.
- Never weaken, skip, `xfail` or delete a test to get green; never add an ignore directive; never
  edit CI config or `pytest.ini`.
- Five gates must pass: `tools/export_pdf.py --check`, `tools/gen_provenance.py --check`,
  `tools/gen_disclaimers.py --check`, `tools/check_scale.py`, `tools/check_osm_bbox.py --all`.
  Use `--check`; the writing branches rewrite real artifacts.
- Run the suite in a shuffled order sometimes — it rebinds `COURSE` and drops modules from
  `sys.modules`, so a test can silently reconfigure the next one.
- `legal/03` and `legal/05` are **generated**. Regenerate them with their tools; never hand-edit.
- Prefer deriving a published figure over typing it. A hand-typed count goes stale the moment the
  corpus changes; several have.

## 6. Adding a course

Follow `PIPELINE.md`. Before spending a build, check that the elevation data still describes
today's ground — a course rebuilt or moved since the survey cannot be given green reads, and
`poppy-ridge` ships blank greens for exactly that reason. Cross-check the scorecard's par against
OSM's own `golf=hole` tags, confirm each tee's per-hole yardages sum to the total the card prints,
and record rating and slope **together or not at all** — a rating without its slope, or a women's
figure printed in a men's column, is the defect class this project has already had to withdraw.
