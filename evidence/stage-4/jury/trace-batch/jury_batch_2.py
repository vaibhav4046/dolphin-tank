"""jury checks, part 2: U31-U39 (net effect incl. held funds, rejection atomicity, recorded_at, snapshots, replay, refunds x batches)."""
import json
import sys
from datetime import datetime, timedelta

from jlib import *

EXE = sys.argv[1]
svc = Svc(EXE)


def exp(name, r, status, c=None):
    s, o = r
    ok = s == status and (c is None or code(o) == c)
    check(name, ok, "got %s %s" % (s, json.dumps(o)[:400] if not isinstance(o, bytes) else o[:300]))
    return o


def dt(s):
    return datetime.fromisoformat(s)


E = iso(now() - timedelta(seconds=5))


def world3():
    w = World(svc, fixture({h: 1000 for h in ["op", "ada", "bob", "cy", "dee"]}))
    X = w.pay("ada", "bob", 200)["payment_id"]
    Y = w.pay("cy", "ada", 200)["payment_id"]
    Z = w.pay("bob", "cy", 200)["payment_id"]
    s, a = svc.j("POST", "/authorizations", w.tok["ada"], key(), {"to_handle": "dee", "amount": 700})
    assert s == 201, (s, a)
    m = w.me("ada")
    assert (m["total"], m["held"], m["available"]) == (1000, 700, 300), m
    return w, X, Y, Z


def run(label, builder_args, items_fn, status, c, after=None):
    """fresh world3, run a batch, assert (status, code), and on success that balances moved by the net revision deltas."""
    global E
    w, X, Y, Z = world3()
    E = iso(now())  # effective after every payment of this world exists, so only the net current effect is under test
    before = w.balances()
    r = w.batch("op", items_fn(X, Y, Z))
    exp(label, r, status, c)
    if status == 201:
        check(label + " [sum of balances conserved]", w.total() == sum(before.values()))
        for h in w.tok:
            m = w.me(h)
            check(label + " [%s available never negative]" % h, m["available"] >= 0 and m["total"] >= 0, m)
    else:
        check(label + " [balances unchanged]", w.balances() == before)
    return w


# ---------------------------------------------------------------- U31 net effect, one wallet, with held funds (ada available 300)
run("U31 X up 300 (ada net -300 = available) -> 201", None, lambda X, Y, Z: [item(X, 1, 500, E)], 201, None)
run("U31 X up 301 (ada net -301 > available 300; held 700 not spendable) -> 409", None, lambda X, Y, Z: [item(X, 1, 501, E)], 409, "insufficient_funds")
run("U31 X up 1000 + Y up 1000: ada nets 0, cy -1000 = exactly its funds -> 201", None, lambda X, Y, Z: [item(X, 1, 1200, E), item(Y, 1, 1200, E)], 201, None)
run("U31 same, other input order -> 201", None, lambda X, Y, Z: [item(Y, 1, 1200, E), item(X, 1, 1200, E)], 201, None)
run("U31 X up 1000 + Y up 1001: cy short by 1 -> 409", None, lambda X, Y, Z: [item(X, 1, 1200, E), item(Y, 1, 1201, E)], 409, "insufficient_funds")
run("U31 X up 1000 + Y up 699: ada net -301 -> 409", None, lambda X, Y, Z: [item(X, 1, 1200, E), item(Y, 1, 899, E)], 409, "insufficient_funds")
run("U31 X up 1000 + Y up 700: ada net -300 = available -> 201", None, lambda X, Y, Z: [item(X, 1, 1200, E), item(Y, 1, 900, E)], 201, None)
run("U31 Y down to 0 (debits receiver ada 200) + X up 100: ada -300 -> 201", None, lambda X, Y, Z: [item(Y, 1, 0, E), item(X, 1, 300, E)], 201, None)
run("U31 Y down to 0 + X up 101: ada -301 -> 409", None, lambda X, Y, Z: [item(Y, 1, 0, E), item(X, 1, 301, E)], 409, "insufficient_funds")
run("U31 chain X up 300 + Z up 1300: bob nets -1000 = exactly its funds -> 201, either order", None, lambda X, Y, Z: [item(Z, 1, 1500, E), item(X, 1, 500, E)], 201, None)
run("U31 chain X up 300 + Z up 1301: bob nets -1001 -> 409", None, lambda X, Y, Z: [item(X, 1, 500, E), item(Z, 1, 1501, E)], 409, "insufficient_funds")
run("U31 a wallet's decrease funds another item's increase on the same wallet (X down 200, Y up 200 on ada side) -> 201", None,
    lambda X, Y, Z: [item(X, 1, 0, E), item(Y, 1, 400, E)], 201, None)  # ada: +200 (X reversed) +200 (Y up credits ada) ; cy -200

