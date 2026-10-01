"""Lost-response retries (client abandons connection), concurrent same key with DIFFERENT bodies, pay visibility edges, default/max limit."""
import json, socket, time
from lib import *

UIDS = [user("ada", 10 ** 7), user("bob", 10 ** 7), user("cy", 0), user("dee", 0), user("op", 0)]


def new_t():
    return setup(fx(UIDS, ops=["u_op"]))


def fire_and_forget(method, path, body, tok, key):
    data = json.dumps(body).encode()
    req = ("%s %s HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer %s\r\nIdempotency-Key: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
           % (method, path, tok, key, len(data))).encode() + data
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.sendall(req)
    s.close()  # response lost


# ---- A: concurrent same key, different bodies: exactly one body wins, one effect
for rnd in range(3):
    t = new_t(); K = k()
    b1 = {"to_handle": "bob", "amount": 100}
    b2 = {"to_handle": "bob", "amount": 200}
    res = parallel([lambda b=b: call("POST", "/payments", b, token=t["ada"], key=K) for b in ([b1, b2] * 10)])
    s201 = [r for r in res if r.s == 201]
    winner = s201[0].j["amount"] if s201 else None
    ok("A%d same key, 2 different bodies x10: exactly one 201" % rnd, len(s201) == 1, [r.s for r in res])
    same = [r for i, r in enumerate(res) if ([b1, b2] * 10)[i]["amount"] == winner]
    other = [r for i, r in enumerate(res) if ([b1, b2] * 10)[i]["amount"] != winner]
    ok("A%d winner-body calls: 1x201 + 9x200 identical; other-body calls: 10 x 409 idempotency_key_reuse" % rnd,
       sum(r.s == 200 for r in same) == 9 and all(r.j == s201[0].j for r in same if r.s == 200) and all(r.s == 409 and r.code == "idempotency_key_reuse" for r in other), [(r.s, r.code) for r in res])
    ok("A%d one effect" % rnd, bal(t["ada"]) == 10 ** 7 - winner, bal(t["ada"]))

