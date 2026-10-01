"""I15: the browser signed in on the stage-1 service survives export -> import into stage 2. A tiny same-origin proxy sends API calls to the stage-1 service until the import, then to the stage-2 service
(page/assets/HTML always come from stage 2, the only build that has a UI). No page reload, no re-login."""
import threading, http.server, http.client, urllib.parse, socketserver
from bl import *

S1 = urllib.parse.urlparse(os.environ["PF1"]); S1H = (S1.hostname, S1.port)
S2H = (HOST, PORT)
PP = int(os.environ["PROXY_PORT"]); PROXY = "http://127.0.0.1:%d" % PP
STATE = {"api": S1H, "seen": []}
UI_PATHS = ("/", "/login", "/signup", "/split", "/requests", "/authorizations")

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def fwd(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
        path = self.path.split("?")[0]; acc = self.headers.get("Accept", "")
        ui = path.startswith("/assets/") or (self.command == "GET" and path in UI_PATHS and "text/html" in acc) or (self.command == "GET" and path in ("/", "/login", "/signup", "/split"))
        tgt = S2H if ui else STATE["api"]
        c = http.client.HTTPConnection(*tgt, timeout=20)
        hd = {k_: v for k_, v in self.headers.items() if k_.lower() not in ("host", "connection", "content-length")}
        c.request(self.command, self.path, body=body, headers=hd)
        r = c.getresponse(); data = r.read()
        STATE["seen"].append((self.command, path, "S1" if tgt == S1H else "S2", r.status))
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

fx = fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 3000)],
             requests=[{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}],
             payments=[{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}])
