#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. All rights reserved.
# "Lucas Green Book" is a trademark of Lucas Wu.
# Published for reference. Not licensed for use, modification or redistribution.
# https://github.com/lucasw9999/lucas-green-book
"""
Build this repository's masthead and mark: assets/banner.png and assets/logo.svg.

WHY THIS IS A TOOL AND NOT A ONE-OFF. The books changed identity in September 2026 --
the cover became a cream field with an embossed contour ground, a gold frame floating
on it, and a monogram of a flag and the letter L. A masthead drawn by hand to look
"close enough" drifts away from the books the moment either moves. So every ink,
weight and proportion below is MEASURED off the cover plate the books print, and the
masthead is regenerated from those measurements rather than retouched.

    python3 tools/build_banner.py            # writes into ./assets
    python3 tools/build_banner.py <repo-root>

Needs `cairosvg` and `Pillow`. Nothing in the repository reads either output back;
they exist for the README.
"""
import math
import os
import sys

import cairosvg
import numpy as np
from PIL import Image

W, H = 1872, 487

# --- inks, measured off the crest plate -------------------------------------
CREAM_OUT = "#faf7f2"   # the plate's full-bleed canvas
CREAM_IN  = "#f8f5f0"   # the field inside the frame
GREEN     = "#014337"   # the frame band, as the plate prints it
INK       = "#00412f"   # GREEN BOOK, the monogram
INK_SOFT  = "#3a6b56"   # the tagline
GOLD      = "#866b39"   # ONE gold: rings, rules, diamond, the word LUCAS (4.69:1 on cream)
CONTOUR   = "#d2c7b5"   # the embossed contour field
STIPPLE   = "#e2d8cb"   # the dot patches

# --- frame: margin / green band / cream gap / gold rule ----------------------
# The plate runs 19 / 19 / 5 / 4 px on a 1536-tall canvas. Scaled to a masthead
# and rounded so each band lands on a whole pixel at 1x.
M, BAND, GAP, RULE = 9, 10, 4, 3
FIELD = M + BAND + GAP + RULE          # 26: first pixel of the field

# --- the lockup --------------------------------------------------------------
CX = W / 2
R = 62.0                # crest outer radius
CY = 112.0              # crest centre
Y_LUCAS = 226.0
Y_MAIN = 315.0
Y_RULE = 360.0
Y_TAG = 418.0


