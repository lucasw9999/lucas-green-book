#!/usr/bin/env python3
"""
Render ONE green from real cached USGS elevation + OSM polygon.

Everything drawn is computed from measured USGS 3DEP elevation -- 0.4 m LiDAR
ground returns where available (1 m seamless DEM as an honest fallback):
  * downhill flow arrows = -gradient of the (denoised) surface
  * contour lines        = iso-elevation of the surface
  * slope heat           = |gradient|, fixed golf scale (0=flat green .. >=5%=red)
The whole drawing is rotated so the hole's APPROACH is at the bottom of the panel.

Honest limit: airborne LiDAR (~10 cm vertical) resolves real overall tilt / tiers,
not sub-inch break -- that needs an on-site survey.
"""
import json, math, os
import numpy as np
import config

DEM = os.path.join(config.COURSE_DIR, "dem_hd")
R_LAT = 111320.0
def mlon(lat): return 111320.0*math.cos(math.radians(lat))

def gauss(a, sig_px):
    r = max(1, int(sig_px*3)); x = np.arange(-r, r+1)
    k = np.exp(-(x**2)/(2*sig_px*sig_px)); k /= k.sum()
    a = np.apply_along_axis(lambda m: np.convolve(m, k, 'same'), 0, a)
    a = np.apply_along_axis(lambda m: np.convolve(m, k, 'same'), 1, a)
    return a

def erode(mask, n):
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:,:]  &= m[:-1,:]; e[:-1,:] &= m[1:,:]
        e[:,1:]  &= m[:,:-1]; e[:,:-1] &= m[:,1:]
        m = e
    return m

def poly_to_px(poly, bbox, W, H):
    xmin, ymin, xmax, ymax = bbox
    return [((lon-xmin)/(xmax-xmin)*W, (ymax-lat)/(ymax-ymin)*H) for lat, lon in poly]

def point_in_poly(x, y, poly):
    inside = False; n = len(poly); j = n-1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi):
            inside = not inside
        j = i
    return inside

def heat_color(slope_pct):
    t = min(max(slope_pct/5.0, 0), 1)
    stops = [(0.0,(120,190,120)),(0.5,(232,224,120)),(1.0,(210,90,70))]
    for a in range(len(stops)-1):
        t0,c0 = stops[a]; t1,c1 = stops[a+1]
        if t <= t1:
            f = 0 if t1==t0 else (t-t0)/(t1-t0)
            c = tuple(int(c0[k]+(c1[k]-c0[k])*f) for k in range(3))
            return f"rgb({c[0]},{c[1]},{c[2]})"
    return "rgb(210,90,70)"

def rot(x, y, cx, cy, deg):
    a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
    dx, dy = x-cx, y-cy
    return (cx + dx*ca - dy*sa, cy + dx*sa + dy*ca)

DIRS = [(0,-1,"back"),(0.71,-0.71,"back-right"),(1,0,"right"),(0.71,0.71,"front-right"),
        (0,1,"front"),(-0.71,0.71,"front-left"),(-1,0,"left"),(-0.71,-0.71,"back-left")]

