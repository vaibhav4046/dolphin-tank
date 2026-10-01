"""B01-B07: fixture matrix for authorizations and authorization_ttl_seconds; reset is atomic."""
import datetime as dt
from lib import *

def iso(delta_s):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

def au(i, frm, to, amount, status="open", delta=7200, **kw):
    d = {"id": i, "from_user_id": frm, "to_user_id": to, "amount": amount, "note": kw.pop("note", "seed"), "visibility": kw.pop("visibility", "public"),
         "status": status, "expires_at": iso(delta)}
    d.update(kw)
    return d

BASE = lambda: fx([user("ada", 10000), user("bob", 2500), user("cy", 0)])
KNOWN = BASE()
KNOWN["authorizations"] = [au("a_known", "u_ada", "u_bob", 1000)]

def known_state():
    reset(KNOWN)
    ta = login("ada@example.com")
    return ta, me(ta), authz(ta)

# ---- omitted ttl => 600; omitted authorizations => empty
f = BASE()
reset(f)
t = {h: login(h + "@example.com") for h in ("ada", "bob", "cy")}
ok("B05 omitted authorizations => empty list", authz(t["ada"])["authorizations"] == [] and me(t["ada"])["held"] == 0)
r = authorize(t["ada"], "bob", 100)
ok("B01 omitted ttl => 600 s", (ts(r.j["expires_at"]) - ts(r.j["created_at"])).total_seconds() == 600, r)
for v, nm in ((1, "1"), (3600, "3600"), (86400, "86400"), (10**9, "1e9")):
    f = BASE(); f["authorization_ttl_seconds"] = v
    r = call("POST", "/_test/reset", f)
    ok("B01 ttl %s accepted (204)" % nm, r.s == 204, r)
    t = {h: login(h + "@example.com") for h in ("ada",)}
    r = authorize(t["ada"], "bob", 100)
    ok("B01 ttl %s -> expires_at = created_at + ttl (RFC3339)" % nm, r.s == 201 and (ts(r.j["expires_at"]) - ts(r.j["created_at"])).total_seconds() == v and RFC3339.match(r.j["expires_at"]), r)
# huge ttl must never 5xx; if accepted the timestamp must stay valid
for v in (10**9 + 1, 2**31, 10**12, 2**53, 10**18, 2**63 - 1, 2**64):
    f = BASE(); f["authorization_ttl_seconds"] = v
    r = call("POST", "/_test/reset", f)
    ok("B01 huge ttl %s: no 5xx on reset (got %s)" % (v, r.s), r.s in (204, 422), r)
    if r.s == 204:
        tk = login("ada@example.com")
        r = authorize(tk, "bob", 100)
        ok("B01 huge ttl %s accepted: authorize no 5xx and valid RFC3339 (got %s)" % (v, r.s), r.s in (201, 422) and (r.s != 201 or RFC3339.match(r.j["expires_at"])), r)

# ---- invalid ttl => 422, state unchanged
for v, nm in ((0, "0"), (-1, "-1"), ("x", "'x'"), ("600", "'600'"), (1.5, "1.5"), (True, "true"), (False, "false"), (None, "null"), ([], "[]"), ({}, "{}"), (0.0, "0.0"), (-600, "-600")):
    ta, m0, a0 = known_state()
    f = BASE(); f["authorization_ttl_seconds"] = v
    f["users"][0]["balance"] = 77
    r = call("POST", "/_test/reset", f)
    ok("B01 ttl %s -> 422 validation_failed" % nm, r.s == 422 and r.code == "validation_failed", r)
    ok("B01 ttl %s: state unchanged (old token, balance, holds)" % nm, me(ta) == m0 and authz(ta) == a0, (me(ta), m0))

# ---- seeded holds: available derived; statuses; sums
f = BASE()
f["authorizations"] = [au("a1", "u_ada", "u_bob", 2000), au("a2", "u_ada", "u_cy", 3000, status="captured", captured_amount=3000),
                       au("a3", "u_ada", "u_bob", 4000, status="voided"), au("a4", "u_ada", "u_bob", 4000, status="expired"),
                       au("a5", "u_ada", "u_bob", 1000, status="open", delta=-7200),  # past expiry: expired, holds nothing
                       au("a6", "u_bob", "u_ada", 500, status="open", delta=7200 * 24)]
