"""I19 states + keyboard use + UI reflecting clock expiry: loading / error+retry on every data route, keyboard-only payment, expiry seen by the UI without a request at the deadline."""
from bl import *

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def settle(page, ms=600): page.wait_for_timeout(ms)
def hscroll(page): return page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
def me_api(t): return api("GET", "/me", token=t)[1]
def ctx_page(br, token, width=375, log=None):
    ctx = br.new_context(); seeded_page(ctx, token); page = ctx.new_page(); page.set_viewport_size({"width": width, "height": 900})
    if log is not None:
        page.on("request", lambda r: log.append({"m": r.method, "url": r.url.replace(BASE, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data}) if r.method != "GET" else None)
    return ctx, page

reset(fixture()); T = tok("ada@example.com")
with sync_playwright() as pw:
    br = launch(pw)
    # ---------- loading and error states on each data route
    for route, ready in (("/", "wallet-balance"), ("/requests", "incoming-list"), ("/authorizations", "empty-authorizations"), ("/split", "split-amount")):
        ctx, page = ctx_page(br, T)
        def slow(rt):
            page.wait_for_timeout(1500); rt.continue_()
        page.route("**/me", slow); page.route("**/requests*", lambda rt: slow(rt) if "text/html" not in rt.request.headers.get("accept", "") else rt.continue_()); page.route("**/authorizations*", lambda rt: slow(rt) if "text/html" not in rt.request.headers.get("accept", "") else rt.continue_())
        page.goto(BASE + route, wait_until="commit"); page.wait_for_timeout(500)
        busy = page.evaluate("() => { const m = document.querySelector('main'); return {busy: m && m.getAttribute('aria-busy'), skeleton: !!document.querySelector('.skeleton, [data-loading], [role=status]'), text: m ? m.innerText.slice(0, 80) : ''}; }")
        ok("I19 %s loading state: aria-busy=true and a loading indicator/skeleton while data is in flight" % route, busy["busy"] == "true" and busy["skeleton"], busy)
        shot(page, "loading_%s" % (route.strip("/") or "wallet"))
        page.wait_for_function("document.querySelector('main') && document.querySelector('main').getAttribute('aria-busy') !== 'true'", timeout=8000)
        ok("I19 %s loading state resolves (aria-busy cleared)" % route, True)
        ctx.close()
        # error state: API unreachable
        ctx, page = ctx_page(br, T)
        page.route("**/me", lambda rt: rt.abort("failed")); page.route("**/requests*", lambda rt: rt.abort("failed") if "text/html" not in rt.request.headers.get("accept", "") else rt.continue_()); page.route("**/authorizations*", lambda rt: rt.abort("failed") if "text/html" not in rt.request.headers.get("accept", "") else rt.continue_())
        page.goto(BASE + route); page.wait_for_timeout(1500)
        main_txt = page.inner_text("main")
        retry = page.locator("main button", has_text="Try again")
        if route == "/split":
            info("/split with /me unreachable shows:", main_txt[:100].replace("\n", " / "))
        else:
            ok("I19 %s error state: explains the failure and offers Try again (no blank page)" % route, ("could not" in main_txt.lower() or "couldn" in main_txt.lower() or "error" in main_txt.lower()) and retry.count() >= 1, main_txt[:160])
            ok("I19 %s error state has no horizontal scroll" % route, hscroll(page))
            shot(page, "error_%s" % (route.strip("/") or "wallet"))
            page.unroute("**/me"); page.unroute("**/requests*"); page.unroute("**/authorizations*")
            if retry.count():
                retry.first.click(); page.wait_for_timeout(1800)
            ok("I19 %s recovery: Try again after the outage reloads the screen" % route, present(page, ready) or present(page, "empty-requests") or present(page, "wallet-balance") or present(page, "authorization-list"), page.inner_text("main")[:120])
        ctx.close()

    # ---------- keyboard-only payment
    reset(fixture()); T = tok("ada@example.com"); log = []
    ctx, page = ctx_page(br, T, log=log); page.goto(BASE + "/"); page.wait_for_selector('[data-testid="pay-handle"]'); page.wait_for_timeout(300)
    tid(page, "pay-handle").focus()
    page.keyboard.type("bob"); page.keyboard.press("Tab"); page.keyboard.type("11.00"); page.keyboard.press("Tab")
    focus_after_amount = page.evaluate("document.activeElement.getAttribute('data-testid')")
    page.keyboard.press("ArrowDown") if focus_after_amount == "pay-visibility" else None
    page.keyboard.press("Tab"); page.keyboard.type("keys only"); page.keyboard.press("Enter"); page.wait_for_timeout(900)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I19 keyboard only: handle, amount, visibility, note typed with Tab; Enter submits the pay form (1 payment of 1100)", len(posts) == 1 and json.loads(posts[0]["body"])["amount"] == 1100 and me_api(T)["balance"] == 8900, (posts, focus_after_amount))
    page.keyboard.press("Tab"); focus = page.evaluate("document.activeElement.getAttribute('data-testid') || document.activeElement.tagName")
    ok("I19 keyboard: focus order continues to the next control after the note field (%s)" % focus, focus in ("pay-submit", "BUTTON"), focus)
    ctx.close()
    # ---------- keyboard only on /requests and /authorizations controls (Enter/Space on buttons)
    exp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))
    reset(fixture(requests=[{"id": "rq_k", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "k", "status": "pending"}],
                  authorizations=[{"id": "a_k", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "k", "visibility": "public", "status": "open", "expires_at": exp}]))
    T = tok("ada@example.com"); ctx, page = ctx_page(br, T)
    page.goto(BASE + "/requests"); page.wait_for_selector('[data-testid="request-pay-rq_k"]'); tid(page, "request-pay-rq_k").focus(); page.keyboard.press("Enter"); page.wait_for_timeout(900)
    ok("I19 keyboard: Enter on the focused request-pay button pays the request", tid(page, "request-item-rq_k").get_attribute("data-status") == "paid" and me_api(T)["balance"] == 9900)
    page.goto(BASE + "/authorizations"); page.wait_for_selector('[data-testid="authorization-void-a_k"]'); tid(page, "authorization-void-a_k").focus(); page.keyboard.press("Space"); page.wait_for_timeout(900)
    ok("I19 keyboard: Space on the focused void button voids the hold", tid(page, "authorization-item-a_k").get_attribute("data-status") == "voided")
    ctx.close()

    # ---------- expiry reflected by the UI with no request at the deadline
    f = fixture(); f["authorization_ttl_seconds"] = 3
    reset(f); T = tok("ada@example.com"); TB = tok("bob@example.com")
    ctx, page = ctx_page(br, T); page.goto(BASE + "/"); page.wait_for_selector('[data-testid="authorize-handle"]'); page.wait_for_timeout(300)
    tid(page, "authorize-handle").fill("bob"); tid(page, "authorize-amount").fill("40.00"); tid(page, "authorize-note").fill("short"); tid(page, "authorize-submit").click(); page.wait_for_timeout(900)
    ok("I20 hold created through the UI: wallet-held 40.00 EUR, available 60.00 EUR", text(page, "wallet-held") == "40.00 EUR" and text(page, "wallet-available") == "60.00 EUR", (text(page, "wallet-held") if present(page, "wallet-held") else None, text(page, "wallet-available")))
    aid = api("GET", "/authorizations", token=T)[1]["authorizations"][0]
    # second page on /authorizations as the receiver, left open across the deadline
    ctx2, page2 = ctx_page(br, TB); page2.goto(BASE + "/authorizations"); page2.wait_for_selector('[data-testid="authorization-capture-%s"]' % aid["authorization_id"])
    deadline = ts_ = None
    import datetime as dt
    end = dt.datetime.fromisoformat(aid["expires_at"].replace("Z", "+00:00")) + dt.timedelta(seconds=0.6)
    while dt.datetime.now(dt.timezone.utc) < end: page.wait_for_timeout(50)
    tid(page, "wallet-refresh").click(); page.wait_for_timeout(900)
    ok("I20 after the deadline (no request sent at the deadline) wallet-refresh shows the released funds: held gone, available 100.00 EUR", not present(page, "wallet-held") and text(page, "wallet-available") == "100.00 EUR" and text(page, "wallet-balance") == "100.00 EUR", (present(page, "wallet-held"), text(page, "wallet-available")))
    tid(page2, "authorization-capture-%s" % aid["authorization_id"]).click(); page2.wait_for_timeout(900)
    ok("I20 stale capture button on an expired hold: authorization-error, list refreshed to expired, capture control removed", present(page2, "authorization-error") and tid(page2, "authorization-item-%s" % aid["authorization_id"]).get_attribute("data-status") == "expired" and not present(page2, "authorization-capture-%s" % aid["authorization_id"]), (present(page2, "authorization-error"), tid(page2, "authorization-item-%s" % aid["authorization_id"]).get_attribute("data-status")))
    shot(page2, "expired_after_stale_capture_375")
    ok("I20 no money moved by the refused capture", me_api(T)["total"] == 10000 and me_api(TB)["total"] == 2500)
    page.goto(BASE + "/authorizations"); page.wait_for_selector('[data-testid="authorization-list"]')
    ok("I20 /authorizations shows the hold as expired without capture/void controls", tid(page, "authorization-item-%s" % aid["authorization_id"]).get_attribute("data-status") == "expired" and not present(page, "authorization-void-%s" % aid["authorization_id"]))
    ctx.close(); ctx2.close()
    br.close()
done("b6_states")
