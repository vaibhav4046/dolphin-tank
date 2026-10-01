"""I19 I20 (S66): computed-style audit of the visual system + state distinctness (not by colour alone)."""
import colorsys, re
from bl import *

NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))
fx = fixture(requests=[{"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                       {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "snacks", "status": "pending"},
                       {"id": "rq_p", "requester_id": "u_ada", "payer_id": "u_dee", "amount": 300, "note": "x", "status": "paid"},
                       {"id": "rq_d", "requester_id": "u_ada", "payer_id": "u_dee", "amount": 300, "note": "x", "status": "declined"},
                       {"id": "rq_c", "requester_id": "u_ada", "payer_id": "u_dee", "amount": 300, "note": "x", "status": "cancelled"}],
             payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                       {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 250, "note": "a much longer note that should wrap nicely on small screens without clipping", "visibility": "private"}],
             authorizations=[{"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": NOW},
                             {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "rent", "visibility": "private", "status": "open", "expires_at": NOW},
                             {"id": "a_cap", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 300, "note": "done", "visibility": "public", "status": "captured", "captured_amount": 300, "expires_at": NOW},
                             {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "note": "v", "visibility": "public", "status": "voided", "expires_at": NOW},
                             {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_dee", "amount": 100, "note": "e", "visibility": "public", "status": "expired", "expires_at": NOW}])
reset(fx); T = tok("ada@example.com")

COLLECT = """
() => {
  const out = {colors: {}, radii: {}, weights: {}, shadows: {}, fonts: {}, images: [], gradients: [], heads: [], body: null};
  const add = (m, k) => { m[k] = (m[k] || 0) + 1; };
  for (const el of document.querySelectorAll('body, body *')) {
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.display === 'none' || r.width === 0 && r.height === 0) continue;
    if (el.closest('.vh')) continue;
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.nodeValue.trim());
    if (hasText) { add(out.colors, 'text ' + cs.color); add(out.weights, cs.fontWeight); add(out.fonts, cs.fontFamily.split(',')[0].replace(/["']/g,'') + ' ' + cs.fontWeight + ' ' + (/^H[1-6]$/.test(el.tagName) ? el.tagName : 'other')); }
    if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)') add(out.colors, 'bg ' + cs.backgroundColor);
    if (cs.borderTopWidth !== '0px' && cs.borderTopStyle !== 'none') add(out.colors, 'border ' + cs.borderTopColor);
    if (cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px') add(out.colors, 'outline ' + cs.outlineColor);
    const rad = cs.borderTopLeftRadius; if (rad !== '0px' && (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || cs.borderTopStyle !== 'none')) add(out.radii, rad);
    if (cs.boxShadow !== 'none') add(out.shadows, cs.boxShadow);
    if (cs.backgroundImage !== 'none') out.gradients.push({tag: el.tagName, cls: String(el.className).slice(0, 30), bi: cs.backgroundImage.slice(0, 120), w: Math.round(r.width), h: Math.round(r.height)});
    if (el.tagName === 'IMG' || el.tagName === 'PICTURE' || el.tagName === 'VIDEO' || el.tagName === 'CANVAS') out.images.push(el.tagName + ' ' + (el.getAttribute('src') || '').slice(0, 40));
    if (/^H[1-3]$/.test(el.tagName)) out.heads.push({tag: el.tagName, text: el.textContent.trim().slice(0, 30), family: cs.fontFamily, weight: cs.fontWeight, size: cs.fontSize});
  }
  const b = getComputedStyle(document.body); out.body = {bg: b.backgroundColor, color: b.color, family: b.fontFamily, weight: b.fontWeight, size: b.fontSize};
  out.fontFaces = [...document.fonts].map(f => f.family + ' ' + f.weight + ' ' + f.status);
  out.cssvars = {};
  for (const v of ['--canvas','--surface','--raised','--text','--text-secondary','--accent','--bg','--color-canvas','--color-surface']) { const x = getComputedStyle(document.documentElement).getPropertyValue(v).trim(); if (x) out.cssvars[v] = x; }
  return out;
}
"""

def rgb(s):
    m = re.search(r"rgba?\(([^)]+)\)", s)
    if not m: return None
    p = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip()) if x]
    return (int(p[0]), int(p[1]), int(p[2]), p[3] if len(p) > 3 else 1.0)

PAL = {"canvas #030014": (3, 0, 20), "surface #060317": (6, 3, 23), "raised #10093a": (16, 9, 58), "text #f4f0ff": (244, 240, 255), "secondary #a8a6b7": (168, 166, 183), "accent #9382ff": (147, 130, 255)}
agg = {"colors": {}, "radii": {}, "weights": {}, "shadows": {}, "fonts": {}, "images": [], "gradients": [], "heads": [], "faces": set(), "bodies": []}
with sync_playwright() as pw:
    br = launch(pw)
    pages = [("/login", False), ("/signup", False), ("/", True), ("/requests", True), ("/split", True), ("/authorizations", True)]
    for width in (375, 1280):
        for route, signed in pages:
            ctx = br.new_context()
            if signed: seeded_page(ctx, T)
            page = ctx.new_page(); page.set_viewport_size({"width": width, "height": 900})
            page.goto(BASE + route); page.wait_for_function("document.querySelector('main') && document.querySelector('main').getAttribute('aria-busy') !== 'true'", timeout=8000); page.wait_for_timeout(500)
            if route == "/split":
                tid(page, "split-amount").fill("10.00"); tid(page, "split-handles").fill("ada,bob,cy"); page.wait_for_timeout(300)
            if route == "/":
                tid(page, "pay-amount").fill("15.005"); tid(page, "pay-handle").fill("bob"); tid(page, "pay-submit").click(); page.wait_for_timeout(500)
            d = page.evaluate(COLLECT)
            for kk in ("colors", "radii", "weights", "shadows", "fonts"):
                for key, v in d[kk].items(): agg[kk][key] = agg[kk].get(key, 0) + v
            agg["images"] += d["images"]; agg["gradients"] += [dict(g, page=route, w_=width) for g in d["gradients"]]; agg["heads"] += d["heads"]; agg["faces"].update(d["fontFaces"]); agg["bodies"].append((route, width, d["body"], d["cssvars"]))
            ctx.close()
    br.close()

print("---- distinct computed colours (role: rgb: count)")
for key, v in sorted(agg["colors"].items(), key=lambda kv: -kv[1]): print("   ", key, v)
info("fonts used (family weight heading-or-other): %s" % sorted(agg["fonts"].items(), key=lambda kv: -kv[1]))
info("font faces loaded in document.fonts: %s" % sorted(agg["faces"]))
info("radii used: %s" % agg["radii"]); info("weights used: %s" % agg["weights"]); info("shadows: %s" % list(agg["shadows"])[:6]); info("css vars sample: %s" % agg["bodies"][0][3])
info("body styles per page: %s" % [(r, w, b["bg"], b["color"], b["family"][:20], b["weight"]) for r, w, b, v in agg["bodies"][:3]])

def near(c, p, tol=2): return c is not None and all(abs(c[i] - p[i]) <= tol for i in range(3))
cols = {k_: rgb(k_.split(" ", 1)[1]) for k_ in agg["colors"]}
body_bgs = {rgb(b["bg"])[:3] for _, _, b, _ in agg["bodies"]}
ok("S66 canvas: body background is #030014 on every route", body_bgs == {(3, 0, 20)}, body_bgs)
for name, rgbv in PAL.items():
    ok("S66 palette value in use: %s" % name, any(c is not None and c[:3] == rgbv for c in cols.values()), name)
body_text = {rgb(b["color"])[:3] for _, _, b, _ in agg["bodies"]}
ok("S66 primary text colour is #f4f0ff", (244, 240, 255) in body_text, body_text)
# anything not in the palette (ignoring alpha overlays of palette colours): list
def in_palette(c): return any(near(c, p, 2) for p in PAL.values())
off = {k_: v for k_, v in agg["colors"].items() if not in_palette(cols[k_]) and cols[k_] is not None}
info("colours outside the 6-colour palette (alpha overlays/tints included): %s" % off)
def hsv(c): return colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)
def hue_deg(c): return hsv(c)[0] * 360
bad_status = []
for k_, c in cols.items():
    if c is None: continue
    h, s, v = hsv(c); hd = h * 360
    if s > 0.25 and v > 0.3 and (hd < 40 or hd > 330 or 75 < hd < 175): bad_status.append((k_, round(hd), round(s, 2)))
