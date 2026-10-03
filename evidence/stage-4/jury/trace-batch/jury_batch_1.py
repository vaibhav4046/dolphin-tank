"""jury checks, part 1: U20-U30 (auth, shape, item validation, ordering, settlement rules, precedence pairs)."""
import json
import sys
from datetime import timedelta

from jlib import *

EXE = sys.argv[1]
svc = Svc(EXE)


def exp(name, r, status, c=None):
    s, o = r
    ok = s == status and (c is None or code(o) == c)
    check(name, ok, "got %s %s" % (s, json.dumps(o)[:300] if not isinstance(o, bytes) else o[:300]))
    return o


def world1():
    users = {h: 10000 for h in ["op", "ada", "bob", "cy", "dee", "eve"]}
    w = World(svc, fixture(users))
    P = {}
    P["A"] = w.pay("ada", "bob", 1000)["payment_id"]
    P["B"] = w.pay("bob", "cy", 1000)["payment_id"]
    P["C"] = w.pay("cy", "dee", 500)["payment_id"]
    s, o = w.settle("op", [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                           {"from_handle": "bob", "to_handle": "cy", "amount": 100},
                           {"from_handle": "cy", "to_handle": "dee", "amount": 100}])
    assert s == 201, (s, o)
    P["S"] = [p["payment_id"] for p in o["payments"]]
    P["SRESP"] = o
    s, a = svc.j("POST", "/authorizations", w.tok["ada"], key(), {"to_handle": "bob", "amount": 300})
    assert s == 201, (s, a)
    s, cap = svc.j("POST", "/authorizations/%s/capture" % a["authorization_id"], w.tok["bob"], key(), {"amount": 300})
    assert s == 201, (s, cap)
    P["CAP"] = cap["payment_id"]
    s, rf = w.refund("bob", P["A"], 200)
    assert s == 201, (s, rf)
    P["REF"] = rf["payment_id"]
    s, rq = svc.j("POST", "/requests", w.tok["bob"], key(), {"payer_handle": "ada", "amount": 400, "note": "rq"})
    assert s == 201, (s, rq)
    s, rp = svc.j("POST", "/requests/%s/pay" % rq["request_id"], w.tok["ada"], key(), {})
    assert s == 201, (s, rp)
    P["RQ"] = rp["payment_id"]
    return w, P


E = iso(now() - timedelta(seconds=5))

# ---------------------------------------------------------------- A: U20 auth and key, parity with settlements
w, P = world1()
op, ada = w.tok["op"], w.tok["ada"]
okb = {"corrections": [item(P["C"], 1, 500, E)]}
oks = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}


def both(label, tok, k, braw_batch=None, braw_set=None, bb=okb, sb=oks):
    s1 = svc.call("POST", "/correction-batches", tok, k, None if braw_batch else bb, braw_batch)
    s2 = svc.call("POST", "/settlements", tok, k, None if braw_set else sb, braw_set)
    c1 = code(json.loads(s1[1])) if s1[0] >= 400 else None
    c2 = code(json.loads(s2[1])) if s2[0] >= 400 else None
    check("U20 %s: batch (%s %s) behaves like settlements (%s %s)" % (label, s1[0], c1, s2[0], c2),
          s1[0] == s2[0] and c1 == c2, (s1, s2))
    return s1


both("no token + key", None, "k1")
both("no token, no key", None, None)
s = both("garbage token", "nope", "k2")
check("U20 garbage token is 401", s[0] == 401)
s = both("non-operator with key", ada, "k3")
check("U20 non-operator is 403 forbidden", s[0] == 403 and code(json.loads(s[1])) == "forbidden")
both("non-operator without key", ada, None)
both("non-operator, unparseable body", ada, "k4", braw_batch=b"{nope", braw_set=b"{nope")
s = both("operator without key", op, None)
check("U20 operator without key is 400 missing_idempotency_key", s[0] == 400 and code(json.loads(s[1])) == "missing_idempotency_key")
both("operator with empty key", op, "")
both("operator with 256-char key", op, "x" * 256)
both("operator unparseable body", op, "k5", braw_batch=b"{nope", braw_set=b"{nope")
both("operator body is an array", op, "k6", braw_batch=b"[]", braw_set=b"[]")
both("operator body {}", op, "k7", bb={}, sb={})
s = svc.call("POST", "/correction-batches", op, "x" * 255, okb)
check("U20 255-char key accepted", s[0] == 201, s)
s = svc.call("GET", "/correction-batches", op)
check("U20 GET /correction-batches is not a route (404/405)", s[0] in (404, 405), s)