def blob(cx, cy, r0, coef, n=160, sx=1.0, sy=1.0):
    """A closed organic contour: r(t) = r0 * (1 + sum a_k sin(k t + p_k))."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        rr = r0 * (1 + sum(a * math.sin(k * t + p) for k, a, p in coef))
        pts.append((cx + rr * math.cos(t) * sx, cy + rr * math.sin(t) * sy))
    return pts


def smooth_path(pts):
    """Closed Catmull-Rom through pts, emitted as cubic beziers."""
    n = len(pts)
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d) + "Z"


def contour_family(cx, cy, r_start, r_step, count, coef, sx=1.0, sy=1.0, grow=1.0):
    """Nested contours around one high point, as on the plate: the innermost ring
    is embossed (heavier, with a soft under-shadow) and the outer ones fade out."""
    out = []
    r0 = r_start
    for i in range(count):
        wgt = 1.9 if i == 0 else 1.3
        op = 0.9 if i == 0 else max(0.20, 0.72 - 0.085 * i)
        p = smooth_path(blob(cx, cy, r0, coef, sx=sx, sy=sy))
        if i == 0:
            out.append(f'<path d="{p}" fill="none" stroke="{CONTOUR}" '
                       f'stroke-width="3.4" opacity="0.20" transform="translate(2,2.5)"/>')
        out.append(f'<path d="{p}" fill="none" stroke="{CONTOUR}" '
                   f'stroke-width="{wgt:.2f}" opacity="{op:.2f}"/>')
        r0 = r0 * grow + r_step
    return "\n    ".join(out)


def stipple(x0, y0, cols, rows, step, fade_from):
    """A square dot patch that fades out along its diagonal, as on the plate."""
    out = []
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * step
            y = y0 + r * step
            f = (c / max(cols - 1, 1) + r / max(rows - 1, 1)) / 2
            op = max(0.0, 1.0 - abs(f - fade_from) * 2.4)
            if op <= 0.02:
                continue
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.1" fill="{STIPPLE}" opacity="{op:.2f}"/>')
    return "\n    ".join(out)


def crest(cx, cy, r):
    """The 2026 monogram: two gold rings, a flag and a serif L, both in ink.

    Every number is the mark's own, normalised by the roundel's outer radius
    (108.5 px on the printed cover plate it was measured from): ring strokes at
    0.977r and 0.885r, both 0.046r wide; the flag's apex 0.373r right of centre;
    the L's arm ending in the upturned bracket the plate draws.
    """
    def P(dx, dy):
        return f"{cx + dx*r:.2f},{cy + dy*r:.2f}"

    def R_(x0, y0, x1, y1, rx=0.0):
        return (f'<rect x="{cx + x0*r:.2f}" y="{cy + y0*r:.2f}" '
                f'width="{(x1-x0)*r:.2f}" height="{(y1-y0)*r:.2f}" '
                f'rx="{rx*r:.2f}" fill="{INK}"/>')

    g = [
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{0.977*r:.2f}" fill="none" '
        f'stroke="{GOLD}" stroke-width="{0.0461*r:.2f}"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{0.885*r:.2f}" fill="none" '
        f'stroke="{GOLD}" stroke-width="{0.0461*r:.2f}"/>',
        # pole, rounded at the top as the plate's is, and its foot bar
        R_(-0.1659, -0.6134, -0.1014, 0.5392, rx=0.032),
        R_(-0.2673, 0.5346, 0.0000, 0.5760, rx=0.010),
        # the flag
        f'<path d="M{P(-0.0829,-0.5899)} L{P(0.3733,-0.4009)} L{P(-0.0737,-0.1659)} Z" fill="{INK}"/>',
        # the serif L: stem, arm, and the bracket that flares up off the arm's end
        f'<path d="M{P(0.1382,0.0691)} L{P(0.2212,0.0691)} L{P(0.2212,0.3733)} '
        f'L{P(0.3594,0.3733)} L{P(0.3594,0.4286)} L{P(0.1382,0.4286)} Z" fill="{INK}"/>',
        f'<path d="M{P(0.2995,0.3733)} L{P(0.3594,0.3410)} L{P(0.3594,0.3733)} Z" fill="{INK}"/>',
    ]
    return "\n    ".join(g)


MAIN_TEXT = ('<text x="{x:.1f}" y="{y:.0f}" text-anchor="middle" '
             'font-family="Helvetica,Arial,sans-serif" font-size="82" letter-spacing="1" '
             'font-weight="800" fill="{fill}">GREEN BOOK</text>')


def wordmark_right_edge():
    """Where GREEN BOOK actually ends, measured rather than guessed.

    The trademark mark has to sit just off the K, and its offset is a property of
    the rendered type, not of the string -- a font substitution would move it.
    So the wordmark is rendered alone and its ink is measured.
    """
    probe = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}">'
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>'
             + MAIN_TEXT.format(x=CX, y=Y_MAIN, fill="#000000") + '</svg>')
    png = "/tmp/_wordmark_probe.png"
    cairosvg.svg2png(bytestring=probe.encode(), write_to=png,
                     output_width=W, output_height=H)
    a = np.asarray(Image.open(png).convert("L"))
    xs = np.nonzero((a < 128).any(axis=0))[0]
    ys = np.nonzero((a < 128).any(axis=1))[0]
    return xs.max() + 1, ys.min()


def build():
    # Two high points, one at each end, their contours running off the edge -- the
    # plate's arrangement, turned on its side. Elongated because a masthead is wide.
    left = contour_family(96, 176, 62, 26, 8,
                          [(1, 0.26, 0.6), (2, 0.17, 2.2), (3, 0.09, 4.6)],
                          sx=1.45, sy=1.0, grow=1.18)
    right = contour_family(1786, 336, 54, 24, 8,
                           [(1, 0.28, 2.5), (2, 0.15, 0.2), (3, 0.08, 1.6)],
                           sx=1.5, sy=1.05, grow=1.2)

    tm_x, cap_y = wordmark_right_edge()

    half = 226.0   # the divider's half-width; the plate's is 0.45 of the card
    dgap = 26.0    # the break the diamond sits in
    dh = 13.0

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"
     viewBox="0 0 {W} {H}" role="img" aria-label="Lucas Green Book">
  <defs>
    <clipPath id="field">
      <rect x="{FIELD}" y="{FIELD}" width="{W-2*FIELD}" height="{H-2*FIELD}"/>
    </clipPath>
    <!-- the contour field belongs to the ends; a veil of the field's own cream
         keeps the middle clear for the lockup -->
    <linearGradient id="veil" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0.00" stop-color="{CREAM_IN}" stop-opacity="0"/>
      <stop offset="0.19" stop-color="{CREAM_IN}" stop-opacity="0"/>
      <stop offset="0.33" stop-color="{CREAM_IN}" stop-opacity="1"/>
      <stop offset="0.67" stop-color="{CREAM_IN}" stop-opacity="1"/>
      <stop offset="0.81" stop-color="{CREAM_IN}" stop-opacity="0"/>
      <stop offset="1.00" stop-color="{CREAM_IN}" stop-opacity="0"/>
    </linearGradient>
  </defs>

  <!-- full bleed: the background runs to all four edges, the frame floats on it -->
  <rect width="{W}" height="{H}" fill="{CREAM_OUT}"/>
  <rect x="{FIELD}" y="{FIELD}" width="{W-2*FIELD}" height="{H-2*FIELD}" fill="{CREAM_IN}"/>

  <g clip-path="url(#field)">
    {left}
    {right}
    {stipple(300, 70, 9, 7, 20, 0.30)}
    {stipple(1500, 330, 9, 6, 20, 0.62)}
    <rect x="{FIELD}" y="{FIELD}" width="{W-2*FIELD}" height="{H-2*FIELD}" fill="url(#veil)"/>
  </g>

  <!-- the frame: green band, cream gap, gold rule -->
  <rect x="{M + BAND/2}" y="{M + BAND/2}" width="{W-2*M-BAND}" height="{H-2*M-BAND}"
        fill="none" stroke="{GREEN}" stroke-width="{BAND}"/>
  <rect x="{M+BAND+GAP+RULE/2}" y="{M+BAND+GAP+RULE/2}"
        width="{W-2*(M+BAND+GAP)-RULE}" height="{H-2*(M+BAND+GAP)-RULE}"
        fill="none" stroke="{GOLD}" stroke-width="{RULE}"/>

  <!-- the mark -->
  <g>
    {crest(CX, CY, R)}
  </g>

  <!-- the wordmark; the type stack the books set their covers in -->
  <text x="{CX+7:.0f}" y="{Y_LUCAS:.0f}" text-anchor="middle"
        font-family="Helvetica,Arial,sans-serif" font-size="27" letter-spacing="14"
        font-weight="600" fill="{GOLD}">LUCAS</text>
  {MAIN_TEXT.format(x=CX, y=Y_MAIN, fill=INK)}
  <text x="{tm_x + 9:.0f}" y="{cap_y + 21:.0f}"
        font-family="Helvetica,Arial,sans-serif" font-size="24" fill="{INK}">&#8482;</text>

  <!-- the gold divider, broken for its diamond -->
  <path d="M{CX-half:.0f},{Y_RULE:.0f} H{CX-dgap:.0f} M{CX+dgap:.0f},{Y_RULE:.0f} H{CX+half:.0f}"
        stroke="{GOLD}" stroke-width="2.4"/>
  <path d="M{CX:.0f},{Y_RULE-dh:.0f} L{CX+dh:.0f},{Y_RULE:.0f} L{CX:.0f},{Y_RULE+dh:.0f} L{CX-dh:.0f},{Y_RULE:.0f} Z"
        fill="{GOLD}"/>

  <text x="{CX:.0f}" y="{Y_TAG:.0f}" text-anchor="middle"
        font-family="Georgia,'Times New Roman',serif" font-style="italic" font-size="30"
        fill="{INK_SOFT}">Green-reading &amp; yardage books</text>
</svg>
'''


def logo_svg(size=512):
    """The mark on its own, at any size, on no background."""
    r = size * 0.5 / 1.06     # a little air outside the outer ring
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}" role="img" aria-label="Lucas Green Book">\n  '
            + crest(size / 2, size / 2, r).replace('\n    ', '\n  ') + '\n</svg>\n')


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    png_path = os.path.join(root, "assets", "banner.png")
    logo_path = os.path.join(root, "assets", "logo.svg")

    with open(logo_path, "w") as fh:
        fh.write(logo_svg())

    # The masthead's SVG is an intermediate, not an asset: 120 KB of bezier soup
    # that nothing reads back, and this file is what reproduces it.
    tmp_svg, tmp_png = "/tmp/_lgb_banner.svg", "/tmp/_lgb_banner_2x.png"
    with open(tmp_svg, "w") as fh:
        fh.write(build())
    # rendered at 2x and resampled: the wordmark is large, the contours are hairlines
    cairosvg.svg2png(url=tmp_svg, write_to=tmp_png, output_width=W * 2, output_height=H * 2)
    img = Image.open(tmp_png).convert("RGB").resize((W, H), Image.LANCZOS)
    # 256 colours, dithered: the field is nearly flat and the contours are hairlines,
    # so an adaptive palette halves the file with no banding anyone can see at 1x.
    img.quantize(colors=256, method=Image.MEDIANCUT,
                 dither=Image.FLOYDSTEINBERG).save(png_path, optimize=True)

    for p in (logo_path, png_path):
        print(f"{p}  {os.path.getsize(p)} bytes")