# ---------------------------------------------------------------- U32 rejection leaves state byte-identical; key is reusable afterwards
for name, mk, st in [
    ("stale", lambda X: [item(X, 9, 250, E)], 409), ("unknown", lambda X: [item("p_nope", 1, 1, E)], 404),
    ("validation", lambda X: [item(X, 1, -1, E)], 422), ("unaffordable", lambda X: [item(X, 1, 501, E)], 409),
    ("capture", None, 422), ("incomplete", None, 422)]:
    w, X, Y, Z = world3()
    s, sr = w.settle("op", [{"from_handle": "bob", "to_handle": "cy", "amount": 10}, {"from_handle": "cy", "to_handle": "dee", "amount": 10}])
    members = [p["payment_id"] for p in sr["payments"]]
    if name == "capture":
        s, a = svc.j("POST", "/authorizations", w.tok["bob"], key(), {"to_handle": "cy", "amount": 5})
        s, cap = svc.j("POST", "/authorizations/%s/capture" % a["authorization_id"], w.tok["cy"], key(), {"amount": 5})
        bad = [item(cap["payment_id"], 1, 1, E)]
    elif name == "incomplete":
        bad = [item(members[0], 1, 1, E)]
    else:
        bad = mk(X)
    k = key("retry")
    b = svc.export()
    s, o = w.batch("op", bad, k=k)
    check("U32 class %s rejected with %s" % (name, st), s == st, (s, o))
    check("U32 class %s: export byte-identical" % name, svc.export() == b)
    s, o = w.batch("op", [item(X, 1, 250, E)], k=k)
    check("U32 class %s: same key then succeeds with a different valid body (201)" % name, s == 201, (s, o))
    s2, o2 = w.batch("op", [item(X, 1, 250, E)], k=k)
    check("U32 class %s: and now replays 200 identical" % name, s2 == 200 and o2 == o, (s2, o2))

# ---------------------------------------------------------------- U33/U34 body, shared recorded_at strictly after every member's previous one
w = World(svc, fixture({h: 5000 for h in ["op", "bob", "cy"]}))
P1, P2, P3 = [w.pay("op", "bob", 100)["payment_id"] for _ in range(3)]
rec = {}
def single(pid, amt):
    rev = max(r["revision"] for r in w.revs("op", pid))
    s, o = w.correct("op", pid, rev, amt, E)
    assert s == 201, (s, o)
    assert o.get("correction_batch_id", None) is None, o
    return o
for a in (110, 120, 130):
    single(P1, a)