assert api("POST", "/_test/reset", fx, base=S1H)[0] == 204
assert api("POST", "/_test/reset", fixture(users=[user("zed", 1)]), base=S2H)[0] == 204   # destination starts as an unrelated fixture
ok("precondition: stage-1 service /me has no available/held", "available" not in api("GET", "/me", token=api("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}, base=S1H)[1]["token"], base=S1H)[1])

log = []
with sync_playwright() as pw:
    br = launch(pw); ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 900})
    page.on("request", lambda r: log.append({"m": r.method, "url": r.url.replace(PROXY, ""), "key": r.headers.get("idempotency-key"), "body": r.post_data}) if r.method != "GET" else None)
    # ---- sign in through the real login form; the token comes from the STAGE-1 service
    page.goto(PROXY + "/login")
    tid(page, "login-email").fill("ada@example.com"); tid(page, "login-password").fill("correct horse"); tid(page, "login-submit").click()
    page.wait_for_selector('[data-testid="current-user"]', timeout=8000); settle(page, 800)
    ok("I15 signed in on the stage-1 backend through the UI", "Ada" in text(page, "current-user") and text(page, "current-handle") == "ada")
    pre_bal = text(page, "wallet-balance") if present(page, "wallet-balance") else None
    info("pre-upgrade wallet-balance as the UI shows it against the stage-1 /me:", pre_bal, "| available present:", present(page, "wallet-available"))
    shot(page, "upgrade_before_import")
    # ---- a payment whose response is lost AFTER it committed on the stage-1 service
    mode = {"m": "drop"}
    def h(route):
        if route.request.method != "POST": return route.continue_()
        if mode["m"] == "drop":
            route.fetch(); route.abort("failed")
        else: route.continue_()
    page.route("**/payments", h)
    tid(page, "pay-handle").fill("cy"); tid(page, "pay-amount").fill("15.00"); tid(page, "pay-note").fill("lost dinner"); tid(page, "pay-visibility").select_option("public")
    tid(page, "pay-submit").click(); settle(page, 1200)
    ok("I15 pre-upgrade: lost response -> pay-uncertain (not pay-error)", present(page, "pay-uncertain") and not present(page, "pay-error"))
    s1_login = api("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}, base=S1H)[1]["token"]
    s1_balance = api("GET", "/me", token=s1_login, base=S1H)[1]["balance"]
    ok("I15 the stage-1 service committed the payment (balance 8500)", s1_balance == 8500, s1_balance)
    st, newreq = api("POST", "/requests", {"payer_handle": "ada", "amount": 400, "note": "pending after"}, token=api("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"}, base=S1H)[1]["token"], key=k(), base=S1H)
    assert st == 201
    # ---- THE UPGRADE: export from stage 1, import into stage 2, flip the backend. The page is NOT reloaded.
    st, ex = api("GET", "/_test/export", base=S1H); assert st == 200
    st, _ = api("POST", "/_test/import", raw=json.dumps(ex).encode(), base=S2H); assert st == 204, st
    STATE["api"] = S2H
    # ---- same page: refresh the wallet
    tid(page, "wallet-refresh").click(); settle(page, 1000)
    ok("I15 session still valid after the upgrade (no redirect to /login, current-user still shown)", "/login" not in page.url and present(page, "current-user") and "Ada" in text(page, "current-user"), page.url)
    ok("I15 imported balance shown after refresh: wallet-balance 85.00 EUR", text(page, "wallet-balance") == "85.00 EUR", text(page, "wallet-balance"))
    ok("I15 wallet-available present and equal to 85.00 EUR (stage-2 /me shape), wallet-held absent", present(page, "wallet-available") and text(page, "wallet-available") == "85.00 EUR" and not present(page, "wallet-held"), [text(page, t_) for t_ in ("wallet-available",) if present(page, t_)])
    ok("I15 pay form kept its values through the upgrade", (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(), tid(page, "pay-note").input_value()) == ("cy", "15.00", "lost dinner"))
    ok("I15 pay-uncertain still visible (outcome not yet resolved)", present(page, "pay-uncertain"))
    # ---- retry the lost payment with the unchanged form: same key + body, recovers the original
    page.unroute("**/payments"); mode["m"] = "pass"
    tid(page, "pay-submit").click(); settle(page, 1200)
    posts = [x for x in log if x["url"].endswith("/payments")]
    ok("I15 retry after upgrade sent the SAME Idempotency-Key and byte-identical body", len(posts) == 2 and posts[0]["key"] == posts[1]["key"] and posts[0]["body"] == posts[1]["body"], [(p["key"], p["body"]) for p in posts])
    ok("I15 retry recovered the original payment: pay-uncertain and pay-error gone, balance still 85.00 EUR (money once)", not present(page, "pay-uncertain") and not present(page, "pay-error") and text(page, "wallet-balance") == "85.00 EUR", (present(page, "pay-uncertain"), present(page, "pay-error"), text(page, "wallet-balance")))
    srv_me = api("GET", "/me", token=s1_login, base=S2H)[1]
    ok("I15 stage-2 server: ada total 8500 (debited once), available 8500, held 0", (srv_me["total"], srv_me["available"], srv_me["held"]) == (8500, 8500, 0), srv_me)
    feed = [e.inner_text() for e in page.locator('[data-testid^="activity-item-"]').all()]
    ok("I15 feed shows the lost payment exactly once", len([f for f in feed if "lost dinner" in f]) == 1, feed)
    on_s2 = [s for s in STATE["seen"] if s[1] == "/payments" and s[0] == "POST"]
    ok("I15 retried POST /payments reached the STAGE-2 backend and was a replay (200)", on_s2 and on_s2[-1][2] == "S2" and on_s2[-1][3] == 200, on_s2)
    shot(page, "upgrade_after_retry")
    # ---- pending request payable through the request screen (navigation via the UI nav)
    page.locator('nav a[href="/requests"]').click(); page.wait_for_selector('[data-testid="incoming-list"]', timeout=8000); settle(page, 700)
    ok("I15 imported pending requests listed: seeded and 'pending after'", page.locator('[data-testid="request-item-rq_seed"]').count() == 1 and page.locator('[data-testid="request-item-%s"]' % newreq["request_id"]).count() == 1, page.eval_on_selector_all("[data-testid^=request-item-]", "e => e.map(x => x.getAttribute('data-testid'))"))
    ok("I15 pending incoming requests have a pay button", present(page, "request-pay-rq_seed") and present(page, "request-pay-" + newreq["request_id"]))
    tid(page, "request-pay-rq_seed").click(); settle(page, 1000)
    ok("I15 pending request paid through the UI after the upgrade: status paid, no request-error", tid(page, "request-item-rq_seed").get_attribute("data-status") == "paid" and not present(page, "request-error"), (tid(page, "request-item-rq_seed").get_attribute("data-status"), present(page, "request-error")))
    srv_me = api("GET", "/me", token=s1_login, base=S2H)[1]
    ok("I15 request payment moved money once: ada total 7300", srv_me["total"] == 7300 and srv_me["available"] == 7300, srv_me)
    shot(page, "upgrade_requests_after_pay")
    sum_tot = sum(api("GET", "/me", token=api("POST", "/auth/login", {"email": e_ + "@example.com", "password": "correct horse"}, base=S2H)[1]["token"], base=S2H)[1]["total"] for e_ in ("ada", "bob", "cy"))
    ok("A01 conservation: totals sum to 15500", sum_tot == 15500, sum_tot)
    info("proxy traffic (method path backend status) sample:", STATE["seen"][-12:])
    br.close()
done("b4_upgrade")