# ---------------------------------------------------------------- B: U21 shape
w, P = world1()
many = []
for i in range(32):
    many.append(w.pay("op", "bob", 1)["payment_id"])
for name, body in [
    ("no corrections key", {}), ("corrections null", {"corrections": None}), ("corrections string", {"corrections": "x"}),
    ("corrections object", {"corrections": {}}), ("corrections empty", {"corrections": []}),
    ("33 items with unknown ids", {"corrections": [item("p_nope%d" % i, 1, 1, E) for i in range(33)]}),
    ("33 items with real ids", {"corrections": [item(many[i % 32], 1, 2, E) for i in range(33)]}),
    ("duplicate payment_id", {"corrections": [item(many[0], 1, 2, E), item(many[1], 1, 2, E), item(many[0], 1, 3, E)]}),
    ("element is a number", {"corrections": [5]}), ("element is a string", {"corrections": ["x"]}),
    ("element is null", {"corrections": [None]}), ("element is an array", {"corrections": [[]]}),
    ("missing payment_id", {"corrections": [{"expected_revision": 1, "amount": 2, "effective_at": E, "reason": "r"}]}),
    ("payment_id number", {"corrections": [item(5, 1, 2, E)]}),
    ("payment_id null", {"corrections": [item(None, 1, 2, E)]}),
]:
    r = svc.j("POST", "/correction-batches", w.tok["op"], key(), body)
    rs = svc.j("POST", "/settlements", w.tok["op"], key(), {"transfers": body.get("corrections")} if "corrections" in body else {})
    exp("U21 shape %s -> 422 validation_failed" % name, r, 422, "validation_failed")
before = svc.export()
r = w.batch("op", [item(m, 1, 2, E) for m in many])
exp("U21 exactly 32 distinct items -> 201", r, 201)
check("U21 32 revisions returned in input order", [x["payment_id"] for x in r[1]["revisions"]] == many)
check("U21 shape-rejected batches changed nothing before that (export differs only after the 201)", before != svc.export())
# 1 item is the lower bound
r = w.batch("op", [item(P["C"], 1, 400, E)])
exp("U21 one item -> 201", r, 201)

# ---------------------------------------------------------------- C: U22 item validation == single correction validation
w, P = world1()
cases = []
base = lambda **kw: dict({"expected_revision": 1, "amount": 5, "effective_at": E, "reason": "r"}, **kw)
def drop(d, k):
    d = dict(d)
    d.pop(k, None)
    return d
future = iso(now() + timedelta(hours=1))
for k, vals in [
    ("amount", [0, -1, 1000000000, 1000000001, 5.5, "5", True, None, 5.0, [5], {"a": 1}]),
    ("expected_revision", [0, -1, 1.5, "1", True, None, 1.0, [1]]),
    ("effective_at", ["", "2026-09-20T12:00:00", "2026-09-20", future, "2099-01-01T00:00:00-12:00", 5, None, "2026-09-20 12:00:00+00:00", iso(now() - timedelta(days=1), 2), "garbage"]),
    ("reason", ["", "x" * 200, "x" * 201, "é" * 200, "é" * 201, "\U0001F600" * 200, "\U0001F600" * 201, 5, None, True]),
]:
    for v in vals:
        cases.append(("%s=%r" % (k, v if not isinstance(v, str) or len(v) < 30 else v[:8] + "...(%d)" % len(v)), base(**{k: v})))
    cases.append(("%s missing" % k, drop(base(), k)))