single(P2, 140)
prev = max(dt(r["recorded_at"]) for p in (P1, P2, P3) for r in w.revs("op", p))
s, o = w.batch("op", [item(P3, 1, 90, E), item(P1, 4, 80, E), item(P2, 2, 70, E)])
exp("U33 batch 201", (s, o), 201)
check("U33 body keys are exactly correction_batch_id, recorded_at, revisions", sorted(o) == ["correction_batch_id", "recorded_at", "revisions"], sorted(o))
check("U33 revisions in input order", [r["payment_id"] for r in o["revisions"]] == [P3, P1, P2])
check("U33 revision numbers follow each payment's own history [2,5,3]", [r["revision"] for r in o["revisions"]] == [2, 5, 3], [r["revision"] for r in o["revisions"]])
check("U34 every revision shares recorded_at with the batch", all(r["recorded_at"] == o["recorded_at"] for r in o["revisions"]))
check("U34 every revision carries correction_batch_id", all(r.get("correction_batch_id") == o["correction_batch_id"] for r in o["revisions"]))
check("U34 recorded_at strictly later than every member's previous recorded_at (P1 had 4 revisions, P2 2, P3 1)", dt(o["recorded_at"]) > prev, (o["recorded_at"], prev.isoformat()))
check("U33 revision objects carry payment_id, revision, amount, effective_at, recorded_at, reason, correction_batch_id",
      all(set(("payment_id", "revision", "amount", "effective_at", "recorded_at", "reason", "correction_batch_id")) <= set(r) for r in o["revisions"]))
for p in (P1, P2, P3):
    rv = w.revs("op", p)
    times = [dt(r["recorded_at"]) for r in rv]
    check("U34 /revisions of %s strictly increasing recorded_at" % p, all(a < b for a, b in zip(times, times[1:])), [r["recorded_at"] for r in rv])
    check("U34 /revisions of %s: only the batch revision has the batch id, others null" % p,
          [r["correction_batch_id"] for r in rv][:-1] == [None] * (len(rv) - 1) and rv[-1]["correction_batch_id"] == o["correction_batch_id"], rv)
rvb = w.revs("bob", P1)
check("U34 the receiver reads the same revisions", rvb == w.revs("op", P1))
n = single(P1, 60)
check("U34 a single correction after a batch records later than the batch and has null batch id", dt(n["recorded_at"]) > dt(o["recorded_at"]) and n["correction_batch_id"] is None, n)
s, o2 = w.batch("op", [item(P2, 3, 65, E)])
check("U34 distinct batches get distinct ids", o2["correction_batch_id"] != o["correction_batch_id"])
# tight alternation: strict monotonicity per payment under same-tick pressure
ok = True
for i in range(40):
    r = max(x["revision"] for x in w.revs("op", P1))
    if i % 2:
        s, x = w.batch("op", [item(P1, r, 50 + i, E), item(P3, max(y["revision"] for y in w.revs("op", P3)), 40 + i, E)])
    else:
        s, x = w.correct("op", P1, r, 50 + i, E)
    ok = ok and s == 201
for p in (P1, P3):
    times = [dt(r["recorded_at"]) for r in w.revs("op", p)]
    check("U34 40 alternating batch/single writes: %s recorded_at strictly increasing (%d revisions)" % (p, len(times)), all(a < b for a, b in zip(times, times[1:])) and ok)
# known_at views before/after the batch instant
s, st1 = svc.j("GET", "/statement?known_at=" + o2["recorded_at"].replace("+", "%2B"), w.tok["bob"])
ent = [e for e in st1["entries"] if e["payment"]["payment_id"] == P2][0]
check("U34 known_at == batch recorded_at already sees the batch revision (at-or-before)", ent["revision"] == 4 and ent["payment"]["amount"] == 65, ent)
t_before = (dt(o2["recorded_at"]) - timedelta(microseconds=1)).isoformat().replace("+", "%2B")
s, st0 = svc.j("GET", "/statement?known_at=" + t_before, w.tok["bob"])
ent = [e for e in st0["entries"] if e["payment"]["payment_id"] == P2][0]
check("U34 known_at 1us before the batch sees the previous revision", ent["revision"] == 3 and ent["payment"]["amount"] != 65, ent)

# ---------------------------------------------------------------- U35 effective time cannot be later than now
w = World(svc, fixture({h: 5000 for h in ["op", "bob"]}))
P = w.pay("op", "bob", 100)["payment_id"]
for name, e in [("now+2s", iso(now() + timedelta(seconds=2))), ("now+1h", iso(now() + timedelta(hours=1))), ("year 2099", "2099-01-01T00:00:00+00:00"),
                ("now+2s spelled +14:00", iso(now() + timedelta(seconds=2), 14)), ("now+1h spelled -12:00", iso(now() + timedelta(hours=1), -12))]:
    b = svc.export()
    exp("U35 effective_at %s -> 422" % name, w.batch("op", [item(P, 1, 90, e)]), 422, "validation_failed")
    check("U35 %s: state unchanged" % name, svc.export() == b)
