"""J36-J50: historical holds on /me?as_of&known_at, closed_at, hold-aware historical_overdraft, seeded holds, statement purity, linked immutability."""
import sys, time
from lib3 import *

now = lambda: dt.datetime.now(UTC)


def view(tok, as_of=None, known_at=None):
    r = me_at(tok, as_of, known_at)
    assert r.s == 200, r
    j = r.j
    return (j["total"], j["held"], j["available"], j["balance"])


def vok(name, tok, as_of, exp, known_at=None):
    got = view(tok, iso(as_of) if isinstance(as_of, dt.datetime) else as_of, known_at)
    ok("%s: total/held/available = %s" % (name, exp), got[:3] == exp and got[3] == exp[0], got)


def scn(bal, ttl=None, extra=None):
    f = fx([user(h, b) for h, b in bal.items()])
    if ttl is not None:
        f["authorization_ttl_seconds"] = ttl
    if extra:
        f.update(extra)
    return setup(f), f


# ============================================================ H1 lifecycle timeline: authorize -> partial capture -> final capture
t, f = scn({"ada": 10000, "bob": 0, "cy": 0})
A, B, C = t["ada"], t["bob"], t["cy"]
TOTAL = 10000
au = authorize(A, "bob", 3000, note="dep", vis="private")
a = au.j
Ca = P(a["created_at"])
ok("J47 open authorization exposes closed_at: null", au.s == 201 and "closed_at" in a and a["closed_at"] is None, a)
time.sleep(1.15)
c1 = capture(B, a["authorization_id"], amount=1000, final=False)
Pb = P(c1.j["created_at"])
ok("J01 capture payment created_at RFC3339; authorization_id set", c1.s == 201 and RFC3339.match(c1.j["created_at"]) and c1.j["authorization_id"] == a["authorization_id"], c1)
ok("J47 closed_at still null after a non-final capture", authz(A, a["authorization_id"])["closed_at"] is None)
time.sleep(1.15)
c2 = capture(B, a["authorization_id"], amount=500)  # final: releases 1500
Pc = P(c2.j["created_at"])
a_end = authz(A, a["authorization_id"])
ok("J47 final capture closes: status captured, remaining 0, closed_at not null", a_end["status"] == "captured" and a_end["remaining_amount"] == 0 and a_end["closed_at"] is not None and RFC3339.match(a_end["closed_at"]), a_end)
cl = P(a_end["closed_at"])
ok("J47 closed_at is the event time of the final capture (within 1 s of the capture payment, not after it)", cl <= Pc + US and (Pc - cl).total_seconds() < 1.0, (a_end["closed_at"], c2.j["created_at"]))
vok("J45 ada before authorization", A, Ca - US, (10000, 0, 10000))
vok("J45/J46 ada at authorization creation instant (created_at): hold present", A, Ca, (10000, 3000, 7000))
vok("J45 ada just before 1st capture: hold 3000 total 10000", A, Pb - US, (10000, 3000, 7000))
vok("J45 ada at 1st (non-final) capture: total 9000, hold reduced to 2000 at capture time", A, Pb, (9000, 2000, 7000))
vok("J45 ada between captures", A, Pb + (Pc - Pb) / 2, (9000, 2000, 7000))
vok("J45 ada just before final capture", A, Pc - US, (9000, 2000, 7000))
vok("J45 ada at final capture: total 8500, remainder 1500 released at the event time", A, Pc, (8500, 0, 8500))
vok("J45 ada far future", A, "9999-12-31T23:59:59Z", (8500, 0, 8500))
vok("J47 ada at closed_at: hold released", A, cl, (8500 if cl >= Pc else 9000, 0, 8500 if cl >= Pc else 9000)) if cl >= Pc else ok("J47 closed_at before capture payment instant: view at closed_at has the hold released", view(A, a_end["closed_at"])[1] == 0, view(A, a_end["closed_at"]))
vok("J44 bob (receiver) never sees ada's hold: at Ca", B, Ca, (0, 0, 0))
vok("J44 bob at Pb", B, Pb, (1000, 0, 1000))
vok("J44 bob at Pc", B, Pc, (1500, 0, 1500))
vok("J44 current ada", A, None, (8500, 0, 8500))
ok("J29 sum of totals constant at Ca, Pb, Pc, closed_at", all(sum(view(t[h], iso(x))[0] for h in t) == TOTAL for x in (Ca, Pb, Pc, cl)))