f["users"][0]["available"] = 5; f["users"][0]["held"] = 99
reset(f)
ta, tb = login("ada@example.com"), login("bob@example.com")
m = me(ta)
ok("B02 seeded available/held in users ignored; derived: total 10000 held 2000 available 8000", (m["balance"], m["total"], m["held"], m["available"]) == (10000, 10000, 2000, 8000), m)
mb = me(tb)
ok("B04 bob (payer of a6) held 500", (mb["total"], mb["held"], mb["available"]) == (2500, 500, 2000), mb)
L = {a["authorization_id"]: a for a in authz(ta)["authorizations"]}
ok("B04 ids preserved, 6 listed for ada", sorted(L) == ["a1", "a2", "a3", "a4", "a5", "a6"], sorted(L))
ok("B04 statuses read back: open/captured/voided/expired", (L["a1"]["status"], L["a2"]["status"], L["a3"]["status"], L["a4"]["status"]) == ("open", "captured", "voided", "expired"), L)
ok("B06 seeded open with past expires_at reads expired, remaining 0", L["a5"]["status"] == "expired" and L["a5"]["remaining_amount"] == 0, L["a5"])
ok("B04 open seeded remaining == amount", L["a1"]["remaining_amount"] == 2000 and L["a1"]["captured_amount"] == 0, L["a1"])
ok("B04 closed seeded remaining 0", all(L[i]["remaining_amount"] == 0 for i in ("a2", "a3", "a4")), L)
print("INFO seeded captured a2 captured_amount=%s payment_id=%s payment_ids=%s" % (L["a2"]["captured_amount"], L["a2"]["payment_id"], L["a2"].get("payment_ids")))
ok("B06 seeded fields echoed (amount, note, visibility, from/to, currency)", (L["a1"]["amount"], L["a1"]["note"], L["a1"]["visibility"], L["a1"]["from_handle"], L["a1"]["to_handle"], L["a1"]["currency"]) == (2000, "seed", "public", "ada", "bob", "EUR"), L["a1"])
ok("B06 expires_at is RFC3339 with offset", RFC3339.match(L["a1"]["expires_at"]), L["a1"])
ok("B04 status filters on seeded", len(authz(ta, status="open")["authorizations"]) == 2 and len(authz(ta, status="expired")["authorizations"]) == 2, authz(ta, status="expired"))
ok("B04 captured seeded hold cannot be captured again: 409 authorization_not_open", (lambda r: r.s == 409 and r.code == "authorization_not_open")(capture(tb, "a2", amount=1)) or capture(login("cy@example.com"), "a2", amount=1).s == 409)
ok("B04 expired-by-seed hold capture 409 authorization_expired", (lambda r: r.s == 409 and r.code == "authorization_expired")(capture(tb, "a5", amount=1)), capture(tb, "a5", amount=1))
ok("D04 seeded open holds are not in activity", call("GET", "/activity", token=ta).j["payments"] == [])
# seeded open hold is capturable and spends reserved funds; funds blocked by seeded holds
r = capture(tb, "a1", amount=800, final=False)
ok("E03 capture of seeded hold: 201, payment authorization_id a1", r.s == 201 and r.j["authorization_id"] == "a1" and r.j["note"] == "seed", r)
ok("E06 seeded hold remainder 1200", authz(ta, "a1")["remaining_amount"] == 1200 and me(ta)["held"] == 1200 and me(ta)["total"] == 9200)
r = void(ta, "a1")
ok("F01 void seeded hold", r.s == 200 and me(ta)["held"] == 0)
reset(f)
ta = login("ada@example.com")
r = pay(ta, "cy", 8001)
ok("A06 payment above available (seeded hold 2000 of 10000) refused", r.s == 409 and r.code == "insufficient_funds", r)
ok("A02 payment of exactly available (8000) allowed", pay(ta, "cy", 8000).s == 201)

# ---- sum of seeded unexpired open holds vs balance
def hold_fx(balance, holds):
    g = fx([user("ada", balance), user("bob", 0)])
    g["authorizations"] = holds
    return g