exp("U35 effective_at a few seconds ago spelled +14:00 -> 201", w.batch("op", [item(P, 1, 90, iso(now() - timedelta(seconds=3), 14))]), 201)

# ---------------------------------------------------------------- U36 originals and receipts never change
w = World(svc, fixture({h: 5000 for h in ["op", "ada", "bob", "cy"]}))
orig = {}
k1 = key("orig-pay")
s, b1 = w.svc.call("POST", "/payments", w.tok["ada"], k1, {"to_handle": "bob", "amount": 500, "note": "n", "visibility": "public"})
assert s == 201
pid = json.loads(b1)["payment_id"]
ks = key("orig-set")
sb = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 100}]}
s, b2 = svc.call("POST", "/settlements", w.tok["op"], ks, sb)
assert s == 201
sres = json.loads(b2)
members = [p["payment_id"] for p in sres["payments"]]
kr = key("orig-ref")
s, b3 = svc.call("POST", "/payments/%s/refunds" % pid, w.tok["bob"], kr, {"amount": 50})
assert s == 201
kc = key("orig-corr")
cbody = {"expected_revision": 1, "amount": 450, "effective_at": E, "reason": "single"}
s, b4 = svc.call("POST", "/payments/%s/corrections" % pid, w.tok["ada"], kc, cbody)
assert s == 201
act0 = {h: svc.call("GET", "/activity?limit=200", w.tok[h])[1] for h in ("ada", "bob", "cy")}
rev1_0 = w.revs("ada", pid)[0]
s, bb = svc.call("POST", "/correction-batches", w.tok["op"], key(), {"corrections": [item(pid, 2, 300, E)] + [item(m, 1, 10, E) for m in members]})
check("U36 batch over the original payment and the whole settlement -> 201", s == 201, bb)
for name, path, tok, k, body, orig_b in [("payment", "/payments", "ada", k1, {"to_handle": "bob", "amount": 500, "note": "n", "visibility": "public"}, b1),
                                          ("settlement", "/settlements", "op", ks, sb, b2),
                                          ("refund", "/payments/%s/refunds" % pid, "bob", kr, {"amount": 50}, b3),
                                          ("correction", "/payments/%s/corrections" % pid, "ada", kc, cbody, b4)]:
    s, b = svc.call("POST", path, w.tok[tok], k, body)
    check("U36 replay of original %s after the batch -> 200, byte-identical body" % name, s == 200 and b == orig_b, (s, b[:200], orig_b[:200]))
check("U36 revision 1 of the payment unchanged", w.revs("ada", pid)[0] == rev1_0)
for h in ("ada", "bob", "cy"):
    check("U36 /activity of %s unchanged by the batch (originals keep their original amounts)" % h, svc.call("GET", "/activity?limit=200", w.tok[h])[1] == act0[h])

# ---------------------------------------------------------------- U37 snapshots
w = World(svc, fixture({h: 5000 for h in ["op", "ada", "bob"]}))
A = [w.pay("ada", "bob", a)["payment_id"] for a in (100, 200, 300)]
def page(tok, token, limit, offset):
    return svc.j("GET", "/statement?snapshot=%s&limit=%d&offset=%d" % (token, limit, offset), w.tok[tok])