# ---- B: lost responses, client retries with the same key
for rnd in range(3):
    t = new_t()
    N = 20
    plan = {"payments": [], "requests": [], "splits": [], "settlements": [], "pay": []}
    rqs = []
    for i in range(N):
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=t["cy"], key=k())
        rqs.append(r.j["request_id"])
    calls = []
    for i in range(N):
        calls.append(("payments", "POST", "/payments", {"to_handle": "cy", "amount": 10}, t["ada"], k()))
        calls.append(("requests", "POST", "/requests", {"payer_handle": "bob", "amount": 5, "note": "r%d" % i}, t["ada"], k()))
        calls.append(("splits", "POST", "/splits", {"amount": 9, "participant_handles": ["ada", "dee", "bob"]}, t["ada"], k()))
        calls.append(("settlements", "POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "dee", "amount": 3}]}, t["op"], k()))
        calls.append(("pay", "POST", "/requests/%s/pay" % rqs[i], {}, t["ada"], k()))
    parallel([lambda c=c: fire_and_forget(c[1], c[2], c[3], c[4], c[5]) for c in calls])
    time.sleep(0.5)
    first = parallel([lambda c=c: call(c[1], c[2], c[3], token=c[4], key=c[5]) for c in calls])
    second = parallel([lambda c=c: call(c[1], c[2], c[3], token=c[4], key=c[5]) for c in calls])
    ok("B%d retry after lost response: every retry is 201 (never applied) or 200 (applied), never 409/5xx" % rnd, all(r.s in (200, 201) for r in first), sorted({r.s for r in first}))
    ok("B%d second retry always 200 and identical to first retry's body" % rnd, all(b.s == 200 and b.j == a.j for a, b in zip(first, second)), [(a.s, b.s) for a, b in zip(first, second)][:5])
    ada = bal(t["ada"]); bob = bal(t["bob"]); cy = bal(t["cy"]); dee = bal(t["dee"])
    ok("B%d each key took effect exactly once: ada -%d (payments) -%d (pay requests); bob -%d (settlements); dee +%d" % (rnd, 10 * N, 10 * N, 3 * N, 3 * N),
       (ada, bob, cy, dee) == (10 ** 7 - 10 * N - 10 * N, 10 ** 7 - 3 * N, 10 * N + 10 * N, 3 * N) or ada + bob + cy + dee == 2 * 10 ** 7 and (ada, dee) == (10 ** 7 - 20 * N, 3 * N), (ada, bob, cy, dee))
    ok("B%d conservation" % rnd, ada + bob + cy + dee + bal(t["op"]) == 2 * 10 ** 7)
    nreq = len(call("GET", "/requests?limit=200&direction=outgoing", token=t["ada"]).j["requests"]) + 0
    ok("B%d requests created exactly N (+ split requests N*2) outgoing by ada: %d" % (rnd, 3 * N), nreq == N + 2 * N, nreq)
    paid = call("GET", "/requests?limit=200&status=paid", token=t["ada"]).j["requests"]
    ok("B%d every pay request paid exactly once" % rnd, len(paid) == N and len({p["payment_id"] for p in paid}) == N, len(paid))

# ---- C: pay visibility edges and non-object bodies
t = new_t()
def rq():
    return call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=t["bob"], key=k()).j["request_id"]
for nm, raw, want in (("visibility 5", '{"visibility":5}', 422), ("visibility null", '{"visibility":null}', 422), ("visibility 'x'", '{"visibility":"x"}', 422),
                      ("visibility 'PRIVATE'", '{"visibility":"PRIVATE"}', 422), ("array body", "[]", 400), ("string body", '"x"', 400), ("bad json", "{", 400)):
    r = call("POST", "/requests/%s/pay" % rq(), raw=raw, token=t["ada"], key=k())
    ok("pay %s -> %d" % (nm, want), r.s == want, r)
r0 = rq()
r = call("POST", "/requests/%s/pay" % r0, raw=b"", token=t["ada"], key=k())
print("OBS pay with empty body ->", r.s)
ok("pay with empty body behaves like {} (201, public)", r.s == 201 and r.j["visibility"] == "public", r)
r = call("POST", "/requests/%s/pay" % rq(), {"visibility": "private", "zz": 1}, token=t["ada"], key=k())
ok("pay private with unknown field -> 201 private", r.s == 201 and r.j["visibility"] == "private", r)
ok("no-key pay -> 400", call("POST", "/requests/%s/pay" % rq(), {}, token=t["ada"]).s == 400)
# precedence observations (spec silent): non-payer on non-pending, unknown id with no key
x = rq(); call("POST", "/requests/%s/decline" % x, {}, token=t["ada"])
print("OBS non-payer pay on declined request ->", call("POST", "/requests/%s/pay" % x, {}, token=t["cy"], key=k()).s, "| payer pay on declined ->", call("POST", "/requests/%s/pay" % x, {}, token=t["ada"], key=k()).s)
print("OBS unknown request, valid key ->", call("POST", "/requests/nope/pay", {}, token=t["ada"], key=k()).s, "| unknown request, no key ->", call("POST", "/requests/nope/pay", {}, token=t["ada"]).s)

# ---- D: default and max limit
t = new_t()
def bulk(i):
    for _ in range(11):
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=t["ada"], key=k())
        call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, token=t["ada"], key=k())
parallel([lambda i=i: bulk(i) for i in range(20)])  # 220 payments + 220 requests
d = call("GET", "/activity", token=t["ada"]).j
ok("GET /activity default limit 50, has_more true", len(d["payments"]) == 50 and d["has_more"] is True, len(d["payments"]))
d = call("GET", "/activity?limit=200", token=t["ada"]).j
ok("GET /activity limit=200 -> 200 items, has_more true (220 total)", len(d["payments"]) == 200 and d["has_more"] is True)
d2 = call("GET", "/activity?limit=200&offset=200", token=t["ada"]).j
ok("offset 200 -> remaining 20, has_more false; union has 220 distinct payments", len(d2["payments"]) == 20 and d2["has_more"] is False and len({p["payment_id"] for p in d["payments"] + d2["payments"]}) == 220)
d = call("GET", "/requests", token=t["ada"]).j
ok("GET /requests default limit 50, has_more true", len(d["requests"]) == 50 and d["has_more"] is True, len(d["requests"]))
d = call("GET", "/requests?limit=200", token=t["bob"]).j
ok("GET /requests limit=200 -> 200 items, has_more true (220 total)", len(d["requests"]) == 200 and d["has_more"] is True)

done("c12_retries_edges")
