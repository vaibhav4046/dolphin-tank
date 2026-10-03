"""I08-I10 I13 I17 I18: /requests actions + stale refusal, /split preview, /authorizations + authorize/capture/void flows."""
from bl import *

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def shown(page, t): return tid(page, t).count() > 0 and tid(page, t).first.is_visible()
def wait_present(page, t, timeout=5000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, timeout=timeout); return True
    except Exception: return False
def settle(page, ms=500): page.wait_for_timeout(ms)
def me_api(token): return api("GET", "/me", token=token)[1]
def new_page(br, token, width=375, log=None):
    ctx = br.new_context(); seeded_page(ctx, token); page = ctx.new_page(); page.set_viewport_size({"width": width, "height": 900})
    if log is not None:
        page.on("request", lambda r: log.append({"m": r.method, "url": r.url.replace(BASE, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data}) if r.method != "GET" else None)
    return ctx, page
def goto(page, path, testid=None):
    page.goto(BASE + path)
    page.wait_for_function("document.querySelector('main') && document.querySelector('main').getAttribute('aria-busy') !== 'true'", timeout=8000)
    if testid: wait_present(page, testid)
    settle(page, 250)
def status_of(page, tid_):
    return tid(page, tid_).get_attribute("data-status") if present(page, tid_) else None
def future(h=2): return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + h * 3600))
def past(h=2): return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - h * 3600))