sb0 = svc.j("GET", "/statement?limit=2", w.tok["bob"])[1]
tok_b = sb0["snapshot"]
frozen = {(l, o): page("bob", tok_b, l, o) for l, o in [(2, 0), (2, 2), (1, 1), (50, 0)]}
sa0 = svc.j("GET", "/statement?limit=1", w.tok["ada"])[1]
tok_a = sa0["snapshot"]
fro_a = {(l, o): page("ada", tok_a, l, o) for l, o in [(1, 0), (1, 2), (50, 0)]}
s, o = w.batch("op", [item(A[0], 1, 0, E), item(A[1], 1, 50, E)])
assert s == 201, (s, o)
for (l, off), exp0 in frozen.items():
    r = page("bob", tok_b, l, off)
    check("U37 bob's old token still pages limit=%d offset=%d exactly as before the batch" % (l, off), r == exp0, (r, exp0))
for (l, off), exp0 in fro_a.items():
    r = page("ada", tok_a, l, off)
    check("U37 ada's old token limit=%d offset=%d frozen" % (l, off), r == exp0, (r, exp0))
check("U37 old token still reports the old closing balance and the 100/200/300 amounts",
      [e["payment"]["amount"] for e in frozen[(50, 0)][1]["entries"]] == [100, 200, 300] and frozen[(50, 0)][1]["closing_balance"] == 5600, frozen[(50, 0)])
new = svc.j("GET", "/statement?limit=50", w.tok["bob"])[1]
amts = {e["payment"]["payment_id"]: (e["payment"]["amount"], e["revision"], e["delta"]) for e in new["entries"]}
check("U37 a new statement shows the batch revisions (revision 2, amounts 0 and 50)", amts[A[0]] == (0, 2, 0) and amts[A[1]] == (50, 2, 50) and amts[A[2]] == (300, 1, 300), amts)
check("U37 new statement closing balance reflects the batch (5000 + 0 + 50 + 300)", new["closing_balance"] == 5350, new["closing_balance"])
check("U37 new statement balances add up", new["opening_balance"] + sum(e["delta"] for e in new["entries"]) == new["closing_balance"])
tok_new = new["snapshot"]
fro_new = page("bob", tok_new, 50, 0)
s, o = w.batch("op", [item(A[2], 1, 10, E)])
check("U37 a token taken after the batch also survives the next batch", page("bob", tok_new, 50, 0) == fro_new)
check("U37 another user's token is 404", svc.j("GET", "/statement?snapshot=%s" % tok_b, w.tok["ada"])[0] == 404)
check("U37 snapshot with from= is 422", svc.j("GET", "/statement?snapshot=%s&from=2020-01-01T00:00:00%%2B00:00" % tok_b, w.tok["bob"])[0] == 422)

# ---------------------------------------------------------------- U38 replay
w = World(svc, fixture({h: 5000 for h in ["op", "op2", "ada", "bob"]}, ops=("op", "op2")))
Q = [w.pay("ada", "bob", 100)["payment_id"] for _ in range(4)]
K = key("replay")
body = {"corrections": [item(Q[0], 1, 90, E), item(Q[1], 1, 80, E)]}
s, b1 = svc.call("POST", "/correction-batches", w.tok["op"], K, body)
check("U38 first use 201", s == 201)
s, b2 = svc.call("POST", "/correction-batches", w.tok["op"], K, body)
check("U38 replay 200 byte-identical", s == 200 and b2 == b1, (s, b2[:200]))
s, b3 = svc.call("POST", "/correction-batches", w.tok["op"], K, raw=json.dumps({"corrections": [dict(reversed(list(i.items()))) for i in body["corrections"]]}, indent=3).encode())
check("U38 same JSON value (reordered keys, other whitespace) is a replay 200, same bytes", s == 200 and b3 == b1, (s, b3[:200]))
w.correct("ada", Q[0], 2, 95, E)  # newer revision exists now
s, b4 = svc.call("POST", "/correction-batches", w.tok["op"], K, body)
check("U38 replay after a newer revision still returns the original response", s == 200 and b4 == b1)
s, o = svc.j("POST", "/correction-batches", w.tok["op"], K, {"corrections": [item(Q[2], 1, 90, E)]})
check("U38 same key, different body -> 409 idempotency_key_reuse", s == 409 and code(o) == "idempotency_key_reuse", (s, o))
s, o = svc.j("POST", "/correction-batches", w.tok["op"], K, {"corrections": [item(Q[0], 1, -9, E)]})
check("U38 same key, body changed to an invalid one -> still 409 key reuse (resolved before validation)", s == 409 and code(o) == "idempotency_key_reuse", (s, o))
s, o = svc.j("POST", "/correction-batches", w.tok["op"], K, {"corrections": []})
check("U38 same key, empty corrections -> 409 key reuse", s == 409 and code(o) == "idempotency_key_reuse", (s, o))
s, o = svc.j("POST", "/correction-batches", w.tok["op2"], K, {"corrections": [item(Q[3], 1, 90, E)]})
check("U38 another operator may use the same key string independently (201)", s == 201, (s, o))
s, o = svc.j("POST", "/settlements", w.tok["op"], K, {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})
check("U38 the same key on another path (settlements) is a first use (201), not a replay", s == 201, (s, o))
s, o = svc.j("POST", "/payments/%s/corrections" % Q[2], w.tok["ada"], K, {"expected_revision": 1, "amount": 99, "effective_at": E, "reason": "x"})
check("U38 the same key on a single correction is a first use (201)", s == 201, (s, o))
s, b5 = svc.call("POST", "/correction-batches", w.tok["op"], K, body)
check("U38 and the batch replay is still intact afterwards", s == 200 and b5 == b1)

