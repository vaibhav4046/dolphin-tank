"""Real-browser smoke for pocketful stage 2 (loom). Run inside df-harness-runner (python3 + playwright + chromium)."""
import copy, json, os, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
SHOTS = "/work/shots"
os.makedirs(SHOTS, exist_ok=True)
RESULTS = []


def iso(delta):
    return (datetime.now(timezone.utc) + delta).replace(microsecond=0).isoformat()


def http(method, path, body=None, token=None, key=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def user(uid, handle, name, balance):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse", "display_name": name, "handle": handle, "balance": balance}


USERS = [user("u_ada", "ada", "Ada", 10000), user("u_bob", "bob", "Bob", 2500), user("u_cy", "cy", "Cy", 0)]
POPULATED = {
    "currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 600, "users": USERS,
    "payments": [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee ☕", "visibility": "public", "created_at": iso(timedelta(hours=-3))},
        {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1250, "note": "", "visibility": "public", "created_at": iso(timedelta(hours=-2))},
        {"id": "p_3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300, "note": "a very long note that keeps going and going and going so the narrow layout has to wrap it neatly", "visibility": "private", "created_at": iso(timedelta(hours=-1))},
        {"id": "p_4", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "private between others", "visibility": "private", "created_at": iso(timedelta(minutes=-30))},
    ],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending", "created_at": iso(timedelta(hours=-2))},
        {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "lunch", "status": "pending", "created_at": iso(timedelta(hours=-1))},
        {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 99, "note": "", "status": "declined", "created_at": iso(timedelta(hours=-5))},
        {"id": "rq_4", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 500, "note": "coffee", "status": "paid", "payment_id": "p_1", "created_at": iso(timedelta(hours=-4))},
    ],
    "authorizations": [
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": iso(timedelta(hours=2)), "created_at": iso(timedelta(minutes=-20))},
        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "tickets", "visibility": "private", "status": "open", "expires_at": iso(timedelta(hours=3)), "created_at": iso(timedelta(minutes=-10))},
        {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 900, "note": "done", "visibility": "public", "status": "captured", "captured_amount": 700, "expires_at": iso(timedelta(hours=2)), "created_at": iso(timedelta(hours=-3))},
        {"id": "a_4", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "", "visibility": "public", "status": "voided", "expires_at": iso(timedelta(hours=2)), "created_at": iso(timedelta(hours=-4))},
        {"id": "a_5", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 300, "note": "old", "visibility": "public", "status": "open", "expires_at": iso(timedelta(hours=-2)), "created_at": iso(timedelta(hours=-6))},
    ],
}
EMPTY = {"currency": "EUR", "minor_units": 2, "users": USERS}
SIMPLE = {"currency": "EUR", "minor_units": 2, "users": USERS, "requests": [
    {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}


def reset(fix):
    st, body = http("POST", "/_test/reset", fix)
    assert st == 204, (st, body)


def token_of(handle):
    st, body = http("POST", "/auth/login", {"email": f"{handle}@example.com", "password": "correct horse"})
    assert st == 200, (st, body)
    return body["token"]


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


class Session:
    def __init__(self, browser, width=1280, height=900, token=None):
        self.ctx = browser.new_context(viewport={"width": width, "height": height})
        if token:
            self.ctx.add_init_script(f"if(!localStorage.getItem('pocketful.token')) localStorage.setItem('pocketful.token','{token}')")
        self.page = self.ctx.new_page()
        self.errors, self.posts, self.external = [], [], []
        self.page.on("request", lambda r: self.external.append(r.url) if not r.url.startswith((BASE, "data:")) else None)
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.posts.append((r.method, r.url.replace(BASE, ""), r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST" else None)

    def t(self, testid):
        return self.page.locator(f'[data-testid="{testid}"]')

    def txt(self, testid):
        return self.t(testid).inner_text().strip()

    def goto(self, path):
        self.page.goto(BASE + path, wait_until="domcontentloaded")
        self.page.wait_for_selector("main[aria-busy='false'], .auth-wrap")

    def shot(self, name):
        self.page.screenshot(path=f"{SHOTS}/{name}.png", full_page=True)

    def no_hscroll(self, name):
        sw, cw = self.page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        check(f"no horizontal scroll {name}", sw <= cw, f"{sw}>{cw}")

    def ui_login(self, handle):
        self.goto("/login")
        self.t("login-email").fill(f"{handle}@example.com")
        self.t("login-password").fill("correct horse")
        self.t("login-submit").click()
        self.page.wait_for_url(BASE + "/")
        self.t("wallet-available").wait_for()


def amount(s):
    return int(s.t("wallet-balance").get_attribute("data-amount"))


AUDIT_JS = r"""() => {
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const parse = (s) => { const m = s.match(/[\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; };
  const mix = (fg, bg, a) => [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const bgOf = (el) => { let stack = []; for (let e = el; e; e = e.parentElement) stack.push(e); let bg = [3, 0, 20]; for (const e of stack.reverse()) { const c = parse(getComputedStyle(e).backgroundColor); if (c[3] > 0) bg = mix(c, bg, c[3]); } return bg; };
  const opacityOf = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const out = { n: 0, min: 99, low: [], small: [], weights: [], fonts: new Set(), radii: new Set(), shadows: [] };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement; const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('.vh,.skip-link')) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    const bg = bgOf(el); const fgc = parse(cs.color); const fg = mix(fgc, bg, fgc[3] * opacityOf(el));
    const size = parseFloat(cs.fontSize); const large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const cr = ratio(fg, bg); out.n++; out.min = Math.min(out.min, large ? cr + 1.5 : cr); if (cr < (large ? 3 : 4.5)) out.low.push([n.textContent.trim().slice(0, 30), cr.toFixed(2)]);
    if (parseInt(cs.fontWeight) > 500) out.weights.push(el.tagName);
    out.fonts.add(cs.fontFamily.split(',')[0].replace(/"/g, ''));
  }
  for (const el of document.querySelectorAll('button, input:not([type=checkbox]), select, a, [role=button]')) {
    if (el.closest('.vh') || el.classList.contains('skip-link')) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0) continue;
    if (r.height < 43.5) out.small.push([el.tagName, (el.getAttribute('data-testid') || el.textContent.trim()).slice(0, 24), r.height]);
  }
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.boxShadow !== 'none' && !/inset/.test(cs.boxShadow)) out.shadows.push(el.tagName + '.' + el.className);
    if (cs.borderTopLeftRadius !== '0px') out.radii.add(cs.borderTopLeftRadius);
  }
  return { n: out.n, min: out.min, low: out.low, small: out.small, weights: out.weights, fonts: [...out.fonts], radii: [...out.radii], shadows: out.shadows };
}"""


def audit(s, name):
    r = s.page.evaluate(AUDIT_JS)
    check(f"contrast >= 4.5 {name}", not r["low"] and r["n"] > 5, f"{r['low'][:4]} n={r['n']}")
    print(f"INFO {name}: {r['n']} text nodes audited, lowest contrast {r['min']:.2f}", flush=True)
    check(f"touch targets >= 44px {name}", not r["small"], str(r["small"][:4]))
    check(f"no font weight above 500 {name}", not r["weights"], str(r["weights"][:4]))
    check(f"only DM Sans / Inter {name}", set(r["fonts"]) <= {"DM Sans", "Inter"}, str(r["fonts"]))
    check(f"radii only 5/16/32 (+50% glyphs) {name}", set(r["radii"]) <= {"5px", "16px", "32px", "50%"}, str(r["radii"]))
    check(f"no drop shadows {name}", not r["shadows"], str(r["shadows"][:4]))


def screens(browser, tag, handle):
    for label, (w, h) in {"375": (375, 800), "1280": (1280, 900)}.items():
        s = Session(browser, w, h)
        s.goto("/login")
        s.shot(f"{tag}-login-{label}")
        s.no_hscroll(f"{tag} /login {label}")
        audit(s, f"{tag} /login {label}")
        s.goto("/signup")
        s.shot(f"{tag}-signup-{label}")
        s.no_hscroll(f"{tag} /signup {label}")
        s.ui_login(handle)
        for path, name in [("/", "home"), ("/requests", "requests"), ("/split", "split"), ("/authorizations", "authorizations")]:
            s.goto(path)
            if path == "/split":
                s.t("split-amount").fill("10.00")
                s.t("split-handles").fill("ada, bob, cy")
            s.shot(f"{tag}-{name}-{label}")
            s.no_hscroll(f"{tag} {path} {label}")
            audit(s, f"{tag} {path} {label}")
            check(f"{tag} {path} {label}: current-user/handle present", s.txt("current-user") != "" and s.txt("current-handle") == handle)
        check(f"{tag} {label}: no console errors", not s.errors, str(s.errors))
        check(f"{tag} {label}: no request left the origin", not s.external, str(s.external))
        s.ctx.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---- populated + empty screens, and the hold headline right after reset
        reset(POPULATED)
        s = Session(browser)
        s.ui_login("ada")
        check("reset with seeded hold: available is the headline", s.txt("wallet-available") == "80.00 EUR" and s.t("wallet-available").get_attribute("data-amount") == "8000", s.txt("wallet-available"))
        check("total and held secondary", s.txt("wallet-balance") == "100.00 EUR" and s.txt("wallet-held") == "20.00 EUR")
        sizes = s.page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t => parseFloat(getComputedStyle(document.querySelector(`[data-testid="${t}"]`)).fontSize))""")
        check("available font larger than total and held", sizes[0] > sizes[1] and sizes[0] > sizes[2], str(sizes))
        ids = [e.get_attribute("data-testid") for e in s.page.locator('[data-testid^="activity-item-"]').all()]
        check("activity-item order", ids == ["activity-item-p_3", "activity-item-p_2", "activity-item-p_1"], str(ids))
        check("activity amount/note exact", s.txt("activity-amount-p_1") == "5.00 EUR" and s.t("activity-note-p_2").text_content() == "" and s.t("activity-note-p_1").text_content() == "coffee ☕")
        check("data-visibility", s.t("activity-item-p_3").get_attribute("data-visibility") == "private")
        # focus walk through the pay form
        s.t("pay-handle").focus()
        seen = []
        for _ in range(5):
            seen.append(s.page.evaluate("(()=>{const e=document.activeElement;const c=getComputedStyle(e);return [e.getAttribute('data-testid'),c.outlineStyle,c.outlineWidth]})()"))
            s.page.keyboard.press("Tab")
        check("visible focus outline on pay form controls", all(x[1] != "none" and x[2] == "2px" for x in seen), str(seen))
        s.ctx.close()
        screens(browser, "populated", "ada")
        reset(EMPTY)
        screens(browser, "empty", "cy")

        # ---- signup via UI, empty wallet
        s = Session(browser, 375, 800)
        s.goto("/signup")
        check("auth-error absent initially", s.t("auth-error").count() == 0)
        s.t("signup-email").fill("dana@example.com")
        s.t("signup-password").fill("short")
        s.t("signup-display-name").fill("Dana")
        s.t("signup-submit").click()
        s.t("auth-error").wait_for()
        s.shot("state-signup-refused-375")
        s.t("signup-password").fill("longenough1")
        check("auth-error removed on edit", s.t("auth-error").count() == 0)
        s.t("signup-submit").click()
        s.page.wait_for_url(BASE + "/")
        s.t("wallet-available").wait_for()
        check("signup lands on / with empty wallet and no held", s.txt("wallet-available") == "0.00 EUR" and s.t("wallet-held").count() == 0 and s.txt("current-handle") == "dana")
        s.ctx.close()

        # ---- pay flow: pay, double submit once, same key, invalid amount, changed field
        reset(POPULATED)
        s = Session(browser)
        s.ui_login("ada")
        s.t("pay-handle").fill("bob")
        s.t("pay-amount").fill("15.005")
        n = len(s.posts)
        s.t("pay-submit").click()
        s.t("pay-error").wait_for()
        check("15.005 rejected, no request sent", len(s.posts) == n and s.t("pay-error").inner_text().strip() != "")
        s.t("pay-amount").fill("15")
        s.t("pay-note").fill("dinner")
        s.t("pay-visibility").select_option("private")
        s.t("pay-submit").click()
        s.t("pay-success").wait_for()
        pays = [p for p in s.posts if p[1] == "/payments"]
        check("pay sent integer minor units", json.loads(pays[0][3])["amount"] == 1500 and '"amount":1500' in pays[0][3].replace(" ", ""), pays[0][3])
        check("pay-error absent after success, values kept", s.t("pay-error").count() == 0 and s.t("pay-amount").input_value() == "15" and s.t("pay-note").input_value() == "dinner" and s.t("pay-visibility").input_value() == "private")
        s.t("wallet-balance").wait_for()
        bal1 = amount(s)
        s.t("pay-submit").click()
        s.t("pay-success").wait_for()
        s.page.wait_for_function("document.querySelector('[data-testid=pay-submit]').getAttribute('aria-busy') !== 'true'")
        pays = [p for p in s.posts if p[1] == "/payments"]
        check("double submit sends the SAME key and body", len(pays) == 2 and pays[0][2] == pays[1][2] and pays[0][3] == pays[1][3], str(pays))
        st, act = http("GET", "/activity?limit=200", token=token_of("ada"))
        mine = [p for p in act["payments"] if p["note"] == "dinner"]
        check("one payment moved money once", len(mine) == 1 and amount(s) == bal1 == 8500, f"{len(mine)} {amount(s)} {bal1}")
        check("balance fell once", bal1 == 10000 - 1500, str(bal1))
        s.t("pay-note").fill("dinner 2")
        s.t("pay-submit").click()
        s.page.wait_for_function("document.querySelectorAll('[data-testid^=activity-item-]').length === 5")
        pays = [p for p in s.posts if p[1] == "/payments"]
        check("changed field mints a new key", pays[-1][2] != pays[0][2])
        check("feed shows the new payment first", s.t("activity-list").locator(":scope > li").first.get_attribute("data-testid").startswith("activity-item-"))
        s.shot("state-pay-success-1280")
        s.ctx.close()

        # ---- uncertain: response lost after commit, retry same key, one payment
        reset(POPULATED)
        s = Session(browser, 375, 800)
        s.ui_login("ada")
        state = {"lost": 0}

        def lose_once(route):
            if route.request.method == "POST" and state["lost"] == 0:
                state["lost"] += 1
                route.fetch()
                route.abort()
            else:
                route.continue_()
        s.page.route("**/payments", lose_once)
        s.t("pay-handle").fill("bob")
        s.t("pay-amount").fill("7.50")
        s.t("pay-submit").click()
        s.t("pay-uncertain").wait_for()
        check("lost response -> pay-uncertain nonempty, no pay-error", s.txt("pay-uncertain") != "" and s.t("pay-error").count() == 0, s.txt("pay-uncertain"))
        s.shot("state-pay-uncertain-375")
        s.t("pay-submit").click()
        s.t("pay-success").wait_for()
        pays = [p for p in s.posts if p[1] == "/payments"]
        check("retry used the same key and body", len(pays) == 2 and pays[0][2] == pays[1][2] and pays[0][3] == pays[1][3])
        check("uncertain and error gone after retry", s.t("pay-uncertain").count() == 0 and s.t("pay-error").count() == 0)
        st, act = http("GET", "/activity?limit=200", token=token_of("ada"))
        check("exactly one 7.50 payment", len([p for p in act["payments"] if p["amount"] == 750]) == 1)
        check("wallet-balance fell once", amount(s) == 10000 - 750, str(amount(s)))

        # ---- refused: spend elsewhere
        s.page.unroute("**/payments")
        s.t("pay-handle").fill("cy")
        s.t("pay-amount").fill("70.00")
        s.t("pay-note").fill("too much")
        http("POST", "/payments", {"to_handle": "bob", "amount": 7000, "note": "elsewhere"}, token_of("ada"), "elsewhere-1")
        s.t("pay-submit").click()
        s.t("pay-error").wait_for()
        s.page.wait_for_function("document.querySelector('[data-testid=wallet-balance]').dataset.amount === '2250'")
        check("refused: pay-error, balance refreshed, inputs kept", s.t("pay-amount").input_value() == "70.00" and s.t("pay-note").input_value() == "too much" and s.t("pay-handle").input_value() == "cy" and s.t("pay-uncertain").count() == 0)
        s.shot("state-pay-refused-375")
        s.ctx.close()

        # ---- request cancelled elsewhere, stale button gone
        reset(SIMPLE)
        s = Session(browser)
        s.ui_login("ada")
        s.goto("/requests")
        s.t("request-pay-rq_1").wait_for()
        check("pending incoming shows pay+decline, no cancel", s.t("request-decline-rq_1").count() == 1 and s.t("request-cancel-rq_1").count() == 0)
        http("POST", "/requests/rq_1/cancel", {}, token_of("bob"))
        s.t("request-pay-rq_1").click()
        s.t("request-error").wait_for()
        s.page.wait_for_function("document.querySelector('[data-testid=request-pay-rq_1]') === null")
        check("request-error shown and stale pay button gone", s.t("request-item-rq_1").get_attribute("data-status") == "cancelled", s.t("request-item-rq_1").get_attribute("data-status"))
        s.shot("state-request-stale-1280")
        s.ctx.close()

        # ---- pay a pending request through the UI, then outgoing cancel
        reset(SIMPLE)
        s = Session(browser)
        s.ui_login("ada")
        s.goto("/requests")
        s.t("request-pay-rq_1").click()
        s.page.wait_for_function("document.querySelector('[data-testid=request-item-rq_1]').dataset.status === 'paid'")
        check("request paid via UI, wallet refreshed", amount(s) == 10000 - 1200 and s.t("request-pay-rq_1").count() == 0)
        check("no request-error after a successful pay", s.t("request-error").count() == 0)
        s.ctx.close()

        # ---- latest refresh wins, out-of-order responses
        reset(EMPTY)
        s = Session(browser)
        s.ui_login("ada")
        held = []

        def delay_first_me(route):
            if route.request.method == "GET" and route.request.url.endswith("/me") and not held:
                held.append((route, route.fetch()))
            else:
                route.continue_()
        s.page.route("**/me", delay_first_me)
        s.t("wallet-refresh").click()
        s.page.wait_for_function("true")
        while not held:
            s.page.wait_for_timeout(50)
        http("POST", "/payments", {"to_handle": "bob", "amount": 1000, "note": "x"}, token_of("ada"), "lw-1")
        s.t("wallet-refresh").click()
        s.page.wait_for_function("document.querySelector('[data-testid=wallet-balance]').dataset.amount === '9000'")
        route, resp = held[0]
        route.fulfill(response=resp)
        s.page.wait_for_timeout(300)
        check("latest refresh wins: delayed older read does not overwrite", s.t("wallet-balance").get_attribute("data-amount") == "9000", s.t("wallet-balance").get_attribute("data-amount"))
        s.ctx.close()

        # ---- split preview equals submitted shares
        reset(EMPTY)
        s = Session(browser)
        s.ui_login("ada")
        s.goto("/split")
        check("split-preview present when empty", s.t("split-preview").count() == 1)
        s.t("split-amount").fill("10.00")
        s.t("split-handles").fill("ada, bob, cy")
        shares = [s.txt(f"split-share-{h}") for h in ("ada", "bob", "cy")]
        check("split preview 3.34/3.33/3.33", shares == ["3.34 EUR", "3.33 EUR", "3.33 EUR"], str(shares))
        s.t("split-handles").fill("cy, ada, bob")
        check("reorder moves the extra unit", s.txt("split-share-cy") == "3.34 EUR" and s.txt("split-share-ada") == "3.33 EUR")
        s.t("split-handles").fill("ada, bob, cy")
        with s.page.expect_response(lambda r: r.url.endswith("/splits")) as info:
            s.t("split-submit").click()
        body = info.value.json()
        check("submitted shares equal the preview", [x["amount"] for x in body["shares"]] == [334, 333, 333])
        s.t("split-success").wait_for()
        s.shot("state-split-done-375")
        s.ctx.close()

        # ---- authorize -> available falls, held appears; capture on receiver; void on payer
        reset(EMPTY)
        sa = Session(browser)
        sb = Session(browser, 375, 800)
        sa.ui_login("ada")
        sb.ui_login("bob")
        sa.goto("/authorizations")
        check("empty-authorizations shown", sa.t("empty-authorizations").count() == 1)
        sa.shot("state-authorizations-empty-1280")
        sa.t("authorize-handle").fill("bob")
        sa.t("authorize-amount").fill("20.00")
        sa.t("authorize-note").fill("deposit")
        sa.t("authorize-submit").click()
        sa.t("authorize-success").wait_for()
        sa.page.wait_for_function("document.querySelector('[data-testid=wallet-held]') !== null")
        check("available falls, held appears", sa.txt("wallet-available") == "80.00 EUR" and sa.txt("wallet-held") == "20.00 EUR" and sa.txt("wallet-balance") == "100.00 EUR")
        item = sa.page.locator('[data-testid^="authorization-item-"]').first
        aid = item.get_attribute("data-testid").replace("authorization-item-", "")
        check("payer sees void, no capture", sa.t(f"authorization-void-{aid}").count() == 1 and sa.t(f"authorization-capture-{aid}").count() == 0)
        check("expires text is RFC 3339", sa.txt(f"authorization-expires-{aid}").count("T") == 1 and sa.txt(f"authorization-expires-{aid}").endswith("+00:00"), sa.txt(f"authorization-expires-{aid}"))
        sb.goto("/authorizations")
        check("receiver sees prefilled capture amount, no void", sb.t(f"authorization-capture-amount-{aid}").input_value() == "20.00" and sb.t(f"authorization-void-{aid}").count() == 0)
        sb.t(f"authorization-capture-amount-{aid}").fill("7.00")
        sb.page.locator(f'label:has-text("Keep the rest on hold")').first.click()
        sb.t(f"authorization-capture-{aid}").click()
        sb.t("authorization-success").wait_for()
        sb.page.wait_for_function(f"document.querySelector('[data-testid=authorization-item-{aid}]').dataset.status === 'open' && document.querySelector('[data-testid=authorization-capture-amount-{aid}]').value === '13.00'")
        check("partial capture keeps remainder open, input re-prefilled", sb.txt("wallet-balance") == "32.00 EUR" and sb.t(f"authorization-captured-{aid}").count() == 0)
        sb.shot("state-authorization-partial-375")
        sb.t(f"authorization-capture-{aid}").click()
        sb.page.wait_for_function(f"document.querySelector('[data-testid=authorization-item-{aid}]').dataset.status === 'captured'")
        check("capture rest closes it; captured shown", sb.txt(f"authorization-captured-{aid}") == "20.00 EUR" and sb.t(f"authorization-capture-{aid}").count() == 0 and sb.txt("wallet-balance") == "45.00 EUR")
        # void on the payer's page
        sa.t("authorize-note").fill("second")
        sa.t("authorize-amount").fill("5.00")
        sa.t("authorize-submit").click()
        sa.t("authorize-success").wait_for()
        first = sa.page.locator('[data-testid^="authorization-item-"]').first.get_attribute("data-testid").replace("authorization-item-", "")
        sa.page.wait_for_selector(f'[data-testid="authorization-void-{first}"]')
        sa.t(f"authorization-void-{first}").click()
        sa.page.wait_for_function(f"document.querySelector('[data-testid=authorization-item-{first}]').dataset.status === 'voided'")
        check("void releases the hold", sa.t("wallet-held").count() == 0 and sa.t(f"authorization-void-{first}").count() == 0 and sa.txt("wallet-available") == "80.00 EUR", sa.txt("wallet-available"))
        sa.shot("state-authorizations-populated-1280")
        # refused capture: expired seeded hold, and exceed
        reset(POPULATED)
        s2 = Session(browser)
        s2.ui_login("ada")
        s2.goto("/authorizations")
        check("expired seeded hold shows expired, no controls", s2.t("authorization-item-a_5").get_attribute("data-status") == "expired" and s2.t("authorization-capture-a_5").count() == 0)
        check("partial/closed matrix", s2.t("authorization-captured-a_3").count() == 1 and s2.t("authorization-captured-a_1").count() == 0 and s2.t("authorization-void-a_1").count() == 1 and s2.t("authorization-capture-a_2").count() == 1)
        s2.t("authorization-capture-amount-a_2").fill("9.99")
        s2.t("authorization-capture-a_2").click()
        s2.t("authorization-error").wait_for()
        check("capture over remaining refused with message; typed amount kept", s2.t("authorization-capture-amount-a_2").input_value() == "9.99" and "still on hold" in s2.txt("authorization-error"), s2.txt("authorization-error"))
        s2.shot("state-authorization-refused-1280")
        s2.ctx.close()

        # ---- stage-1 shaped export -> import while signed in; lost payment retried with the same key
        reset(SIMPLE)
        s = Session(browser)
        s.ui_login("ada")
        state = {"lost": 0}
        s.page.route("**/payments", lose_once)
        s.t("pay-handle").fill("bob")
        s.t("pay-amount").fill("5.00")
        s.t("pay-submit").click()
        s.t("pay-uncertain").wait_for()
        st, exp = http("GET", "/_test/export")
        for k in ("authorizations", "authorization_ttl_seconds"):
            exp["state"].pop(k, None)
        for p in exp["state"]["payments"]:
            p.pop("authorization_id", None)
        st, _ = http("POST", "/_test/import", exp)
        check("stage-1 shaped export imports", st == 204, str(st))
        s.t("pay-submit").click()
        s.t("pay-success").wait_for()
        check("signed-in after import, retry recovered, one payment", s.t("pay-uncertain").count() == 0 and amount(s) == 9500 and len(s.page.locator('[data-testid^="activity-item-"]').all()) == 1, str(amount(s)))
        s.goto("/requests")
        s.t("request-pay-rq_1").click()
        s.page.wait_for_function("document.querySelector('[data-testid=request-item-rq_1]').dataset.status === 'paid'")
        check("pending request payable after import", amount(s) == 9500 - 1200)
        s.ctx.close()
        browser.close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


main()
