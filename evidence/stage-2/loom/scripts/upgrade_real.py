"""Real stage-1 export -> stage-2 import while a browser holds a stage-1 token (S29-S31)."""
import json, os, sys, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

S2, S1 = "http://127.0.0.1:8080", "http://127.0.0.1:8081"
SHOTS = "/work/shots"


def http(base, method, path, body=None, token=None, key=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)
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


def user(uid, handle, name, bal):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse", "display_name": name, "handle": handle, "balance": bal}


FIX = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", "Ada", 10000), user("u_bob", "bob", "Bob", 2500)],
       "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}],
       "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" [{detail}]"), flush=True)
    if not ok:
        fails.append(name)


st, _ = http(S1, "POST", "/_test/reset", FIX)
check("stage-1 server reset", st == 204, st)
st, login = http(S1, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
tok = login["token"]
st, pay = http(S1, "POST", "/payments", {"to_handle": "bob", "amount": 700, "note": "from stage 1", "visibility": "public"}, tok, "s1-key-1")
check("stage-1 payment created", st == 201, st)
st, exp = http(S1, "GET", "/_test/export")
check("stage-1 export", st == 200 and exp["format_version"] == 1, st)

http(S2, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [user("u_x", "zed", "Zed", 5)]})
st, _ = http(S2, "POST", "/_test/import", exp)
check("stage-2 imports the real stage-1 export", st == 204, st)
st, me = http(S2, "GET", "/me", token=tok)
check("stage-1 token still valid on stage-2", st == 200 and me["balance"] == 10000 - 700 and me["available"] == me["balance"] and me["held"] == 0, str(me))
st, rep = http(S2, "POST", "/payments", {"to_handle": "bob", "amount": 700, "note": "from stage 1", "visibility": "public"}, tok, "s1-key-1")
check("stage-1 idempotency key replays after import (200, same payment)", st == 200 and rep["payment_id"] == pay["payment_id"], str(rep))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('pocketful.token','{tok}')")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(S2 + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=wallet-available]")
    t = lambda i: page.locator(f'[data-testid="{i}"]')
    check("browser holding a stage-1 token stays signed in", t("current-handle").inner_text() == "ada" and "/login" not in page.url)
    check("imported balance and feed shown", t("wallet-available").inner_text() == "93.00 EUR" and page.locator('[data-testid^="activity-item-"]').count() == 2, t("wallet-available").inner_text())
    page.screenshot(path=f"{SHOTS}/upgrade-real-home-1280.png", full_page=True)
    page.goto(S2 + "/requests", wait_until="domcontentloaded")
    t("request-pay-rq_1").click()
    page.wait_for_function("document.querySelector('[data-testid=request-item-rq_1]').dataset.status === 'paid'")
    check("imported pending request payable via the UI", t("wallet-balance").inner_text() == "81.00 EUR", t("wallet-balance").inner_text())
    check("no page errors", not errors, str(errors))
    b.close()
sys.exit(1 if fails else 0)