# known_at x holds
vok("J46 known_at before the authorization was known: no hold (as_of far future, known_at=Ca-1s)", A, "9999-12-31T23:59:59Z", (10000, 0, 10000), known_at=iso(Ca - dt.timedelta(seconds=1)))
vok("J46 known_at = creation: hold known, as_of=Ca", A, Ca, (10000, 3000, 7000), known_at=iso(Ca))
vok("J46 known_at just before 1st capture, as_of = after it: capture unknown -> payment absent, hold 3000 then expires at deadline (as_of = Pb+1s)", A, Pb + dt.timedelta(seconds=1), (10000, 3000, 7000), known_at=iso(Pb - US))
vok("J46 once creation is known the deadline is known: as_of far future with known_at before 1st capture -> hold expired", A, "9999-12-31T23:59:59Z", (10000, 0, 10000), known_at=iso(Pb - US))
vok("J46 known_at between captures, as_of now: 1st capture known, 2nd not", A, None, (9000, 2000, 7000), known_at=iso(Pb + (Pc - Pb) / 2))
vok("J46 known_at = final capture event: everything known", A, None, (8500, 0, 8500), known_at=c2.j["created_at"])
# hold counted in current /me too
# statement purity (J50)
st = stmt(A, limit=200).j
ids = [e["payment"]["payment_id"] for e in st["entries"]]
ok("J50 statement lists the two capture payments exactly once each, nothing for authorize/release/expiry", ids == [c1.j["payment_id"], c2.j["payment_id"]] and all(e["payment"]["authorization_id"] == a["authorization_id"] for e in st["entries"]) and len(st["entries"]) == 2, ids)
ok("J50 statement balance_after follows total (not available): 9000 then 8500; closing 8500 == /me.total", [e["balance_after"] for e in st["entries"]] == [9000, 8500] and st["closing_balance"] == 8500 == me(A)["total"], st)
ok("J50 authorization is not an activity item", not any(p.get("authorization_id") is None and p["amount"] == 3000 for p in call("GET", "/activity?limit=200", token=A).j["payments"]))
rv = revs(A, c1.j["payment_id"])
ok("J18 capture payment revision 1: effective_at == recorded_at == created_at", len(rv) == 1 and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == Pb and rv[0]["amount"] == 1000, rv)
# J43 correcting a capture
before = (me(A), me(B), stmt(A).j["entries"])
for who, tk in [("payer/sender", A), ("receiver/capturer", B)]:
    r = correct(tk, c1.j["payment_id"], 1, 900, c1.j["created_at"], "no")
    ok("J43 %s correcting a capture -> 422 linked_payment_immutable (sender) or 403 forbidden (non-sender); never 201" % who, (r.s == 422 and r.code == "linked_payment_immutable") if tk is A else (r.s in (403, 422)), r)
ok("J43 attempt left everything unchanged", (me(A), me(B), stmt(A).j["entries"]) == before)

# ============================================================ H2 void after a partial capture; void timing; payment_ids preserved
time.sleep(0.2)
t, f = scn({"ada": 10000, "bob": 0})
A, B = t["ada"], t["bob"]
a = authorize(A, "bob", 4000).j
time.sleep(1.15)
cc = capture(B, a["authorization_id"], amount=1500, final=False)
Pb = P(cc.j["created_at"])
time.sleep(1.15)
vr = void(A, a["authorization_id"])
a_v = authz(A, a["authorization_id"])
ok("J47 void closes: status voided, closed_at set, payment_ids kept, captured_amount 1500, remaining 0", vr.s == 200 and a_v["status"] == "voided" and a_v["closed_at"] and a_v["payment_ids"] == [cc.j["payment_id"]] and a_v["captured_amount"] == 1500 and a_v["remaining_amount"] == 0, a_v)
Cv = P(a_v["closed_at"])
vok("J45 before void: hold = remainder 2500 (after non-final capture)", A, Cv - US, (8500, 2500, 6000))
vok("J45 at closed_at (void time): remainder released", A, Cv, (8500, 0, 8500))
vok("J45 hold during window between capture and void", A, Pb, (8500, 2500, 6000))
ok("J47 void twice is 200 and closed_at is stable", void(A, a["authorization_id"]).s == 200 and authz(A, a["authorization_id"])["closed_at"] == a_v["closed_at"])
# immediate void with no capture
a2 = authorize(A, "bob", 700).j
time.sleep(1.1)
void(A, a2["authorization_id"])
a2e = authz(A, a2["authorization_id"])
vok("J45 void without capture: held 700 just before, 0 at closed_at", A, P(a2e["closed_at"]) - US, (8500, 700, 7800))
vok("J45 void without capture: released at closed_at", A, P(a2e["closed_at"]), (8500, 0, 8500))