n = len(cases)
single_ps = [w.pay("op", "bob", 10)["payment_id"] for _ in range(n)]
batch_ps = [w.pay("op", "bob", 10)["payment_id"] for _ in range(n)]
mism = 0
for (name, body), sp, bp in zip(cases, single_ps, batch_ps):
    s1, o1 = svc.j("POST", "/payments/%s/corrections" % sp, w.tok["op"], key(), body)
    s2, o2 = svc.j("POST", "/correction-batches", w.tok["op"], key(), {"corrections": [dict(body, payment_id=bp)]})
    same = s1 == s2 and code(o1) == code(o2)
    if not same:
        mism += 1
    check("U22 item %s -> batch (%s %s) == single (%s %s)" % (name, s2, code(o2), s1, code(o1)), same)
    if s2 == 201:
        r = o2["revisions"][0]
        ok = all(r.get(f) == o1.get(f) for f in ("amount", "effective_at", "reason", "revision", "payment_id") if f != "payment_id")
        check("U22   accepted item body shape == single revision shape for %s" % name, ok, (r, o1))
check("U22 summary: no parity mismatches over %d bodies" % n, mism == 0)

# ---------------------------------------------------------------- D: U23 index order of item errors, per-item class order
w, P = world1()
good = lambda pid: item(pid, 1, 400, E)
def snap_and_check(name, items, status, c):
    b = svc.export()
    r = w.batch("op", items)
    exp(name, r, status, c)
    check(name + " [state byte-identical]", svc.export() == b)

snap_and_check("U23 unknown at idx1, stale at idx2 -> 404", [good(P["C"]), item("p_nope", 1, 1, E), item(P["B"], 9, 1, E)], 404, "not_found")
snap_and_check("U23 stale at idx1, unknown at idx2 -> 409 stale_revision", [good(P["C"]), item(P["B"], 9, 1, E), item("p_nope", 1, 1, E)], 409, "stale_revision")
snap_and_check("U23 validation at idx2, stale at idx1 -> 409", [good(P["C"]), item(P["B"], 9, 1, E), item(P["A"], 1, -1, E)], 409, "stale_revision")
snap_and_check("U23 validation at idx1, 404 at idx2 -> 422 validation_failed", [good(P["C"]), item(P["A"], 1, -1, E), item("p_nope", 1, 1, E)], 422, "validation_failed")
snap_and_check("U23 same item invalid AND unknown -> validation (ordinary order)", [item("p_nope", 1, -1, E)], 422, "validation_failed")
snap_and_check("U23 same item capture AND stale -> linked_payment_immutable", [item(P["CAP"], 9, 1, E)], 422, "linked_payment_immutable")
snap_and_check("U23 same item refund payment AND stale -> linked_payment_immutable", [item(P["REF"], 9, 1, E)], 422, "linked_payment_immutable")
snap_and_check("U23 same item stale AND below refunded -> stale_revision", [item(P["A"], 9, 100, E)], 409, "stale_revision")
snap_and_check("U23 below refunded (A refunded 200) -> refund_exceeds_payment", [item(P["A"], 1, 199, E)], 422, "refund_exceeds_payment")
snap_and_check("U23 future effective_at at idx1, stale idx2 -> 422", [good(P["C"]), item(P["A"], 1, 900, future), item(P["B"], 9, 1, E)], 422, "validation_failed")
snap_and_check("U23 stale item after unknown settlement-less idx order: idx0 stale, idx1 capture -> stale", [item(P["B"], 9, 1, E), item(P["CAP"], 1, 1, E)], 409, "stale_revision")
snap_and_check("U23 idx0 capture, idx1 stale -> linked", [item(P["CAP"], 1, 1, E), item(P["B"], 9, 1, E)], 422, "linked_payment_immutable")

# ---------------------------------------------------------------- E: U24 any user, ordinary + request + settlement; U28 unknown fields
w, P = world1()
b0 = w.balances()
items = [dict(item(P["RQ"], 1, 300, E), extra_field=1, settlement_id="x", refund_of="y"),
         item(P["C"], 1, 450, E)] + [item(m, 1, 50, E) for m in P["S"]]
