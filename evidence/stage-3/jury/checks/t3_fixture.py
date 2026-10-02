"""J03 J04 J05 J18 J19: seeded payments with created_at, balance preserved, future ts refused, opening balances, corrections vs opening."""
import time
from lib3 import *

NOW = dt.datetime.now(UTC)


def seeded(i, frm, to, amt, ago_s=None, ts=None, note="", vis="public"):
    d = {"id": "p_s%d" % i, "from_user_id": frm, "to_user_id": to, "amount": amt, "note": note, "visibility": vis}
    if ago_s is not None:
        d["created_at"] = iso(NOW - dt.timedelta(seconds=ago_s))
    if ts is not None:
        d["created_at"] = ts
    return d


# opening ada 10000, bob 2500, cy 0; seeded (listed OUT of time order): ada->bob 500 (3h ago), bob->cy 200 (2h ago), ada->cy 100 (1h ago)
SP = [seeded(3, "u_ada", "u_cy", 100, 3600, note="third", vis="private"),
      seeded(1, "u_ada", "u_bob", 500, 10800, note="first"),
      seeded(2, "u_bob", "u_cy", 200, 7200, note="second")]
f = fx([user("ada", 9400), user("bob", 2800), user("cy", 300), user("dee", 5000)], payments=SP)
t = setup(f)
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
TOTAL = 9400 + 2800 + 300 + 5000

# J05 balance unchanged by loading
ok("J05 /me balance == fixture balance for every user (seeded payments not replayed against balances)",
   [me(t[h])["balance"] for h in ("ada", "bob", "cy", "dee")] == [9400, 2800, 300, 5000], [me(t[h]) for h in t])
ok("J05 total/available == balance, held 0", all(me(t[h])["total"] == me(t[h])["balance"] == me(t[h])["available"] and me(t[h])["held"] == 0 for h in t))

# J03 supplied created_at honoured; activity order by created_at regardless of array order
act = call("GET", "/activity", token=A)
ids = [p["payment_id"] for p in act.j["payments"]]
ok("J03 activity returns seeded payments newest first by supplied created_at (not array order)", ids[:3] == ["p_s3", "p_s2", "p_s1"] or ids[:3] == ["p_s3", "p_s2", "p_s1"][::1], ids)
for sp in SP:
    got = [p for p in act.j["payments"] if p["payment_id"] == sp["id"]]
    ok("J03 seeded %s created_at equals supplied instant" % sp["id"], got and P(got[0]["created_at"]) == P(sp["created_at"]) and RFC3339.match(got[0]["created_at"]), got)

# J18 revision 1 of a seeded payment
rv = revs(A, "p_s1")
ok("J18 seeded p_s1 revision 1: amount 500, effective_at == recorded_at == created_at (supplied), reason ''",
   len(rv) == 1 and rv[0]["revision"] == 1 and rv[0]["amount"] == 500 and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(SP[1]["created_at"]) and rv[0]["reason"] == "", rv)

# opening balances: ada 10000 (9400+500+100), bob 2500 (2800-500+200), cy 0 (300-200-100)
OPEN = {"ada": 10000, "bob": 2500, "cy": 0, "dee": 5000}
t0 = P(SP[1]["created_at"])
for h, ob in OPEN.items():
    r = me_at(t[h], iso(t0 - dt.timedelta(seconds=1)))
    ok("J19 as_of before earliest seeded payment returns derived opening for %s (%d)" % (h, ob), r.s == 200 and r.j["balance"] == ob, r)
    s = stmt(t[h])
    ok("J19 statement opening_balance for %s == derived opening %d; closing == current" % (h, ob), s.s == 200 and s.j["opening_balance"] == ob and s.j["closing_balance"] == me(t[h])["balance"], s)
    ok("J19 statement opening + deltas == closing for %s" % h, s.j["opening_balance"] + sum(e["delta"] for e in s.j["entries"]) == s.j["closing_balance"])
