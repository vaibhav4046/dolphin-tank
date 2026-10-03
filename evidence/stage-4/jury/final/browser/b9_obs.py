"""Observations (not requirement rows): heading structure per route and interactive target sizes at 375/390/768/1280 on the stage-4 image."""
from bl import *

reset(fixture(payments=[{"id": "p_1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "n", "visibility": "public"}]))
T = tok("ada@example.com")
SIZE_JS = """() => [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea')].filter(e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !e.closest('.skip-link, .vh'); })
  .map(e => { const r = e.getBoundingClientRect(); return {tag: e.tagName, text: (e.innerText || e.getAttribute('aria-label') || e.id || '').trim().slice(0, 24), w: Math.round(r.width), h: Math.round(r.height), inline: e.tagName === 'A' && getComputedStyle(e).display === 'inline' && !!e.closest('p')}; })"""
with sync_playwright() as pw:
    br = launch(pw)
    for signed in (True, False):
        for route in (("/", "/requests", "/split", "/authorizations") if signed else ("/login", "/signup")):
            for w in (375, 390, 768, 1280):
                ctx = br.new_context(viewport={"width": w, "height": 900})
                if signed: seeded_page(ctx, T)
                page = ctx.new_page(); page.goto(BASE + route); page.wait_for_timeout(900)
                heads = page.evaluate("() => [...document.querySelectorAll('h1,h2,h3')].map(h => h.tagName + ':' + h.textContent.trim().slice(0, 30))")
                small = [s for s in page.evaluate(SIZE_JS) if s["h"] < 44 or s["w"] < 44]
                info("route %-16s @%4d headings=%s targets<44px=%s" % (route, w, heads, [(s["tag"], s["text"], s["w"], s["h"]) for s in small]))
                if w == 375 and route in ("/", "/signup"): shot(page, "obs_%s_375" % (route.strip("/") or "wallet"))
                ctx.close()
    br.close()
done("b9_obs")
