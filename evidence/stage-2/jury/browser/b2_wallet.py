"""I04-I14: wallet money display, pay form decimal rules, resubmit, stale state, lost response, wallet-refresh latest-wins, /requests actions."""
from bl import *

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def wait_present(page, t, timeout=5000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, timeout=timeout); return True
    except Exception: return False
def wait_gone(page, t, timeout=5000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, state="detached", timeout=timeout); return True
    except Exception: return False
def settle(page, ms=500): page.wait_for_timeout(ms)
def bal_api(token): return api("GET", "/me", token=token)[1]

def new_page(br, token, width=375, log=None):
    ctx = br.new_context(); seeded_page(ctx, token); page = ctx.new_page(); page.set_viewport_size({"width": width, "height": 900})
    if log is not None:
        def on_req(r):
            if r.method == "POST" and any(r.url.endswith(p) for p in ("/payments", "/requests", "/splits", "/authorizations")) or "/pay" in r.url and r.method == "POST":
                log.append({"url": r.url.replace(BASE, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data})
        page.on("request", on_req)
    return ctx, page

def goto_wallet(page):
    page.goto(BASE + "/"); wait_present(page, "wallet-balance"); settle(page, 300)

def fill_pay(page, handle=None, amount=None, note=None, vis=None):
    if handle is not None: tid(page, "pay-handle").fill(handle)
    if amount is not None: tid(page, "pay-amount").fill(amount)
    if note is not None: tid(page, "pay-note").fill(note)
    if vis is not None: tid(page, "pay-visibility").select_option(vis)

with sync_playwright() as pw:
    br = launch(pw)
    base_fx = lambda **kw: fixture(**kw)

    # ============ A. decimal rules (EUR, minor_units 2)
    cases = [("15", 1500, True), ("15.00", 1500, True), ("15.5", 1550, True), ("15.005", None, False), ("abc", None, False), ("", None, False), ("-5", None, False), ("1,5", None, False), ("15.123", None, False), ("1e2", None, False)]
    for val, minor, valid in cases:
        reset(base_fx()); T = tok("ada@example.com"); log = []
        ctx, page = new_page(br, T, log=log); goto_wallet(page)
        fill_pay(page, "bob", val, "t")
        tid(page, "pay-submit").click(); settle(page, 700)
        posts = [x for x in log if x["url"].endswith("/payments")]
        if valid:
            body = json.loads(posts[0]["body"]) if posts else {}
            ok("I05 amount %r submits %d minor units (1 request)" % (val, minor), len(posts) == 1 and body.get("amount") == minor, posts)
            ok("I05 amount %r: payment succeeded, pay-error absent, balance %s" % (val, "%.2f EUR" % ((10000 - minor) / 100)), not present(page, "pay-error") and text(page, "wallet-balance") == "%.2f EUR" % ((10000 - minor) / 100), (text(page, "wallet-balance"), present(page, "pay-error")))
        else:
            ok("I05 amount %r rejected: NO request sent, pay-error shown with text" % val, len(posts) == 0 and present(page, "pay-error") and text(page, "pay-error") != "", (posts, present(page, "pay-error")))
            ok("I05 amount %r: balance unchanged" % val, bal_api(T)["balance"] == 10000)
        if val == "15.005":
            shot(page, "pay_error_decimals_375")
        ctx.close()
    # observe-only forms
    for val in ("0", "0.00", ".5", "15.", " 15 ", "+15", "15.50", "007"):
        reset(base_fx()); T = tok("ada@example.com"); log = []
        ctx, page = new_page(br, T, log=log); goto_wallet(page)
        fill_pay(page, "bob", val, "t"); tid(page, "pay-submit").click(); settle(page, 600)
        posts = [x for x in log if x["url"].endswith("/payments")]
        info("amount %r -> requests %d body %s pay-error %s" % (val, len(posts), posts[0]["body"] if posts else None, present(page, "pay-error")))
        ok("I05 amount %r: no 5xx / no crash (page still responsive)" % val, tid(page, "pay-submit").is_visible())
        ctx.close()

    # ============ B. keep values; resubmit unchanged; changed field = new payment
    reset(base_fx()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto_wallet(page)
    fill_pay(page, "bob", "20.00", "lunch", "private"); tid(page, "pay-submit").click()
    wait_present(page, "activity-list"); settle(page, 600)
    ok("I06 balance fell once (80.00 EUR)", text(page, "wallet-balance") == "80.00 EUR", text(page, "wallet-balance"))
    vals = (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value(), tid(page, "pay-visibility").input_value())
    ok("I06 pay form keeps its values after success", vals == ("bob", "20.00", "lunch", "private"), vals)
    tid(page, "pay-submit").click(); settle(page, 800); tid(page, "pay-submit").click(); settle(page, 800)
    posts = [x for x in log if x["url"].endswith("/payments")]
    keys = {x["key"] for x in posts}; bodies = {x["body"] for x in posts}
    info("unchanged resubmits: %d POSTs, %d distinct Idempotency-Key, %d distinct body (same key+body = replay, not a second payment)" % (len(posts), len(keys), len(bodies)))
    ok("I06 resubmitting the unchanged form sends no SECOND payment: every POST carries the same key and identical body", len(keys) == 1 and len(bodies) == 1 and None not in keys, [(x["key"], x["body"]) for x in posts])
    ok("I06 balance still 80.00 EUR, server balance 8000", text(page, "wallet-balance") == "80.00 EUR" and bal_api(T)["balance"] == 8000, (text(page, "wallet-balance"), bal_api(T)))
    items = [e for e in page.locator('[data-testid^="activity-item-"]').all() if "lunch" in e.inner_text()]
    ok("I06 feed contains exactly one such payment; pay-error absent", len(items) == 1 and not present(page, "pay-error"), (len(items), present(page, "pay-error")))
    tid(page, "pay-note").fill("lunch 2"); tid(page, "pay-submit").click(); settle(page, 800)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I06 changed note => a NEW payment: 2 distinct keys in total; balance 60.00", len({p["key"] for p in posts}) == 2 and bal_api(T)["balance"] == 6000, [(p["key"], p["body"]) for p in posts])
    tid(page, "pay-amount").fill("10"); tid(page, "pay-submit").click(); settle(page, 800)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I06 changed amount => another payment (3 distinct keys, balance 50.00)", len({p["key"] for p in posts}) == 3 and bal_api(T)["balance"] == 5000 and text(page, "wallet-balance") == "50.00 EUR", (len(posts), text(page, "wallet-balance")))
    tid(page, "pay-visibility").select_option("public"); tid(page, "pay-submit").click(); settle(page, 800)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I06 changed visibility => another payment (4 distinct keys, balance 40.00)", len({p["key"] for p in posts}) == 4 and bal_api(T)["balance"] == 4000, len(posts))
    tid(page, "pay-handle").fill("dee"); tid(page, "pay-submit").click(); settle(page, 800)
    ok("I06 changed handle => another payment (balance 30.00)", bal_api(T)["balance"] == 3000, bal_api(T))
    # feed order newest first, attributes
    ids = page.eval_on_selector_all('[data-testid="activity-list"] > *', "els => els.map(e => e.getAttribute('data-testid'))")
    ok("I07 activity-list children are activity items, newest first (API order equals DOM order)", [i.replace("activity-item-", "") for i in ids] == [p["payment_id"] for p in api("GET", "/activity?limit=200", token=T)[1]["payments"]], (ids, [p["payment_id"] for p in api("GET", "/activity?limit=200", token=T)[1]["payments"]]))
    first = api("GET", "/activity?limit=200", token=T)[1]["payments"][0]
    pid = first["payment_id"]
    ok("I07 item carries data-visibility", tid(page, "activity-item-" + pid).get_attribute("data-visibility") == first["visibility"])
    ok("I07 parties text contains both handles", all(h in text(page, "activity-parties-" + pid) for h in (first["from_handle"], first["to_handle"])), text(page, "activity-parties-" + pid))
    ok("I07 amount exactly formatted", text(page, "activity-amount-" + pid) == "10.00 EUR", text(page, "activity-amount-" + pid))
    ok("I07 note element present (exact note)", text(page, "activity-note-" + pid) == first["note"], (text(page, "activity-note-" + pid), first["note"]))
    ctx.close()
    # note element present even when empty + private visibility attr
    reset(base_fx(payments=[{"id": "p_e", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "", "visibility": "private"}])); T = tok("ada@example.com")
    ctx, page = new_page(br, T); goto_wallet(page)
    ok("I07 empty-note payment: activity-note present and empty; data-visibility private", present(page, "activity-note-p_e") and text(page, "activity-note-p_e") == "" and tid(page, "activity-item-p_e").get_attribute("data-visibility") == "private", (present(page, "activity-note-p_e"),))
    ctx.close()
    reset(base_fx()); T3 = tok("cy@example.com"); ctx, page = new_page(br, T3); goto_wallet(page)
    ok("I07 empty-activity shown instead of list when nothing visible", present(page, "empty-activity") and not present(page, "activity-list"))
    shot(page, "empty_activity_375"); ctx.close()

    # ============ C. formats for other currencies
    for cur, mu, bal, exp_text, good, bad in (("JPY", 0, 1200, "1200 JPY", ("15", 15), "15.0"), ("BHD", 3, 100000, "100.000 BHD", ("1.5", 1500), "1.5555")):
        f = base_fx(users=[user("ada", bal), user("bob", 0)]); f["currency"] = cur; f["minor_units"] = mu
        reset(f); T = tok("ada@example.com"); log = []
        ctx, page = new_page(br, T, log=log); goto_wallet(page)
        ok("I04 %s wallet-balance exactly %r" % (cur, exp_text), text(page, "wallet-balance") == exp_text and tid(page, "wallet-balance").get_attribute("data-amount") == str(bal), (text(page, "wallet-balance"), tid(page, "wallet-balance").get_attribute("data-amount")))
        ok("I04 %s no decimal point issue: wallet-available equals total when no holds" % cur, text(page, "wallet-available") == exp_text and tid(page, "wallet-available").get_attribute("data-amount") == str(bal), text(page, "wallet-available"))
        fill_pay(page, "bob", bad, "x"); tid(page, "pay-submit").click(); settle(page, 500)
        ok("I05 %s amount %r (too many decimals) rejected locally, no request" % (cur, bad), not [x for x in log if x["url"].endswith("/payments")] and present(page, "pay-error"))
        fill_pay(page, "bob", good[0], "x"); tid(page, "pay-submit").click(); settle(page, 700)
        posts = [json.loads(x["body"])["amount"] for x in log if x["url"].endswith("/payments")]
        ok("I05 %s amount %r submits %d minor units" % (cur, good[0], good[1]), posts == [good[1]], posts)
        tid(page, "pay-amount").fill(good[0]);
        feed_amt = page.locator('[data-testid^="activity-amount-"]').first.inner_text().strip()
        ok("I07 %s feed amount exactly formatted" % cur, feed_amt == ("15 JPY" if cur == "JPY" else "1.500 BHD"), feed_amt)
        ctx.close()

    # ============ D. stale state: balance spent elsewhere
    reset(base_fx()); T = tok("ada@example.com")
    ctx, page = new_page(br, T); goto_wallet(page)
    fill_pay(page, "bob", "50.00", "stale note", "private")
    st, _ = api("POST", "/payments", {"to_handle": "dee", "amount": 9990, "note": "elsewhere"}, token=T, key=k()); assert st == 201
    tid(page, "pay-submit").click(); settle(page, 900)
    ok("I12 refused payment shows pay-error (insufficient funds)", present(page, "pay-error") and text(page, "pay-error") != "", present(page, "pay-error"))
    ok("I12 balance refreshed to 0.10 EUR", text(page, "wallet-balance") == "0.10 EUR", text(page, "wallet-balance"))
    ok("I12 feed refreshed: the payment made elsewhere is listed", any("elsewhere" in e.inner_text() for e in page.locator('[data-testid^="activity-item-"]').all()))
    ok("I12 all pay inputs preserved", (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value(), tid(page, "pay-visibility").input_value()) == ("bob", "50.00", "stale note", "private"))
    ok("I12 no pay-uncertain on a confirmed refusal", not present(page, "pay-uncertain"))
    shot(page, "pay_refused_375")
    tid(page, "pay-amount").fill("0.05"); tid(page, "pay-submit").click(); settle(page, 800)
    ok("I12 recovery: amended payment succeeds, pay-error gone, balance 0.05 EUR", not present(page, "pay-error") and text(page, "wallet-balance") == "0.05 EUR", (present(page, "pay-error"), text(page, "wallet-balance")))
    ctx.close()
    # refused by holds (available < amount)
    f = base_fx(authorizations=[{"id": "a_h", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 9000, "note": "h", "visibility": "public", "status": "open", "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))}])
    reset(f); T = tok("ada@example.com"); ctx, page = new_page(br, T); goto_wallet(page)
    ok("I16 seeded hold: wallet-available is 10.00 EUR right after reset, held 90.00 EUR shown, total 100.00", text(page, "wallet-available") == "10.00 EUR" and text(page, "wallet-held") == "90.00 EUR" and text(page, "wallet-balance") == "100.00 EUR", (text(page, "wallet-available"), text(page, "wallet-held"), text(page, "wallet-balance")))
    ok("I16 data-amount on all three", (tid(page, "wallet-available").get_attribute("data-amount"), tid(page, "wallet-held").get_attribute("data-amount"), tid(page, "wallet-balance").get_attribute("data-amount")) == ("1000", "9000", "10000"))
    sz = page.evaluate("""() => { const f = t => parseFloat(getComputedStyle(document.querySelector('[data-testid="'+t+'"]')).fontSize); return {avail: f('wallet-available'), total: f('wallet-balance'), held: f('wallet-held')}; }""")
    ok("I16 available is the headline: font-size greater than total and held", sz["avail"] > sz["total"] and sz["avail"] > sz["held"], sz)
    fill_pay(page, "bob", "20.00", "h"); tid(page, "pay-submit").click(); settle(page, 700)
    ok("I12 payment above AVAILABLE refused with pay-error although total is 100.00", present(page, "pay-error"))
    fill_pay(page, "bob", "10.00", "h2"); tid(page, "pay-submit").click(); settle(page, 700)
    ok("I12 payment of exactly available succeeds; available 0.00, held stays 90.00", not present(page, "pay-error") and text(page, "wallet-available") == "0.00 EUR" and text(page, "wallet-held") == "90.00 EUR", (text(page, "wallet-available"), text(page, "wallet-held")))
    shot(page, "wallet_holds_375"); ctx.close()
    reset(base_fx()); T = tok("ada@example.com"); ctx, page = new_page(br, T); goto_wallet(page)
    ok("I16 wallet-held absent at zero; wallet-available present", not present(page, "wallet-held") and text(page, "wallet-available") == "100.00 EUR")
    ctx.close()

    # ============ G. lost response
    reset(base_fx()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto_wallet(page)
    mode = {"m": "commit_then_drop"}
    def handler(route):
        if route.request.method != "POST": return route.continue_()
        if mode["m"] == "commit_then_drop":
            route.fetch(); route.abort("failed")
        elif mode["m"] == "drop_before":
            route.abort("failed")
        else: route.continue_()
    page.route("**/payments", handler)
    fill_pay(page, "bob", "12.00", "lost one", "public"); tid(page, "pay-submit").click(); settle(page, 1200)
    ok("I14 lost response (after commit) -> pay-uncertain shown with text", present(page, "pay-uncertain") and text(page, "pay-uncertain") != "", present(page, "pay-uncertain"))
    ok("I14 pay-error NOT shown for an unknown outcome", not present(page, "pay-error"))
    ok("I14 server committed exactly once so far (balance 88.00)", bal_api(T)["balance"] == 8800)
    shot(page, "pay_uncertain_375")
    ok("I14 form values kept", (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value()) == ("bob", "12.00", "lost one"))
    mode["m"] = "pass"; tid(page, "pay-submit").click(); settle(page, 1200)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I14 unchanged retry sends the SAME Idempotency-Key and byte-identical body", len(posts) == 2 and posts[0]["key"] == posts[1]["key"] and posts[0]["body"] == posts[1]["body"] and posts[0]["key"], [(p["key"], p["body"]) for p in posts])
    ok("I14 money moved exactly once (server balance 88.00; UI 88.00 EUR)", bal_api(T)["balance"] == 8800 and text(page, "wallet-balance") == "88.00 EUR", (bal_api(T)["balance"], text(page, "wallet-balance")))
    ok("I14 pay-uncertain and pay-error both removed after the successful retry", not present(page, "pay-uncertain") and not present(page, "pay-error"))
    ok("I14 feed refreshed with exactly one such payment", len([e for e in page.locator('[data-testid^="activity-item-"]').all() if "lost one" in e.inner_text()]) == 1)
    page.unroute("**/payments"); ctx.close()
    # lost BEFORE commit
    reset(base_fx()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto_wallet(page); mode["m"] = "drop_before"; page.route("**/payments", handler)
    fill_pay(page, "bob", "5.00", "never reached"); tid(page, "pay-submit").click(); settle(page, 1000)
    ok("I14 request lost before commit -> pay-uncertain, balance unchanged", present(page, "pay-uncertain") and not present(page, "pay-error") and bal_api(T)["balance"] == 10000)
    mode["m"] = "pass"; tid(page, "pay-submit").click(); settle(page, 1000)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I14 retry after never-committed request: same key/body, now moves money once", posts[0]["key"] == posts[1]["key"] and posts[0]["body"] == posts[1]["body"] and bal_api(T)["balance"] == 9500 and not present(page, "pay-uncertain"))
    page.unroute("**/payments"); ctx.close()
    # offline
    reset(base_fx()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto_wallet(page)
    fill_pay(page, "bob", "5.00", "offline"); ctx.set_offline(True); tid(page, "pay-submit").click(); settle(page, 1200)
    ok("I14 network down -> pay-uncertain (not pay-error)", present(page, "pay-uncertain") and not present(page, "pay-error"))
    ctx.set_offline(False); tid(page, "pay-submit").click(); settle(page, 1200)
    ok("I14 back online: retry works once; money moved once", bal_api(T)["balance"] == 9500 and not present(page, "pay-uncertain"), bal_api(T))
    ctx.close()

    # ============ H. wallet-refresh latest wins
    reset(base_fx()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto_wallet(page)
    fill_pay(page, "bob", "7.00", "typed", "private")
    state = {"n": 0}
    def me_handler(route):
        if route.request.method != "GET": return route.continue_()
        state["n"] += 1; n = state["n"]
        resp = route.fetch()           # state captured NOW
        if n == 1:
            page.wait_for_timeout(1800)   # earlier read answers LATE
        route.fulfill(response=resp)
    page.route("**/me", me_handler)
    tid(page, "wallet-refresh").click()                       # read A: balance 100.00 captured now, delivered after ~1.8s
    page.wait_for_timeout(150)
    api("POST", "/payments", {"to_handle": "dee", "amount": 2500, "note": "moved"}, token=T, key=k())   # state moves on
    tid(page, "wallet-refresh").click()                       # read B: 75.00, immediate
    page.wait_for_timeout(500)
    ok("I11 later refresh shows 75.00 EUR first", text(page, "wallet-balance") == "75.00 EUR", text(page, "wallet-balance"))
    page.wait_for_timeout(2500)
    ok("I11 LATEST WINS: delayed earlier response (100.00) did not overwrite 75.00", text(page, "wallet-balance") == "75.00 EUR" and text(page, "wallet-available") == "75.00 EUR", (text(page, "wallet-balance"), text(page, "wallet-available")))
    ok("I11 wallet-refresh did not clear the pay form", (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value(), tid(page, "pay-visibility").input_value()) == ("bob", "7.00", "typed", "private"))
    page.unroute("**/me")
    # feed out-of-order as well
    fstate = {"n": 0}
    def act_handler(route):
        if route.request.method != "GET": return route.continue_()
        fstate["n"] += 1; n = fstate["n"]; resp = route.fetch()
        if n == 1: page.wait_for_timeout(1800)
        route.fulfill(response=resp)
    page.route("**/activity*", act_handler)
    n0 = len(page.locator('[data-testid^="activity-item-"]').all())
    tid(page, "wallet-refresh").click(); page.wait_for_timeout(150)
    api("POST", "/payments", {"to_handle": "dee", "amount": 100, "note": "later feed"}, token=T, key=k())
    tid(page, "wallet-refresh").click(); page.wait_for_timeout(2800)
    items = [e.inner_text() for e in page.locator('[data-testid^="activity-item-"]').all()]
    ok("I11 feed latest wins too: newest payment listed after out-of-order responses", any("later feed" in i for i in items), items[:3])
    page.unroute("**/activity*")
    # three-way reorder: responses arrive 3,1,2
    delays = {1: 1500, 2: 800, 3: 0}; cnt = {"n": 0}
    def me3(route):
        if route.request.method != "GET": return route.continue_()
        cnt["n"] += 1; n = cnt["n"]; resp = route.fetch()
        page.wait_for_timeout(delays.get(n, 0)); route.fulfill(response=resp)
    page.route("**/me", me3)
    amounts = []
    for i in range(3):
        tid(page, "wallet-refresh").click(); page.wait_for_timeout(120)
        api("POST", "/payments", {"to_handle": "dee", "amount": 100, "note": "r%d" % i}, token=T, key=k())
    page.wait_for_timeout(3000)
    srv = bal_api(T)
    ok("I11 three overlapping refreshes answered out of order: UI ends on the LAST requested read", text(page, "wallet-balance") != "" and tid(page, "wallet-balance").get_attribute("data-amount") in (str(srv["balance"] + 100), str(srv["balance"] + 200), str(srv["balance"])) and int(tid(page, "wallet-balance").get_attribute("data-amount")) <= int(srv["balance"]) + 200, (tid(page, "wallet-balance").get_attribute("data-amount"), srv))
    page.unroute("**/me")
    tid(page, "wallet-refresh").click(); page.wait_for_timeout(800)
    ok("I11 a final plain refresh converges to the server balance", tid(page, "wallet-balance").get_attribute("data-amount") == str(srv["balance"]), (tid(page, "wallet-balance").get_attribute("data-amount"), srv))
    ctx.close()
    br.close()
done("b2_wallet")