# as_of at each seeded instant
for i, (sp, exp) in enumerate([(SP[1], {"ada": 9500, "bob": 3000, "cy": 0, "dee": 5000}), (SP[2], {"ada": 9500, "bob": 2800, "cy": 200, "dee": 5000}), (SP[0], {"ada": 9400, "bob": 2800, "cy": 300, "dee": 5000})]):
    for h in OPEN:
        r = me_at(t[h], sp["created_at"])
        ok("J08 seeded as_of exactly at %s for %s = %d" % (sp["id"], h, exp[h]), r.s == 200 and r.j["balance"] == exp[h], r)
    ok("J29 sum constant at %s" % sp["id"], sum(me_at(t[h], sp["created_at"]).j["balance"] for h in OPEN) == TOTAL)

# private seeded payment visible in statement for both parties, not for dee
sa = stmt(A).j
sd = stmt(D).j
ok("J17 private seeded payment appears in sender's and receiver's statement", any(e["payment"]["payment_id"] == "p_s3" for e in sa["entries"]) and any(e["payment"]["payment_id"] == "p_s3" for e in stmt(C).j["entries"]))
ok("J17 third party's statement has none of them (dee untouched)", sd["entries"] == [] and sd["opening_balance"] == 5000 == sd["closing_balance"], sd)
ok("J17 statement oldest first", [e["payment"]["payment_id"] for e in sa["entries"]] == ["p_s1", "p_s3"], [e["payment"]["payment_id"] for e in sa["entries"]])

# J18/J19 corrections never change opening balance
c = correct(A, "p_s1", 1, 800, SP[1]["created_at"], "bigger")
ok("J19 correct seeded payment 500 -> 800 at its original instant: 201", c.s == 201, c)
ok("J19 corrections do not change the opening balance (statement + far-past as_of)", stmt(A).j["opening_balance"] == 10000 and me_at(A, "1970-01-01T00:00:00Z").j["balance"] == 10000)
ok("J19 current balance moved by the 300 difference only", me(A)["balance"] == 9400 - 300 and me(B)["balance"] == 2800 + 300)
ok("J29 current sum constant after correction", sum(me(t[h])["balance"] for h in t) == TOTAL)

# J19 new accounts open at zero
r = call("POST", "/auth/signup", {"email": "new.user@example.com", "password": "correct horse", "display_name": "New"})
tn = r.j["token"]
ok("J19 new account opens at zero: statement opening 0, far-past as_of 0", stmt(tn).j["opening_balance"] == 0 and me_at(tn, "1970-01-01T00:00:00Z").j["balance"] == 0)
p = pay(A, "new_user", 50)
ok("J19 new account after receiving: current 50, as_of before payment 0", p.s == 201 and me(tn)["balance"] == 50 and me_at(tn, iso(P(p.j["created_at"]) - US)).j["balance"] == 0)

