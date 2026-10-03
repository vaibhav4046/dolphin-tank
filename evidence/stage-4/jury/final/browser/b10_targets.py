"""B12 on the other refund targets and other currencies: a request payment and a capture are refundable from the browser (request/hold stay closed), refunds in 0- and 3-decimal currencies."""
from bl import *

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def settle(page, ms=500): page.wait_for_timeout(ms)
def wait_present(page, t, timeout=6000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, timeout=timeout); return True
    except Exception: return False
NOW2H = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 7200))

def acts(token):
    out, off = [], 0
    while True:
        s, j = api("GET", "/activity?limit=100&offset=%d" % off, token=token)
        out += j["payments"]
        if not j.get("has_more"): return out
        off += 100

with sync_playwright() as pw:
    br = launch(pw)
    # ---------- request payment + capture as refund targets
    reset(fixture(users=[user("ada", 10000), user("bob", 5000), user("cy", 0)],
                  requests=[{"id": "rq_pay", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}],
                  authorizations=[{"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": NOW2H}]))
    Tada, Tbob = tok("ada@example.com"), tok("bob@example.com")
    s, pay = api("POST", "/requests/rq_pay/pay", None, token=Tada, key=k()); ok("setup: request paid by ada via API", s in (200, 201), (s, pay))
    s, cap = api("POST", "/authorizations/a_cap/capture", {"amount": 1500}, token=Tbob, key=k()); ok("setup: bob captured 15.00 of the hold", s in (200, 201), (s, cap))
    pay_id = pay.get("payment_id") or (pay.get("payment") or {}).get("payment_id"); cap_id = cap.get("payment_id") or (cap.get("payment") or {}).get("payment_id")
    info("request payment id", pay_id, "capture payment id", cap_id)
    if not (pay_id and cap_id):
        info("bodies", pay, cap)
        ok("setup: payment ids found", False, (pay, cap))
    else:
        ctx = br.new_context(viewport={"width": 375, "height": 900}); seeded_page(ctx, Tbob); page = ctx.new_page()
        page.goto(BASE + "/"); wait_present(page, "activity-item-" + pay_id); settle(page, 400)
        ok("B12 the receiver (bob) is offered Refund on a REQUEST payment", present(page, "refund-toggle-" + pay_id))
        ok("B12 the receiver (bob) is offered Refund on a CAPTURE payment", present(page, "refund-toggle-" + cap_id))
        ok("B12 capture and request payments say where they came from", "Pays a request" in page.locator('[data-testid="activity-item-%s"]' % pay_id).inner_text() and "authorisation" in page.locator('[data-testid="activity-item-%s"]' % cap_id).inner_text())
        before = api("GET", "/me", token=Tbob)[1]
        tid(page, "refund-toggle-" + pay_id).click(); tid(page, "refund-amount-" + pay_id).fill("3.00"); tid(page, "refund-submit-" + pay_id).click()
        ok("B12 refund of a request payment succeeds in the browser", wait_present(page, "refund-success-" + pay_id))
        tid(page, "refund-toggle-" + cap_id).click(); tid(page, "refund-submit-" + cap_id).click()
        ok("B12 full refund of a capture (default amount 15.00) succeeds", wait_present(page, "refund-success-" + cap_id) and wait_present(page, "refund-done-" + cap_id))
        settle(page, 600)
        after = api("GET", "/me", token=Tbob)[1]
        ok("B12 bob's total fell by 300 + 1500", after["total"] == before["total"] - 1800, (before, after))
        rs = [p for p in acts(Tbob) if p.get("refund_of") in (pay_id, cap_id)]
        ok("B12 refund payments: refund_of names the target, request_id and authorization_id null", len(rs) == 2 and all(p["request_id"] is None and p["authorization_id"] is None for p in rs), rs)
        reqs = api("GET", "/requests", token=Tada)[1]
        rq = [r for r in (reqs.get("requests") if isinstance(reqs, dict) else reqs) if r.get("request_id") == "rq_pay"]
        ok("B12 the request stays paid (refund never reopens it)", rq and rq[0]["status"] == "paid", rq)
        auth = api("GET", "/authorizations", token=Tada)[1]
        al = [a for a in (auth.get("authorizations") if isinstance(auth, dict) else auth) if a.get("authorization_id") == "a_cap"]
        me_a = api("GET", "/me", token=Tada)[1]
        ok("B12 the authorization stays captured and the released hold is not restored (held 0)", al and al[0]["status"] == "captured" and me_a["held"] == 0, (al, me_a))
        ctx.close()
        ctx = br.new_context(viewport={"width": 375, "height": 900}); seeded_page(ctx, Tada); page = ctx.new_page()
        page.goto(BASE + "/"); wait_present(page, "wallet-available"); settle(page, 500)
        ok("B12 the payer (ada) of those payments is offered no refund control, including on the received refund payments", page.locator('[data-testid^="refund-"]').count() == 0, page.locator('[data-testid^="refund-"]').count())
        ctx.close()
    # ---------- currencies with 0 and 3 decimals
    for cur, mu, amount, default, typed, want, label in (("JPY", 0, 5000, "5000", "1200", 1200, "0-decimal"), ("KWD", 3, 12345, "12.345", "2.500", 2500, "3-decimal")):
        f = fixture(users=[user("ada", 100000), user("bob", 100000)], payments=[{"id": "p_c", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": amount, "note": "n", "visibility": "public"}])
        f["currency"] = cur; f["minor_units"] = mu
        s, _ = api("POST", "/_test/reset", f)
        ok("setup %s fixture accepted" % label, s == 204, s)
        T = tok("ada@example.com"); ctx = br.new_context(viewport={"width": 375, "height": 900}); seeded_page(ctx, T); page = ctx.new_page()
        page.goto(BASE + "/"); wait_present(page, "activity-item-p_c"); settle(page, 300)
        tid(page, "refund-toggle-p_c").click()
        ok("B12 %s default refund amount is the whole payment %r" % (label, default), tid(page, "refund-amount-p_c").input_value() == default, tid(page, "refund-amount-p_c").input_value())
        tid(page, "refund-amount-p_c").fill(typed); tid(page, "refund-submit-p_c").click()
        ok("B12 %s refund of %s sent as %d minor units" % (label, typed, want), wait_present(page, "refund-success-p_c") and [p["amount"] for p in acts(T) if p.get("refund_of") == "p_c"] == [want], [p["amount"] for p in acts(T) if p.get("refund_of") == "p_c"])
        settle(page, 500)
        left = tid(page, "refund-limit-p_c").inner_text() if present(page, "refund-limit-p_c") else None
        info("B12 %s limit hint after the refund: %s" % (label, left))
        tid(page, "refund-amount-p_c").fill("1" + "0" * 12 if mu == 0 else "9999999999.999"); tid(page, "refund-submit-p_c").click(); settle(page, 600)
        ok("B12 %s out-of-range/over-limit amount refused with a message, nothing moved" % label, present(page, "refund-error-p_c") and [p["amount"] for p in acts(T) if p.get("refund_of") == "p_c"] == [want], text(page, "refund-error-p_c") if present(page, "refund-error-p_c") else None)
        ctx.close()
    br.close()
done("b10_targets")