ok("S66 no red/green (or orange/yellow) status colours anywhere", not bad_status, bad_status)
sat = {k_: (round(hue_deg(c)), round(hsv(c)[1], 2)) for k_, c in cols.items() if c is not None and hsv(c)[1] > 0.3 and hsv(c)[2] > 0.5}
info("saturated light colours (hue,sat): %s" % sat)
ok("S66 single accent: every saturated light colour is within the accent hue band (240-260 deg)", all(235 <= h <= 262 for h, s in sat.values()), sat)
heads = agg["heads"]
ok("S66 headings use DM Sans at weight 500 (%d headings)" % len(heads), heads and all("DM Sans" in h["family"] and h["weight"] == "500" for h in heads), [h for h in heads if "DM Sans" not in h["family"] or h["weight"] != "500"][:4])
body_fonts = [kk for kk in agg["fonts"] if kk.endswith("other")]
ok("S66 body/other text uses Inter at weight 400 or 500 (or DM Sans for display numerals): families %s" % sorted({b.rsplit(" ", 2)[0] for b in body_fonts}), all(b.rsplit(" ", 2)[0] in ("Inter", "DM Sans") and b.rsplit(" ", 2)[1] in ("400", "500") for b in body_fonts), body_fonts)
ok("S66 no font-weight above 500 anywhere", all(int(w) <= 500 for w in agg["weights"]), agg["weights"])
ok("S66 Inter and DM Sans font faces both loaded from the page (status loaded)", any("Inter" in f and "loaded" in f for f in agg["faces"]) and any("DM Sans" in f and "loaded" in f for f in agg["faces"]), sorted(agg["faces"]))
rad = {float(r.rstrip("px")) for r in agg["radii"] if r.endswith("px")}
info("radius values in px: %s ; non-px: %s" % (sorted(rad), [r for r in agg["radii"] if not r.endswith("px")]))
ok("S66 radii restricted to the 5 / 16 / 32 scale (pill radii counted separately)", rad <= {5.0, 16.0, 32.0} or all(r in (5.0, 16.0, 32.0) or r >= 99 for r in rad), sorted(rad))
shadows = list(agg["shadows"])
ok("S66 no drop shadows: every box-shadow is inset", all("inset" in s for s in shadows), shadows[:4])
ok("S66 no stock imagery / mascots: no img/picture/video/canvas elements", not agg["images"], agg["images"])
big = [g for g in agg["gradients"] if g["w"] * g["h"] > 0.4 * g["w_"] * 900 and "gradient" in g["bi"]]
info("elements with background-image: %s" % agg["gradients"][:6])
ok("S66 no large gradients (no gradient covering > 40 percent of the viewport)", not big, big[:3])
done("b5_visual")
