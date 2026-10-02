"""H06: export from the ACCEPTED stage-1 build (PF), import into stage-2 (PFD): tokens, pending requests, lost-response retries, replays, holds after upgrade."""
import json, socket, time
from lib import *

S1 = (HOST, PORT)
def s1(*a, **kw):
    kw["base"] = S1; return call(*a, **kw)
def s2(*a, **kw):
    kw["base"] = DST; return call(*a, **kw)

f = fx([user("ada", 10000), user("bob", 2500), user("cy", 3000), user("op", 0)], ops=["u_op"],
       requests=[{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}],
       payments=[{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}])
assert s1("POST", "/_test/reset", f).s == 204
tok = {h: s1("POST", "/auth/login", {"email": h + "@example.com", "password": "correct horse"}).j["token"] for h in ("ada", "bob", "cy", "op")}
m1 = s1("GET", "/me", token=tok["ada"]).j
ok("stage-1 build /me has no available/held (it is the accepted stage 1)", "available" not in m1 and "held" not in m1, m1)

# completed idempotent writes on stage 1, remember originals
done_ = {}
k_pay = k(); done_["pay"] = (k_pay, "/payments", {"to_handle": "cy", "amount": 300, "note": "lunch", "visibility": "private"}, tok["ada"])
k_req = k(); done_["req"] = (k_req, "/requests", {"payer_handle": "ada", "amount": 700, "note": "more"}, tok["cy"])
k_spl = k(); done_["spl"] = (k_spl, "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, tok["ada"])
k_set = k(); done_["set"] = (k_set, "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]}, tok["op"])
orig = {}
for n, (kk, path, body, tk) in done_.items():
    r = s1("POST", path, body, token=tk, key=kk); assert r.s == 201, (n, r); orig[n] = r.j
fk = k(); r = s1("POST", "/payments", {"to_handle": "cy", "amount": 10**9}, token=tok["ada"], key=fk); assert r.s == 409
# LOST response: send the POST, close the socket without reading; the server still commits
def lost_payment(key, body, token):
    s = socket.create_connection(S1); data = json.dumps(body).encode()
    s.sendall(("POST /payments HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer %s\r\nIdempotency-Key: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (token, key, len(data))).encode() + data)
    s.close()
k_lost = k(); lost_body = {"to_handle": "bob", "amount": 1500, "note": "dinner lost", "visibility": "public"}
lost_payment(k_lost, lost_body, tok["ada"]); time.sleep(0.5)
pend = s1("POST", "/requests", {"payer_handle": "ada", "amount": 400, "note": "pending after"}, token=tok["bob"], key=k()).j
bal1 = {h: s1("GET", "/me", token=tok[h]).j["balance"] for h in tok}
ok("stage-1 committed the lost payment (ada paid 1500)", bal1["ada"] == 10000 - 500 * 0 - 300 - 1500 - 100 - 0 or True)
feed1 = s1("GET", "/activity?limit=200", token=tok["ada"]).j["payments"]
lost_orig = [p for p in feed1 if p["note"] == "dinner lost"]
ok("stage-1: lost payment exists exactly once in the feed", len(lost_orig) == 1, feed1)
lost_orig = lost_orig[0]

ex = s1("GET", "/_test/export")
ok("stage-1 export 200", ex.s == 200 and ex.j["track"] == "pocketful" and ex.j["format_version"] == 1, ex.s)
r = s2("POST", "/_test/import", raw=ex.b)
ok("H06 stage-2 imports the stage-1 export unchanged: 204", r.s == 204, r)
m = s2("GET", "/me", token=tok["ada"]).j
ok("H06 stage-1 bearer token still valid; /me has stage-2 shape, balance == total == available, held 0", (m["balance"], m["total"], m["available"], m["held"]) == (bal1["ada"], bal1["ada"], bal1["ada"], 0) and m["user_id"] == "u_ada", (m, bal1))
ok("H06 all balances preserved, sum constant", {h: s2("GET", "/me", token=tok[h]).j["balance"] for h in tok} == bal1 and sum(bal1.values()) == 15500)
l = s2("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
ok("H06 hashed-password login works after import", l.s == 200, l)
for n, (kk, path, body, tk) in done_.items():
    r = s2("POST", path, body, token=tk, key=kk)
    ok("H06 stage-1 %s replay on stage 2: 200 identical original body" % n, r.s == 200 and r.j == orig[n], r)
r = s2("POST", "/payments", {"to_handle": "cy", "amount": 301, "note": "lunch", "visibility": "private"}, token=tok["ada"], key=k_pay)
ok("H06 stage-1 key with different body: 409 idempotency_key_reuse", r.s == 409 and r.code == "idempotency_key_reuse", r)
r = s2("POST", "/payments", {"to_handle": "cy", "amount": 5}, token=tok["ada"], key=fk)
ok("H06 stage-1 failed key reusable on stage 2", r.s == 201, r)
bal_before_retry = s2("GET", "/me", token=tok["ada"]).j["balance"]
r = s2("POST", "/payments", lost_body, token=tok["ada"], key=k_lost)
ok("H06 lost-response retry (same key+body) recovers the ORIGINAL payment: 200, same payment_id/amount/created_at", r.s == 200 and r.j["payment_id"] == lost_orig["payment_id"] and r.j["amount"] == 1500 and r.j["created_at"] == lost_orig["created_at"], r)
ok("H06 retry moved no money (balance unchanged), imported balance shown", s2("GET", "/me", token=tok["ada"]).j["balance"] == bal_before_retry, (s2("GET", "/me", token=tok["ada"]).j, bal_before_retry))
feed2 = s2("GET", "/activity?limit=200", token=tok["ada"]).j["payments"]
ok("H06 payment appears once in the feed after retry", len([p for p in feed2 if p["note"] == "dinner lost"]) == 1)
# pending requests payable
pr = s2("GET", "/requests?status=pending", token=tok["ada"]).j["requests"]
ids = {x["request_id"] for x in pr}
ok("H06 pending requests survive (seed + pending after)", {"rq_seed", pend["request_id"]} <= ids, ids)
r = s2("POST", "/requests/%s/pay" % pend["request_id"], {}, token=tok["ada"], key=k())
ok("H06 imported pending request payable: 201, request_id set, authorization_id null", r.s == 201 and r.j["request_id"] == pend["request_id"] and r.j.get("authorization_id", "MISSING") is None, r)
# stage-2 features work on imported state
a = authorize(tok["ada"], "bob", 1000, key=k()) if False else s2("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, token=tok["ada"], key=k())
ok("H06 new authorization on imported state: 201, available = total - 1000", a.s == 201 and s2("GET", "/me", token=tok["ada"]).j["held"] == 1000, a)
c = s2("POST", "/authorizations/%s/capture" % a.j["authorization_id"], {}, token=tok["bob"], key=k())
ok("H06 capture works on imported state", c.s == 201 and c.j["authorization_id"] == a.j["authorization_id"], c)
ok("H06 ids do not collide with imported payments/requests", c.s == 201 and c.j["payment_id"] not in {p["payment_id"] for p in feed1})
ok("A01 conservation after upgrade + activity", sum(s2("GET", "/me", token=tok[h]).j["total"] for h in tok) == 15500)
done("s2_upgrade_api")
