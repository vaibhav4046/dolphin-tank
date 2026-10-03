"""Stage-3 export -> stage-4 import in a real browser (loom). The stage-4 process replaces the stage-3 one on the
same port while the page stays open, so the session token, the page's pending payment attempt and its idempotency
key all have to survive the upgrade. Needs /tmp/pf3.exe (stage-3 build) and /tmp/pf4.exe (stage-4 build)."""
import os, subprocess, sys, time, urllib.request
from datetime import timedelta
from playwright.sync_api import sync_playwright
import common
from common import *

PORT = 8085
B = f"http://127.0.0.1:{PORT}"
common.BASE = B
TMP = os.environ.get("TMPDIR", "/tmp")
PF3, PF4 = os.environ.get("PF3", "/tmp/pf3.exe"), os.environ.get("PF4", "/tmp/pf4.exe")
USERS = [user("u_ada", "ada", "Ada", 10000), user("u_bob", "bob", "Bob", 2500)]
FIX = {"currency": "EUR", "minor_units": 2, "users": USERS,
       "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public", "created_at": iso(timedelta(hours=-3))}],
       "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}


def start(exe):
    proc = subprocess.Popen([exe], env={**os.environ, "PORT": str(PORT)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(B + "/health").read()
            return proc
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("server did not start: " + exe)


def stop(proc):
    proc.terminate()
    proc.wait()


def run(pw, width):
    p3 = start(PF3)
    try:
        assert http("POST", "/_test/reset", FIX)[0] == 204
        ada, bob = token_of("ada"), token_of("bob")
        b = pw.chromium.launch()
        s = Session(b, width, token=ada, base=B)
        pg = s.page
        s.goto("/")
        s.t("pay-handle").fill("bob")
        s.t("pay-amount").fill("7.00")
        s.t("pay-note").fill("sent before the upgrade")
        seen = []
        def lose(route):
            seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
            route.fetch()
            route.abort("connectionreset")
        pg.route("**/payments", lambda route: lose(route) if route.request.method == "POST" else route.continue_())
        s.t("pay-submit").click()
        s.t("pay-uncertain").wait_for()
        check(f"[{width}] stage 3: lost payment reads as unconfirmed", "could not confirm" in s.t("pay-uncertain").inner_text())
        before_me = http("GET", "/me", token=ada)[1]
        check(f"[{width}] stage 3: the server did apply it once", before_me["balance"] == 10000 - 700, str(before_me))
        st, export = http("GET", "/_test/export")
        check(f"[{width}] stage-3 export taken", st == 200 and export["format_version"] == 1, st)
        stop(p3)
        p4 = start(PF4)
    except Exception:
        stop(p3)
        raise
    try:
        st, _ = http("POST", "/_test/import", export)
        check(f"[{width}] stage-4 imports the stage-3 export", st == 204, st)
        check(f"[{width}] sessions (tokens) survive the import", http("GET", "/me", token=ada)[0] == 200 and http("GET", "/me", token=bob)[0] == 200)
        pg.unroute("**/payments")
        s.t("pay-submit").click()
        s.t("pay-success").wait_for()
        sent = [p for p in s.posts if p[0] == "/payments"]
        check(f"[{width}] retry after the upgrade re-sends the same key and body", len(sent) == 2 and sent[0][1] == sent[1][1] == seen[0][0] and sent[0][2] == sent[1][2], str(sent))
        me = http("GET", "/me", token=ada)[1]
        check(f"[{width}] the lost payment is applied exactly once (replay, not a second payment)", me["balance"] == 10000 - 700, str(me))
        pg.wait_for_function("document.querySelectorAll('[data-testid^=activity-item-]').length >= 2")
        check(f"[{width}] the page stayed signed in on the upgraded server", "/login" not in pg.url and s.t("current-handle").inner_text() == "ada")
        s.hscroll_ok(f"{width} after upgrade")
        s.shot(f"upgrade-wallet-{width}")
        s.goto("/requests")
        s.t("request-pay-rq_1").click()
        pg.wait_for_function("document.querySelector('[data-testid=request-item-rq_1]').dataset.status === 'paid'")
        check(f"[{width}] the imported pending request is payable in the browser", True)
        s.hscroll_ok(f"{width} requests after upgrade")
        check(f"[{width}] no page errors or external requests", not [e for e in s.errors if not e.startswith("Failed to load resource")] and not s.external, str(s.errors + s.external))
        s.ctx.close()

        r = Session(b, width, token=bob, base=B)
        r.goto("/")
        r.t("refund-toggle-p_1").click()
        r.t("refund-amount-p_1").fill("1.00")
        r.t("refund-submit-p_1").click()
        r.t("refund-success-p_1").wait_for()
        feed = http("GET", "/activity?limit=100", token=ada)[1]["payments"]
        refunds = [p for p in feed if p.get("refund_of") == "p_1"]
        old = [p for p in feed if p["payment_id"] == "p_1"][0]
        check(f"[{width}] a stage-3 payment is refundable on the upgraded server; old payment reads refund_of null", len(refunds) == 1 and refunds[0]["amount"] == 100 and old.get("refund_of") is None, str(refunds))
        r.hscroll_ok(f"{width} refund of an imported payment")
        r.shot(f"upgrade-refund-{width}")
        r.ctx.close()
        b.close()
    finally:
        stop(p4)


if __name__ == "__main__":
    with sync_playwright() as pw:
        for w in (375, 1280):
            run(pw, w)
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'ALL PASSED'}")
    sys.exit(1 if FAILS else 0)