def render(hole, center_yd=None, tournament=False):
    meta = json.load(open(f"{DEM}/hole{hole:02d}.json"))
    arr = np.load(f"{DEM}/hole{hole:02d}.npy").astype('float64')
    H, W = arr.shape
    bbox = meta['bbox']; xmin, ymin, xmax, ymax = bbox
    clat = meta['green_center'][0]
    px_x = (xmax-xmin)*mlon(clat)/W        # meters per pixel (E)
    px_y = (ymax-ymin)*R_LAT/H             # meters per pixel (N)

    poly = poly_to_px(meta['polygon'], bbox, W, H)
    # rasterize polygon mask
    ys, xs = np.mgrid[0:H, 0:W]
    mask = np.zeros((H, W), bool)
    # scanline point-in-poly (vectorized-ish, fine at this size)
    for r in range(H):
        row = []
        yv = r+0.5
        xints = []
        n = len(poly); j = n-1
        for i in range(n):
            xi, yi = poly[i]; xj, yj = poly[j]
            if (yi > yv) != (yj > yv):
                xints.append((xj-xi)*(yv-yi)/(yj-yi+1e-12)+xi)
            j = i
        xints.sort()
        for k in range(0, len(xints)-1, 2):
            a = int(math.ceil(xints[k]-0.5)); b = int(math.floor(xints[k+1]-0.5))
            if b >= a:
                mask[r, max(0,a):min(W,b+1)] = True
    if mask.sum() < 20:
        mask[:] = False
        for r in range(H):
            for c in range(W):
                if point_in_poly(c+0.5, r+0.5, poly): mask[r,c]=True

    surf = gauss(arr, 3.0)                       # ~1.5 m smoothing
    core = erode(mask, 3)                        # trim collar (~1.5 m)
    if core.sum() < 20: core = mask

    gy, gx = np.gradient(surf, px_y, px_x)       # dz/d(row=south), dz/d(col=east) per meter
    slope = np.hypot(gx, gy)*100.0
    # downhill in PIXEL space (col+ = east/right, row+ = south/down): -gradient
    dcol = -gx; drow = -gy

    # --- robust summary: least-squares plane over the green core ---
    zc = surf[core]
    relief_m = float(zc.max()-zc.min()) if core.any() else 0.0
    med_slope = float(np.median(slope[core])) if core.any() else 0.0
    rr, cc = np.where(core)
    Xe = cc*px_x                     # east meters
    Yn = -rr*px_y                    # north meters (row+ is south)
    A = np.c_[Xe, Yn, np.ones(len(Xe))]
    (a, b, d0), *_ = np.linalg.lstsq(A, surf[core], rcond=None)
    tilt_pct = math.hypot(a, b)*100.0                 # dominant plane tilt
    resid = surf[core] - A.dot([a, b, d0])
    undul_ft = float((resid.max()-resid.min()))*3.28084 if len(resid) else 0.0
    # plane downhill in pixel space: east=+col -> dcol=-a ; north=-row -> drow=+b
    pdc, pdr = -a, b
    # confidence: is the dominant tilt above the LiDAR noise floor over the green?
    span_m = max(math.hypot(Xe.max()-Xe.min(), Yn.max()-Yn.min()), 1.0) if len(Xe) else 1.0
    rise_ft = tilt_pct/100.0*span_m*3.28084
    conf = "firm" if (tilt_pct >= 1.2 and rise_ft >= 0.8) else "subtle"

    # rotation so approach bearing points UP on screen
    B = meta['approach_bearing']
    # approach direction as pixel vector: east=+col, north=-row -> (sinB, -cosB)
    a_ang = math.degrees(math.atan2(-math.cos(math.radians(B)), math.sin(math.radians(B))))
    theta = -90.0 - a_ang                        # rotate group by theta so approach -> up
    cx, cy = W/2.0, H/2.0

    # dominant break direction, expressed in SCREEN frame (after rotation)
    sdx, sdy = rot(pdc, pdr, 0, 0, theta)        # rotate the plane-downhill vector
    nrm = math.hypot(sdx, sdy) or 1
    sdx, sdy = sdx/nrm, sdy/nrm
    best = max(DIRS, key=lambda d: d[0]*sdx + d[1]*sdy)[2]

    # ---- tight viewBox around the ROTATED green: fills the card, no empty space ----
    rp0 = [rot(x, y, cx, cy, theta) for x, y in poly]
    rxmin = min(p[0] for p in rp0); rxmax = max(p[0] for p in rp0)
    rymin = min(p[1] for p in rp0); rymax = max(p[1] for p in rp0)
    padL, padR, padT, padB = 7, 11, 8, 14    # room: compass(top), grid #s(right), scale+approach(bottom)
    VBx, VBy = rxmin-padL, rymin-padT
    VBw, VBh = (rxmax-rxmin)+padL+padR, (rymax-rymin)+padT+padB
    vb = f"{VBx:.1f} {VBy:.1f} {VBw:.1f} {VBh:.1f}"

    # heat cells
    cells = []
    step = 1
    for r in range(0, H, step):
        for c in range(0, W, step):
            if mask[r, c]:
                cells.append(f'<rect x="{c}" y="{r}" width="1.05" height="1.05" fill="{heat_color(slope[r,c])}"/>')
    heat = f'<g opacity="0.62">{"".join(cells)}</g>'

    # contour lines, fine 0.15 m in BOTH modes. Rule 4.3 limits SCALE + book size,
    # not the presence of contours/arrows/% -- so the tournament book keeps full
    # detail (a conforming coarse-scale book); only the scale is capped below.
    segs = []
    cint = 0.15
    zmin, zmax = surf[mask].min(), surf[mask].max()
    lvl = math.ceil(zmin/cint)*cint
    levels = []
    while lvl < zmax:
        levels.append(lvl); lvl += cint
    def itp(v1, v2, p1, p2, L):
        t = 0.5 if abs(v2-v1)<1e-9 else (L-v1)/(v2-v1)
        return (p1[0]+(p2[0]-p1[0])*t, p1[1]+(p2[1]-p1[1])*t)
    for L in levels:
        for r in range(H-1):
            for c in range(W-1):
                if not (mask[r,c] or mask[r+1,c] or mask[r,c+1] or mask[r+1,c+1]):
                    continue
                TL,TR,BL,BR = surf[r,c],surf[r,c+1],surf[r+1,c],surf[r+1,c+1]
                cTL,cTR,cBL,cBR = (c,r),(c+1,r),(c,r+1),(c+1,r+1)
                pts=[]
                if (TL-L)*(TR-L)<0: pts.append(itp(TL,TR,cTL,cTR,L))
                if (TR-L)*(BR-L)<0: pts.append(itp(TR,BR,cTR,cBR,L))
                if (BL-L)*(BR-L)<0: pts.append(itp(BL,BR,cBL,cBR,L))
                if (TL-L)*(BL-L)<0: pts.append(itp(TL,BL,cTL,cBL,L))
                if len(pts)>=2:
                    mx=(pts[0][0]+pts[1][0])/2; my=(pts[0][1]+pts[1][1])/2
                    ri,ci=int(my),int(mx)
                    if 0<=ri<H and 0<=ci<W and mask[ri,ci]:
                        segs.append(f'<line x1="{pts[0][0]:.1f}" y1="{pts[0][1]:.1f}" x2="{pts[1][0]:.1f}" y2="{pts[1][1]:.1f}"/>')
    contours = f'<g stroke="#3c5a34" stroke-width="0.5" opacity="0.55">{"".join(segs)}</g>'

    # flow arrows, dense in BOTH modes (allowed within the scale limit)
    arrows = []
    smax = max(np.percentile(slope[core], 92), 1.0) if core.any() else 5.0
    a_step = 6
    a_min = 0.4
    for r in range(3, H-3, a_step):
        for c in range(3, W-3, a_step):
            if not core[r, c]: continue
            m = slope[r, c]
            if m < a_min: continue
            L = 2.2 + 3.4*min(m/smax, 1.0)
            vx, vy = dcol[r, c], drow[r, c]
            nn = math.hypot(vx, vy) or 1
            vx, vy = vx/nn*L, vy/nn*L
            ex, ey = c+vx, r+vy
            # keep the whole arrow (tip + a small head allowance) inside the green outline
            if not (point_in_poly(ex, ey, poly) and point_in_poly(ex+vx*0.28, ey+vy*0.28, poly)):
                continue
            ang = math.atan2(vy, vx)
            h = 1.7
            arrows.append(
                f'<line x1="{c}" y1="{r}" x2="{ex:.1f}" y2="{ey:.1f}"/>'
                f'<polygon points="{ex:.1f},{ey:.1f} {ex-h*math.cos(ang-0.5):.1f},{ey-h*math.sin(ang-0.5):.1f} '
                f'{ex-h*math.cos(ang+0.5):.1f},{ey-h*math.sin(ang+0.5):.1f}"/>')
    arrowg = f'<g stroke="#15271b" stroke-width="0.7" fill="#15271b" stroke-linecap="round">{"".join(arrows)}</g>'

    poly_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in poly) + " Z"
    outline = f'<path d="{poly_d}" fill="none" stroke="#20402a" stroke-width="1.3"/>'

    body = (f'<g transform="rotate({theta:.2f} {cx:.1f} {cy:.1f})">'
            f'{heat}{contours}{arrowg}{outline}</g>')

    # ---- depth references: 5-yd front->back grid + F/C/B ----
    px_m = (px_x + px_y) / 2.0
    rp = [rot(x, y, cx, cy, theta) for x, y in poly]      # polygon in screen space
    rxs = [p[0] for p in rp]; rys = [p[1] for p in rp]
    front_y, back_y = max(rys), min(rys)                  # approach edge is at bottom
    midx = (min(rxs)+max(rxs))/2.0
    depth_yd = (front_y-back_y)*px_m/0.9144
    width_yd = (max(rxs)-min(rxs))*px_m/0.9144
    def xspan(yy):                                        # green x-extent at screen-y yy
        xs=[]
        n=len(rp)
        for i in range(n):
            x1,y1=rp[i]; x2,y2=rp[(i+1)%n]
            if (y1>yy)!=(y2>yy):
                xs.append(x1+(x2-x1)*(yy-y1)/(y2-y1))
        return (min(xs),max(xs)) if len(xs)>=2 else None
    step = 4.572/px_m                                     # 5 yards in pixels
    glines=[]; k=1; yy=front_y-step
    while yy>back_y:
        sp=xspan(yy)
        if sp:
            glines.append(f'<line x1="{sp[0]:.1f}" y1="{yy:.1f}" x2="{sp[1]:.1f}" y2="{yy:.1f}"/>'
                          f'<text x="{sp[1]+1.5:.1f}" y="{yy+1.5:.1f}" font-size="3.4" fill="#8a8a8a" stroke="none">{k*5}</text>')
        yy-=step; k+=1
    gridg=f'<g stroke="#9a9a9a" stroke-width="0.35" stroke-dasharray="2,2" opacity="0.7" fill="#8a8a8a">{"".join(glines)}</g>'
    # (front/center/back yardage tags removed by request -- declutter the green)
    fcb=""
    # pin ring the golfer marks on the day (pin moves daily -> not pre-printed).
    # Small so it never covers the green's slope/bunker detail.
    pin=(f'<circle cx="{midx:.1f}" cy="{(front_y+back_y)/2:.1f}" r="1.4" fill="none" stroke="#c0392b" stroke-width="0.7" stroke-dasharray="1.2,1.2"/>')

    # slope % numbers in steeper zones (kept in BOTH modes -- allowed at this scale)
    chosen=[]
    cand=[]
    for r in range(4,H-4,6):
        for c in range(4,W-4,6):
            if core[r,c] and slope[r,c]>=1.5:
                cand.append((float(slope[r,c]),r,c))
    cand.sort(reverse=True)
    for sl,r,c in cand:
        sx,sy=rot(c,r,cx,cy,theta)
        # keep slope numbers inside the frame and off the top-right compass
        sx=min(max(sx, VBx+2.5), VBx+VBw-2.5)
        sy=min(max(sy, VBy+3.0), VBy+VBh-4.0)
        if (sx-(VBx+VBw-5.5))**2 + (sy-(VBy+6.5))**2 < 6.0**2:   # skip compass zone
            continue
        if all((sx-ox)**2+(sy-oy)**2>16**2 for ox,oy,_ in chosen):
            chosen.append((sx,sy,sl))
        if len(chosen)>=7: break
    slabels=("<g>"+"".join(
        f'<text x="{sx:.1f}" y="{sy:.1f}" font-size="4.6" text-anchor="middle" '
        f'paint-order="stroke" stroke="#fff" stroke-width="1.2" fill="#111" font-weight="700">{int(round(sl))}</text>'
        for sx,sy,sl in chosen)+"</g>")

    # scale bar (tournament): a printed 5-yard bar to verify the scale, tucked in the
    # bottom-LEFT of the frame so it never collides with the approach label (bottom-right).
    scalebar = ""
    scale_max_in = round(0.075 * depth_yd, 3)   # legal max on-page height for this green
    if tournament:
        blen = 4.572 / px_m                      # 5 yards in view units
        bx0 = VBx + 2.5; by0 = VBy + VBh - 3.5
        scalebar = (f'<g stroke="#333" stroke-width="0.7">'
                    f'<line x1="{bx0:.1f}" y1="{by0:.1f}" x2="{bx0+blen:.1f}" y2="{by0:.1f}"/>'
                    f'<line x1="{bx0:.1f}" y1="{by0-1.3:.1f}" x2="{bx0:.1f}" y2="{by0+1.3:.1f}"/>'
                    f'<line x1="{bx0+blen:.1f}" y1="{by0-1.3:.1f}" x2="{bx0+blen:.1f}" y2="{by0+1.3:.1f}"/>'
                    f'<text x="{bx0+blen/2:.1f}" y="{by0-2.0:.1f}" font-size="3.6" text-anchor="middle" fill="#333" stroke="none">5 yd</text></g>')

    # compass (true north): small, top-right of the tight frame
    ncx, ncy = VBx+VBw-5.5, VBy+6.5
    nx, ny = rot(0, -1, 0, 0, theta)
    comp = (f'<g stroke="#666" fill="#666">'
            f'<line x1="{ncx:.1f}" y1="{ncy:.1f}" x2="{ncx+nx*4:.1f}" y2="{ncy+ny*4:.1f}" stroke-width="0.7"/>'
            f'<circle cx="{ncx:.1f}" cy="{ncy:.1f}" r="0.7"/>'
            f'<text x="{ncx+nx*6:.1f}" y="{ncy+ny*6+1.3:.1f}" font-size="3.4" text-anchor="middle">N</text></g>')

    # In tournament mode: size the green as large as possible while (a) staying a safe
    # margin UNDER the Rule 4.3 cap (0.36 in : 5 yd, ~4% under 3/8) AND (b) fitting inside
    # its panel so nothing overflows/clips. Whichever is smaller wins -> consistent framing.
    if tournament:
        legal_kf = 0.36 * px_m / 4.572                                   # legal ceiling
        grn_w_in = (config.CARD_W_IN - 2*0.07) * (2.4/4.0) - 0.03        # .grn column width
        grn_h_in = config.CARD_H_IN - 2*0.07 - 0.50 - 0.18              # minus header + foot
        fit_kf = min(grn_w_in/VBw, grn_h_in/VBh)                         # fit the whole frame
        kf = min(legal_kf, fit_kf)
        wattr, hattr = f'{VBw*kf:.3f}in', f'{VBh*kf:.3f}in'
        wrapopen = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%">'
        wrapclose = '</div>'
    else:
        wattr = hattr = '100%'
        wrapopen = wrapclose = ''

    svg = (f'{wrapopen}<svg viewBox="{vb}" width="{wattr}" height="{hattr}" preserveAspectRatio="xMidYMid meet">'
           f'{body}{gridg}{slabels}{pin}{fcb}{scalebar}{comp}'
           f'<text x="{VBx+VBw-2.5:.1f}" y="{VBy+VBh-2.5:.1f}" font-size="4" text-anchor="end" fill="#333">&#9650; approach</text>'
           f'</svg>{wrapclose}')


    summary = dict(relief_ft=round(relief_m*3.28084,1), median_slope=round(med_slope,1),
                   tilt_pct=round(tilt_pct,1), feeds=best, undul_ft=round(undul_ft,1),
                   conf=conf, depth_yd=int(round(depth_yd)), width_yd=int(round(width_yd)),
                   scale_max_in=scale_max_in)
    return svg, summary


if __name__ == "__main__":
    for h in range(1, 19):
        try:
            _, s = render(h)
            print(f"hole {h:2d}: feeds {s['feeds']:11s} tilt {s['tilt_pct']:.1f}%  median {s['median_slope']:.1f}%  relief {s['relief_ft']:.1f} ft")
        except Exception as e:
            print(f"hole {h:2d}: ERROR {type(e).__name__}: {e}")
