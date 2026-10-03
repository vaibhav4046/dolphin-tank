"""B04: the browser signed in on the STAGE-3 service survives export -> import into the STAGE-4 service. A tiny same-origin proxy sends API calls to the stage-3 service until the import,
then to the stage-4 service (page/assets/HTML always come from stage 4). No page reload, no re-login."""
import threading, http.server, http.client, urllib.parse, socketserver
from bl import *

S3 = urllib.parse.urlparse(os.environ["PF3"]); S3H = (S3.hostname, S3.port)
S4H = (HOST, PORT)
PP = int(os.environ["PROXY_PORT"]); PROXY = "http://127.0.0.1:%d" % PP
STATE = {"api": S3H, "seen": []}
UI_PATHS = ("/", "/login", "/signup", "/split", "/requests", "/authorizations")

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def fwd(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
        path = self.path.split("?")[0]; acc = self.headers.get("Accept", "")
        ui = path.startswith("/assets/") or (self.command == "GET" and path in UI_PATHS and "text/html" in acc) or (self.command == "GET" and path in ("/", "/login", "/signup", "/split"))
        tgt = S4H if ui else STATE["api"]
        c = http.client.HTTPConnection(*tgt, timeout=20)
        hd = {k_: v for k_, v in self.headers.items() if k_.lower() not in ("host", "connection", "content-length")}
        c.request(self.command, self.path, body=body, headers=hd)
        r = c.getresponse(); data = r.read()
        STATE["seen"].append((self.command, path, "S3" if tgt == S3H else "S4", r.status))
        self.send_response(r.status)
        for k_, v in r.getheaders():
            if k_.lower() not in ("connection", "transfer-encoding", "content-length"): self.send_header(k_, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = fwd

class TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True
srv = TS(("127.0.0.1", PP), H); threading.Thread(target=srv.serve_forever, daemon=True).start()

def text(page, t): return tid(page, t).inner_text().strip()
def present(page, t): return tid(page, t).count() > 0
def settle(page, ms=600): page.wait_for_timeout(ms)
def wait_present(page, t, timeout=6000):
    try: page.wait_for_selector('[data-testid="%s"]' % t, timeout=timeout); return True
    except Exception: return False
def tk(email, base): return api("POST", "/auth/login", {"email": email, "password": "correct horse"}, base=base)[1]["token"]

# seeded on the STAGE-3 service: a pending request, a payment that gets corrected in stage 3, a received payment refunded after the upgrade
fx = fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 3000)],
             requests=[{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}],
             payments=[{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                       {"id": "p_recv", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2000, "note": "refundable", "visibility": "public"}])
assert api("POST", "/_test/reset", fx, base=S3H)[0] == 204
assert api("POST", "/_test/reset", fixture(users=[user("zed", 1)]), base=S4H)[0] == 204   # destination starts as an unrelated fixture
ada3 = tk("ada@example.com", S3H); bob3 = tk("bob@example.com", S3H)
ok("precondition: the source is a stage-3 service (no refund_of on its payments)", all("refund_of" not in p for p in api("GET", "/activity", token=ada3, base=S3H)[1]["payments"]))
ok("precondition: stage-3 revisions route exists on the source", api("GET", "/payments/p_seed/revisions", token=ada3, base=S3H)[0] == 200)
ok("precondition: the source has no refund route", api("POST", "/payments/p_recv/refunds", {"amount": 100}, token=ada3, key=k(), base=S3H)[0] in (404, 405))

