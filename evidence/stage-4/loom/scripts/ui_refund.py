"""Stage-4 refund control in a real browser (loom). BASE=http://127.0.0.1:8084 PORT=8084 stage-4 binary running."""
import sys, time
from datetime import timedelta
from playwright.sync_api import sync_playwright
from common import *

USERS = [user("u_ada", "ada", "Ada", 10000), user("u_bob", "bob", "Bob", 2500), user("u_cy", "cy", "Cy", 100)]
FIX = {"currency": "EUR", "minor_units": 2, "users": USERS, "payments": [
    {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000, "note": "coffee", "visibility": "public", "created_at": iso(timedelta(hours=-3))},
    {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "lunch", "visibility": "private", "created_at": iso(timedelta(hours=-2))},
    {"id": "p_3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 5000, "note": "rent", "visibility": "public", "created_at": iso(timedelta(hours=-1))}]}


def reset():
    st, _ = http("POST", "/_test/reset", FIX)
    assert st == 204, st


def me(handle):
    return http("GET", "/me", token=token_of(handle))[1]


def refund_ids(handle):
    feed = http("GET", "/activity?limit=100", token=token_of(handle))[1]["payments"]
    return [p for p in feed if p.get("refund_of")]


def flow(b, w):
    reset()
    tag = f"{w}"
    s = Session(b, w, token=token_of("bob"))
    p = s.page
    s.goto("/")
    check(f"[{w}] receiver sees Refund on p_1 and p_2 but not on p_3", s.t("refund-toggle-p_1").count() == 1 and s.t("refund-toggle-p_2").count() == 1 and s.t("refund-toggle-p_3").count() == 0)
    check(f"[{w}] panel starts closed", not s.t("refund-panel-p_1").count() and not p.locator("#refund-panel-p_1").is_visible())
    s.hscroll_ok(f"{w} idle feed")
    s.t("refund-toggle-p_1").click()
    check(f"[{w}] opening shows a labelled amount defaulting to the remainder", p.locator("#refund-panel-p_1").is_visible() and s.t("refund-amount-p_1").input_value() == "10.00"
          and p.locator('label[for="refund-amount-p_1"]').inner_text().strip() == "Refund amount" and "10.00" in s.t("refund-limit-p_1").inner_text(), s.t("refund-limit-p_1").inner_text())
    s.hscroll_ok(f"{w} panel open")
    s.shot(f"refund-idle-{w}")

    # validation: nothing is sent
    for bad in ["", "0", "abc", "1.234", "-1"]:
        s.t("refund-amount-p_1").fill(bad)
        s.t("refund-submit-p_1").click()
        s.t("refund-error-p_1").wait_for()
    check(f"[{w}] invalid amounts are refused in the page without any request", not s.refund_posts("p_1"))
    check(f"[{w}] typed text is preserved after a validation refusal", s.t("refund-amount-p_1").input_value() == "-1")

    # loading + double click: one request
    before = s.amount("wallet-available")
    def slow(route):
        p.wait_for_timeout(600)
        route.continue_()
    p.route("**/payments/p_1/refunds", slow)
    s.t("refund-amount-p_1").fill("4.00")
    s.t("refund-submit-p_1").dblclick()
    p.wait_for_selector('[data-testid="refund-submit-p_1"][aria-busy="true"]')
    s.shot(f"refund-sending-{w}")
    s.t("refund-success-p_1").wait_for()
    p.unroute("**/payments/p_1/refunds")
    check(f"[{w}] double click sends exactly one request", len(s.refund_posts("p_1")) == 1, str(s.refund_posts("p_1")))
    p.wait_for_function("document.querySelector('[data-testid=wallet-available]').dataset.amount !== '%d'" % before)
    check(f"[{w}] available funds fall by the refund", s.amount("wallet-available") == before - 400, f"{before} -> {s.amount('wallet-available')}")
    rid = refund_ids("bob")[0]["payment_id"]
    check(f"[{w}] refund row shows 'Refund of p_1' and the success notice stays", "Refund of p_1" in s.t(f"activity-refund-of-{rid}").inner_text() and "Refunded" in s.t("refund-success-p_1").inner_text())
    check(f"[{w}] refund payment itself offers no refund", s.t(f"refund-toggle-{rid}").count() == 0)
    check(f"[{w}] remainder updates to 6.00 from what the page knows", "6.00" in s.t("refund-limit-p_1").inner_text() and s.t("refund-amount-p_1").input_value() == "6.00", s.t("refund-limit-p_1").inner_text())
    s.hscroll_ok(f"{w} after success")
    s.shot(f"refund-success-{w}")
    check(f"[{w}] sum of balances preserved", sum(me(h)["balance"] for h in ("ada", "bob", "cy")) == 10000 + 2500 + 100)

    # refused: more than is left
    s.t("refund-amount-p_1").fill("7.00")
    s.t("refund-submit-p_1").click()
    s.t("refund-error-p_1").wait_for()
    check(f"[{w}] over-remainder is refused with a reason and the input kept", "more than is left" in s.t("refund-error-p_1").inner_text() and s.t("refund-amount-p_1").input_value() == "7.00"
          and s.t("refund-error-p_1").get_attribute("role") == "alert", s.t("refund-error-p_1").inner_text())
    s.hscroll_ok(f"{w} refused")
    s.shot(f"refund-refused-{w}")

    # stale: ada corrects p_1 down to 5.00 elsewhere; bob's page still offers 6.00
    ada = token_of("ada")
    st, corr = http("POST", "/payments/p_1/corrections", {"expected_revision": 1, "amount": 500, "effective_at": FIX["payments"][0]["created_at"], "reason": "stale test"}, ada, f"corr-{tag}")
    check(f"[{w}] setup: correction of p_1 to 5.00", st == 201, str(corr))
    s.t("refund-amount-p_1").fill("6.00")
    s.t("refund-submit-p_1").click()
    p.wait_for_function("document.querySelector('[data-testid=refund-limit-p_1]') && document.querySelector('[data-testid=refund-limit-p_1]').textContent.includes('1.00')")
    check(f"[{w}] stale limit refused, then corrected amount learned (limit 1.00), typed 6.00 kept", s.t("refund-amount-p_1").input_value() == "6.00" and "1.00" in s.t("refund-limit-p_1").inner_text())
    s.t("refund-amount-p_1").fill("1.00")
    s.t("refund-submit-p_1").click()
    s.t("refund-done-p_1").wait_for()
    check(f"[{w}] exact remainder accepted; row then says nothing is left", "Nothing left" in s.t("refund-done-p_1").inner_text() and s.t("refund-toggle-p_1").count() == 0)

    # uncertain: the server applies p_2's refund but the response is lost
    s.t("refund-toggle-p_2").click()
    s.t("refund-amount-p_2").fill("2.00")
    seen = []
    def lose(route):
        seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        route.fetch()
        route.abort("connectionreset")
    p.route("**/payments/p_2/refunds", lose)
    s.t("refund-submit-p_2").click()
    s.t("refund-uncertain-p_2").wait_for()
    txt = s.t("refund-uncertain-p_2").inner_text()
    check(f"[{w}] lost response reads as unknown, not refused", "Unconfirmed" in txt and "could not confirm" in txt and s.t("refund-error-p_2").count() == 0 and s.t("refund-uncertain-p_2").get_attribute("data-kind") == "uncertain", txt)
    check(f"[{w}] input kept after the unknown outcome", s.t("refund-amount-p_2").input_value() == "2.00")
    s.hscroll_ok(f"{w} uncertain")
    s.shot(f"refund-uncertain-{w}")
    p.unroute("**/payments/p_2/refunds")
    s.t("refund-submit-p_2").click()
    s.t("refund-success-p_2").wait_for()
    sent = s.refund_posts("p_2")
    check(f"[{w}] retry re-sends the same key and body", len(sent) == 2 and sent[0][1] == sent[1][1] and sent[0][2] == sent[1][2] and sent[0][1] == seen[0][0], str(sent))
    rf = [r for r in refund_ids("bob") if r["refund_of"] == "p_2"]
    check(f"[{w}] the lost-response refund exists once (200 replay, not a second refund)", len(rf) == 1 and rf[0]["amount"] == 200, str(rf))

    # server answers the page cannot predict: shown with reasons (mocked envelopes except where noted)
    for code, status, want in [("forbidden", 403, "Only the person who received"), ("not_found", 404, "could not be found"), ("invalid_refund_target", 422, "cannot itself be refunded")]:
        def refuse(route, c=code, st=status):
            route.fulfill(status=st, content_type="application/json", body='{"error":{"code":"%s","message":"x"}}' % c)
        p.route("**/payments/p_2/refunds", lambda route: refuse(route))
        s.t("refund-amount-p_2").fill("1.00")
        s.t("refund-submit-p_2").click()
        s.t("refund-error-p_2").wait_for()
        check(f"[{w}] {status} {code} shows its reason (mocked envelope)", want in s.t("refund-error-p_2").inner_text(), s.t("refund-error-p_2").inner_text())
        p.unroute("**/payments/p_2/refunds")
    unexpected = [e for e in s.errors if not e.startswith("Failed to load resource")]
    check(f"[{w}] no external requests and no script errors (browser logs for the deliberate 4xx/aborted responses ignored)", not s.external and not unexpected, str(s.external + unexpected))
    s.ctx.close()

    # insufficient funds (real): cy holds p_3's 50.00 but only has 1.00 available
    c = Session(b, w, token=token_of("cy"))
    c.goto("/")
    c.t("refund-toggle-p_3").click()
    c.t("refund-submit-p_3").click()
    c.t("refund-error-p_3").wait_for()
    check(f"[{w}] insufficient available funds is a refusal with the reason, nothing moved", "Not enough available funds" in c.t("refund-error-p_3").inner_text() and me("cy")["balance"] == 100, c.t("refund-error-p_3").inner_text())
    c.hscroll_ok(f"{w} insufficient")
    c.ctx.close()


def quality(b):
    reset()
    for w in (375, 768, 1280):
        s = Session(b, w, token=token_of("bob"))
        s.goto("/")
        s.t("refund-toggle-p_1").click()
        s.t("refund-amount-p_1").fill("99.00")
        s.t("refund-submit-p_1").click()
        s.t("refund-error-p_1").wait_for()
        check(f"[{w}] no font weight above 500", s.page.evaluate(WEIGHT_JS) == [], str(s.page.evaluate(WEIGHT_JS)))
        c = s.page.evaluate(CONTRAST_JS)
        check(f"[{w}] contrast >= 4.5 on every text (worst {c['ratio']}: {c.get('text')})", c["ratio"] >= 4.5, str(c))
        check(f"[{w}] every visible input has a label", s.page.evaluate(UNLABELLED_JS) == [], str(s.page.evaluate(UNLABELLED_JS)))
        check(f"[{w}] touch targets >= 44px high", s.page.evaluate(SMALL_TARGET_JS) == [], str(s.page.evaluate(SMALL_TARGET_JS)))
        check(f"[{w}] DM Sans and Inter loaded from the page's own origin", s.page.evaluate("document.fonts.check('500 16px \"DM Sans\"') && document.fonts.check('400 16px Inter')"))
        s.page.keyboard.press("Tab")
        ring = None
        for _ in range(80):
            s.page.keyboard.press("Tab")
            ring = s.page.evaluate("(() => { const e = document.activeElement; const c = getComputedStyle(e); return [e.dataset.testid || e.tagName, c.outlineStyle, parseFloat(c.outlineWidth)]; })()")
            if ring[0] == "refund-toggle-p_2":
                break
        check(f"[{w}] keyboard reaches the Refund toggle and shows a focus ring", ring and ring[0] == "refund-toggle-p_2" and ring[1] != "none" and ring[2] >= 2, str(ring))
        s.page.keyboard.press("Enter")
        check(f"[{w}] Enter on the toggle opens the panel (aria-expanded true)", s.t("refund-toggle-p_2").get_attribute("aria-expanded") == "true")
        s.shot(f"refund-quality-{w}")
        s.ctx.close()
    for w, label in ((320, "320 px"), (640, "200% zoom of 1280")):
        s = Session(b, w, token=token_of("bob"))
        s.goto("/")
        s.t("refund-toggle-p_1").click()
        s.t("refund-amount-p_1").fill("99.00")
        s.t("refund-submit-p_1").click()
        s.t("refund-error-p_1").wait_for()
        s.hscroll_ok(f"{label} with panel and refusal")
        s.shot(f"refund-{w}")
        s.ctx.close()
    s = Session(b, 375, token=token_of("bob"), reduced_motion="reduce")
    s.goto("/")
    s.t("refund-toggle-p_1").click()
    ok = s.page.evaluate("[...document.querySelectorAll('button, .notice, .refund-panel')].every(e => { const c = getComputedStyle(e); return (c.transitionDuration === '0s' || c.transitionDuration === '') && c.animationName === 'none'; })")
    check("reduced motion: no transitions or animations on refund controls", ok)
    s.ctx.close()


def session_paths(b):
    reset()
    s = Session(b, 1280, token=token_of("ada"))
    s.goto("/")
    check("sender (ada) is offered no Refund on p_1/p_2/p_3", s.page.locator('[data-testid^="refund-toggle-"]').count() == 0)
    s.ctx.close()
    s = Session(b, 1280)
    s.goto("/login")
    s.t("login-email").fill("bob@example.com"); s.t("login-password").fill("correct horse"); s.t("login-submit").click()
    s.t("wallet-available").wait_for()
    s.t("refund-toggle-p_1").click()
    s.t("refund-amount-p_1").fill("3.00")
    s.t("refund-submit-p_1").click()
    s.t("refund-success-p_1").wait_for()
    s.t("logout-button").click()
    s.page.wait_for_url(BASE + "/login")
    s.t("login-email").fill("bob@example.com"); s.t("login-password").fill("correct horse"); s.t("login-submit").click()
    s.t("wallet-available").wait_for()
    s.t("refund-toggle-p_1").click()
    check("refund after logout/login: the earlier 3.00 refund is counted, remainder 7.00", "7.00" in s.t("refund-limit-p_1").inner_text() and s.t("refund-amount-p_1").input_value() == "7.00")
    s.t("refund-amount-p_1").fill("7.00")
    s.t("refund-submit-p_1").click()
    s.t("refund-done-p_1").wait_for()
    check("refund after logout/login succeeds with a fresh key", len({k for (_, k, _) in s.refund_posts("p_1")}) == 2)
    check("no console errors", not s.errors, str(s.errors))
    s.ctx.close()


if __name__ == "__main__":
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for w in (375, 768, 1280):
            flow(b, w)
        quality(b)
        session_paths(b)
        b.close()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'ALL PASSED'}")
    sys.exit(1 if FAILS else 0)
