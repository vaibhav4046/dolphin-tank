"""A01 A03 A04 A05 D01 D02 D04 D05 E03-E08 F01 C04: authorization lifecycle, /me shape, capture payment shape."""
from lib import *

t = setup(fx([user("ada", 10000), user("bob", 2500), user("cy", 0), user("dee", 5000)]))
TOTAL = 17500


def totals():
    return sum(me(t[h])["total"] for h in t)


# ---- /me with no holds
m = me(t["ada"])
ok("A04 /me keys with no holds", {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"} <= set(m), m)
ok("A04 no holds: balance==total==available, held 0", m["balance"] == m["total"] == m["available"] == 10000 and m["held"] == 0, m)

# ---- authorize
r = authorize(t["ada"], "bob", 2000, note="deposit", vis="private")
ok("D01 authorize 201", r.s == 201, r)
a = r.j
for f in ("authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount",
          "currency", "note", "visibility", "status", "expires_at", "payment_id", "created_at", "remaining_amount"):
    ok("D01 field present: " + f, f in a, a)
ok("D01 values", (a["from_user_id"], a["from_handle"], a["to_user_id"], a["to_handle"], a["amount"], a["captured_amount"], a["currency"],
                  a["note"], a["visibility"], a["status"], a["payment_id"], a["remaining_amount"]) ==
   ("u_ada", "ada", "u_bob", "bob", 2000, 0, "EUR", "deposit", "private", "open", None, 2000), a)
ok("C04 expires_at = created_at + 600s", (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600, (a["created_at"], a["expires_at"]))
ok("C04 timestamps RFC3339 with offset", RFC3339.match(a["created_at"]) and RFC3339.match(a["expires_at"]), a)
ok("D01 payment_ids empty or absent at creation", a.get("payment_ids", []) == [], a)
aid = a["authorization_id"]
m = me(t["ada"])
ok("D05 ada: total 10000 available 8000 held 2000 balance 10000", (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 8000, 2000), m)
mb = me(t["bob"])
ok("A01 bob untouched by hold", (mb["total"], mb["available"], mb["held"]) == (2500, 2500, 0), mb)
ok("A01 conservation after authorize", totals() == TOTAL)
for h in ("ada", "bob", "cy"):
    feed = call("GET", "/activity?limit=200", token=t[h]).j["payments"]
    ok("D04 open authorization not in activity for " + h, feed == [], feed)
ok("D04 GET /authorizations lists it for payer and receiver, not stranger",
   authz(t["ada"], aid) is not None and authz(t["bob"], aid) is not None and authz(t["cy"], aid) is None)

# ---- default (final) partial capture releases remainder
r = capture(t["bob"], aid, amount=1500)
ok("E03 capture 201", r.s == 201, r)
p = r.j
for f in ("payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "created_at", "authorization_id"):
    ok("E03 payment field present: " + f, f in p, p)
ok("E03 payment shape values", (p["from_handle"], p["to_handle"], p["amount"], p["currency"], p["note"], p["visibility"], p["request_id"], p["authorization_id"]) ==
   ("ada", "bob", 1500, "EUR", "deposit", "private", None, aid), p)
ok("E04 remainder released in same step: ada total 8500 available 8500 held 0", (lambda m: (m["total"], m["available"], m["held"], m["balance"]) == (8500, 8500, 0, 8500))(me(t["ada"])), me(t["ada"]))
ok("E04 bob received 1500", me(t["bob"])["total"] == 4000)
a2 = authz(t["bob"], aid)
ok("E04 authorization captured, captured_amount 1500, payment_id", (a2["status"], a2["captured_amount"], a2["payment_id"], a2["remaining_amount"]) == ("captured", 1500, p["payment_id"], 0), a2)
ok("E07 payment_ids lists capture", a2.get("payment_ids") == [p["payment_id"]], a2)
ok("A01 conservation after capture", totals() == TOTAL)
fa = call("GET", "/activity?limit=200", token=t["ada"]).j["payments"]
fb = call("GET", "/activity?limit=200", token=t["bob"]).j["payments"]
fc = call("GET", "/activity?limit=200", token=t["cy"]).j["payments"]
ok("E03 private capture visible to payer and receiver, hidden from stranger",
   any(x["payment_id"] == p["payment_id"] for x in fa) and any(x["payment_id"] == p["payment_id"] for x in fb) and not fc, (fa, fb, fc))
ok("E03 feed copy of payment has authorization_id", [x for x in fa if x["payment_id"] == p["payment_id"]][0].get("authorization_id") == aid)
r = capture(t["bob"], aid, amount=1)
ok("E05 second capture after final: 409 authorization_not_open", r.s == 409 and r.code == "authorization_not_open", r)
r = capture(t["bob"], aid)
ok("E05 second capture default amount: 409 authorization_not_open", r.s == 409 and r.code == "authorization_not_open", r)
ok("F01 void captured: 409 authorization_not_open", (lambda r: r.s == 409 and r.code == "authorization_not_open")(void(t["ada"], aid)))

# ---- public default + full capture default amount
r = authorize(t["ada"], "cy", 1000)
ok("D02 defaults note '' and visibility public", r.s == 201 and r.j["note"] == "" and r.j["visibility"] == "public", r)
aid2 = r.j["authorization_id"]
r = capture(t["cy"], aid2)
ok("E04 default amount captures remaining", r.s == 201 and r.j["amount"] == 1000 and r.j["visibility"] == "public", r)
ok("E03 public capture visible to stranger", any(x["payment_id"] == r.j["payment_id"] for x in call("GET", "/activity?limit=200", token=t["dee"]).j["payments"]))
ok("A01 conservation", totals() == TOTAL)

# ---- extended capture mode
r = authorize(t["ada"], "bob", 3000, note="ext", vis="public")
aid3 = r.j["authorization_id"]
base_ada = me(t["ada"])["total"]
r1 = capture(t["bob"], aid3, amount=700, final=False)
ok("E06 capture 700 final:false 201", r1.s == 201 and r1.j["amount"] == 700, r1)
x = authz(t["bob"], aid3)
ok("E06 stays open, captured 700, remaining 2300", (x["status"], x["captured_amount"], x["remaining_amount"], x["payment_id"]) == ("open", 700, 2300, r1.j["payment_id"]), x)
m = me(t["ada"])
ok("E06 ada total -700, held 2300, available = total - held", (m["total"], m["held"], m["available"]) == (base_ada - 700, 2300, base_ada - 700 - 2300), m)
r2 = capture(t["bob"], aid3, amount=1000, final=False)
ok("E06 second extended capture", r2.s == 201 and r2.j["amount"] == 1000, r2)
x = authz(t["bob"], aid3)
ok("E07 captured_amount cumulative, payment_id latest, payment_ids ordered",
   (x["captured_amount"], x["payment_id"], x.get("payment_ids")) == (1700, r2.j["payment_id"], [r1.j["payment_id"], r2.j["payment_id"]]), x)
r = capture(t["bob"], aid3, amount=1301, final=False)
ok("E07 exceeds REMAINING (1300) -> 422 capture_exceeds_authorization", r.s == 422 and r.code == "capture_exceeds_authorization", r)
ok("E07 refused capture changed nothing", authz(t["bob"], aid3)["captured_amount"] == 1700)
r3 = capture(t["bob"], aid3, final=False)
ok("E06 omitted amount with final:false = whole remainder; closes", r3.s == 201 and r3.j["amount"] == 1300, r3)
x = authz(t["bob"], aid3)
ok("E06 whole remainder closes even with final:false", (x["status"], x["captured_amount"], x["remaining_amount"], len(x.get("payment_ids", []))) == ("captured", 3000, 0, 3), x)
m = me(t["ada"])
ok("E06 hold gone: held 0", m["held"] == 0 and m["available"] == m["total"] == base_ada - 3000, m)
r = capture(t["bob"], aid3, amount=1, final=False)
ok("E05 closed hold cannot be captured", r.s == 409 and r.code == "authorization_not_open", r)

# explicit whole remainder amount with final:false
r = authorize(t["ada"], "bob", 1000)
aid4 = r.j["authorization_id"]
r = capture(t["bob"], aid4, amount=1000, final=False)
x = authz(t["bob"], aid4)
ok("E06 amount == whole remainder, final:false closes", r.s == 201 and x["status"] == "captured" and x["remaining_amount"] == 0, (r, x))

# final capture of extended releases remainder
r = authorize(t["ada"], "bob", 2000)
aid5 = r.j["authorization_id"]
capture(t["bob"], aid5, amount=500, final=False)
held_mid = me(t["ada"])["held"]
r = capture(t["bob"], aid5, amount=300)  # final default true
x = authz(t["bob"], aid5)
ok("E06 final capture closes and releases remainder", held_mid == 1500 and r.s == 201 and x["status"] == "captured" and x["captured_amount"] == 800 and x["remaining_amount"] == 0 and me(t["ada"])["held"] == 0, (held_mid, r, x))
ok("E07 final capture shows payment_ids length 2", len(x.get("payment_ids", [])) == 2, x)

# explicit final:true
r = authorize(t["ada"], "bob", 1000)
aid6 = r.j["authorization_id"]
r = capture(t["bob"], aid6, amount=400, final=True)
ok("E06 explicit final:true releases", r.s == 201 and me(t["ada"])["held"] == 0 and authz(t["bob"], aid6)["status"] == "captured")

# ---- void after partial capture
r = authorize(t["ada"], "bob", 2000, note="v")
aid7 = r.j["authorization_id"]
rc = capture(t["bob"], aid7, amount=500, final=False)
pre = me(t["ada"])
rv = void(t["ada"], aid7)
ok("F01 void 200 voided", rv.s == 200 and rv.j["status"] == "voided", rv)
ok("E08 void releases only remainder, preserves captures", (rv.j["captured_amount"], rv.j["remaining_amount"], rv.j.get("payment_ids"), rv.j["payment_id"]) == (500, 0, [rc.j["payment_id"]], rc.j["payment_id"]), rv.j)
m = me(t["ada"])
ok("E08 ada: held 0; total unchanged by void (500 already moved)", m["held"] == 0 and m["total"] == pre["total"] and m["available"] == pre["total"], (pre, m))
rv2 = void(t["ada"], aid7)
ok("F01 void twice: 200 current state", rv2.s == 200 and rv2.j == rv.j, rv2)
r = capture(t["bob"], aid7, amount=1)
ok("E05 capture after void: 409 authorization_not_open", r.s == 409 and r.code == "authorization_not_open", r)
ok("A01 conservation", totals() == TOTAL)

# plain void no capture
r = authorize(t["ada"], "bob", 1500)
aid8 = r.j["authorization_id"]
ok("D05 held 1500", me(t["ada"])["held"] == 1500)
rv = void(t["ada"], aid8)
ok("F01 void plain: released, captured_amount 0, payment_id null", rv.s == 200 and rv.j["captured_amount"] == 0 and rv.j["payment_id"] is None and rv.j["remaining_amount"] == 0 and me(t["ada"])["held"] == 0, rv)

# ---- payments elsewhere carry authorization_id null
p1 = pay(t["ada"], "bob", 100)
ok("E03 plain payment authorization_id null, request_id null, no hold", p1.s == 201 and p1.j.get("authorization_id", "MISSING") is None and p1.j["request_id"] is None and me(t["ada"])["held"] == 0, p1)
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=t["bob"], key=k())
pr = call("POST", "/requests/%s/pay" % rq.j["request_id"], {}, token=t["ada"], key=k())
ok("E03 request-pay payment authorization_id null, request_id set", pr.s == 201 and pr.j.get("authorization_id", "MISSING") is None and pr.j["request_id"] == rq.j["request_id"], pr)
done("s2_lifecycle")
