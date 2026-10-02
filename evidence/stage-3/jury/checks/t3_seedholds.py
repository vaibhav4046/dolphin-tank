"""J49 seeded holds in history + correction/authorize race at the available boundary."""
import time
from lib3 import *

now = lambda: dt.datetime.now(UTC)
T0 = now()
f = fx([user("ada", 10000), user("bob", 2000), user("cy", 0)])
f["authorizations"] = [
    {"id": "a_open_noct", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 3000, "note": "n", "visibility": "public", "status": "open", "expires_at": iso(T0 + dt.timedelta(hours=3))},
    {"id": "a_open_ct", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 1000, "note": "", "visibility": "private", "status": "open", "created_at": iso(T0 - dt.timedelta(hours=2)), "expires_at": iso(T0 + dt.timedelta(hours=2))},
    {"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "", "visibility": "public", "status": "captured", "captured_amount": 500, "expires_at": iso(T0 + dt.timedelta(hours=5))},
    {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "", "visibility": "public", "status": "voided", "expires_at": iso(T0 + dt.timedelta(hours=5))},
    {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "note": "", "visibility": "public", "status": "expired", "expires_at": iso(T0 - dt.timedelta(hours=5))},
]
t = setup(f)
A, B, C = t["ada"], t["bob"], t["cy"]
TOTAL = 12000
m = me(A)
ok("J49 current: ada held 4000 (two seeded open holds), available 6000, total 10000; closed seeded ones hold nothing", (m["total"], m["held"], m["available"]) == (10000, 4000, 6000), m)
vok = lambda name, tok, as_of, exp: ok(name, (lambda v: v == exp)(tuple(me_at(tok, as_of).j[k_] for k_ in ("total", "held", "available"))), me_at(tok, as_of).j)
vok("J49 as_of far past (before reset): neither seeded hold exists yet (noct hold assumed created at reset; ct hold created 2h ago)", A, "1970-01-01T00:00:00Z", (10000, 0, 10000))
vok("J49 as_of 3h ago: no holds", A, iso(T0 - dt.timedelta(hours=3)), (10000, 0, 10000))
vok("J49 as_of 1h ago: only the created_at-supplied hold (1000)", A, iso(T0 - dt.timedelta(hours=1)), (10000, 1000, 9000))
vok("J49 as_of exactly its supplied created_at: hold present", A, iso(T0 - dt.timedelta(hours=2)), (10000, 1000, 9000))
vok("J49 as_of just before its supplied created_at: absent", A, iso(T0 - dt.timedelta(hours=2) - US), (10000, 0, 10000))
vok("J49 as_of now: both holds (4000)", A, iso(now()), (10000, 4000, 6000))
vok("J46 as_of 2h30m ahead: ct hold expired at its deadline (2h), noct still open", A, iso(T0 + dt.timedelta(hours=2, minutes=30)), (10000, 3000, 7000))
vok("J46 as_of 4h ahead: both expired by deadline", A, iso(T0 + dt.timedelta(hours=4)), (10000, 0, 10000))
vok("J44 receivers unaffected (bob)", B, iso(now()), (2000, 0, 2000))
azs = {a["authorization_id"]: a for a in call("GET", "/authorizations?limit=200", token=A).j["authorizations"]}
ok("J47 seeded open: closed_at null; seeded closed ones: key present (value unspecified)", azs["a_open_noct"]["closed_at"] is None and azs["a_open_ct"]["closed_at"] is None and all("closed_at" in azs[i] for i in ("a_cap", "a_void", "a_exp")), azs)
ok("J47 seeded created_at echoed for the supplied one", P(azs["a_open_ct"]["created_at"]) == T0 - dt.timedelta(hours=2), azs["a_open_ct"])
ok("J29 sum of totals constant for seeded views", all(sum(me_at(t[h], x).j["total"] for h in t) == TOTAL for x in ("1970-01-01T00:00:00Z", iso(T0 - dt.timedelta(hours=1)), iso(now()))))
sa = stmt(A).j
ok("J50 statement contains no entries for seeded authorizations (no payments)", sa["entries"] == [] and sa["opening_balance"] == sa["closing_balance"] == 10000, sa)

# ---- correction vs authorize race at the available boundary
for rd in range(6):
    f2 = fx([user("ada", 1000), user("bob", 0), user("cy", 0)])
    t2 = setup(f2)
    A2, B2 = t2["ada"], t2["bob"]
    q = pay(A2, "bob", 400).j        # ada total 600
    res = parallel([lambda: correct(A2, q["payment_id"], 1, 900, q["created_at"], "up"), lambda: authorize(A2, "cy", 500)])
    mm = me(A2)
    ok("J52 round %d: correction(+500) vs authorize(500) with 600 available: not both; ada total/available never negative %s" % (rd, (mm["total"], mm["held"], mm["available"])),
       not (res[0].s == 201 and res[1].s == 201) and mm["available"] >= 0 and mm["total"] >= 0 and sorted([res[0].s, res[1].s]) == [201, 409], [(r.s, r.code) for r in res])
    ok("J29 sum constant", sum(me(t2[h])["total"] for h in t2) == 1000)
done("t3_seedholds")
