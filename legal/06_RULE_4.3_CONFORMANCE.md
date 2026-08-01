# Rule 4.3 Conformance — why "Designed to conform" is honest

The cover says **"Designed to conform · Rule 4.3."** This documents why that claim is truthful
and defensible (and why we did NOT say "conforms" or "USGA‑approved").

## The rule
The size and scale limits are **not** in the body of Rule 4.3 — they are in **Clarification 4.3a/1,
"Limitations on Using Green‑Reading Materials"** (USGA/R&A, effective 1 January 2023; re‑checked
2026‑07‑29, unchanged). Verbatim:
- *"Any image of a putting green must be limited to a scale of 3/8 inch to 5 yards (1:480) or
  smaller"* — a **ceiling**, so a green printed smaller (1:600, say) is fine, and
- *"Any book or other paper containing a map or image of a putting green must not be larger than
  4 1/4 inches x 7 inches."*
- No magnification. Hand‑drawn notes must sit inside a size‑limit book and be written by the player
  and/or caddie.

A pre‑printed book falls under **Rule 4.3a(3)** — information gathered before the round, allowed.
**Nothing in Rule 4.3 limits contour interval, arrow density or slope percentages**; only scale,
size and magnification. Note these limits **apply by default in every competition** (general
penalty for a first breach, disqualification for a second) — they are not Committee‑optional.
What *is* Committee‑level is that **neither the USGA nor the R&A "approves" green books**: there is
no conformance list for them, unlike clubs and balls.

## Two Local Rules a Committee may adopt, which this book cannot satisfy
- **Model Local Rule G‑11** — the Committee may require players to use **only a yardage book it has
  approved**. Where G‑11 is in effect, this book may not be used to read a green **even if perfectly
  scaled**, because it is not the approved book. G‑11's own text says it "is intended only for the
  highest levels of competitive golf."
- **Model Local Rule G‑12** — bans referencing **any** material to help read the line of play on the
  putting green.

So "confirm with your Committee" is not a cure for an over‑scale card; it is a check on whether
G‑11/G‑12 is in force at your event. The books say to confirm before competition for this reason.

## How the product is built to stay within it
- **Green print scale:** rendered at **0.36 in : 5 yd**, i.e. ~4% **under** the 3/8 in (0.375 in)
  cap — a deliberate safety margin so print/rounding can't push a green over the limit.
  (See `render_green.py`: `legal_kf = 0.36 * px_m / 4.572`, then `kf = min(legal_kf, fit_kf)` —
  0.36 is a CEILING and the panel fit usually binds first: measured, 26 of 198 greens reach it,
  median 1:588.)
- **Measured, not asserted.** The intended cap was once defeated by a single CSS rule: the size was
  emitted as an SVG `width=` presentation attribute, which has zero specificity, so the stylesheet
  overrode it and 15 of 198 greens printed over the limit while three documents claimed the cap
  held. `tools/check_scale.py` now **lays every book out in a real browser under print media and
  measures the drawn green there**, exiting non‑zero above 0.375 in : 5 yd. Latest run:
  **198/198 conforming, worst 0.3602 in : 5 yd (1:500)**, 4.0% margin. Never trust the renderer's
  intent again — measure the artifact.

  Two precise statements about what that gate does and does not do, because an earlier revision of
  this file overstated it:
  - It gates on the **browser layout under print media**, not on the exported PDF. It also reports
    the printed 5‑yd bar length read out of the PDF, and **that figure gates too** —
    any bar over 0.375 in is appended to the failure list and exits non‑zero
    (`check_scale.py`: `over_bar` → `failures`), because the legal claim is about the
    ARTIFACT. (Until this was corrected the gate measured the SCREEN layout while the README
    claimed print media — so a print‑only CSS rule could have enlarged a green past the cap without
    tripping it. Screen and print layouts were in fact identical, so no shipped number was wrong.)
  - The exported **PDF is checked separately**: `tools/export_pdf.py --check` proves each PDF was
    produced from the HTML currently on disk (by recorded content hash), and a test reads the printed
    card size straight out of the PDF's crop marks and compares it to the 4.25 × 7 in limit.
- **Per‑hole, not per‑book.** Scale is computed per green, so it legitimately varies (roughly 1:500
  to 1:945). Per the USGA's own FAQ (Q9), if one image did exceed the cap only **that hole's** image
  becomes unusable for reading the green — the rest of the book stays fine.
- **Book size:** cards are **3.5 × 5.0 in** — well under the 4.25 × 7 in cap.
  (See `config.py`: `CARD_DEFAULT_W_IN, CARD_DEFAULT_H_IN = 3.5, 5.0`; `CARD_W_IN`/`CARD_H_IN` are
  per‑course overrides and no course sets `"card"`, so every built book is 3.5 × 5.0 in.)
- **Which books this covers, and the one it does not.** Everything above is about the **standard
  pocket edition**, the book meant for competition. The **enlarged edition**
  (`COACH=1`) deliberately breaks the scale cap so the greens read at arm's length: measured off its
  own layout under print media, across all 54 of its greens, it prints **0.368–0.599 in : 5 yd
  (1:489 to 1:301) — from 2% UNDER the cap to 60% over**, with 53 of the 54 over it
  (monarch‑bay hole 14 alone lands inside). Measured off the browser layout, not the PDFs:
  the enlarged edition prints **no 5‑yd scale bar at all** (`render_green.py` emits it only
  when `tournament=True`), so there is nothing in those PDFs to measure.
  That is a design decision, not a defect, and it is stated on the enlarged edition's own guide card:
  *"Printed larger than tournament scale: a practice aid, NOT a conforming competition book under
  Rule 4.3. Use the pocket edition in competition."* It also omits the "DESIGNED TO CONFORM · RULE 4.3" cover badge that the
  pocket book carries, and it sits **outside** the 198/198 gate above rather than passing it. `tools/check_scale.py`
  now measures the enlarged books too — every figure in this paragraph is its output, median
  **0.458 in : 5 yd (1:393)** — but reports them in a separate, non‑gating section, because gating
  an edition built to exceed the cap would be a gate against a design decision. Recorded here because a conformance document that never
  mentions the one edition that does not conform invites the reader to assume every book does.

## Why the wording is safe
- We say **"Designed to conform,"** not "conforms" / "legal" / "USGA‑approved." It is an
  accurate statement of design intent, not a guarantee of official sanction.
- The fine print makes it conditional: *"designed to fall within the size & scale limits …
  but conformance is not guaranteed for every hole — confirm with your Committee before
  competition; the maker is not responsible for any ruling, penalty or disqualification."*
- The product is **free / not for sale**, so Lanham Act false‑advertising (which needs a
  commercial ad and competitor injury) has no real hook; a consumer‑protection theory needs a
  paying, deceived consumer — absent here.

## Rule going forward
Never imply official approval (no "USGA/R&A approved," no governing‑body logos). Keep the
marketing card‑size number equal to the actual trim (≤ 4.25 × 7). Keep the green scale ≤ 3/8:5.
