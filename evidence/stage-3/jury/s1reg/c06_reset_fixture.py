"""J11, J26-J29, J17: reset semantics, fixtures (JPY/BHD), negative balance rejection with state intact, id collision, reset under load."""
import threading, time
from lib import *

# ---- currencies
for cur, mu, pay_amt in (("JPY", 0, 1000), ("BHD", 3, 1500), ("EUR", 2, 1500)):
    t = setup(fx([user("ada", 100000), user("bob", 5), user("cy", 0), user("dee", 0)], currency=cur, mu=mu))
    m = me(t["ada"])
    ok("%s fixture: /me currency/minor_units/balance" % cur, m["currency"] == cur and m["minor_units"] == mu and m["balance"] == 100000, m)
    p = call("POST", "/payments", {"to_handle": "bob", "amount": pay_amt}, token=t["ada"], key=k())
    ok("%s payment carries currency, balances exact" % cur, p.s == 201 and p.j["currency"] == cur and (bal(t["ada"]), bal(t["bob"])) == (100000 - pay_amt, 5 + pay_amt), p)
    rq = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=t["ada"], key=k())
    sp = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, token=t["ada"], key=k())
    ok("%s request/split carry currency" % cur, rq.j["currency"] == cur and sp.j["currency"] == cur, (rq, sp))

# ---- negative balance: 422 and state intact (tokens, balances, payments, idempotency)
t = setup(fx())
K = k()
p = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=t["ada"], key=K)
snap = (bal(t["ada"]), bal(t["bob"]), call("GET", "/activity", token=t["ada"]).b)
bad = fx([user("ada", 10), user("bob", -1)])
r = call("POST", "/_test/reset", bad)
ok("reset with negative balance -> 422 validation_failed", r.s == 422 and r.code == "validation_failed", r)
ok("  state intact: old tokens valid, balances, feed identical", (bal(t["ada"]), bal(t["bob"]), call("GET", "/activity", token=t["ada"]).b) == snap)
ok("  idempotency record intact: replay -> 200 original", call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=t["ada"], key=K).j == p.j)
ok("  old user handles/login still work (ada 'correct horse')", call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).s == 200)
for nm, f in (("minor_units 1", fx(mu=1)), ("minor_units 4", fx(mu=4)), ("duplicate handle", fx([user("ada", 1), user("ada2", 1, uid="u_x")]))):
    if nm == "duplicate handle":
        f["users"][1]["handle"] = "ada"
    r = call("POST", "/_test/reset", f)
    print("OBS reset %s -> %s %s" % (nm, r.s, r.code))
    ok("reset %s -> 4xx (not 5xx/204)" % nm, r.s in (400, 422), r)
ok("reset: invalid JSON -> 400 malformed_request", (lambda r: r.s == 400 and r.code == "malformed_request")(call("POST", "/_test/reset", raw="{bad")))
ok("state still intact after all rejected resets", (bal(t["ada"]), bal(t["bob"])) == snap[:2])
r = call("POST", "/_test/reset", fx())
ok("reset 204, empty body, no auth needed", r.s == 204 and r.b == b"", r)

# ---- reset clears everything incl. signups, tokens, idempotency
t = setup(fx())
s = call("POST", "/auth/signup", {"email": "newbie@x.com", "password": "password1", "display_name": "N"})
K = k()
r1 = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=t["ada"], key=K)
call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=t["bob"], key=k())
reset(fx())
ok("reset: old tokens 401", call("GET", "/me", token=t["ada"]).s == 401 and call("GET", "/me", token=s.j["token"]).s == 401)
ok("reset: signup-created user gone (login 401), handle/email reusable", call("POST", "/auth/login", {"email": "newbie@x.com", "password": "password1"}).s == 401
   and call("POST", "/auth/signup", {"email": "newbie@x.com", "password": "password1", "display_name": "N"}).s == 201)
t = {u["handle"]: login(u["email"]) for u in fx()["users"]}
ok("reset: seeded balances restored, no payments/requests", bal(t["ada"]) == 10000 and call("GET", "/activity", token=t["ada"]).j["payments"] == [] and call("GET", "/requests", token=t["ada"]).j["requests"] == [])
r2 = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=t["ada"], key=K)
ok("reset: idempotency keys cleared (same key+body -> 201 not 200)", r2.s == 201 and bal(t["ada"]) == 9900, r2)
ok("reset: ids restart or at least differ from nothing; first payment id is a <=64 char string", isinstance(r2.j["payment_id"], str) and 0 < len(r2.j["payment_id"]) <= 64)

# ---- seeded users, requests in all statuses, ids, collisions
ff = fx(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                  {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "", "visibility": "private"}],
        requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                  {"id": "rq_7", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 1, "note": "d", "status": "declined"},
                  {"id": "rq_9", "requester_id": "u_dee", "payer_id": "u_ada", "amount": 2, "note": "c", "status": "cancelled"}])
