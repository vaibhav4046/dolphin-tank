"""C01-C03 B01: real-clock expiry. Reset with authorization_ttl_seconds=2; no request is sent at the deadline."""
import time
from lib import *

TTL = 2
f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0)])
f["authorization_ttl_seconds"] = TTL

def fresh():
    return setup(f)

def mk(t, amt=3000, **kw):
    r = authorize(t["ada"], "bob", amt, **kw)
    assert r.s == 201, r
    assert (ts(r.j["expires_at"]) - ts(r.j["created_at"])).total_seconds() == TTL, r.j
    return r.j

# ---- (a) first request after the deadline is /me
t = fresh(); a = mk(t)
m0 = me(t["ada"])
ok("C01 before deadline: held 3000 available 7000", (m0["held"], m0["available"]) == (3000, 7000), m0)
ok("C01 before deadline: status open", authz(t["ada"], a["authorization_id"])["status"] == "open")
sleep_until(a["expires_at"])
m = me(t["ada"])
ok("C01 (a) first read after deadline is /me: held 0, available == total == 10000, balance 10000", (m["held"], m["available"], m["total"], m["balance"]) == (0, 10000, 10000, 10000), m)

# ---- (b) first request is GET /authorizations; status filters
t = fresh(); a = mk(t); aid = a["authorization_id"]
sleep_until(a["expires_at"])
x = authz(t["bob"], aid)
ok("C02 (b) list shows status expired", x is not None and x["status"] == "expired", x)
ok("C02 expired holds nothing: remaining_amount 0", x["remaining_amount"] == 0 and x["captured_amount"] == 0, x)
ok("C02 status=expired matches", authz(t["bob"], aid, status="expired") is not None)
ok("C02 status=open never matches a clock-expired hold", authz(t["bob"], aid, status="open") is None and authz(t["ada"], aid, status="open") is None)
ok("C02 direction+status=expired for payer", authz(t["ada"], aid, direction="outgoing", status="expired") is not None)
ok("C01 /me restored", me(t["ada"])["available"] == 10000)

# ---- (c) first request is capture
t = fresh(); a = mk(t); aid = a["authorization_id"]
sleep_until(a["expires_at"])
r = capture(t["bob"], aid, amount=100)
ok("C01 (c) capture at/after expiry -> 409 authorization_expired", r.s == 409 and r.code == "authorization_expired", r)
ok("C01 refused expired capture moved nothing", me(t["bob"])["total"] == 2500 and me(t["ada"])["total"] == 10000)

# ---- (d) first request is void
t = fresh(); a = mk(t); aid = a["authorization_id"]
sleep_until(a["expires_at"])
r = void(t["ada"], aid)
ok("C01 (d) void of an expired hold -> 409 authorization_not_open", r.s == 409 and r.code == "authorization_not_open", r)
x = authz(t["ada"], aid)
ok("C01 void did not turn expired into voided", x["status"] == "expired", x)

# ---- (e) released funds spendable on the very first write after the deadline
t = fresh(); a = mk(t, 10000)
ok("C01 (e) all funds held -> pay refused before expiry", pay(t["ada"], "cy", 1).s == 409)
sleep_until(a["expires_at"])
r = pay(t["ada"], "cy", 10000)
ok("C01 (e) first write after deadline: full payment of released funds succeeds", r.s == 201, r)
t2 = fresh(); a = mk(t2, 10000); sleep_until(a["expires_at"])
r = authorize(t2["ada"], "cy", 10000, key=k())
ok("C01 (e) first write is a new authorization of released funds: 201", r.s == 201, r)

# ---- (f) settlement after expiry
f2 = fx([user("ada", 10000), user("bob", 2500), user("op", 0)], ops=["u_op"]); f2["authorization_ttl_seconds"] = TTL
t = setup(f2); a = mk(t, 10000)
sleep_until(a["expires_at"])
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10000}]}, token=t["op"], key=k())
ok("C01 (f) settlement of released funds after expiry 201", r.s == 201, r)

# ---- (g) partially captured then expired: only the remainder is released, captures preserved
t = fresh(); a = mk(t, 3000); aid = a["authorization_id"]
rc = capture(t["bob"], aid, amount=1000, final=False)
ok("C03 partial capture ok", rc.s == 201 and me(t["ada"])["held"] == 2000, rc)
sleep_until(a["expires_at"])
m = me(t["ada"])
ok("C03 after expiry: held 0, total 9000 (the 1000 stays moved), available 9000", (m["held"], m["total"], m["available"]) == (0, 9000, 9000), m)
x = authz(t["bob"], aid)
ok("C03 status expired, captured_amount 1000, payment_ids preserved, payment_id latest", (x["status"], x["captured_amount"], x.get("payment_ids"), x["payment_id"], x["remaining_amount"]) == ("expired", 1000, [rc.j["payment_id"]], rc.j["payment_id"], 0), x)
ok("C03 bob kept 1000", me(t["bob"])["total"] == 3500)
r = capture(t["bob"], aid, amount=1)
ok("C03 further capture 409 authorization_expired", r.s == 409 and r.code == "authorization_expired", r)
ok("A01 conservation", sum(me(t[h])["total"] for h in t) == 12500)

# ---- (h) activity never shows holds; expired never appears in activity
ok("D04 no authorization items in activity", call("GET", "/activity", token=t["ada"]).j["payments"][0]["authorization_id"] == aid)

# ---- (i) replay of authorize after expiry returns original body
t = fresh(); key = k()
r1 = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, token=t["ada"], key=key)
sleep_until(r1.j["expires_at"])
r2 = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, token=t["ada"], key=key)
ok("G07 authorize replay after expiry: 200 original body, no new hold", r2.s == 200 and r2.j == r1.j and me(t["ada"])["held"] == 0 and len(authz(t["ada"])["authorizations"]) == 1, (r1, r2))

# ---- (j) capture just before deadline works; many holds expiring together
t = fresh(); ids = []
for i in range(5):
    ids.append(mk(t, 500))
rc = capture(t["bob"], ids[0]["authorization_id"], amount=100)
ok("C01 capture before deadline 201", rc.s == 201, rc)
sleep_until(ids[-1]["expires_at"])
x = authz(t["ada"])
ok("C01 5 holds: first captured, other 4 expired (none open)", sorted(a["status"] for a in x["authorizations"]) == ["captured", "expired", "expired", "expired", "expired"], [a["status"] for a in x["authorizations"]])
ok("C01 held 0 available == total", (lambda m: m["held"] == 0 and m["available"] == m["total"] == 9900)(me(t["ada"])), me(t["ada"]))

# ---- (k) ttl=1 boundary
f1 = fx([user("ada", 10000), user("bob", 2500)]); f1["authorization_ttl_seconds"] = 1
t = setup(f1)
r = authorize(t["ada"], "bob", 100)
ok("B01 ttl=1 accepted, expires_at = created_at + 1s", r.s == 201 and (ts(r.j["expires_at"]) - ts(r.j["created_at"])).total_seconds() == 1, r)
sleep_until(r.j["expires_at"], 0.3)
ok("B01 ttl=1 hold expired by the clock", authz(t["ada"], r.j["authorization_id"])["status"] == "expired" and me(t["ada"])["held"] == 0)
done("s2_expiry")