r = svc.j("POST", "/correction-batches", w.tok["op"], key(), {"corrections": items, "unknown": [1, 2], "note": "x"})
exp("U24/U28 operator batch over request payment + ordinary payment (other users') + full settlement, unknown fields ignored -> 201", r, 201)
b1 = w.balances()
# deltas: RQ bob<-ada 400->300 : ada +100 bob -100; C cy->dee 500->450 : cy +50 dee -50; S: each 100->50, ada->bob, bob->cy, cy->dee
exp_delta = {"ada": +100 + 50, "bob": -100 - 50 + 50, "cy": +50 - 50 + 50 - 50 + 0, "dee": -50 - 50 + 0, "eve": 0, "op": 0}
# settlement: ada->bob 100->50 => ada +50 bob -50; bob->cy => bob +50 cy -50; cy->dee => cy +50 dee -50
exp_delta = {"ada": 100 + 50, "bob": -100 - 50 + 50, "cy": 50 - 50 + 50, "dee": -50 - 50, "eve": 0, "op": 0}
got = {h: b1[h] - b0[h] for h in b0}
check("U24 balances moved exactly by the net revisions %s" % exp_delta, got == exp_delta, got)
check("U24 total unchanged", sum(b1.values()) == sum(b0.values()))
snap_and_check("U24 batch of a capture -> 422 linked_payment_immutable", [item(P["CAP"], 1, 1, E)], 422, "linked_payment_immutable")
snap_and_check("U24 batch of a refund -> 422 linked_payment_immutable", [item(P["REF"], 1, 1, E)], 422, "linked_payment_immutable")
snap_and_check("U24 capture in a batch with valid items still rejects whole batch", [item(P["B"], 1, 900, E), item(P["CAP"], 1, 1, E)], 422, "linked_payment_immutable")
# operator is not special-cased on the sender side: a non-operator sender cannot batch his own payment
exp("U24 non-operator sender cannot use the batch route -> 403", svc.j("POST", "/correction-batches", w.tok["ada"], key(), {"corrections": [item(P["B"], 1, 900, E)]}), 403, "forbidden")

# ---------------------------------------------------------------- F: U25/U26/U27 settlements
w, P = world1()
s1, s2, s3 = P["S"]
snap_and_check("U25 two of three members -> 422 incomplete_settlement", [item(s1, 1, 50, E), item(s2, 1, 50, E)], 422, "incomplete_settlement")
snap_and_check("U25 one of three members -> 422 incomplete_settlement", [item(s2, 1, 50, E)], 422, "incomplete_settlement")
snap_and_check("U25 all members + ordinary but one member stale -> 409 stale (item error first)", [item(s1, 1, 50, E), item(s2, 9, 50, E), item(s3, 1, 50, E)], 409, "stale_revision")
snap_and_check("U25 member + capture in same batch -> linked_payment_immutable first", [item(s1, 1, 50, E), item(P["CAP"], 1, 1, E)], 422, "linked_payment_immutable")
snap_and_check("U26 complete but instants differ by 1s -> 422 validation_failed", [item(s1, 1, 50, E), item(s2, 1, 50, iso(now() - timedelta(seconds=6))), item(s3, 1, 50, E)], 422, "validation_failed")
snap_and_check("U26 complete but instants differ by 1us in the same offset -> 422", [item(s1, 1, 50, "2026-10-03T08:00:00.000000+00:00"), item(s2, 1, 50, "2026-10-03T08:00:00.000001+00:00"), item(s3, 1, 50, "2026-10-03T08:00:00.000000+00:00")], 422, "validation_failed")
snap_and_check("U25/U26 incomplete AND unequal instants (decision b) -> incomplete_settlement", [item(s1, 1, 50, E), item(s2, 1, 50, iso(now() - timedelta(seconds=9)))], 422, "incomplete_settlement")
# offset spellings of one instant
t0 = now() - timedelta(seconds=30)
sp = [iso(t0, 0), iso(t0, 2), iso(t0, -5)]
r = w.batch("op", [item(s1, 1, 60, sp[0]), item(s2, 1, 60, sp[1]), item(s3, 1, 60, sp[2])])
exp("U26 same instant spelled +00:00 / +02:00 / -05:00 -> 201", r, 201)
revs = w.revs("ada", s1)
check("U26 revision keeps the effective_at text it was given", [x["effective_at"] for x in revs][-1] in sp, revs[-1])
# a member's second correction in a later batch needs rev 2
r = w.batch("op", [item(s1, 1, 40, E), item(s2, 1, 40, E), item(s3, 1, 40, E)])
exp("U25 members at stale rev 1 after one batch -> 409", r, 409, "stale_revision")
r = w.batch("op", [item(s1, 2, 40, E), item(s2, 2, 40, E), item(s3, 2, 40, E)])
exp("U25 members at rev 2 -> 201", r, 201)
# U27 single route
w, P = world1()
exp("U27 single correction of a nonmember payment by its sender -> 201", w.correct("ada", P["A"], 1, 900, E), 201)
exp("U27 single correction of a settlement member by its sender -> 422 linked_payment_immutable", w.correct("ada", P["S"][0], 1, 90, E), 422, "linked_payment_immutable")
r = w.correct("op", P["S"][0], 1, 90, E)
check("U27 single correction of a settlement member by a non-sender is refused (403 or 422)", r[0] in (403, 422), r)