for desc, g, exp in (
    ("sum == balance accepted", hold_fx(3000, [au("x1", "u_ada", "u_bob", 1000), au("x2", "u_ada", "u_bob", 2000)]), 204),
    ("sum == balance + 1 rejected", hold_fx(3000, [au("x1", "u_ada", "u_bob", 1000), au("x2", "u_ada", "u_bob", 2001)]), 422),
    ("single hold above balance rejected", hold_fx(100, [au("x1", "u_ada", "u_bob", 101)]), 422),
    ("expired-by-clock open hold above balance accepted (holds nothing)", hold_fx(100, [au("x1", "u_ada", "u_bob", 5000, delta=-7200)]), 204),
    ("voided/captured/expired above balance accepted", hold_fx(100, [au("x1", "u_ada", "u_bob", 5000, status="voided"), au("x2", "u_ada", "u_bob", 5000, status="captured", captured_amount=5000), au("x3", "u_ada", "u_bob", 5000, status="expired")]), 204),
    ("unexpired holds sum above balance but one expired: only unexpired count", hold_fx(1000, [au("x1", "u_ada", "u_bob", 1000), au("x2", "u_ada", "u_bob", 9000, delta=-7200)]), 204),
    ("balance 0, hold 1 rejected", hold_fx(0, [au("x1", "u_ada", "u_bob", 1)]), 422),
):
    ta, m0, a0 = known_state()
    r = call("POST", "/_test/reset", g)
    ok("B03 %s -> %d" % (desc, exp), r.s == exp and (exp == 204 or r.code == "validation_failed"), r)
    if exp == 422:
        ok("B03 %s: state unchanged (old token, holds)" % desc, me(ta) == m0 and authz(ta) == a0)
    else:
        tk = login("ada@example.com"); m = me(tk)
        ok("B03 %s: /me invariants hold, held <= total" % desc, inv(m), m)
# seeded hold per-user sums: two payers independent
g = fx([user("ada", 1000), user("bob", 1000)]); g["authorizations"] = [au("y1", "u_ada", "u_bob", 1000), au("y2", "u_bob", "u_ada", 1000)]
ok("B03 holds of different payers do not pool", call("POST", "/_test/reset", g).s == 204)

# ---- invalid seeded authorization entries must not 5xx and must be atomic
for desc, ent in (("unknown payer", au("z1", "u_nobody", "u_bob", 10)), ("unknown receiver", au("z2", "u_ada", "u_nobody", 10)),
                  ("bad status", au("z3", "u_ada", "u_bob", 10, status="zzz")), ("negative amount", au("z4", "u_ada", "u_bob", -5)),
                  ("string amount", au("z5", "u_ada", "u_bob", "10")), ("bad expires_at", au("z6", "u_ada", "u_bob", 10, expires_at="garbage")),
                  ("payer == receiver", au("z7", "u_ada", "u_ada", 10)), ("duplicate ids", None)):
    ta, m0, a0 = known_state()
    g = hold_fx(1000, [ent] if ent else [au("d1", "u_ada", "u_bob", 10), au("d1", "u_ada", "u_bob", 10)])
    r = call("POST", "/_test/reset", g)
    print("INFO seeded %s -> %s %s" % (desc, r.s, r.code))
    ok("B07 seeded %s: no 5xx; if rejected state is unchanged" % desc, r.s < 500 and (r.s == 204 or (me(ta) == m0 and authz(ta) == a0)), r)
    if r.s == 204:
        pass
# ---- reset clears holds + keys + tokens
f = BASE(); f["authorizations"] = [au("a_x", "u_ada", "u_bob", 500)]
reset(f); ta = login("ada@example.com")
key = k(); authorize(ta, "bob", 100, key=key)
reset(BASE()); ta = login("ada@example.com")
ok("B07 reset clears authorizations", authz(ta)["authorizations"] == [] and me(ta)["held"] == 0)
r = authorize(ta, "bob", 100, key=key)
ok("B07 reset clears idempotency keys (same key is first use again: 201)", r.s == 201, r)
done("s2_fixture")