# ---------------------------------------------------------------- U39 refunds of settlement members x batches
SETKEY = key("world4-settle")
SETBODY = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 300}, {"from_handle": "bob", "to_handle": "cy", "amount": 200}, {"from_handle": "cy", "to_handle": "dee", "amount": 100}]}


def world4():
    w = World(svc, fixture({h: 1000 for h in ["op", "ada", "bob", "cy", "dee", "eve"]}))
    s, sr = w.settle("op", SETBODY["transfers"], k=SETKEY)
    assert s == 201
    return w, sr, [p["payment_id"] for p in sr["payments"]]

w, sr, M = world4()
s, rf = w.refund("bob", M[0], 100)
check("U39 refund of a settlement member -> 201", s == 201, (s, rf))
check("U39 refund payment: refund_of names the member, settlement_id null", rf.get("refund_of") == M[0] and "settlement_id" in rf and rf["settlement_id"] is None, rf)
act = svc.j("GET", "/activity?limit=200", w.tok["ada"])[1]["payments"]
mem = {p["payment_id"]: p.get("settlement_id") for p in act}
check("U39 members keep settlement_id, refund has none", mem.get(M[0]) == sr["settlement_id"] and mem.get(rf["payment_id"]) is None, mem)
# member completeness counts original members only: all three, refund not included
b = svc.export()
exp("U39 batch with the refund payment as an item -> linked_payment_immutable", w.batch("op", [item(M[0], 1, 150, E), item(M[1], 1, 150, E), item(M[2], 1, 50, E), item(rf["payment_id"], 1, 1, E)]), 422, "linked_payment_immutable")
check("U39 ...and nothing changed", svc.export() == b)
exp("U39 batch of two original members with the refund present -> incomplete_settlement", w.batch("op", [item(M[0], 1, 150, E), item(M[1], 1, 150, E)]), 422, "incomplete_settlement")
exp("U39 batch lowering the refunded member to 99 (< refunded 100) -> refund_exceeds_payment", w.batch("op", [item(M[0], 1, 99, E), item(M[1], 1, 150, E), item(M[2], 1, 50, E)]), 422, "refund_exceeds_payment")
check("U39 ...nothing changed", svc.export() == b)
r = w.batch("op", [item(M[0], 1, 100, E), item(M[1], 1, 150, E), item(M[2], 1, 50, E)])
exp("U39 batch of all original members, refunded member lowered to exactly the refunded 100 -> 201", r, 201)
exp("U39 now a refund of 1 more exceeds the corrected amount -> 422 refund_exceeds_payment", w.refund("bob", M[0], 1), 422, "refund_exceeds_payment")
r = w.batch("op", [item(M[0], 2, 400, E), item(M[1], 2, 150, E), item(M[2], 2, 50, E)])
exp("U39 batch raising the refunded member to 400 -> 201", r, 201)
exp("U39 refund of 300 more (cumulative 400 == corrected) -> 201", w.refund("bob", M[0], 300), 201)
exp("U39 refund of 1 more -> 422", w.refund("bob", M[0], 1), 422, "refund_exceeds_payment")
rep = svc.j("POST", "/settlements", w.tok["op"], SETKEY, SETBODY)
check("U39 settlement replay after refunds and batches -> 200, original receipt (3 members, membership unchanged)", rep[0] == 200 and rep[1] == sr and len(rep[1]["payments"]) == 3, rep)
# U39 funds boundary with a refund and a hold (bob: 1000+300-100 refund = 1200; hold 1100 -> available 100)
w = World(svc, fixture({h: 1000 for h in ["op", "ada", "bob", "eve"]}))
s, sr = w.settle("op", [{"from_handle": "ada", "to_handle": "bob", "amount": 300}])
m = sr["payments"][0]["payment_id"]
exp("U39 setup refund 100", w.refund("bob", m, 100), 201)
s, a = svc.j("POST", "/authorizations", w.tok["bob"], key(), {"to_handle": "eve", "amount": 1100})
mm = w.me("bob")
check("U39 setup: bob total 1200 held 1100 available 100", (mm["total"], mm["held"], mm["available"]) == (1200, 1100, 100), mm)
b = svc.export()
exp("U39 lowering the member to 100 debits bob 200 > available 100 -> insufficient_funds", w.batch("op", [item(m, 1, 100, E)]), 409, "insufficient_funds")
check("U39 ...unchanged", svc.export() == b)
exp("U39 lowering the member to 200 debits bob 100 = available -> 201", w.batch("op", [item(m, 1, 200, E)]), 201)
mm = w.me("bob")
check("U39 afterwards bob total 1100 held 1100 available 0", (mm["total"], mm["held"], mm["available"]) == (1100, 1100, 0), mm)