# ============================================================ H3 expiry by real clock
t, f = scn({"ada": 10000, "bob": 0}, ttl=3)
A, B = t["ada"], t["bob"]
a = authorize(A, "bob", 2500).j
Ea = P(a["expires_at"])
ok("J47 expires_at = created_at + ttl(3s)", (Ea - P(a["created_at"])).total_seconds() == 3, a)
vok("J46 while still open: as_of = expires_at - 1us (future or now) holds", A, Ea - US, (10000, 2500, 7500))
vok("J46 queries beyond now: an open hold expires at its deadline (as_of = expires_at)", A, Ea, (10000, 0, 10000))
vok("J46 as_of far future: open hold already released", A, "9999-12-31T23:59:59Z", (10000, 0, 10000))
ok("J47 closed_at is null while the hold is still open (clock has not reached expires_at)", authz(A, a["authorization_id"])["closed_at"] is None or now() >= Ea)
sleep_until(a["expires_at"], 0.6)
a_e = authz(A, a["authorization_id"])
ok("J47 after expires_at (no request at the deadline): status expired, remaining 0, closed_at set", a_e["status"] == "expired" and a_e["remaining_amount"] == 0 and a_e["closed_at"] is not None, a_e)
ok("J47 closed_at of an expired authorization is its expires_at (event time of the expiry)", P(a_e["closed_at"]) == Ea, (a_e["closed_at"], a_e["expires_at"]))
vok("J45 after expiry current view: released", A, None, (10000, 0, 10000))
vok("J45 history after expiry: hold present just before expires_at", A, Ea - US, (10000, 2500, 7500))
vok("J45 history after expiry: released at expires_at", A, Ea, (10000, 0, 10000))
# partial capture then expiry preserves capture records, releases only remainder
a3 = authorize(A, "bob", 2000).j
c3 = capture(B, a3["authorization_id"], amount=800, final=False)
sleep_until(a3["expires_at"], 0.6)
a3e = authz(A, a3["authorization_id"])
ok("J47 partial capture then expiry: expired, payment_ids kept, captured 800, closed_at == expires_at", a3e["status"] == "expired" and a3e["captured_amount"] == 800 and a3e["payment_ids"] == [c3.j["payment_id"]] and P(a3e["closed_at"]) == P(a3e["expires_at"]), a3e)
vok("J45 expiry releases only the remainder: total 9200, held 0 after; just before expiry held 1200", A, P(a3e["expires_at"]) - US, (9200, 1200, 8000))
vok("J45 after expiry", A, None, (9200, 0, 9200))

# ============================================================ H4 hold-aware historical overdraft (available negative at a past boundary)
t, f = scn({"ada": 1000, "bob": 0, "cy": 1000})
A, B, C = t["ada"], t["bob"], t["cy"]
a = authorize(A, "bob", 800).j       # t1: available 200
time.sleep(1.15)
p2 = pay(A, "bob", 100).j            # t2: total 900, held 800, available 100
time.sleep(1.15)
p3 = pay(C, "ada", 1000).j           # t3: total 1900
W0 = (me(A), me(B), me(C), stmt(A).j["entries"], revs(A, p2["payment_id"]))
ok("setup H4: ada total 1900 held 800 available 1100", (lambda m: (m["total"], m["held"], m["available"]) == (1900, 800, 1100))(me(A)))
r = correct(A, p2["payment_id"], 1, 250, p2["created_at"], "bigger")
ok("J48 correction making AVAILABLE negative at a past boundary (total 750 >= 0 but hold 800) -> 409 historical_overdraft, currently affordable", r.s == 409 and r.code == "historical_overdraft", r)
ok("J48 failure changed nothing", (me(A), me(B), me(C), stmt(A).j["entries"], revs(A, p2["payment_id"])) == W0)
r = correct(A, p2["payment_id"], 1, 200, p2["created_at"], "exact fit")
ok("J48 correction leaving available exactly 0 at the boundary -> 201", r.s == 201, r)
# hold closed before the payment: same sort of correction is fine
t, f = scn({"ada": 1000, "bob": 0, "cy": 1000})
A, B, C = t["ada"], t["bob"], t["cy"]
a = authorize(A, "bob", 800).j
time.sleep(1.15)
void(A, a["authorization_id"])
time.sleep(1.15)
p2 = pay(A, "bob", 100).j
time.sleep(0.01)
pay(C, "ada", 1000)
r = correct(A, p2["payment_id"], 1, 900, p2["created_at"], "after void")
ok("J48 hold already voided before the payment instant: correction to 900 is fine (total 100 >= 0, no hold)", r.s == 201, r)
r = correct(A, p2["payment_id"], 2, 1000, p2["created_at"], "total zero")
ok("J48 correction making total exactly 0 at a past boundary -> accepted", r.s == 201, r)

# ============================================================ H5 view consistency when funding and hold are created back-to-back (public timestamps)
t, f = scn({"ada": 1000000, "bob": 0, "cy": 0})
A, B, C = t["ada"], t["bob"], t["cy"]
neg, tot, ex = 0, 0, []
for i in range(25):
    pf = pay(A, "bob", 5000)          # funds bob
    au = authorize(B, "cy", 4000)     # bob immediately places a hold funded by that payment
    Cb = au.j["created_at"]
    m = me_at(B, Cb).j
    tot += 1
    if m["available"] < 0 or m["held"] > m["total"]:
        neg += 1
        if len(ex) < 2:
            ex.append({"payment.created_at": pf.j["created_at"], "authorization.created_at": Cb, "me_as_of_authorization.created_at": {k_: m[k_] for k_ in ("total", "held", "available")}})
    void(B, au.j["authorization_id"])
ok("J44/stage-2-invariant: /me?as_of=<authorization.created_at> never shows available < 0 or held > total (hold funded by a payment made just before it) - %d of %d views violated" % (neg, tot), neg == 0, ex)
done("t3_holds")