# ---------------------------------------------------------------- G: U29 precedence, adjacent pairs, current-vs-history
# G-current: settlement incomplete + unaffordable debit -> incomplete first; unequal instants + unaffordable -> validation_failed
w, P = world1()
s1, s2, s3 = P["S"]
big = item(P["A"], 1, 900, E)   # A is ada->bob; refunded 200, going to 900 > 1000-200? ok (not below refunded)
huge = item(P["B"], 1, 100000, E)  # bob->cy raised by 99000: bob cannot afford
snap_and_check("U29 [item error idx2] vs [incomplete idx0..1]: item error wins", [item(s1, 1, 50, E), item(s2, 1, 50, E), item("p_nope", 1, 1, E)], 404, "not_found")
snap_and_check("U29 [incomplete settlement + unaffordable debit] -> incomplete_settlement", [item(s1, 1, 50, E), item(s2, 1, 50, E), huge], 422, "incomplete_settlement")
snap_and_check("U29 [complete settlement w/ unequal instants + unaffordable debit] -> validation_failed", [item(s1, 1, 50, E), item(s2, 1, 50, iso(now() - timedelta(seconds=9))), item(s3, 1, 50, E), huge], 422, "validation_failed")
snap_and_check("U29 [unaffordable debit alone] -> insufficient_funds", [huge], 409, "insufficient_funds")
snap_and_check("U29 [refund_exceeds_payment item + unaffordable later item] -> refund_exceeds_payment", [item(P["A"], 1, 199, E), huge], 422, "refund_exceeds_payment")
snap_and_check("U29 [unaffordable idx0 + stale idx1] -> stale (items before funds)", [huge, item(P["C"], 9, 1, E)], 409, "stale_revision")
snap_and_check("U29 [incomplete idx0 + validation idx1] -> validation_failed (item error beats completeness)", [item(s1, 1, 50, E), item(P["C"], 1, -5, E)], 422, "validation_failed")

# G-history: seeded past; precedence insufficient_funds > historical_overdraft; historical alone
T = now()
seed = [
    {"id": "p_z1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public", "created_at": iso(T - timedelta(hours=3))},
    {"id": "p_a2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "", "visibility": "public", "created_at": iso(T - timedelta(hours=2))},
    {"id": "p_z3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public", "created_at": iso(T - timedelta(hours=1))},
]
users = {"op": 0, "ada": 0, "bob": 100, "cy": 0, "dee": 0}
w = World(svc, fixture(users, seed))
check("G-history fixture: bob 100, ada 0", w.me("bob")["balance"] == 100 and w.me("ada")["balance"] == 0)
T3h = iso(T - timedelta(hours=3))
T1h = iso(T - timedelta(hours=1))
snap_and_check("U29/U30 current affordable but bob negative at T-2h -> historical_overdraft", [item("p_z1", 1, 50, T3h)], 409, "historical_overdraft")
snap_and_check("U29 current unaffordable AND historical negative -> insufficient_funds first", [item("p_z1", 1, 0, T3h), item("p_z3", 1, 0, T1h)], 409, "insufficient_funds")
# combined effect at one instant: bob receives 100 (p_z1 unchanged) and the same instant p_a2 raised... (judged after all movements)
b = svc.export()
r = w.batch("op", [item("p_z1", 1, 100, T3h), item("p_a2", 1, 100, T3h)])
# p_a2 effective moved back to T-3h: at T-3h bob receives 100 from ada and pays 100 to cy in the same instant -> 0 after both: allowed
exp("U29 combined effect at one instant: +100 and -100 effective together -> accepted", r, 201)

print("\nPART1 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
if FAILS:
    print("FAILED: %s" % FAILS)
svc.stop()
sys.exit(1 if FAILS else 0)
