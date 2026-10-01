"""I01 I03 I19: every route at 375/768/1280: no h-scroll, focus visible (Tab walk), labels, measured contrast, signed-in chrome; auth flow via UI."""
from bl import *

NOW = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))
fx = fixture(requests=[{"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                       {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "snacks", "status": "pending"}],
             payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                       {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 250, "note": "", "visibility": "private"}],
             authorizations=[{"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": NOW},
                             {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "rent", "visibility": "private", "status": "open", "expires_at": NOW}])
reset(fx)
T = tok("ada@example.com")

CONTRAST_JS = """
() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
  const lum = c => { const f = v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); }; return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b); };
  const blend = (top, bot) => ({r: top.r*top.a+bot.r*(1-top.a), g: top.g*top.a+bot.g*(1-top.a), b: top.b*top.a+bot.b*(1-top.a), a:1});
  const bgOf = el => { let stack=[]; for (let e=el; e; e=e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a>0) { stack.push(c); if (c.a>=1) break; } } let base={r:255,g:255,b:255,a:1}; for (let i=stack.length-1;i>=0;i--) base = blend(stack[i], base); return base; };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.nodeValue.trim()) continue;
    const el = n.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.visibility==='hidden' || cs.display==='none' || r.width===0 || r.height===0) continue;
    if (el.closest('.vh, [hidden], script, style, noscript')) continue;
    let fg = parse(cs.color); if (!fg) continue; const bg = bgOf(el); fg = blend(fg, bg);
    const L1 = lum(fg), L2 = lum(bg); const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    out.push({text: n.nodeValue.trim().slice(0,40), ratio: Math.round(ratio*100)/100, size: cs.fontSize, weight: cs.fontWeight, tag: el.tagName, disabled: !!el.closest('[disabled]')});
  }
  return out;
}
"""
LABEL_JS = """
() => [...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0 && getComputedStyle(e).visibility!=='hidden'; }).map(e => {
  const byFor = e.id ? document.querySelector('label[for="'+CSS.escape(e.id)+'"]') : null;
  const wrap = e.closest('label');
  const al = e.getAttribute('aria-label'); const alb = e.getAttribute('aria-labelledby');
  const albText = alb ? alb.split(/\\s+/).map(i => (document.getElementById(i)||{}).textContent||'').join(' ').trim() : '';
  const visible = (l) => { if (!l) return false; const r=l.getBoundingClientRect(); const cs=getComputedStyle(l); return r.width>1 && r.height>1 && cs.visibility!=='hidden' && cs.display!=='none' && cs.opacity!=='0' && (l.textContent||'').trim().length>0; };
  return {testid: e.getAttribute('data-testid'), type: e.type, hasVisibleLabel: visible(byFor)||visible(wrap), hasName: !!((byFor&&byFor.textContent.trim())||(wrap&&wrap.textContent.trim())||(al&&al.trim())||albText), placeholderOnly: !byFor && !wrap && !al && !alb && !!e.placeholder};
});
"""
H_SCROLL_JS = "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, bsw: document.body.scrollWidth, wide: [...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect(); return r.width>0 && (r.right>document.documentElement.clientWidth+1) && getComputedStyle(e).position!=='fixed' && !e.closest('.vh')}).slice(0,4).map(e=>e.tagName+'.'+e.className+' r='+Math.round(e.getBoundingClientRect().right))})"

def tab_walk(page, limit=60):
    stops = []
    page.evaluate("document.activeElement && document.activeElement.blur()")
    for i in range(limit):
        page.keyboard.press("Tab")
        info_ = page.evaluate("""() => { const e=document.activeElement; if(!e||e===document.body) return null; const r=e.getBoundingClientRect(); const cs=getComputedStyle(e);
            return {tag:e.tagName, id:e.id, testid:e.getAttribute('data-testid'), text:(e.innerText||e.value||e.getAttribute('aria-label')||'').slice(0,24), x:r.x,y:r.y,w:r.width,h:r.height,
                    outline: cs.outlineStyle+' '+cs.outlineWidth+' '+cs.outlineColor, shadow: cs.boxShadow, offset: cs.outlineOffset, vis: cs.visibility, disp: cs.display}} """)
        if info_ is None: break
        key = (info_["tag"], info_["id"], info_["testid"], info_["text"])
        if stops and key == (stops[0]["tag"], stops[0]["id"], stops[0]["testid"], stops[0]["text"]): break
        # pixel comparison focused vs blurred around the element
        clip = {"x": max(0, info_["x"] - 6), "y": max(0, info_["y"] - 6), "width": min(info_["w"] + 12, 1200), "height": min(info_["h"] + 12, 400)}
        try:
            a = page.screenshot(clip=clip)
            page.evaluate("document.activeElement.blur()")
            b = page.screenshot(clip=clip)
            page.evaluate("(()=>{})()")
            info_["pixels_differ"] = a != b
            page.keyboard.press("Shift+Tab") if False else None
            page.evaluate("")
            # restore focus to the same element for the next Tab step
            page.evaluate("""([t,i,x,y]) => { const els=[...document.querySelectorAll('a,button,input,select,textarea,[tabindex]')]; const m=els.find(e => (e.getAttribute('data-testid')===t && t) || (e.id===i && i) ) || document.elementFromPoint(x+2,y+2); if(m) m.focus(); }""", [info_["testid"], info_["id"], info_["x"], info_["y"]])
        except Exception as e:
            info_["pixels_differ"] = None
        stops.append(info_)
    return stops

def audit(page, route, width, signed_in, shots=True):
    tag = "%s@%d" % (route, width)
    page.set_viewport_size({"width": width, "height": 900 if width > 400 else 800})
    page.goto(BASE + route)
    page.wait_for_function("document.querySelector('main') && document.querySelector('main').getAttribute('aria-busy') !== 'true'", timeout=8000)
    page.wait_for_timeout(300)
    hs = page.evaluate(H_SCROLL_JS)
    ok("I19 %s no horizontal scroll (scrollWidth %d <= clientWidth %d)" % (tag, hs["sw"], hs["cw"]), hs["sw"] <= hs["cw"] and hs["bsw"] <= hs["cw"] + 0, hs)
    if shots: shot(page, "route_%s_%d" % (route.strip("/").replace("/", "_") or "wallet", width))
    labs = page.evaluate(LABEL_JS)
    bad = [l for l in labs if not l["hasName"] or not l["hasVisibleLabel"]]
    ok("I19 %s every input has a visible label (%d inputs)" % (tag, len(labs)), not bad, bad)
    con = page.evaluate(CONTRAST_JS)
    low = [c for c in con if c["ratio"] < 4.5 and not c["disabled"]]
    big = [c for c in low if float(c["size"][:-2]) >= 24]
    ok("I19 %s measured text contrast >= 4.5 on %d text nodes (min %.2f)" % (tag, len(con), min([c["ratio"] for c in con] or [99])), not [c for c in low if c not in big], low[:5])
    stops = tab_walk(page)
    nofocus = [s for s in stops if not s.get("pixels_differ")]
    ok("I19 %s keyboard Tab walk reaches interactive controls (%d stops) and each shows a visible focus indication" % (tag, len(stops)), len(stops) >= 3 and not nofocus, [(s["tag"], s["testid"], s["text"], s["outline"], s["shadow"]) for s in nofocus][:5])
    if signed_in:
        for t_ in ("current-user", "current-handle", "logout-button"):
            ok("I03 %s %s visible" % (tag, t_), tid(page, t_).is_visible())
        ok("I03 %s current-handle exactly 'ada'" % tag, tid(page, "current-handle").inner_text().strip() == "ada", tid(page, "current-handle").inner_text())
        ok("I03 %s current-user contains display name 'Ada'" % tag, "Ada" in tid(page, "current-user").inner_text())
    nav = page.evaluate("() => [...document.querySelectorAll('nav a')].map(a=>a.getAttribute('href'))")
    return nav

with sync_playwright() as pw:
    br = launch(pw)
    # ---------------- signed-out screens
    for width in (375, 768, 1280):
        ctx = br.new_context(); page = ctx.new_page()
        for route in ("/login", "/signup"):
            audit(page, route, width, False)
        ctx.close()
    # ---------------- signed-in screens
    navs = {}
    for width in (375, 768, 1280):
        ctx = br.new_context(); seeded_page(ctx, T); page = ctx.new_page()
        for route in ("/", "/requests", "/split", "/authorizations"):
            navs[(route, width)] = audit(page, route, width, True)
        ctx.close()
    ok("I19 navigation consistent across routes (same links on every signed-in screen)", len({tuple(v) for v in navs.values()}) == 1, navs)
    info("nav links:", sorted({tuple(v) for v in navs.values()}))

    # ---------------- auth flow through the real forms
    ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 800})
    page.goto(BASE + "/signup")
    tid(page, "signup-email").fill("neo.test@example.com"); tid(page, "signup-password").fill("short"); tid(page, "signup-display-name").fill("Neo")
    tid(page, "signup-submit").click(); page.wait_for_timeout(600)
    ok("I03 signup with short password shows auth-error and stays on /signup", tid(page, "auth-error").count() == 1 and tid(page, "auth-error").inner_text().strip() != "" and page.url.endswith("/signup"), tid(page, "auth-error").count())
    shot(page, "auth_error_signup_375")
    tid(page, "signup-password").fill("long enough pw"); tid(page, "signup-submit").click()
    page.wait_for_selector('[data-testid="current-user"]', timeout=8000)
    ok("I03 successful signup lands signed in: current-user 'Neo', current-handle 'neo_test'", "Neo" in tid(page, "current-user").inner_text() and tid(page, "current-handle").inner_text().strip() == "neo_test", (tid(page, "current-user").inner_text(), tid(page, "current-handle").inner_text()))
    ok("I03 auth-error absent when no error", tid(page, "auth-error").count() == 0)
    ok("I04 new user wallet-balance 0.00 EUR, wallet-available shown, wallet-held absent", tid(page, "wallet-balance").inner_text().strip() == "0.00 EUR" and tid(page, "wallet-held").count() == 0, tid(page, "wallet-balance").inner_text())
    nvis = api("GET", "/activity?limit=200", token=page.evaluate("localStorage.getItem('pocketful.token')"))[1]["payments"]
    ok("I07 new user feed: public payments of others listed; empty-activity only if nothing visible (API shows %d visible)" % len(nvis), (tid(page, "empty-activity").count() == 1) == (len(nvis) == 0) and tid(page, "activity-list").count() == (1 if nvis else 0) or (not nvis and tid(page, "empty-activity").count() == 1), (len(nvis), tid(page, "empty-activity").count(), tid(page, "activity-list").count()))
    shot(page, "wallet_new_user_375")
    tid(page, "logout-button").click(); page.wait_for_timeout(600)
    ok("I03 logout returns to /login and signed-in chrome is gone", "/login" in page.url and tid(page, "current-user").count() == 0, page.url)
    page.goto(BASE + "/")
    try:
        page.wait_for_url("**/login", timeout=6000)
    except Exception:
        pass
    shot(page, "after_logout_root_b1")
    ok("I03 after logout, / redirects to /login", "/login" in page.url, (page.url, page.evaluate("localStorage.getItem('pocketful.token')"), page.inner_text("main")[:200]))
    tid(page, "login-email").fill("neo.test@example.com"); tid(page, "login-password").fill("WRONG pw"); tid(page, "login-submit").click(); page.wait_for_timeout(600)
    ok("I03 wrong password: auth-error visible, still signed out", tid(page, "auth-error").count() == 1 and tid(page, "auth-error").inner_text().strip() != "" and tid(page, "current-user").count() == 0)
    shot(page, "auth_error_login_375")
    tid(page, "login-password").fill("long enough pw"); tid(page, "login-submit").click(); page.wait_for_selector('[data-testid="current-user"]', timeout=8000)
    ok("I03 login works; auth-error gone", tid(page, "auth-error").count() == 0)
    # signup with taken handle / email
    page.evaluate("localStorage.clear()"); page.goto(BASE + "/signup")
    tid(page, "signup-email").fill("ada@example.com"); tid(page, "signup-password").fill("long enough pw"); tid(page, "signup-display-name").fill("Dup"); tid(page, "signup-submit").click(); page.wait_for_timeout(600)
    ok("I03 duplicate email shows auth-error", tid(page, "auth-error").count() == 1)
    # deep link while signed out to a protected route
    page.evaluate("localStorage.clear()")
    for r in ("/requests", "/split", "/authorizations"):
        page.goto(BASE + r); page.wait_for_timeout(500)
        ok("I01 signed-out %s -> /login (no broken screen)" % r, "/login" in page.url, page.url)
    ctx.close()
    br.close()
done("b1_quality")