t = setup(ff)
ok("fixture: seeded users log in with their password; wrong password 401", all(call("POST", "/auth/login", {"email": u["email"], "password": u["password"]}).s == 200 for u in ff["users"])
   and call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong horse"}).s == 401)
ok("fixture: balances are as given (not replayed against payments)", [bal(t[h]) for h in ("ada", "bob", "cy", "dee")] == [10000, 2500, 0, 5000])
got = {x["request_id"]: x for x in call("GET", "/requests?limit=200", token=t["ada"]).j["requests"]}
ok("fixture: requests with ids/status/amount/note preserved", {i: (x["status"], x["amount"], x["note"]) for i, x in got.items()} == {"rq_1": ("pending", 1200, "taxi"), "rq_7": ("declined", 1, "d"), "rq_9": ("cancelled", 2, "c")}, got)
ok("fixture: request fields resolve handles and timestamps", got["rq_1"]["requester_handle"] == "bob" and got["rq_1"]["payer_handle"] == "ada" and bool(RFC3339.match(got["rq_1"]["created_at"])), got["rq_1"])
ok("fixture: seeded pending request payable by ada", call("POST", "/requests/rq_1/pay", {}, token=t["ada"], key=k()).s == 201 and bal(t["ada"]) == 8800)
seed_ids = {"p_1", "p_3"}
news = [call("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=t["dee"], key=k()).j["payment_id"] for _ in range(6)]
ok("new payment ids never collide with seeded ids or each other", len(set(news)) == 6 and not (set(news) & seed_ids) and all("p_1" != n and "p_3" != n for n in news), news)
pf = [x["payment_id"] for x in call("GET", "/activity?limit=200", token=t["cy"]).j["payments"]]
ok("every payment in cy's feed has a distinct id", len(pf) == len(set(pf)), pf)
newr = [call("POST", "/requests", {"payer_handle": "cy", "amount": 1}, token=t["dee"], key=k()).j["request_id"] for _ in range(6)]
ok("new request ids never collide with seeded (rq_1, rq_7, rq_9) or each other", len(set(newr)) == 6 and not (set(newr) & {"rq_1", "rq_7", "rq_9"}), newr)
suid = call("POST", "/auth/signup", {"email": "zzz@x.com", "password": "password1", "display_name": "Z"}).j["user_id"]
ok("signup user_id distinct from seeded ids", suid not in {u["id"] for u in ff["users"]} and len(suid) <= 64, suid)

# ---- scale / timing of reset (10 s limit) and repeated resets
for n, distinct in ((300, True), (1000, False)):
    us = [user("u%d" % i, 100, pw=("pw%06d" % i if distinct else "correct horse")) for i in range(n)]
    t0 = time.time()
    r = call("POST", "/_test/reset", fx(us), timeout=30)
    dt = time.time() - t0
    ok("reset with %d users (%s passwords) -> 204 in %.2fs (<10s)" % (n, "distinct" if distinct else "identical", dt), r.s == 204 and dt < 10, (r.s, dt))
    ok("  last user can log in", call("POST", "/auth/login", {"email": us[-1]["email"], "password": us[-1]["password"]}).s == 200)
t0 = time.time()
for i in range(20):
    reset(fx())
ok("20 repeated resets (%.2fs)" % (time.time() - t0), True)

# ---- reset under concurrent load: no 5xx; final state exactly the fixture
stop = threading.Event()
odd = []


def hammer(i):
    tok = None
    while not stop.is_set():
        if tok is None:
            r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
            tok = r.j.get("token") if r.s == 200 else None
            continue
        r = call("GET", "/me", token=tok)
        if r.s == 200 and r.j is None:
            odd.append("200 null")
        elif r.s not in (200, 401):
            odd.append(r.s)
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=tok, key=k())
        if r.s not in (201, 401, 404, 409):
            odd.append(("pay", r.s, r.code))
        if r.s == 401:
            tok = None


ths = [threading.Thread(target=hammer, args=(i,)) for i in range(12)]
[x.start() for x in ths]
for i in range(8):
    reset(fx())
    time.sleep(0.05)
stop.set(); [x.join() for x in ths]
t = setup(fx())
ok("reset under load: no 5xx, no unexpected statuses", not [o for o in odd if o != "200 null"], odd[:5])
print("OBS /me 200-null observations during concurrent reset:", odd.count("200 null"))
ok("after final reset: state is exactly the fixture", [bal(t[h]) for h in ("ada", "bob", "cy", "dee")] == [10000, 2500, 0, 5000] and call("GET", "/activity", token=t["ada"]).j["payments"] == [])

done("c06_reset_fixture")
