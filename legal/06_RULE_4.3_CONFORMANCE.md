# Rule 4.3 Conformance — why "Designed to conform" is honest

The cover says **"Designed to conform · Rule 4.3."** This documents why that claim is truthful
and defensible (and why we did NOT say "conforms" or "USGA‑approved").

## The rule
Rule of Golf **4.3** limits green‑reading materials in competition to:
- **Image scale** no more detailed than **3/8 inch : 5 yards** (1:480), and
- a book **no larger than 4.25 × 7 inches**,
- showing only significant slopes/tiers (arrows, contours and % are allowed at that scale).
Conformance is a **Committee‑level, per‑competition** determination — **neither the USGA nor
the R&A "approves" green books.**

## How the product is built to stay within it
- **Green print scale:** rendered at **0.36 in : 5 yd**, i.e. ~4% **under** the 3/8 in (0.375 in)
  cap — a deliberate safety margin so print/rounding can't push a green over the limit.
  (See `render_green.py`: `kf = 0.36 * px_m / 4.572`.)
- **Book size:** cards are **3.5 × 5.0 in** — well under the 4.25 × 7 in cap.
  (See `config.py`: `CARD_W_IN = 3.5`, `CARD_H_IN = 5.0`.)

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