# ---------------------------------------------------------------- historical boundaries through the batch route, incl. a hold placed in the past
T = now()
seed = [{"id": "p_h1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "", "visibility": "public", "created_at": iso(T - timedelta(hours=3))},
        {"id": "p_h2", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 300, "note": "", "visibility": "public", "created_at": iso(T - timedelta(hours=1))}]
auth = [{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_dee", "amount": 500, "note": "", "visibility": "public", "status": "open",
         "created_at": iso(T - timedelta(hours=2, minutes=30)), "expires_at": iso(T + timedelta(hours=2))}]
fx = fixture({"op": 0, "ada": 800, "bob": 1000, "cy": 1000, "dee": 0}, seed, extra={"authorizations": auth})
w = World(svc, fx)
mm = w.me("ada")
check("hist setup: ada total 800 held 500 available 300", (mm["total"], mm["held"], mm["available"]) == (800, 500, 300), mm)
b = svc.export()
exp("U30 batch lowering p_h1 to 400 at T-3h: current avail ok (300-100) but available is negative at the T-2.5h hold boundary -> historical_overdraft",
    w.batch("op", [item("p_h1", 1, 400, iso(T - timedelta(hours=3)))]), 409, "historical_overdraft")
check("hist unchanged after rollback", svc.export() == b)
exp("U30 lowering p_h1 with effective_at T-2h removes it before the T-2.5h hold boundary too -> historical_overdraft", w.batch("op", [item("p_h1", 1, 400, iso(T - timedelta(hours=2)))]), 409, "historical_overdraft")
exp("U30 decrease p_h1 effective T-3h by 0 (no-op) -> 201", w.batch("op", [item("p_h1", 1, 500, iso(T - timedelta(hours=3)))]), 201)

print("\nPART2 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
if FAILS:
    print("FAILED: %s" % FAILS)
svc.stop()
sys.exit(1 if FAILS else 0)