log = []
with sync_playwright() as pw:
    br = launch(pw); ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 900})
    page.on("request", lambda r: log.append({"m": r.method, "url": r.url.replace(PROXY, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data}) if r.method != "GET" else None)
    page.goto(PROXY + "/login")
    tid(page, "login-email").fill("ada@example.com"); tid(page, "login-password").fill("correct horse"); tid(page, "login-submit").click()
    page.wait_for_selector('[data-testid="current-user"]', timeout=8000); wait_present(page, "wallet-available"); settle(page, 800)
    ok("B04 signed in through the UI on the stage-3 backend", "Ada" in text(page, "current-user") and text(page, "current-handle") == "ada")
    ok("B04 pre-upgrade wallet from the stage-3 /me: available 100.00 EUR headline, received payment listed", text(page, "wallet-available") == "100.00 EUR" and present(page, "activity-item-p_recv"), text(page, "wallet-available"))
    shot(page, "b04_before_import")
    mode = {"m": "drop"}
    def h(route):
        if route.request.method != "POST": return route.continue_()
        if mode["m"] == "drop": route.fetch(); route.abort("failed")
        else: route.continue_()
    page.route("**/payments", h)
    tid(page, "pay-handle").fill("cy"); tid(page, "pay-amount").fill("15.00"); tid(page, "pay-note").fill("lost dinner"); tid(page, "pay-visibility").select_option("public")
    tid(page, "pay-submit").click(); settle(page, 1200)
    ok("B04 pre-upgrade lost response -> pay-uncertain (not pay-error)", present(page, "pay-uncertain") and not present(page, "pay-error"))
    ok("B04 stage-3 committed the payment: ada total 8500", api("GET", "/me", token=ada3, base=S3H)[1]["total"] == 8500)
    # stage-3-only features before the upgrade: a correction by the sender, a new pending request
    s, c3 = api("POST", "/payments/p_seed/corrections", {"expected_revision": 1, "amount": 450, "effective_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 1)), "reason": "typo"}, token=ada3, key=k(), base=S3H)
    ok("B04 stage-3 correction of p_seed to 450 accepted before export", s == 201, (s, c3))
    st, newreq = api("POST", "/requests", {"payer_handle": "ada", "amount": 400, "note": "pending after"}, token=bob3, key=k(), base=S3H); assert st == 201
    st, ex = api("GET", "/_test/export", base=S3H); assert st == 200
    ok("B04 the export is a stage-3 export (no refund_of in state.payments)", ex.get("track") == "pocketful" and all("refund_of" not in p for p in ex["state"]["payments"]), list(ex.keys()))
    # ---- THE UPGRADE: stage-3 export into the stage-4 service, API traffic flipped, page NOT reloaded
    st, _ = api("POST", "/_test/import", raw=json.dumps(ex).encode(), base=S4H); assert st == 204, st
    STATE["api"] = S4H
    tid(page, "wallet-refresh").click(); settle(page, 1000)
    ok("B04 session kept: no redirect to /login, still Ada", "/login" not in page.url and present(page, "current-user") and "Ada" in text(page, "current-user"), page.url)
    ok("B04 imported balances: total 85.50 EUR (8500 + 50 from the stage-3 correction), available 85.50", text(page, "wallet-balance") == "85.50 EUR" and text(page, "wallet-available") == "85.50 EUR", (text(page, "wallet-balance"), text(page, "wallet-available")))
    ok("B04 pay form kept its values; pay-uncertain still shown", (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value()) == ("cy", "15.00", "lost dinner") and present(page, "pay-uncertain"))
    page.unroute("**/payments"); mode["m"] = "pass"
    tid(page, "pay-submit").click(); settle(page, 1200)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("B04 lost payment retried on stage 4 with the SAME key and byte-identical body", len(posts) == 2 and posts[0]["key"] == posts[1]["key"] and posts[0]["body"] == posts[1]["body"], [(p["key"], p["body"]) for p in posts])
    ok("B04 retry recovered the original: uncertain/error gone, balance still 85.50 EUR (money once)", not present(page, "pay-uncertain") and not present(page, "pay-error") and text(page, "wallet-balance") == "85.50 EUR")
    on4 = [s_ for s_ in STATE["seen"] if s_[1] == "/payments" and s_[0] == "POST"]
    ok("B04 retried POST /payments reached the STAGE-4 backend and was a replay (200)", on4 and on4[-1][2] == "S4" and on4[-1][3] == 200, on4)
    feed = [e.inner_text() for e in page.locator('[data-testid^="activity-item-"]').all()]
    ok("B04 feed lists the lost payment exactly once", len([f for f in feed if "lost dinner" in f]) == 1, feed)
    ok("B04 imported payments read refund_of null on stage 4", all(p.get("refund_of", "MISSING") is None for p in api("GET", "/activity?limit=100", token=ada3, base=S4H)[1]["payments"]))
    revs = api("GET", "/payments/p_seed/revisions", token=ada3, base=S4H)[1]["revisions"]
    ok("B04 stage-3 correction retained after import: 2 revisions, current amount 450", len(revs) == 2 and max(revs, key=lambda r: r["revision"])["amount"] == 450, revs)
    # B12 on imported data
    ok("B12/B04 refund control offered on the imported received payment p_recv, not on the sent p_seed", present(page, "refund-toggle-p_recv") and not present(page, "refund-p_seed"))
    tid(page, "refund-toggle-p_recv").click(); tid(page, "refund-amount-p_recv").fill("5.00"); tid(page, "refund-submit-p_recv").click()
    ok("B12/B04 refund of an imported payment succeeds in the browser", wait_present(page, "refund-success-p_recv") and text(page, "refund-success-p_recv") == "Refunded 5.00 EUR to @bob.", text(page, "refund-success-p_recv") if present(page, "refund-success-p_recv") else None)
    settle(page, 700)
    me4 = api("GET", "/me", token=ada3, base=S4H)[1]
    ok("B12/B04 server: ada total 8050 after the 500 refund", me4["total"] == 8050, me4)
    shot(page, "b04_after_retry_and_refund")
    page.locator('nav a[href="/requests"]').click(); page.wait_for_selector('[data-testid="incoming-list"]', timeout=8000); settle(page, 700)
    ok("B04 imported pending requests listed (seeded and 'pending after') with Pay buttons", page.locator('[data-testid="request-item-rq_seed"]').count() == 1 and page.locator('[data-testid="request-item-%s"]' % newreq["request_id"]).count() == 1 and present(page, "request-pay-rq_seed") and present(page, "request-pay-" + newreq["request_id"]))
    tid(page, "request-pay-rq_seed").click(); settle(page, 1000)
    ok("B04 pending request paid through the UI after the upgrade: status paid, no request-error", tid(page, "request-item-rq_seed").get_attribute("data-status") == "paid" and not present(page, "request-error"))
    me4 = api("GET", "/me", token=ada3, base=S4H)[1]
    ok("B04 request payment moved money once: ada total 6850", me4["total"] == 6850 and me4["available"] == 6850, me4)
    shot(page, "b04_requests_after_pay")
    tot = sum(api("GET", "/me", token=tk(e_ + "@example.com", S4H), base=S4H)[1]["total"] for e_ in ("ada", "bob", "cy"))
    ok("B04 conservation: totals still sum to 15500", tot == 15500, tot)
    br.close()
done("b8_upgrade34")
