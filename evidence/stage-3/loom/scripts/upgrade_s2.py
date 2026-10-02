"""Real stage-2 export (with authorizations and captures) -> stage-3 import, browser session kept (T51, T64)."""
import json, sys, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

S3, S2 = "http://127.0.0.1:8080", "http://127.0.0.1:8081"
SHOTS = "/work/shots"


def http(base, method, path, body=None, token=None, key=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)
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


def user(uid, handle, name, bal):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse", "display_name": name, "handle": handle, "balance": bal}


FIX = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3600,
       "users": [user("u_ada", "ada", "Ada", 10000), user("u_bob", "bob", "Bob", 2500)],
       "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}],
       "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" [{detail}]"), flush=True)
    if not ok:
        fails.append(name)


st, _ = http(S2, "POST", "/_test/reset", FIX)
check("stage-2 server reset", st == 204, st)
st, login = http(S2, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
tok = login["token"]
st, bob = http(S2, "POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"})
btok = bob["token"]
st, pay = http(S2, "POST", "/payments", {"to_handle": "bob", "amount": 700, "note": "from stage 2", "visibility": "public"}, tok, "s2-key-1")
check("stage-2 payment created", st == 201, st)
st, a1 = http(S2, "POST", "/authorizations", {"to_handle": "bob", "amount": 2000, "note": "deposit"}, tok, "s2-auth-1")
check("stage-2 authorization created", st == 201 and a1["status"] == "open", str(a1))
st, cap = http(S2, "POST", f"/authorizations/{a1['authorization_id']}/capture", {"amount": 500, "final": False}, btok, "s2-cap-1")
check("stage-2 partial capture", st == 201 and cap["authorization_id"] == a1["authorization_id"], str(cap))
st, a2 = http(S2, "POST", "/authorizations", {"to_handle": "bob", "amount": 300}, tok, "s2-auth-2")
st, v = http(S2, "POST", f"/authorizations/{a2['authorization_id']}/void", {}, tok)
check("stage-2 voided authorization", st == 200 and v["status"] == "voided", str(v))
st, me2 = http(S2, "GET", "/me", token=tok)
st, exp = http(S2, "GET", "/_test/export")
check("stage-2 export", st == 200 and exp["format_version"] == 1, st)

http(S3, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [user("u_x", "zed", "Zed", 5)]})
st, _ = http(S3, "POST", "/_test/import", exp)
check("stage-3 imports the real stage-2 export", st == 204, st)
st, me = http(S3, "GET", "/me", token=tok)
same = all(me[k] == me2[k] for k in ("balance", "total", "available", "held"))
check("stage-2 token valid; balance/total/available/held unchanged by the import", st == 200 and same and me["balance"] == me["total"], f"{me} vs {me2}")
st, rep = http(S3, "POST", "/payments", {"to_handle": "bob", "amount": 700, "note": "from stage 2", "visibility": "public"}, tok, "s2-key-1")
check("stage-2 idempotency key replays after import (200, same payment)", st == 200 and rep["payment_id"] == pay["payment_id"], str(rep))
st, rep = http(S3, "POST", f"/authorizations/{a1['authorization_id']}/capture", {"amount": 500, "final": False}, btok, "s2-cap-1")
check("stage-2 capture key replays after import", st == 200 and rep["payment_id"] == cap["payment_id"], str(rep))

st, lst = http(S3, "GET", "/authorizations", token=tok)
by = {a["authorization_id"]: a for a in lst["authorizations"]}
check("imported authorizations expose closed_at: open null, voided non-null",
      by[a1["authorization_id"]]["closed_at"] is None and by[a2["authorization_id"]]["closed_at"] is not None, str(lst)[:400])
st, revs = http(S3, "GET", f"/payments/{cap['payment_id']}/revisions", token=tok)
check("imported capture has revision 1", st == 200 and len(revs["revisions"]) == 1, str(revs))
st, bad = http(S3, "POST", f"/payments/{cap['payment_id']}/corrections",
               {"expected_revision": 1, "amount": 100, "effective_at": cap["created_at"], "reason": "no"}, tok, "s2-corr-capture")
check("correcting an imported capture is 422 linked_payment_immutable", st == 422 and bad["error"]["code"] == "linked_payment_immutable", str(bad))
st, stm = http(S3, "GET", "/statement", token=tok)
ids = [e["payment"]["payment_id"] for e in stm["entries"]]
check("statement shows the capture exactly once and no authorization/void rows",
      st == 200 and ids.count(cap["payment_id"]) == 1 and len(ids) == len(set(ids)), str(ids))
check("statement arithmetic: opening + deltas == closing == balance",
      stm["opening_balance"] + sum(e["delta"] for e in stm["entries"]) == stm["closing_balance"] == me["balance"], str(stm)[:300])
st, ok = http(S3, "POST", f"/payments/{pay['payment_id']}/corrections",
              {"expected_revision": 1, "amount": 300, "effective_at": pay["created_at"], "reason": "partial refund"}, tok, "s2-corr-1")
check("a correction of an imported payment works (201, revision 2)", st == 201 and ok["revision"] == 2, str(ok))
st, me3 = http(S3, "GET", "/me", token=tok)
check("correction moved 400 back to the sender", st == 200 and me3["balance"] == me["balance"] + 400, f"{me3} vs {me}")
st, feed = http(S3, "GET", "/activity", token=tok)
amounts = {p["payment_id"]: p["amount"] for p in feed["payments"]}
check("feed still shows the original amount", amounts.get(pay["payment_id"]) == 700, str(amounts))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('pocketful.token','{tok}')")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(S3 + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=wallet-available]")
    t = lambda i: page.locator(f'[data-testid="{i}"]')
    check("browser holding a stage-2 token stays signed in", t("current-handle").inner_text() == "ada" and "/login" not in page.url)
    check("wallet balance equals the API balance (which equals total)", t("wallet-balance").get_attribute("data-amount") == str(me3["balance"]), t("wallet-balance").get_attribute("data-amount"))
    check("feed shows the original payments", page.locator('[data-testid^="activity-item-"]').count() >= 3, page.locator('[data-testid^="activity-item-"]').count())
    page.screenshot(path=f"{SHOTS}/upgrade-s2-home-1280.png", full_page=True)
    page.goto(S3 + "/requests", wait_until="domcontentloaded")
    t("request-pay-rq_1").click()
    page.wait_for_function("document.querySelector('[data-testid=request-item-rq_1]').dataset.status === 'paid'")
    check("imported pending request payable via the UI", True)
    page.goto(S3 + "/authorizations", wait_until="domcontentloaded")
    page.wait_for_selector("main[aria-busy='false']")
    page.screenshot(path=f"{SHOTS}/upgrade-s2-authorizations-1280.png", full_page=True)
    check("no page errors / console errors", not errors, str(errors))
    b.close()
sys.exit(1 if fails else 0)