# J03 omitted created_at = reset time, before subsequent API payments
f2 = fx([user("ada", 10000), user("bob", 2500)], payments=[{"id": "p_o1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public"},
                                                          {"id": "p_o2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 50, "note": "", "visibility": "private"}])
t2 = setup(f2)
api = pay(t2["ada"], "bob", 10)
a2 = call("GET", "/activity", token=t2["ada"]).j["payments"]
byid = {p["payment_id"]: p for p in a2}
ok("J03 omitted created_at: seeded payments carry a created_at <= first API payment", all(RFC3339.match(byid[i]["created_at"]) and P(byid[i]["created_at"]) <= P(api.j["created_at"]) for i in ("p_o1", "p_o2")), a2)
ok("J03 omitted created_at is the reset instant (within 5 s of the API payment)", all((P(api.j["created_at"]) - P(byid[i]["created_at"])).total_seconds() < 5 for i in ("p_o1", "p_o2")))
ok("J03 both omitted seeded payments share the reset time", P(byid["p_o1"]["created_at"]) == P(byid["p_o2"]["created_at"]), byid)
rv = revs(t2["ada"], "p_o1")
ok("J18 omitted: revision 1 effective_at == recorded_at == created_at == reset time", P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(byid["p_o1"]["created_at"]), rv)
ok("J03 API payment strictly after seeded in statement order and activity newest-first", [e["payment"]["payment_id"] for e in stmt(t2["ada"]).j["entries"]][-1] == api.j["payment_id"] and a2[0]["payment_id"] == api.j["payment_id"])
ok("J05 balances after omit-ts seeded + 1 API payment: fixture 10000 - 10 API = 9990", me(t2["ada"])["balance"] == 9990 and me_at(t2["ada"], "1970-01-01T00:00:00Z").j["balance"] == 10000 - 50 + 100)

# J03 non-UTC offset accepted
off = (NOW - dt.timedelta(hours=1)).astimezone(dt.timezone(dt.timedelta(hours=-5))).isoformat(timespec="seconds")
f3 = fx([user("ada", 10000), user("bob", 2500)], payments=[{"id": "p_z", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public", "created_at": off}])
r = call("POST", "/_test/reset", f3)
ok("J03 seeded created_at with -05:00 offset accepted", r.s == 204, r)
tz = {h: login(h + "@example.com") for h in ("ada", "bob")}
a = call("GET", "/activity", token=tz["ada"]).j["payments"]
ok("J03 offset created_at preserved as the same instant", P(a[0]["created_at"]) == P(off) and RFC3339.match(a[0]["created_at"]), (a, off))

# J04 future seeded created_at -> 422, state unchanged
reset(f)  # known state again (ada etc.)
tA = login("ada@example.com")
before = (me(tA), call("GET", "/activity", token=tA).j, stmt(tA).j["entries"])
for label, ts_ in [("+1h", iso(NOW + dt.timedelta(hours=1))), ("+1day", iso(NOW + dt.timedelta(days=1))), ("+1y", iso(NOW + dt.timedelta(days=365))), ("9999", "9999-12-31T23:59:59Z"), ("+30s", iso(dt.datetime.now(UTC) + dt.timedelta(seconds=30)))]:
    bad = fx([user("ada", 777), user("zed", 5)], payments=[{"id": "p_f", "from_user_id": "u_ada", "to_user_id": "u_zed", "amount": 1, "created_at": ts_}])
    r = call("POST", "/_test/reset", bad)
    ok("J04 future seeded created_at (%s) -> 422 validation_failed" % label, r.s == 422 and r.code == "validation_failed", r)
    after = (me(tA), call("GET", "/activity", token=tA).j, stmt(tA).j["entries"])
    ok("J04 %s: state unchanged (old users, tokens, balance, feed, statement)" % label, after == before and call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}).s == 401)
# one future among several valid seeded payments also refuses the whole fixture
bad = fx([user("ada", 777), user("zed", 5)], payments=[{"id": "p_g", "from_user_id": "u_ada", "to_user_id": "u_zed", "amount": 1, "created_at": iso(NOW - dt.timedelta(hours=2))}, {"id": "p_f", "from_user_id": "u_zed", "to_user_id": "u_ada", "amount": 1, "created_at": iso(NOW + dt.timedelta(days=2))}])
r = call("POST", "/_test/reset", bad)
ok("J04 mixed valid+future seeded -> 422 and nothing applied", r.s == 422 and me(tA) == before[0] and call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}).s == 401, r)
# a recent past instant is accepted
ok_f = fx([user("ada", 10000), user("zed", 5)], payments=[{"id": "p_p", "from_user_id": "u_ada", "to_user_id": "u_zed", "amount": 1, "created_at": iso(dt.datetime.now(UTC) - dt.timedelta(seconds=2))}])
ok("J04 recent past (now-2s) accepted", call("POST", "/_test/reset", ok_f).s == 204)
# malformed created_at: refused without 5xx and without changing state
reset(f); tA = login("ada@example.com"); before = me(tA)
for label, v in [("garbage", "garbage"), ("naive", "2026-01-01T00:00:00"), ("number", 123), ("empty", ""), ("null", None)]:
    bad = fx([user("ada", 777), user("zed", 5)], payments=[{"id": "p_m", "from_user_id": "u_ada", "to_user_id": "u_zed", "amount": 1, "created_at": v}])
    r = call("POST", "/_test/reset", bad)
    if r.s == 204:
        INFO = "INFO malformed created_at %s ACCEPTED (204) - spec only names future" % label
        print(INFO)
        reset(f); tA = login("ada@example.com")
    else:
        ok("J04 malformed created_at %s: 4xx validation, state unchanged" % label, r.s in (400, 422) and me(tA) == before, r)
done("t3_fixture")