with sync_playwright() as pw:
    br = launch(pw)

    # =================================================== /requests
    rqs = [{"id": "rq_in1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
           {"id": "rq_in2", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 300, "note": "tea", "status": "pending"},
           {"id": "rq_in3", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 100, "note": "old", "status": "paid"},
           {"id": "rq_in4", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 100, "note": "old2", "status": "declined"},
           {"id": "rq_out1", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 450, "note": "snacks", "status": "pending"},
           {"id": "rq_out2", "requester_id": "u_ada", "payer_id": "u_dee", "amount": 50, "note": "gone", "status": "cancelled"},
           {"id": "rq_big", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 900000, "note": "huge", "status": "pending"}]
    reset(fixture(requests=rqs)); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto(page, "/requests", "incoming-list")
    ok("I08 incoming-list and outgoing-list present, empty-requests absent", present(page, "incoming-list") and present(page, "outgoing-list") and not shown(page, "empty-requests") and not present(page, "request-error"))
    for rid, st, inc in (("rq_in1", "pending", True), ("rq_in2", "pending", True), ("rq_in3", "paid", True), ("rq_in4", "declined", True), ("rq_out1", "pending", False), ("rq_out2", "cancelled", False)):
        ok("I08 %s data-status=%s" % (rid, st), status_of(page, "request-item-" + rid) == st, status_of(page, "request-item-" + rid))
        inside = page.locator('[data-testid="%s"] [data-testid="request-item-%s"]' % ("incoming-list" if inc else "outgoing-list", rid)).count() == 1
        ok("I08 %s listed in the %s list" % (rid, "incoming" if inc else "outgoing"), inside)
    ok("I08 request-amount exact formatted", text(page, "request-amount-rq_in1") == "12.00 EUR" and text(page, "request-amount-rq_out1") == "4.50 EUR", (text(page, "request-amount-rq_in1"), text(page, "request-amount-rq_out1")))
    ok("I08 pay/decline only on PENDING incoming", present(page, "request-pay-rq_in1") and present(page, "request-decline-rq_in1") and not present(page, "request-pay-rq_in3") and not present(page, "request-decline-rq_in4") and not present(page, "request-pay-rq_out1") and not present(page, "request-decline-rq_out1"))
    ok("I08 cancel only on PENDING outgoing", present(page, "request-cancel-rq_out1") and not present(page, "request-cancel-rq_out2") and not present(page, "request-cancel-rq_in1"))
    shot(page, "requests_375")
    # pay
    tid(page, "request-pay-rq_in1").click(); settle(page, 800)
    ok("I10 pay: request becomes paid without reload, buttons removed", status_of(page, "request-item-rq_in1") == "paid" and not present(page, "request-pay-rq_in1") and not present(page, "request-decline-rq_in1") and not present(page, "request-error"))
    ok("I08 pay moved money once: ada 88.00, bob 37.00", (me_api(T)["balance"], me_api(tok("bob@example.com"))["balance"]) == (8800, 3700), me_api(T))
    posts = [x for x in log if x["url"].endswith("/pay")]
    ok("I08 pay sent POST /requests/{id}/pay with an Idempotency-Key", len(posts) == 1 and posts[0]["key"], posts)
    # decline
    tid(page, "request-decline-rq_in2").click(); settle(page, 800)
    ok("I10 decline: request declined, buttons removed", status_of(page, "request-item-rq_in2") == "declined" and not present(page, "request-pay-rq_in2"))
    # cancel
    tid(page, "request-cancel-rq_out1").click(); settle(page, 800)
    ok("I10 cancel: request cancelled, button removed", status_of(page, "request-item-rq_out1") == "cancelled" and not present(page, "request-cancel-rq_out1"))
    # insufficient funds
    tid(page, "request-pay-rq_big").click(); settle(page, 800)
    ok("I08 pay refused (insufficient funds): request-error shown, request stays pending, pay button still there", present(page, "request-error") and text(page, "request-error") != "" and status_of(page, "request-item-rq_big") == "pending" and present(page, "request-pay-rq_big"), (present(page, "request-error"), status_of(page, "request-item-rq_big")))
    shot(page, "request_error_375")
    ctx.close()
    # stale: cancelled elsewhere while pay button visible
    reset(fixture(requests=[{"id": "rq_a", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                            {"id": "rq_b", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 100, "note": "b", "status": "pending"},
                            {"id": "rq_c", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 100, "note": "c", "status": "pending"}]))
    T = tok("ada@example.com"); TB = tok("bob@example.com"); TC = tok("cy@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto(page, "/requests", "request-pay-rq_a")
    ok("I13 precondition: pay button visible", present(page, "request-pay-rq_a"))
    st, _ = api("POST", "/requests/rq_a/cancel", {}, token=TB); assert st == 200
    tid(page, "request-pay-rq_a").click(); settle(page, 900)
    ok("I13 request cancelled elsewhere: payment refused -> request-error shown", present(page, "request-error") and text(page, "request-error") != "", present(page, "request-error"))
    ok("I13 request list refreshed: item now cancelled and the stale pay button is gone", status_of(page, "request-item-rq_a") == "cancelled" and not present(page, "request-pay-rq_a") and not present(page, "request-decline-rq_a"), (status_of(page, "request-item-rq_a"), present(page, "request-pay-rq_a")))
    ok("I13 no money moved", me_api(T)["balance"] == 10000)
    # declined elsewhere then decline click; paid elsewhere then pay click replays? (different key) -> request_not_pending
    st, _ = api("POST", "/requests/rq_b/decline", {}, token=T); assert st == 200
    tid(page, "request-pay-rq_b").click(); settle(page, 900)
    ok("I13 request declined elsewhere: pay refused, request-error, list refreshed (pay button gone)", present(page, "request-error") and status_of(page, "request-item-rq_b") == "declined" and not present(page, "request-pay-rq_b"), status_of(page, "request-item-rq_b"))
    st, _ = api("POST", "/requests/rq_c/pay", {}, token=T, key=k()); assert st == 201
    tid(page, "request-decline-rq_c").click(); settle(page, 900)
    ok("I13 request paid elsewhere: decline refused, request-error, list shows paid", present(page, "request-error") and status_of(page, "request-item-rq_c") == "paid", (present(page, "request-error"), status_of(page, "request-item-rq_c")))
    ctx.close()
    # empty
    reset(fixture()); T = tok("cy@example.com"); ctx, page = new_page(br, T); goto(page, "/requests", "empty-requests")
    ok("I08 empty-requests shown (visible) when both lists empty", shown(page, "empty-requests"), shown(page, "empty-requests"))
    shot(page, "empty_requests_375"); ctx.close()
    # request form on wallet page
    reset(fixture()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto(page, "/", "request-handle")
    tid(page, "request-handle").fill("bob"); tid(page, "request-amount").fill("15.005"); tid(page, "request-note").fill("x"); tid(page, "request-submit").click(); settle(page, 600)
    ok("I05 request form: 15.005 rejected locally, request-error shown, nothing sent", present(page, "request-error") and not [x for x in log if x["url"].endswith("/requests")], log)
    tid(page, "request-amount").fill("15"); tid(page, "request-handle").fill("nobody"); tid(page, "request-submit").click(); settle(page, 700)
    ok("I08 request to unknown handle -> request-error (server refusal)", present(page, "request-error"))
    tid(page, "request-handle").fill("ada"); tid(page, "request-submit").click(); settle(page, 700)
    ok("I08 request to self -> request-error", present(page, "request-error"))
    tid(page, "request-handle").fill("bob"); tid(page, "request-submit").click(); settle(page, 800)
    ok("I08 valid request: request-error cleared; server has the pending request of 1500", not present(page, "request-error") and [r for r in api("GET", "/requests?direction=outgoing", token=T)[1]["requests"] if r["amount"] == 1500 and r["status"] == "pending"] != [], api("GET", "/requests", token=T)[1])
    goto(page, "/requests", "outgoing-list")
    ok("I10 new request listed in outgoing-list with cancel button", page.locator('[data-testid="outgoing-list"] [data-testid^="request-item-"]').count() == 1 and page.locator('[data-testid^="request-cancel-"]').count() == 1)
    ctx.close()

    # =================================================== /split
    reset(fixture()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto(page, "/split", "split-amount")
    def preview(amount, handles):
        tid(page, "split-amount").fill(amount); tid(page, "split-handles").fill(handles); settle(page, 400)
        return {h: text(page, "split-share-" + h) for h in [x.strip() for x in handles.split(",") if x.strip()] if present(page, "split-share-" + h)}
    p1 = preview("10.00", "ada,bob,cy")
    ok("I09 preview 10.00 / 3: 3.34, 3.33, 3.33 EUR in order", p1 == {"ada": "3.34 EUR", "bob": "3.33 EUR", "cy": "3.33 EUR"}, p1)
    p2 = preview("10.00", "bob,cy,ada")
    ok("I09 reordered handles move the extra unit to the first participant", p2 == {"bob": "3.34 EUR", "cy": "3.33 EUR", "ada": "3.33 EUR"}, p2)
    p3 = preview("0.01", "ada,bob,cy")
    ok("I09 preview 0.01 / 3: 0.01, 0.00, 0.00", p3 == {"ada": "0.01 EUR", "bob": "0.00 EUR", "cy": "0.00 EUR"}, p3)
    p4 = preview("0.10", "ada,bob,cy"); p5 = preview("9.99", "ada,bob,cy"); p6 = preview("0.05", "ada, bob ,cy,dee, x_y")
    ok("I09 preview 0.10 / 3 = 0.04, 0.03, 0.03; 9.99 / 3 = 3.33 x3", p4 == {"ada": "0.04 EUR", "bob": "0.03 EUR", "cy": "0.03 EUR"} and p5 == {"ada": "3.33 EUR", "bob": "3.33 EUR", "cy": "3.33 EUR"}, (p4, p5))
    ok("I09 handles with spaces/commas tolerated: 5 participants of 0.05 -> 0.01 each", all(v == "0.01 EUR" for v in p6.values()) and len(p6) == 5, p6)
    ok("I09 typing the preview posted nothing to the server", not [x for x in log if x["m"] == "POST"], log)
    shot(page, "split_preview_375")
    # submit and compare preview to server shares
    tid(page, "split-amount").fill("10.00"); tid(page, "split-handles").fill("bob,ada,cy"); tid(page, "split-note").fill("dinner"); settle(page, 300)
    pv = {h: text(page, "split-share-" + h) for h in ("bob", "ada", "cy")}
    tid(page, "split-submit").click(); settle(page, 1000)
    posts = [x for x in log if x["url"].endswith("/splits")]
    body = json.loads(posts[0]["body"]) if posts else {}
    ok("I09 submit sends POST /splits (1000 minor units, handles in typed order) with an Idempotency-Key", len(posts) == 1 and posts[0]["key"] and body.get("amount") == 1000 and body.get("participant_handles") == ["bob", "ada", "cy"], posts)
    reqs = api("GET", "/requests?direction=outgoing", token=T)[1]["requests"]
    byh = {r["payer_handle"]: r["amount"] for r in reqs}
    ok("I09 server requests equal the previewed shares (bob 3.34, cy 3.33; caller creates none for herself)", byh == {"bob": 334, "cy": 333} and pv == {"bob": "3.34 EUR", "ada": "3.33 EUR", "cy": "3.33 EUR"}, (byh, pv))
    ok("I09 split-error absent after success", not present(page, "split-error"))
    shot(page, "split_after_submit_375")
    # errors
    tid(page, "split-handles").fill("bob,bob"); tid(page, "split-submit").click(); settle(page, 700)
    ok("I09 duplicate handle -> split-error", present(page, "split-error") and text(page, "split-error") != "", present(page, "split-error"))
    tid(page, "split-handles").fill("bob,nobody"); tid(page, "split-submit").click(); settle(page, 700)
    ok("I09 unknown handle -> split-error", present(page, "split-error"))
    n_before = len([x for x in log if x["url"].endswith("/splits")])
    tid(page, "split-handles").fill("bob,cy"); tid(page, "split-amount").fill("10.005"); tid(page, "split-submit").click(); settle(page, 600)
    ok("I09 amount 10.005 rejected locally: split-error, nothing sent", present(page, "split-error") and len([x for x in log if x["url"].endswith("/splits")]) == n_before)
    tid(page, "split-amount").fill("abc"); tid(page, "split-submit").click(); settle(page, 500)
    ok("I09 nonnumeric amount: split-error, nothing sent", present(page, "split-error") and len([x for x in log if x["url"].endswith("/splits")]) == n_before)
    tid(page, "split-amount").fill("10.00"); tid(page, "split-handles").fill(""); tid(page, "split-submit").click(); settle(page, 500)
    ok("I09 empty handles: split-error, nothing sent", present(page, "split-error") and len([x for x in log if x["url"].endswith("/splits")]) == n_before)
    ctx.close()
    f = fixture(users=[user("ada", 1200), user("bob", 0), user("cy", 0)]); f["currency"] = "JPY"; f["minor_units"] = 0
    reset(f); T = tok("ada@example.com"); ctx, page = new_page(br, T); goto(page, "/split", "split-amount")
    pj = preview("1000", "ada,bob,cy")
    ok("I09 JPY preview 1000 / 3 = 334, 333, 333 JPY", pj == {"ada": "334 JPY", "bob": "333 JPY", "cy": "333 JPY"}, pj)
    ctx.close()

    # =================================================== /authorizations
    exp_future, exp_past = future(), past()
    fa = fixture(authorizations=[
        {"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": exp_future},
        {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "rent", "visibility": "private", "status": "open", "expires_at": exp_future},
        {"id": "a_cap", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 300, "note": "done", "visibility": "public", "status": "captured", "captured_amount": 300, "expires_at": exp_future},
        {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "note": "v", "visibility": "public", "status": "voided", "expires_at": exp_future},
        {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_dee", "amount": 100, "note": "e", "visibility": "public", "status": "open", "expires_at": exp_past}])
    reset(fa); T = tok("ada@example.com"); TB = tok("bob@example.com"); log = []
    ctx, page = new_page(br, T, log=log); goto(page, "/authorizations", "authorization-list")
    api_l = {a["authorization_id"]: a for a in api("GET", "/authorizations?limit=200", token=T)[1]["authorizations"]}
    ok("I17 authorization-list present, empty-authorizations absent, authorization-error absent", present(page, "authorization-list") and not present(page, "empty-authorizations") and not present(page, "authorization-error"))
    ids = page.eval_on_selector_all('[data-testid="authorization-list"] > *', "els => els.map(e => e.getAttribute('data-testid'))")
    ok("I17 children are authorization items, DOM order equals API order (newest first)", [i.replace("authorization-item-", "") for i in ids] == list(api("GET", "/authorizations?limit=200", token=T)[1]["authorizations"][i]["authorization_id"] for i in range(len(ids))), (ids,))
    for aid_, st in (("a_out", "open"), ("a_in", "open"), ("a_cap", "captured"), ("a_void", "voided"), ("a_exp", "expired")):
        ok("I17 %s data-status=%s" % (aid_, st), status_of(page, "authorization-item-" + aid_) == st, status_of(page, "authorization-item-" + aid_))
    ok("I17 authorization-amount exact formatted", text(page, "authorization-amount-a_out") == "20.00 EUR" and text(page, "authorization-amount-a_in") == "7.00 EUR", (text(page, "authorization-amount-a_out"), text(page, "authorization-amount-a_in")))
    ok("I17 authorization-captured present ONLY when captured (a_cap = 3.00 EUR)", present(page, "authorization-captured-a_cap") and text(page, "authorization-captured-a_cap") == "3.00 EUR" and not any(present(page, "authorization-captured-" + i) for i in ("a_out", "a_in", "a_void", "a_exp")), present(page, "authorization-captured-a_cap"))
    ok("I17 authorization-expires text is the RFC 3339 expires_at", text(page, "authorization-expires-a_out") == api_l["a_out"]["expires_at"] and RFC3339_ok(text(page, "authorization-expires-a_out")) if False else text(page, "authorization-expires-a_out") == api_l["a_out"]["expires_at"], (text(page, "authorization-expires-a_out"), api_l["a_out"]["expires_at"]))
    ok("I17 capture input + button ONLY on incoming OPEN (a_in)", present(page, "authorization-capture-a_in") and present(page, "authorization-capture-amount-a_in") and not any(present(page, "authorization-capture-" + i) or present(page, "authorization-capture-amount-" + i) for i in ("a_out", "a_cap", "a_void", "a_exp")))
    ok("I17 capture input pre-filled with the remaining amount (7.00)", tid(page, "authorization-capture-amount-a_in").input_value() in ("7.00", "7"), tid(page, "authorization-capture-amount-a_in").input_value())
    ok("I17 void button ONLY on outgoing OPEN (a_out)", present(page, "authorization-void-a_out") and not any(present(page, "authorization-void-" + i) for i in ("a_in", "a_cap", "a_void", "a_exp")))
    shot(page, "authorizations_375")
    # capture partial
    tid(page, "authorization-capture-amount-a_in").fill("15.005"); tid(page, "authorization-capture-a_in").click(); settle(page, 500)
    n_cap = len([x for x in log if "/capture" in x["url"]])
    ok("I17 capture amount 15.005 rejected locally (authorization-error, no request)", present(page, "authorization-error") and n_cap == 0, (present(page, "authorization-error"), n_cap))
    tid(page, "authorization-capture-amount-a_in").fill("9.00"); tid(page, "authorization-capture-a_in").click(); settle(page, 800)
    ok("I18 capture above remaining (9.00 > 7.00): authorization-error shown, nothing moved", present(page, "authorization-error") and me_api(T)["balance"] == 10000 and status_of(page, "authorization-item-a_in") == "open")
    shot(page, "authorization_error_375")
    tid(page, "authorization-capture-amount-a_in").fill("3.00"); tid(page, "authorization-capture-a_in").click(); settle(page, 900)
    caps = [x for x in log if "/capture" in x["url"] and x["body"] and "3" in x["body"]]
    srv = api("GET", "/authorizations?limit=200", token=T)[1]["authorizations"]; srv = {a["authorization_id"]: a for a in srv}["a_in"]
    info("capture 3.00 of 7.00 via UI: request body %s ; server now status=%s captured=%s remaining=%s" % (caps[-1]["body"] if caps else None, srv["status"], srv["captured_amount"], srv["remaining_amount"]))
    ok("I18 partial capture: ada (receiver) credited 3.00 exactly once; authorization-error cleared", me_api(T)["balance"] == 10300 and not present(page, "authorization-error"), (me_api(T), present(page, "authorization-error")))
    ok("I18 UI list matches server after capture (status %s)" % srv["status"], status_of(page, "authorization-item-a_in") == srv["status"], status_of(page, "authorization-item-a_in"))
    if srv["status"] == "open":
        ok("I18 partial-then-rest: UI keeps remainder open; input prefilled with new remaining 4.00", tid(page, "authorization-capture-amount-a_in").input_value() in ("4.00", "4"), tid(page, "authorization-capture-amount-a_in").input_value())
        tid(page, "authorization-capture-a_in").click(); settle(page, 900)
        s2 = {a["authorization_id"]: a for a in api("GET", "/authorizations?limit=200", token=T)[1]["authorizations"]}["a_in"]
        ok("I18 capture the rest (prefilled 4.00): captured 7.00, status captured, captured amount shown, controls gone", s2["status"] == "captured" and s2["captured_amount"] == 700 and status_of(page, "authorization-item-a_in") == "captured" and text(page, "authorization-captured-a_in") == "7.00 EUR" and not present(page, "authorization-capture-a_in"), (s2, status_of(page, "authorization-item-a_in")))
    else:
        info("UI capture is final: partial capture closed the hold and released the remainder (spec default); 'rest' cannot be captured after")
        ok("I18 final partial capture closed hold: status captured, captured 3.00 shown, controls gone", status_of(page, "authorization-item-a_in") == "captured" and text(page, "authorization-captured-a_in") == "3.00 EUR" and not present(page, "authorization-capture-a_in"))
    # void
    tid(page, "authorization-void-a_out").click(); settle(page, 900)
    ok("I18 void: item voided, void button removed, no error", status_of(page, "authorization-item-a_out") == "voided" and not present(page, "authorization-void-a_out") and not present(page, "authorization-error"))
    ok("I18 void released the hold: server held 0", me_api(T)["held"] == 0 and me_api(T)["available"] == me_api(T)["total"], me_api(T))
    ctx.close()
    # stale capture/void
    reset(fa); T = tok("ada@example.com"); TB = tok("bob@example.com")
    ctx, page = new_page(br, T); goto(page, "/authorizations", "authorization-list")
    st, _ = api("POST", "/authorizations/a_in/void", {}, token=TB); assert st == 200
    tid(page, "authorization-capture-a_in").click(); settle(page, 900)
    ok("I18 hold voided elsewhere: capture refused -> authorization-error, list refreshed (voided, stale controls gone)", present(page, "authorization-error") and status_of(page, "authorization-item-a_in") == "voided" and not present(page, "authorization-capture-a_in"), (present(page, "authorization-error"), status_of(page, "authorization-item-a_in")))
    st, _ = api("POST", "/authorizations/a_out/capture", {}, token=TB, key=k()); assert st == 201
    tid(page, "authorization-void-a_out").click(); settle(page, 900)
    ok("I18 hold captured elsewhere: void refused -> authorization-error, list shows captured, void button gone", present(page, "authorization-error") and status_of(page, "authorization-item-a_out") == "captured" and not present(page, "authorization-void-a_out"), (present(page, "authorization-error"), status_of(page, "authorization-item-a_out")))
    ctx.close()
    # empty
    reset(fixture()); T = tok("ada@example.com"); ctx, page = new_page(br, T); goto(page, "/authorizations", "empty-authorizations")
    ok("I17 empty-authorizations shown (and no list) when there are none", present(page, "empty-authorizations") and not present(page, "authorization-list"))
    shot(page, "empty_authorizations_375"); ctx.close()

    # =================================================== authorize form (find the page that has it)
    reset(fixture()); T = tok("ada@example.com"); log = []
    ctx, page = new_page(br, T, log=log)
    home = None
    for path in ("/", "/authorizations"):
        goto(page, path)
        if present(page, "authorize-handle"): home = path; break
    ok("I17 authorize form reachable (found on %s)" % home, home is not None)
    def authz_fill(h, a, n="", v=None):
        tid(page, "authorize-handle").fill(h); tid(page, "authorize-amount").fill(a); tid(page, "authorize-note").fill(n)
        if v: tid(page, "authorize-visibility").select_option(v)
    authz_fill("bob", "15.005", "x"); tid(page, "authorize-submit").click(); settle(page, 600)
    ok("I17 authorize 15.005 rejected locally: authorize-error, no request", present(page, "authorize-error") and not [x for x in log if x["url"].endswith("/authorizations")])
    authz_fill("bob", "abc"); tid(page, "authorize-submit").click(); settle(page, 500)
    ok("I17 authorize nonnumeric rejected locally", present(page, "authorize-error") and not [x for x in log if x["url"].endswith("/authorizations")])
    authz_fill("bob", "500.00", "too much"); tid(page, "authorize-submit").click(); settle(page, 800)
    ok("I17 authorize above available -> authorize-error (insufficient funds)", present(page, "authorize-error") and me_api(T)["held"] == 0)
    authz_fill("ada", "5.00"); tid(page, "authorize-submit").click(); settle(page, 800)
    ok("I17 authorize to self -> authorize-error", present(page, "authorize-error"))
    authz_fill("nobody", "5.00"); tid(page, "authorize-submit").click(); settle(page, 800)
    ok("I17 authorize unknown handle -> authorize-error", present(page, "authorize-error"))
    authz_fill("bob", "30.00", "hold it", "private"); tid(page, "authorize-submit").click(); settle(page, 1000)
    posts = [x for x in log if x["url"].endswith("/authorizations") and x["m"] == "POST"]
    ok("I17 authorize ok: authorize-error cleared; body 3000 minor units, key present; server holds 3000", not present(page, "authorize-error") and posts and json.loads(posts[-1]["body"])["amount"] == 3000 and posts[-1]["key"] and me_api(T)["held"] == 3000, (present(page, "authorize-error"), posts[-1:] ))
    ok("I16 wallet-available (headline) 70.00 EUR, wallet-held 30.00 EUR, wallet-balance 100.00 EUR after the hold, without reload", present(page, "wallet-available") and text(page, "wallet-available") == "70.00 EUR" and text(page, "wallet-held") == "30.00 EUR" and text(page, "wallet-balance") == "100.00 EUR", [text(page, t) for t in ("wallet-available", "wallet-held", "wallet-balance") if present(page, t)])
    n_posts = len(posts)
    tid(page, "authorize-submit").click(); settle(page, 800)
    posts = [x for x in log if x["url"].endswith("/authorizations") and x["m"] == "POST"]
    ok("I17 unchanged authorize resubmit does not create a second hold (same key replay)", me_api(T)["held"] == 3000 and len({x["key"] for x in posts[n_posts - 1:]}) == 1, (me_api(T)["held"], [x["key"] for x in posts[-3:]]))
    goto(page, "/authorizations", "authorization-list")
    items = page.locator('[data-testid^="authorization-item-"]').all()
    ok("I17 new hold listed on /authorizations as open, outgoing (void button), amount 30.00 EUR", len(items) == 1 and present(page, "authorization-void-" + items[0].get_attribute("data-testid").replace("authorization-item-", "")) and "30.00 EUR" in items[0].inner_text(), len(items))
    shot(page, "authorizations_after_authorize_375")
    ctx.close()
    # held visible on wallet after reload for seeded; wide layout screenshot of authorizations
    reset(fa); T = tok("ada@example.com"); ctx, page = new_page(br, T, width=1280); goto(page, "/authorizations", "authorization-list"); shot(page, "authorizations_1280"); ctx.close()
    br.close()
done("b3_flows")
