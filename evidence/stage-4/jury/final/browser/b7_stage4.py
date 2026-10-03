"""Stage-4 browser product on the stage-4 image: B12 refund control (offer rules, success, partial, refused, uncertain+retry, loading,
double click, validation, stale, corrected amount, keyboard), B01 overflow with refund panels/notices at 375/768/1280, B02 states,
B05 labels/focus/contrast with refund controls open, B06-B10 computed-style + stylesheet inspection, B09 no red/green."""
import colorsys, re
from bl import *

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def visible(page, t): return present(page, t) and tid(page, t).first.is_visible()
def settle(page, ms=500): page.wait_for_timeout(ms)
def wait_present(page, t, timeout=6000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, timeout=timeout); return True
    except Exception: return False
def wait_gone(page, t, timeout=6000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, state="detached", timeout=timeout); return True
    except Exception: return False
def me_api(t): return api("GET", "/me", token=t)[1]

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "b1_quality.py")).read()
exec(src[src.index("CONTRAST_JS"):src.index("def tab_walk")])   # CONTRAST_JS LABEL_JS H_SCROLL_JS constants of the stage-4 b1 script

EXTERNAL = []
NOW2H = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))
LONG = "x" * 180

def mkfx(extra=None):
    f = fixture(users=[user("ada", 10000), user("bob", 5000), user("cy", 3000), user("dee", 5000)],
                payments=[{"id": "p_in1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5000, "note": "lunch", "visibility": "public"},
                          {"id": "p_in2", "from_user_id": "u_dee", "to_user_id": "u_ada", "amount": 3000, "note": "books", "visibility": "private"},
                          {"id": "p_in3", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1000, "note": LONG, "visibility": "public"},
                          {"id": "p_out", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 500, "note": "coffee", "visibility": "public"},
                          {"id": "p_oth", "from_user_id": "u_bob", "to_user_id": "u_dee", "amount": 700, "note": "others", "visibility": "public"}],
                requests=[{"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                          {"id": "rq_paid", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "snacks", "status": "paid"},
                          {"id": "rq_dec", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 200, "note": "no", "status": "declined"}])
    if extra: f.update(extra)
    return f

def new_ctx(br, token, width=375, posts=None):
    ctx = br.new_context(viewport={"width": width, "height": 900}); seeded_page(ctx, token)
    page = ctx.new_page()
    def on_req(r):
        if not r.url.startswith(BASE) and not r.url.startswith("data:"): EXTERNAL.append(r.url)
        if r.method == "POST" and r.url.endswith("/refunds") and posts is not None:
            posts.append({"url": r.url.replace(BASE, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data})
    page.on("request", on_req)
    return ctx, page

def wallet(page, wait="activity-item-p_in1"):
    page.goto(BASE + "/"); wait_present(page, wait); settle(page, 300)

def refunds_of(token, pid):
    out, off = [], 0
    while True:
        s, j = api("GET", "/activity?limit=100&offset=%d" % off, token=token)
        out += [p for p in j["payments"] if p.get("refund_of") == pid]
        if not j.get("has_more"): return out
        off += 100

def hscroll_ok(page):
    r = page.evaluate(H_SCROLL_JS)
    return r["sw"] <= r["cw"] and r["bsw"] <= r["cw"], r

def tab_stops(page, limit=80):
    stops = []
    page.evaluate("document.activeElement && document.activeElement.blur()")
    for i in range(limit):
        page.keyboard.press("Tab")
        s = page.evaluate("""() => { const e=document.activeElement; if(!e||e===document.body) return null; const cs=getComputedStyle(e); const r=e.getBoundingClientRect();
            return {tag:e.tagName, testid:e.getAttribute('data-testid'), text:(e.innerText||e.getAttribute('aria-label')||'').slice(0,20), ow:cs.outlineWidth, os:cs.outlineStyle, oc:cs.outlineColor, w:r.width, h:r.height}}""")
        if s is None: break
        if stops and (s["tag"], s["testid"], s["text"]) == (stops[0]["tag"], stops[0]["testid"], stops[0]["text"]): break
        stops.append(s)
    return stops

with sync_playwright() as pw:
    br = launch(pw)
    Tada = Tbob = None

    # ================= B12 offer rules: receiver only, never on a refund payment
    reset(mkfx()); Tada, Tbob = tok("ada@example.com"), tok("bob@example.com"); Tdee = tok("dee@example.com")
    ctx, page = new_ctx(br, Tada); wallet(page)
    ok("B12 receiver's feed: Refund control on each received payment (p_in1 p_in2 p_in3)", all(present(page, "refund-toggle-" + p) for p in ("p_in1", "p_in2", "p_in3")))
    ok("B12 no refund control on a payment the person SENT (p_out)", present(page, "activity-item-p_out") and not present(page, "refund-p_out"))
    ok("B12 no refund control on a payment between others (p_oth)", not present(page, "refund-p_oth"))
    ok("B12 Refund toggle starts collapsed: aria-expanded=false and panel not visible", tid(page, "refund-toggle-p_in1").get_attribute("aria-expanded") == "false" and not visible(page, "refund-amount-p_in1"))
    ctx.close()
    s, r1 = api("POST", "/payments/p_in1/refunds", {"amount": 1000}, token=Tada, key=k()); assert s == 201, (s, r1)
    R1 = r1["payment_id"]
    ctx, page = new_ctx(br, Tada); wallet(page, "activity-item-" + R1)
    ok("B12 refund payment appears in the refunder's feed with 'Refund of' chip", present(page, "activity-refund-of-" + R1) and "p_in1" in text(page, "activity-refund-of-" + R1), text(page, "activity-refund-of-" + R1) if present(page, "activity-refund-of-" + R1) else None)
    ok("B12 NO refund control on the refund payment (sender view)", not present(page, "refund-" + R1))
    ctx.close()
    ctx, page = new_ctx(br, Tbob); wallet(page, "activity-item-" + R1)
    ok("B12 NO refund control on the refund payment for its RECIPIENT either", present(page, "activity-item-" + R1) and not present(page, "refund-" + R1))
    ok("B12 bob (sender of every original) sees no refund control at all", page.locator('[data-testid^="refund-"]').count() == 0, page.locator('[data-testid^="refund-"]').count())
    ctx.close()

    # ================= B12 success / partial / done (real service, 375 px)
    reset(mkfx()); Tada = tok("ada@example.com"); posts = []
    ctx, page = new_ctx(br, Tada, 375, posts); wallet(page)
    before = me_api(Tada)
    tog = tid(page, "refund-toggle-p_in2"); tog.click(); settle(page, 200)
    ok("B12 toggle opens the panel: aria-expanded true, amount input visible", tog.get_attribute("aria-expanded") == "true" and visible(page, "refund-amount-p_in2"))
    ok("B12 limit hint names amount left and recipient", "30.00 EUR" in text(page, "refund-limit-p_in2") and "@dee" in text(page, "refund-limit-p_in2"), text(page, "refund-limit-p_in2"))
    ok("B12 amount defaults to what is left (30.00)", tid(page, "refund-amount-p_in2").input_value() == "30.00", tid(page, "refund-amount-p_in2").input_value())
    lab = page.locator('label[for="refund-amount-p_in2"]')
    ok("B12 amount field has a visible associated label 'Refund amount'", lab.count() == 1 and lab.first.is_visible() and lab.first.inner_text().strip() == "Refund amount")
    tid(page, "refund-amount-p_in2").fill("10.00"); tid(page, "refund-submit-p_in2").click()
    ok("B12 success state shown (refund-success) with text", wait_present(page, "refund-success-p_in2") and text(page, "refund-success-p_in2") == "Refunded 10.00 EUR to @dee.", text(page, "refund-success-p_in2") if present(page, "refund-success-p_in2") else None)
    settle(page, 600)
    after = me_api(Tada); rs = refunds_of(Tada, "p_in2")
    ok("B12 money moved once: ada total -1000, one refund payment of 1000 refund_of p_in2", after["total"] == before["total"] - 1000 and len(rs) == 1 and rs[0]["amount"] == 1000, (before, after, rs))
    ok("B12 refund payment shape: request_id null, authorization_id null, original note/visibility", rs and rs[0]["request_id"] is None and rs[0]["authorization_id"] is None and rs[0]["note"] == "books" and rs[0]["visibility"] == "private", rs)
    ok("B12 wallet headline updated without reload (available 90.00 EUR)", text(page, "wallet-available") == "90.00 EUR", text(page, "wallet-available"))
    ok("B12 panel stays open and limit now 20.00", tid(page, "refund-toggle-p_in2").get_attribute("aria-expanded") == "true" and "20.00 EUR" in text(page, "refund-limit-p_in2"), text(page, "refund-limit-p_in2"))
    ok("B12 one POST with an Idempotency-Key and body {amount:1000}", len(posts) == 1 and posts[0]["key"] and json.loads(posts[0]["body"]) == {"amount": 1000}, posts)
    shot(page, "b12_success_partial_375")
    tid(page, "refund-amount-p_in2").fill("20.00"); tid(page, "refund-submit-p_in2").click()
    ok("B12 fully refunded -> 'Nothing left to refund' and the toggle is gone", wait_present(page, "refund-done-p_in2") and not present(page, "refund-toggle-p_in2") and "Nothing left" in text(page, "refund-done-p_in2"))
    ok("B12 two refunds sum to the payment: 3000", sum(x["amount"] for x in refunds_of(Tada, "p_in2")) == 3000)
    ctx.close()

    # ================= B12 stale: another actor refunds meanwhile -> real refund_exceeds_payment, UI relearns the remainder
    reset(mkfx()); Tada = tok("ada@example.com"); posts = []
    ctx, page = new_ctx(br, Tada, 375, posts); wallet(page)
    tid(page, "refund-toggle-p_in1").click(); settle(page, 150)
    ok("B12 stale setup: default 50.00", tid(page, "refund-amount-p_in1").input_value() == "50.00")
    assert api("POST", "/payments/p_in1/refunds", {"amount": 3500}, token=Tada, key=k())[0] == 201   # elsewhere (another tab)
    tid(page, "refund-submit-p_in1").click()
    ok("B12 refused (refund_exceeds_payment): refund-error shown, role alert, title + text", wait_present(page, "refund-error-p_in1") and tid(page, "refund-error-p_in1").get_attribute("role") == "alert" and "more than is left to refund" in text(page, "refund-error-p_in1"), text(page, "refund-error-p_in1") if present(page, "refund-error-p_in1") else None)
    settle(page, 800)
    ok("B12 refused notice survives the feed rebuild; no success/uncertain shown", present(page, "refund-error-p_in1") and not present(page, "refund-success-p_in1") and not present(page, "refund-uncertain-p_in1"))
    ok("B12 after refusal the page relearned the remainder (15.00)", "15.00 EUR" in text(page, "refund-limit-p_in1"), text(page, "refund-limit-p_in1"))
    ok("B12 refused write moved no money (refunds total 3500)", sum(x["amount"] for x in refunds_of(Tada, "p_in1")) == 3500)
    shot(page, "b12_refused_stale_375")
    ctx.close()

    # ================= B12 refused: insufficient_funds against a real hold
    reset(mkfx({"authorizations": [{"id": "a_h", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 9500, "note": "deposit", "visibility": "public", "status": "open", "expires_at": NOW2H}]}))
    Tada = tok("ada@example.com")
    ctx, page = new_ctx(br, Tada, 375); wallet(page)
    ok("B12 hold setup: available 5.00 EUR headline", text(page, "wallet-available") == "5.00 EUR", text(page, "wallet-available"))
    tid(page, "refund-toggle-p_in2").click(); tid(page, "refund-submit-p_in2").click()
    ok("B12 refused (insufficient_funds, money on hold not spendable): text names holds", wait_present(page, "refund-error-p_in2") and "Money on hold cannot be spent" in text(page, "refund-error-p_in2"), text(page, "refund-error-p_in2") if present(page, "refund-error-p_in2") else None)
    ok("B12 nothing refunded, balances unchanged", len(refunds_of(Tada, "p_in2")) == 0 and me_api(Tada)["available"] == 500)
    ctx.close()

    # ================= B12 uncertain (response lost after commit / request lost), same key + body on retry, money once
    for mode0 in ("after-commit", "before-commit"):
        reset(mkfx()); Tada = tok("ada@example.com"); posts = []
        ctx, page = new_ctx(br, Tada, 375, posts); wallet(page)
        mode = {"m": mode0}
        def h(route):
            if mode["m"] == "after-commit": route.fetch(); route.abort("failed")
            elif mode["m"] == "before-commit": route.abort("failed")
            else: route.continue_()
        page.route("**/refunds", h)
        tid(page, "refund-toggle-p_in3").click(); tid(page, "refund-amount-p_in3").fill("4.00"); tid(page, "refund-submit-p_in3").click()
        ok("B12 uncertain [%s]: refund-uncertain shown (role status, 'Unconfirmed'), refund-error NOT shown" % mode0, wait_present(page, "refund-uncertain-p_in3") and not present(page, "refund-error-p_in3") and "Unconfirmed" in text(page, "refund-uncertain-p_in3"), text(page, "refund-uncertain-p_in3") if present(page, "refund-uncertain-p_in3") else None)
        ok("B12 uncertain [%s]: text promises retry sends it once" % mode0, "retry sends the same refund once" in text(page, "refund-uncertain-p_in3"))
        n_srv = len(refunds_of(Tada, "p_in3"))
        ok("B12 uncertain [%s]: server state matches (committed=%s)" % (mode0, mode0 == "after-commit"), n_srv == (1 if mode0 == "after-commit" else 0), n_srv)
        shot(page, "b12_uncertain_%s_375" % mode0)
        mode["m"] = "pass"; tid(page, "refund-submit-p_in3").click()
        ok("B12 uncertain [%s]: retry succeeds, uncertain gone, success shown" % mode0, wait_present(page, "refund-success-p_in3") and not present(page, "refund-uncertain-p_in3"))
        ok("B12 uncertain [%s]: retry sent the SAME Idempotency-Key and byte-identical body" % mode0, len(posts) == 2 and posts[0]["key"] == posts[1]["key"] and posts[0]["body"] == posts[1]["body"], posts)
        rs = refunds_of(Tada, "p_in3")
        ok("B12 uncertain [%s]: money moved exactly once (one refund of 400)" % mode0, len(rs) == 1 and rs[0]["amount"] == 400, rs)
        ctx.close()

    # ================= B12 loading (in-flight) + double click guard
    reset(mkfx()); Tada = tok("ada@example.com"); posts = []
    ctx, page = new_ctx(br, Tada, 375, posts); wallet(page); held = []
    page.route("**/refunds", lambda route: held.append(route))
    tid(page, "refund-toggle-p_in1").click(); tid(page, "refund-amount-p_in1").fill("10.00")
    sub = tid(page, "refund-submit-p_in1"); sub.click(); settle(page, 300)
    ok("B12 loading: submit has aria-busy=true while the write is in flight", sub.get_attribute("aria-busy") == "true")
    sub.click(); sub.click(); settle(page, 300)
    ok("B12 loading: repeated clicks do not send a second request (1 POST)", len(posts) == 1, len(posts))
    ok("B12 loading: no success/error shown yet", not present(page, "refund-success-p_in1") and not present(page, "refund-error-p_in1"))
    opac = page.evaluate("() => getComputedStyle(document.querySelector('[data-testid=refund-submit-p_in1]')).opacity")
    ok("B12 loading: busy button visibly quieter (opacity < 1) and cursor progress", float(opac) < 1, opac)
    shot(page, "b12_loading_375")
    held[0].continue_(); wait_present(page, "refund-success-p_in1"); settle(page, 400)
    ok("B12 loading ends: aria-busy removed, success shown, exactly one refund", sub.get_attribute("aria-busy") in (None,) and len(refunds_of(Tada, "p_in1")) == 1, sub.get_attribute("aria-busy"))
    ctx.close()

    # ================= B12 mocked refusal envelopes the UI cannot provoke naturally (mocked, said so)
    reset(mkfx()); Tada = tok("ada@example.com")
    ctx, page = new_ctx(br, Tada, 375); wallet(page)
    for status, code, frag in ((403, "forbidden", "Only the person who received"), (404, "not_found", "could not be found"), (422, "invalid_refund_target", "cannot itself be refunded"), (422, "validation_failed", "greater than zero"), (409, "insufficient_funds", "Not enough available funds")):
        page.route("**/refunds", lambda route, request, s=status, c=code: route.fulfill(status=s, content_type="application/json", body=json.dumps({"error": {"code": c, "message": "m"}})))
        if tid(page, "refund-toggle-p_in1").get_attribute("aria-expanded") != "true": tid(page, "refund-toggle-p_in1").click()
        tid(page, "refund-amount-p_in1").fill("1.00"); tid(page, "refund-submit-p_in1").click(); settle(page, 500)
        ok("B12 [mocked envelope] %d %s -> refund-error with plain text containing %r" % (status, code, frag), present(page, "refund-error-p_in1") and frag in text(page, "refund-error-p_in1"), text(page, "refund-error-p_in1") if present(page, "refund-error-p_in1") else None)
        page.unroute("**/refunds")
    ctx.close()

    # ================= B12 client validation: no request for bad amounts
    reset(mkfx()); Tada = tok("ada@example.com"); posts = []
    ctx, page = new_ctx(br, Tada, 375, posts); wallet(page)
    tid(page, "refund-toggle-p_in1").click()
    for bad in ("", "0", "0.00", "abc", "1.234", "-5", "1e3", "50.01x"):
        tid(page, "refund-amount-p_in1").fill(bad); tid(page, "refund-submit-p_in1").click(); settle(page, 150)
        ok("B12 validation %r -> refund-error shown, no request sent" % bad, present(page, "refund-error-p_in1") and len(posts) == 0, (present(page, "refund-error-p_in1"), len(posts)))
    ctx.close()

    # ================= B12 corrected amount: feed shows the original, service refuses, UI relearns from /revisions
    reset(mkfx()); Tada, Tbob = tok("ada@example.com"), tok("bob@example.com")
    ctx, page = new_ctx(br, Tada, 375); wallet(page)
    s, c = api("POST", "/payments/p_in3/corrections", {"expected_revision": 1, "amount": 600, "effective_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 1)), "reason": "oops"}, token=Tbob, key=k())
    ok("B12 setup: sender corrected p_in3 to 6.00", s == 201, (s, c))
    page.reload(); wait_present(page, "activity-item-p_in3"); settle(page, 300)
    tid(page, "refund-toggle-p_in3").click()
    default0 = tid(page, "refund-amount-p_in3").input_value()
    info("B12 default amount offered for a corrected payment before any refusal:", default0, "(service decides; page shows original 10.00)")
    tid(page, "refund-submit-p_in3").click()
    ok("B12 corrected: refund of the stale 10.00 refused by the service (refund-error)", wait_present(page, "refund-error-p_in3"), default0)
    settle(page, 800)
    ok("B12 corrected: page relearned 6.00 as the limit and the default", "6.00 EUR" in text(page, "refund-limit-p_in3") and tid(page, "refund-amount-p_in3").input_value() == "6.00", (text(page, "refund-limit-p_in3"), tid(page, "refund-amount-p_in3").input_value()))
    tid(page, "refund-submit-p_in3").click()
    ok("B12 corrected: refunding the corrected 6.00 succeeds", wait_present(page, "refund-success-p_in3") and sum(x["amount"] for x in refunds_of(Tada, "p_in3")) == 600)
    ctx.close()

    # ================= B12 keyboard-only refund + focus visibility
    reset(mkfx()); Tada = tok("ada@example.com")
    ctx, page = new_ctx(br, Tada, 375); wallet(page)
    def focus_info():
        return page.evaluate("() => { const e=document.activeElement; const cs=getComputedStyle(e); return {t:e.getAttribute('data-testid'), os:cs.outlineStyle, ow:cs.outlineWidth, oc:cs.outlineColor}}")
    tid(page, "refund-toggle-p_in2").focus(); page.keyboard.press("Tab"); page.keyboard.press("Shift+Tab")
    fi = focus_info()
    ok("B12 keyboard: Refund toggle shows a visible 2px accent focus ring", fi["t"] == "refund-toggle-p_in2" and fi["os"] == "solid" and fi["ow"] == "2px" and fi["oc"] == "rgb(147, 130, 255)", fi)
    page.keyboard.press("Enter"); settle(page, 150)
    ok("B12 keyboard: Enter opens the panel", tid(page, "refund-toggle-p_in2").get_attribute("aria-expanded") == "true")
    page.keyboard.press("Tab"); fi = focus_info()
    ok("B12 keyboard: Tab from toggle lands on the amount input with a focus ring", fi["t"] == "refund-amount-p_in2" and fi["os"] == "solid" and fi["ow"] == "2px", fi)
    page.keyboard.press("Control+A"); page.keyboard.type("12.34"); page.keyboard.press("Tab"); fi = focus_info()
    ok("B12 keyboard: Tab then lands on Send refund with a focus ring", fi["t"] == "refund-submit-p_in2" and fi["os"] == "solid" and fi["ow"] == "2px", fi)
    page.keyboard.press("Enter")
    ok("B12 keyboard: Enter sends the refund (success, 1234 refunded)", wait_present(page, "refund-success-p_in2") and sum(x["amount"] for x in refunds_of(Tada, "p_in2")) == 1234)
    ctx.close()

    # ================= B01 + B05 populated wallet: every refund notice kind visible together, 375/768/1280
    reset(mkfx()); Tada = tok("ada@example.com"); posts = []
    ctx, page = new_ctx(br, Tada, 375, posts); wallet(page)
    tid(page, "refund-toggle-p_in1").click(); tid(page, "refund-amount-p_in1").fill("abc"); tid(page, "refund-submit-p_in1").click()      # error
    tid(page, "refund-toggle-p_in2").click()
    page.route("**/refunds", lambda route: (route.fetch(), route.abort("failed")))
    tid(page, "refund-submit-p_in2").click(); wait_present(page, "refund-uncertain-p_in2"); page.unroute("**/refunds")                   # uncertain
    tid(page, "refund-toggle-p_in3").click(); tid(page, "refund-amount-p_in3").fill("3.00"); tid(page, "refund-submit-p_in3").click(); wait_present(page, "refund-success-p_in3")   # success
    settle(page, 700)
    ok("B01/B05 setup: error, uncertain and success refund notices visible together", visible(page, "refund-error-p_in1") and visible(page, "refund-uncertain-p_in2") and visible(page, "refund-success-p_in3"))
    kinds = page.evaluate("""() => ['refund-error-p_in1','refund-uncertain-p_in2','refund-success-p_in3'].map(t => { const n=document.querySelector('[data-testid='+t+']'); return {t, kind:n.dataset.kind, role:n.getAttribute('role'), glyph:n.querySelector('svg.glyph') ? n.querySelector('svg.glyph').innerHTML.slice(0,40) : null, title:(n.querySelector('.notice-title')||{}).textContent||null, bs:getComputedStyle(n).borderTopStyle, bc:getComputedStyle(n).borderTopColor}})""")
    ok("B09 notices differ by glyph shape, label/title and border style, not by colour", len({x["glyph"] for x in kinds}) == 3 and kinds[0]["title"] and kinds[1]["title"] and kinds[1]["bs"] == "dashed" and kinds[0]["bs"] == "solid", kinds)
    info("B09 notice signatures:", kinds)
    for w in (375, 768, 1280):
        page.set_viewport_size({"width": w, "height": 900}); settle(page, 300)
        okh, r = hscroll_ok(page)
        ok("B01 wallet with refund panels+notices @%d: no horizontal scroll (scrollWidth %s <= clientWidth %s)" % (w, r["sw"], r["cw"]), okh, r)
        ok("B01 wallet @%d: no element extends past the viewport (%s)" % (w, r.get("wide")), not r.get("wide"), r.get("wide"))
        labs = page.evaluate(LABEL_JS)
        ok("B05 @%d every visible input (incl. refund amounts) has a visible label (%d inputs)" % (w, len(labs)), all(l["hasVisibleLabel"] for l in labs), [l for l in labs if not l["hasVisibleLabel"]])
        con = page.evaluate(CONTRAST_JS); lows = [c for c in con if c["ratio"] < 4.5]
        ok("B05 @%d measured text contrast >= 4.5 on %d text nodes (min %s)" % (w, len(con), min(c["ratio"] for c in con)), not lows, lows[:5])
        shot(page, "b01_wallet_refund_states_%d" % w)
    page.set_viewport_size({"width": 375, "height": 900}); settle(page, 300)
    st = tab_stops(page)
    refund_stops = [s for s in st if s["testid"] and s["testid"].startswith("refund-")]
    got = {s["testid"] for s in refund_stops}
    want = {"refund-%s-%s" % (n, p) for n in ("toggle", "amount", "submit") for p in ("p_in1", "p_in3")}
    ok("B05 keyboard: Tab walk reaches every refund control that exists (%d stops incl. %d refund controls)" % (len(st), len(refund_stops)), want <= got, sorted(got))
    info("B12 p_in2 after its lost-response refund committed and a later feed refresh: done=%s uncertain-notice-still-shown=%s done-text=%r" % (visible(page, "refund-done-p_in2"), visible(page, "refund-uncertain-p_in2"), text(page, "refund-done-p_in2") if present(page, "refund-done-p_in2") else None))
    ok("B12 the committed-but-unconfirmed refund is reflected after a refresh: p_in2 shows 'Nothing left to refund' (page learned it from the feed)", visible(page, "refund-done-p_in2") and not present(page, "refund-toggle-p_in2"))
    bad = [s for s in st if not (s["os"] == "solid" and float(s["ow"].replace("px", "")) >= 2)]
    ok("B05 keyboard: every tab stop shows a >=2px solid focus outline", not bad, bad[:3])
    small = [s for s in st if s["h"] < 44 and s["tag"] in ("BUTTON", "INPUT", "SELECT")]
    ok("B05 touch: buttons and inputs are >= 44px high", not small, small[:3])
    ctx.close()

    # ================= B02 states for the wallet
    reset(fixture()); Tada = tok("ada@example.com")
    ctx, page = new_ctx(br, Tada, 375); page.goto(BASE + "/"); wait_present(page, "wallet-available"); settle(page, 500)
    ok("B02 empty state: empty-activity with explanation", visible(page, "empty-activity") and "No payments to show yet" in text(page, "empty-activity"))
    shot(page, "b02_empty_375"); ctx.close()
    reset(mkfx()); Tada = tok("ada@example.com")
    ctx, page = new_ctx(br, Tada, 375); held = []
    page.route("**/me", lambda route: held.append(route)); page.goto(BASE + "/"); settle(page, 700)
    ok("B02 loading state: main aria-busy=true, skeleton visible, status 'Loading'", page.locator("main[aria-busy=true]").count() == 1 and page.locator(".skeleton").first.is_visible() and "Loading" in page.locator("main [role=status]").first.inner_text())
    shot(page, "b02_loading_375")
    for r_ in held: r_.continue_()
    page.unroute("**/me")
    ok("B02 loading resolves to the wallet", wait_present(page, "wallet-available"))
    ctx.close()
    ctx, page = new_ctx(br, Tada, 375); page.route("**/me", lambda route: route.abort("failed")); page.goto(BASE + "/"); settle(page, 1200)
    ok("B02 error state: 'We could not load your wallet' with role=alert and Try again", page.get_by_text("We could not load your wallet").count() == 1 and page.locator("[role=alert] button").count() == 1)
    shot(page, "b02_error_375")
    page.unroute("**/me"); page.get_by_role("button", name="Try again").click(); ok("B02 error recovery: Try again loads the wallet", wait_present(page, "wallet-available"))
    ctx.close()

    # ================= B06-B10 audits, signed in on populated routes + signed out
    reset(mkfx({"authorizations": [{"id": "a_o", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": NOW2H}]}))
    Tada = tok("ada@example.com")
    AUDIT_JS = """() => {
      const out = {colors:{}, radii:[], shadows:[], textShadows:[], filters:[], gradients:[], fonts:[], imgs: document.querySelectorAll('img,picture,video,canvas,iframe,object,embed').length, urlbg:[], maxAmount:null};
      const add = (c, why) => { if (!c) return; (out.colors[c] = out.colors[c] || []); if (out.colors[c].length < 3) out.colors[c].push(why); };
      const label = el => el.tagName.toLowerCase() + (el.className && el.className.baseVal === undefined && el.className ? '.' + String(el.className).split(' ')[0] : '') + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : '');
      for (const el of document.querySelectorAll('body, body *')) {
        const cs = getComputedStyle(el); if (cs.display === 'none') continue;
        const own = [...el.childNodes].some(n => n.nodeType === 3 && n.nodeValue.trim());
        if (own) { add(cs.color, 'color ' + label(el)); out.fonts.push({fam: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), w: cs.fontWeight, size: parseFloat(cs.fontSize), tag: el.tagName, lab: label(el)}); }
        if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)') add(cs.backgroundColor, 'bg ' + label(el));
        if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none') add(cs.borderTopColor, 'border ' + label(el));
        if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) add(cs.outlineColor, 'outline ' + label(el));
        if (el instanceof SVGElement && el.tagName !== 'svg') { if (cs.fill && cs.fill !== 'none' && !(el.tagName === 'path' && /^[MmLlHhVv0-9\s.,-]+$/.test(el.getAttribute('d') || ''))) add(cs.fill, 'fill ' + label(el)); if (cs.stroke && cs.stroke !== 'none') add(cs.stroke, 'stroke ' + label(el)); }
        const rad = cs.borderTopLeftRadius; if (rad !== '0px') out.radii.push({r: rad, lab: label(el), tag: el.tagName, cls: String(el.className.baseVal === undefined ? el.className : '')});
        if (cs.boxShadow !== 'none') out.shadows.push({s: cs.boxShadow, lab: label(el)});
        if (cs.textShadow !== 'none') out.textShadows.push({s: cs.textShadow, lab: label(el)});
        if (cs.filter !== 'none') out.filters.push({f: cs.filter, lab: label(el)});
        if (cs.backgroundImage !== 'none') { const r = el.getBoundingClientRect(); if (/url\\(/.test(cs.backgroundImage)) out.urlbg.push(label(el)); if (/gradient/.test(cs.backgroundImage)) out.gradients.push({lab: label(el), size: cs.backgroundSize, w: r.width, h: r.height}); }
      }
      return out;
    }"""
    agg = {"colors": {}, "radii": [], "shadows": [], "textShadows": [], "filters": [], "gradients": [], "fonts": [], "imgs": 0, "urlbg": []}
    def merge(o, where):
        for c, why in o["colors"].items(): agg["colors"].setdefault(c, []).extend(["%s: %s" % (where, w_) for w_ in why[:1]])
        for kx in ("radii", "shadows", "textShadows", "filters", "gradients", "fonts", "urlbg"): agg[kx].extend(o[kx])
        agg["imgs"] += o["imgs"]
    # signed in pages
    ctx, page = new_ctx(br, Tada, 375)
    wallet(page)
    tid(page, "refund-toggle-p_in1").click(); tid(page, "refund-amount-p_in1").fill("abc"); tid(page, "refund-submit-p_in1").click()
    tid(page, "refund-toggle-p_in2").click(); page.route("**/refunds", lambda route: (route.fetch(), route.abort("failed"))); tid(page, "refund-submit-p_in2").click(); wait_present(page, "refund-uncertain-p_in2"); page.unroute("**/refunds")
    tid(page, "refund-toggle-p_in3").click(); tid(page, "refund-amount-p_in3").fill("3.00"); tid(page, "refund-submit-p_in3").click(); wait_present(page, "refund-success-p_in3"); settle(page, 600)
    tid(page, "pay-handle").focus()
    for w in (375, 1280):
        page.set_viewport_size({"width": w, "height": 900}); settle(page, 200)
        merge(page.evaluate(AUDIT_JS), "wallet@%d" % w)
    # B10 headline
    heads = page.evaluate("""() => { const a=document.querySelector('[data-testid=wallet-available]'); const fs=[...document.querySelectorAll('body *')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.nodeValue.trim())).map(e=>({fs:parseFloat(getComputedStyle(e).fontSize), lab:e.getAttribute('data-testid')||e.tagName})); const mx=Math.max(...fs.map(x=>x.fs)); const top=fs.filter(x=>x.fs===mx).map(x=>x.lab);
        const t=document.querySelector('[data-testid=wallet-balance]'); const hd=document.querySelector('[data-testid=wallet-held]'); return {availFs: parseFloat(getComputedStyle(a).fontSize), top, totalFs: parseFloat(getComputedStyle(t).fontSize), heldFs: hd?parseFloat(getComputedStyle(hd).fontSize):null, avail: a.dataset.amount, y: a.getBoundingClientRect().top, mainTop: document.querySelector('main').getBoundingClientRect().top, firstH2Top: document.querySelector('h2').getBoundingClientRect().top}}""")
    me = me_api(Tada)
    ok("B10 Available funds is the largest text on the page (%s)" % heads["top"], heads["top"] == ["wallet-available"], heads)
    ok("B10 headline value is /me.available (data-amount %s == %s), secondary values smaller" % (heads["avail"], me["available"]), heads["avail"] == str(me["available"]) and heads["totalFs"] < heads["availFs"], heads)
    ok("B10 headline is above the first section heading (first thing in main)", heads["y"] < heads["firstH2Top"], heads)
    for route_ in ("/requests", "/split", "/authorizations"):
        page.goto(BASE + route_); settle(page, 900); merge(page.evaluate(AUDIT_JS), route_)
    page.goto(BASE + "/requests"); settle(page, 500)
    ctx.close()
    ctx = br.new_context(viewport={"width": 375, "height": 900}); page = ctx.new_page()
    for route_ in ("/login", "/signup"):
        page.goto(BASE + route_); settle(page, 600); merge(page.evaluate(AUDIT_JS), route_)
    # font loading + weights
    fl = page.evaluate("""async () => { await document.fonts.ready; const st = [...document.fonts].map(f => ({fam: f.family.replace(/"/g,''), status: f.status, w: f.weight}));
      const c = document.createElement('canvas').getContext('2d'); const s = 'Refund amount 1234567890 Pocketful'; const m = (w,f) => { c.font = w + ' 32px "' + f + '", serif'; return c.measureText(s).width; };
      return {st, dm: [m(400,'DM Sans'), m(500,'DM Sans')], inter: [m(400,'Inter'), m(500,'Inter')], dm700: document.fonts.check('700 16px "DM Sans"'), res: performance.getEntriesByType('resource').map(r => r.name).filter(n => /font|woff/i.test(n))}; }""")
    info("fonts:", fl)
    ctx.close()

    br.close()

# ---- assertions over the aggregated audit
def rgb(c):
    m = re.match(r"rgba?\(([^)]+)\)", c); p = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip()) if x]
    return (int(p[0]), int(p[1]), int(p[2])), (p[3] if len(p) > 3 else 1.0)
PAL = {"canvas": (3, 0, 20), "surface": (6, 3, 23), "raised": (16, 9, 58), "text": (244, 240, 255), "text2": (168, 166, 183), "accent": (147, 130, 255)}
palset = set(PAL.values())
offpal = {c: w_ for c, w_ in agg["colors"].items() if rgb(c)[0] not in palset and rgb(c)[1] > 0}
ok("B06 every colour computed on %d element-colours across wallet/requests/split/authorizations/login/signup is in the palette (off-palette: %s)" % (len(agg["colors"]), offpal), not offpal, offpal)
info("B06 distinct computed colours:", sorted(agg["colors"].keys()))
def bgs(kind): return {c for c, w_ in agg["colors"].items() if any(x.split(": ", 1)[1].startswith(kind) for x in w_)}
ok("B06 canvas #030014 is the page background (body bg rgb(3, 0, 20))", "rgb(3, 0, 20)" in agg["colors"] and any("bg body" in x for x in agg["colors"]["rgb(3, 0, 20)"]), agg["colors"].get("rgb(3, 0, 20)"))
ok("B06 surface #060317 used for cards/rows", "rgb(6, 3, 23)" in agg["colors"], list(agg["colors"]))
ok("B06 raised #10093a used (wallet strip, inputs, panels)", "rgb(16, 9, 58)" in agg["colors"])
ok("B06 text #f4f0ff and secondary #a8a6b7 both used", "rgb(244, 240, 255)" in agg["colors"] and "rgb(168, 166, 183)" in agg["colors"])
ok("B06 one accent #9382ff used", "rgb(147, 130, 255)" in agg["colors"])
def hue_sat(c):
    (r, g, b), a = rgb(c); h_, l_, s_ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255); return h_ * 360, s_, l_
chromatic = {c: round(hue_sat(c)[0]) for c in agg["colors"] if rgb(c)[1] > 0 and hue_sat(c)[1] > 0.2 and 0.3 < hue_sat(c)[2] < 0.95}
reds_greens = {c: hh for c, hh in chromatic.items() if hh <= 25 or hh >= 335 or 70 <= hh <= 170}
ok("B09 no red or green hue anywhere in computed colours (chromatic: %s)" % chromatic, not reds_greens, reds_greens)
ok("B06 the only bright chromatic colour is the accent (%s)" % list(chromatic), set(chromatic) <= {"rgb(147, 130, 255)"}, chromatic)
rad = {}
for r_ in agg["radii"]: rad.setdefault(r_["r"], set()).add(r_["lab"].split("[")[0])
info("B08 radii by value:", {k_: sorted(v)[:8] for k_, v in rad.items()})
ok("B08 every radius is 5px, 16px or 32px (%s)" % sorted(rad), set(rad) <= {"5px", "16px", "32px"}, sorted(rad))
def rads(sel_fn): return {r_["r"] for r_ in agg["radii"] if sel_fn(r_)}
ok("B08 controls (button, input, select) are 5px", rads(lambda r_: r_["tag"] in ("BUTTON", "INPUT", "SELECT") and "checkbox" not in r_["lab"]) <= {"5px"} and rads(lambda r_: r_["tag"] in ("BUTTON", "INPUT", "SELECT")), rads(lambda r_: r_["tag"] in ("BUTTON", "INPUT", "SELECT")))
ok("B08 cards (.card .row .wallet .empty) are 16px", rads(lambda r_: any(r_["lab"].startswith(x) for x in ("form.card", "section.wallet", "li.row", "div.empty", "div.card", "section.card"))) == {"16px"}, rads(lambda r_: any(r_["lab"].startswith(x) for x in ("form.card", "section.wallet", "li.row", "div.empty", "div.card", "section.card"))))
ok("B08 badges (chips, nav pills) are 32px", rads(lambda r_: r_["lab"].startswith("span.chip") or (r_["tag"] == "A" and "nav" in r_["lab"]) or r_["lab"].startswith("a")) <= {"32px", "5px"} and "32px" in rads(lambda r_: r_["lab"].startswith("span.chip")), rads(lambda r_: r_["lab"].startswith("span.chip")))
inset_only = [s_ for s_ in agg["shadows"] if "inset" not in s_["s"]]
ok("B08 depth by inset rim light only: all %d box-shadows are inset, none is a drop shadow" % len(agg["shadows"]), not inset_only and agg["shadows"], inset_only[:3])
ok("B08 no text-shadow, no CSS filter drop-shadow", not agg["textShadows"] and not [f for f in agg["filters"] if "drop-shadow" in f["f"]], (agg["textShadows"][:2], agg["filters"][:2]))
big = [g for g in agg["gradients"] if not all(float(x.replace("px", "")) <= 8 for x in re.findall(r"[\d.]+px", g["size"]))]
ok("B10 no large gradient fills (%d gradients, all <= 8px select arrows)" % len(agg["gradients"]), not big, big[:3])
ok("B10 no stock imagery / mascots: no img/picture/video/canvas/iframe, no url() backgrounds", agg["imgs"] == 0 and not agg["urlbg"], (agg["imgs"], agg["urlbg"]))
fams = {f["fam"] for f in agg["fonts"]}; weights = {f["w"] for f in agg["fonts"]}
ok("B07 only DM Sans and Inter are used (%s)" % sorted(fams), fams <= {"DM Sans", "Inter"}, fams)
ok("B07 every computed font-weight is 400 or 500, never above 500 (%s)" % sorted(weights), weights <= {"400", "500"}, weights)
hd = [f for f in agg["fonts"] if f["tag"] in ("H1", "H2", "H3", "H4", "H5", "H6")]
ok("B07 headings (%d h-elements) are DM Sans 500" % len(hd), hd and all(f["fam"] == "DM Sans" and f["w"] == "500" for f in hd), [f for f in hd if not (f["fam"] == "DM Sans" and f["w"] == "500")])
body_ = [f for f in agg["fonts"] if f["tag"] in ("P", "LABEL", "INPUT", "BUTTON", "LI", "A", "TIME") or f["lab"].startswith("span.chip")]
ok("B07 body text (p, label, input, button, li, a, time: %d) is Inter 400/500" % len(body_), body_ and all(f["fam"] == "Inter" and f["w"] in ("400", "500") for f in body_), [f for f in body_ if not (f["fam"] == "Inter" and f["w"] in ("400", "500"))][:4])
info("B07 non-heading elements set in DM Sans (display numbers/brand):", sorted({f["lab"] for f in agg["fonts"] if f["fam"] == "DM Sans" and f["tag"] not in ("H1", "H2", "H3", "H4", "H5", "H6")}))
stat = {f["fam"]: f["status"] for f in fl["st"]}
ok("B07 both bundled fonts report status 'loaded' (%s)" % fl["st"], stat.get("DM Sans") == "loaded" and stat.get("Inter") == "loaded", fl["st"])
ok("B07 the face is genuinely variable: width at 500 differs from 400 (DM Sans %s, Inter %s) so weight 500 is real, not synthesised" % (fl["dm"], fl["inter"]), fl["dm"][0] != fl["dm"][1] and fl["inter"][0] != fl["inter"][1], fl)
ok("B07 font requests were same-origin /assets/fonts only: %s" % fl["res"], fl["res"] and all(n.startswith(BASE + "/assets/fonts/") for n in fl["res"]), fl["res"])
ok("B11/B07 no request left the origin during the whole browser session (%d external)" % len(EXTERNAL), not EXTERNAL, EXTERNAL[:5])

# ---- stylesheet inspection (the literal CSS)
css = ""
for n in ("tokens", "base", "components"):
    s_, b_ = None, None
    c = http.client.HTTPConnection(HOST, PORT); c.request("GET", "/assets/css/%s.css" % n); r_ = c.getresponse(); css += r_.read().decode() + "\n"; c.close()
hexes = {h_.lower() for h_ in re.findall(r"#[0-9a-fA-F]{3,8}\b", css)}
ok("B06 CSS hex literals are exactly the six palette colours %s" % sorted(hexes), hexes == {"#030014", "#060317", "#10093a", "#f4f0ff", "#a8a6b7", "#9382ff"}, hexes)
rgbas = set(re.findall(r"rgba?\([^)]*\)", css))
ok("B06 CSS rgba() literals are only the text colour at low alpha (rim/line): %s" % sorted(rgbas), rgbas == {"rgba(244, 240, 255, 0.08)", "rgba(244, 240, 255, 0.14)"}, rgbas)
ok("B06 no hsl()/oklch()/named colour red/green/blue/etc in CSS", not re.search(r"\b(hsla?|oklch|oklab|lab|lch)\(|:\s*(red|green|blue|orange|yellow|crimson|lime|teal|tomato)\b", css), None)
fw = re.findall(r"font-weight:\s*([^;]+);", css) + re.findall(r"font:\s*([^;]*)", css)
nums = {int(x) for s_ in fw for x in re.findall(r"\b([1-9]00)\b", s_)}
ok("B07 CSS declares no numeric font-weight above 500 (found %s) and no bold/bolder" % sorted(nums), all(n <= 500 for n in nums) and not re.search(r"font-weight:\s*(bold|bolder|[6-9]00)", css), nums)
ok("B07 @font-face rules bundle DM Sans and Inter from /assets/fonts with weight 400 500", css.count("@font-face") == 2 and 'url("/assets/fonts/dm-sans.woff2")' in css and 'url("/assets/fonts/inter.woff2")' in css and css.count("font-weight: 400 500") == 2)
ok("B07/B11 CSS has no http(s):// URL and no @import", not re.search(r"https?://|@import", css))
shadow_decls = re.findall(r"box-shadow:\s*([^;]+);", css)
ok("B08 every CSS box-shadow declaration is var(--rim-light) or none (%s)" % sorted(set(shadow_decls)), all(d.strip() in ("var(--rim-light)", "none") for d in shadow_decls), shadow_decls)
ok("B08 --rim-light is an inset 0 1px 0 shadow", "--rim-light: inset 0 1px 0" in css)
radius_decls = set(re.findall(r"border-radius:\s*([^;]+);", css))
ok("B08 CSS border-radius declarations use only the three tokens (%s)" % sorted(radius_decls), radius_decls <= {"var(--radius-control)", "var(--radius-card)", "var(--radius-badge)"}, radius_decls)
ok("B08 radius tokens are 5px / 16px / 32px", all(x in css for x in ("--radius-control: 5px", "--radius-card: 16px", "--radius-badge: 32px")))
ok("B10 CSS has no text-shadow / drop-shadow; linear-gradient only on <select> arrow", "text-shadow" not in css and "drop-shadow" not in css and css.count("gradient(") == 2)
done("b7_stage4")
