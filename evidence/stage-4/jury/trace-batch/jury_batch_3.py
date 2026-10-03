"""jury checks, part 3: U40 concurrency over HTTP and U42 the ten idempotent write paths (batch is the tenth)."""
import json
import sys
from datetime import datetime, timedelta

from jlib import *

EXE = sys.argv[1]
svc = Svc(EXE)


def dt(s):
    return datetime.fromisoformat(s)


def nowE():
    return iso(now())


def statuses(rs):
    return sorted(r[0] for r in rs)


# ---------------------------------------------------------------- U40 C1: 16 batches sharing one payment revision, each with a private payment too
w = World(svc, fixture({h: 100000 for h in ["op", "bob", "cy"]}))
total0 = w.total()
for rnd in range(4):
    SH = w.pay("op", "bob", 1000)["payment_id"]
    PR = [w.pay("op", "cy", 10)["payment_id"] for _ in range(16)]
    E = nowE()
    rs = parallel([(lambda i=i: w.batch_raw("op", [item(PR[i], 1, 20 + i, E), item(SH, 1, 1000 + i + 1, E)])) for i in range(16)])
    st = [r[0] for r in rs]
    check("U40/C1 round %d: 16 batches share SH rev 1 -> exactly one 201, 15 x 409 stale_revision" % rnd,
          sorted(st) == [201] + [409] * 15 and all(json.loads(r[1])["error"]["code"] == "stale_revision" for r in rs if r[0] == 409), st)
    win = st.index(201)
    check("U40/C1 round %d: the shared payment has exactly 2 revisions and carries the winner's amount" % rnd,
          [r["amount"] for r in w.revs("op", SH)] == [1000, 1000 + win + 1], [r["amount"] for r in w.revs("op", SH)])
    others = [len(w.revs("op", PR[i])) for i in range(16)]
    check("U40/C1 round %d: only the winner's private payment was revised (losers rolled back atomically)" % rnd,
          others == [2 if i == win else 1 for i in range(16)], others)
    check("U40/C1 round %d: sum of balances conserved" % rnd, w.total() == total0)

# ---------------------------------------------------------------- C2: batches and single corrections racing on the same payment revision
for rnd in range(5):
    P = w.pay("op", "bob", 500)["payment_id"]
    E = nowE()
    fns = [(lambda i=i: w.batch_raw("op", [item(P, 1, 100 + i, E)])) for i in range(6)]
    fns += [(lambda i=i: (lambda r: (r[0], json.dumps(r[1]).encode()))(w.correct("op", P, 1, 200 + i, E))) for i in range(6)]
    rs = parallel(fns)
    st = [r[0] for r in rs]
    check("U40/C2 round %d: 6 batches + 6 single corrections on one revision -> exactly one 201" % rnd, sorted(st) == [201] + [409] * 11, st)
    check("U40/C2 round %d: the payment has exactly 2 revisions" % rnd, len(w.revs("op", P)) == 2)

# ---------------------------------------------------------------- C3: rings of overlapping batches: winners disjoint, every loser overlaps a winner
for rnd, n in enumerate([3, 5, 8, 12]):
    R = [w.pay("op", "cy", 10)["payment_id"] for _ in range(n)]
    E = nowE()
    sets = [(i, (i + 1) % n) for i in range(n)]
    rs = parallel([(lambda a=a, b=b: w.batch_raw("op", [item(R[a], 1, 11, E), item(R[b], 1, 12, E)])) for a, b in sets])
    win = [i for i, r in enumerate(rs) if r[0] == 201]
    lose = [i for i, r in enumerate(rs) if r[0] != 201]
    used = [x for i in win for x in sets[i]]
    check("U40/C3 ring n=%d: winners pairwise disjoint (%d winners)" % (n, len(win)), len(used) == len(set(used)) and len(win) >= 1, (win, [r[0] for r in rs]))
    check("U40/C3 ring n=%d: every loser got 409 stale_revision and overlaps a winner" % n,
          all(rs[i][0] == 409 and json.loads(rs[i][1])["error"]["code"] == "stale_revision" and (set(sets[i]) & set(used)) for i in lose), [r[0] for r in rs])
    revs = [len(w.revs("op", p)) for p in R]
    check("U40/C3 ring n=%d: every payment has <= 2 revisions, exactly the winners' payments have 2" % n, revs == [2 if i in set(used) else 1 for i in range(n)], revs)
check("U40/C3 sum of balances conserved", w.total() == total0)

# ---------------------------------------------------------------- C4: funds race: 8 batches each debiting ada 80 of her 100 available
w4 = World(svc, fixture({"op": 0, "ada": 1080, "bob": 0, "cy": 0}))  # 80 of it is paid away below
tot4 = w4.total()
PS = [w4.pay("ada", "bob", 10)["payment_id"] for _ in range(8)]
s, a = svc.j("POST", "/authorizations", w4.tok["ada"], key(), {"to_handle": "cy", "amount": 810})
m = w4.me("ada")
check("U40/C4 setup: ada total 1000 held 810 available 190", (m["total"], m["held"], m["available"]) == (1000, 810, 190), m)
E = nowE()
rs = parallel([(lambda i=i: w4.batch_raw("op", [item(PS[i], 1, 100, E)])) for i in range(8)])  # each debits ada 90
st = [r[0] for r in rs]
check("U40/C4 8 batches each debiting ada 90 with 190 available: exactly two win, six 409 insufficient_funds",
      sorted(st) == [201] * 2 + [409] * 6 and all(json.loads(r[1])["error"]["code"] == "insufficient_funds" for r in rs if r[0] == 409), st)
m = w4.me("ada")
check("U40/C4 ada ends with available 10, never negative", m["available"] == 10 and m["total"] == 820, m)
check("U40/C4 conserved", w4.total() == tot4)

# ---------------------------------------------------------------- C5: batch vs refund on one payment: exactly one of {refund, lowering below it} succeeds
w5 = World(svc, fixture({"op": 0, "ada": 100000, "bob": 100000}))
tot5 = w5.total()
res = []
for rnd in range(12):
    P = w5.pay("ada", "bob", 100)["payment_id"]
    E = nowE()
    rs = parallel([lambda: w5.refund("bob", P, 60), lambda: w5.batch("op", [item(P, 1, 50, E)])])
    (rs_s, rs_o), (bs, bo) = rs
    final = w5.revs("ada", P)[-1]["amount"]
    refunded = 60 if rs_s == 201 else 0
    res.append((rs_s, bs))
    check("U40/C5 round %d: refund 60 vs batch lowering to 50: never both succeed, never both fail (refund %s, batch %s)" % (rnd, rs_s, bs),
          (rs_s == 201) != (bs == 201) and refunded <= final, (rs, final))
print("C5 outcomes (refund status, batch status):", sorted(set(res)))
check("U40/C5 conserved", w5.total() == tot5)

# ---------------------------------------------------------------- C6: same key, same body, 20 threads: exactly one effect
w6 = World(svc, fixture({"op": 0, "ada": 100000, "bob": 100000}))
M = [w6.pay("ada", "bob", 100)["payment_id"] for _ in range(3)]
E = nowE()
ada0, bob0 = w6.me("ada")["balance"], w6.me("bob")["balance"]
K = key("same")
body = {"corrections": [item(M[0], 1, 150, E), item(M[1], 1, 50, E), item(M[2], 1, 100, E)]}
rs = parallel([(lambda: svc.call("POST", "/correction-batches", w6.tok["op"], K, body)) for _ in range(20)])
st = [r[0] for r in rs]
check("U42/batch concurrent same key: exactly one 201 and 19 x 200", sorted(st) == [200] * 19 + [201], st)
bodies = {r[1] for r in rs}
check("U42/batch concurrent same key: all 20 bodies identical bytes", len(bodies) == 1, len(bodies))
check("U42/batch concurrent same key: one effect (each member has exactly 2 revisions)", [len(w6.revs("ada", p)) for p in M] == [2, 2, 2])
check("U42/batch concurrent same key: money moved once (+50 for M0, -50 for M1 => ada net 0; bob net 0 but each revision applied once)",
      w6.me("ada")["balance"] == ada0 and w6.me("bob")["balance"] == bob0, (w6.me("ada")["balance"], ada0))
check("U42/batch concurrent same key: amounts are the batch's (150, 50, 100)", [w6.revs("ada", p)[-1]["amount"] for p in M] == [150, 50, 100])
# two different bodies, same key, 10 threads each
K2 = key("diff")
b1 = {"corrections": [item(M[0], 2, 160, E)]}
b2 = {"corrections": [item(M[1], 2, 60, E)]}
rs = parallel([(lambda b=b1: svc.call("POST", "/correction-batches", w6.tok["op"], K2, b)) for _ in range(10)] +
              [(lambda b=b2: svc.call("POST", "/correction-batches", w6.tok["op"], K2, b)) for _ in range(10)])
first = [r for r in rs[:10]]
second = [r for r in rs[10:]]
win_a = sorted(r[0] for r in first) == [200] * 9 + [201] and all(r[0] == 409 for r in second)
win_b = sorted(r[0] for r in second) == [200] * 9 + [201] and all(r[0] == 409 for r in first)
check("U42/batch same key, two different bodies racing: exactly one body wins (one 201, its replays 200, the other body all 409)", win_a != win_b, [r[0] for r in rs])
check("U42/batch ...and only one of the two payments gained a revision", sorted([len(w6.revs("ada", M[0])), len(w6.revs("ada", M[1]))]) == [2, 3], [len(w6.revs("ada", M[0])), len(w6.revs("ada", M[1]))])

# ---------------------------------------------------------------- U42 the ten idempotent write paths
W = World(svc, fixture({h: 100000 for h in ["op", "ada", "bob", "cy"]}))
TAG = [0]


def mk(name):
    TAG[0] += 1
    return "u42-%s-%d" % (name, TAG[0])


def activity(h):
    return svc.j("GET", "/activity?limit=200", W.tok[h])[1]["payments"]


def requests_of(h):
    return svc.j("GET", "/requests?limit=200", W.tok[h])[1]["requests"]


def auths_of(h):
    return svc.j("GET", "/authorizations?limit=200", W.tok[h])[1]["authorizations"]


# each spec: setup(W)->ctx ; call(ctx, variant)->(path, handle, body) ; effect(ctx)->int (count of effects)
def s_payments():
    note = mk("pay")
    return {"note": note}, (lambda c, v: ("/payments", "ada", {"to_handle": "bob", "amount": 10 + v, "note": c["note"]})), \
        (lambda c: len([p for p in activity("ada") if p["note"] == c["note"]]))


def s_requests():
    note = mk("req")
    return {"note": note}, (lambda c, v: ("/requests", "bob", {"payer_handle": "ada", "amount": 20 + v, "note": c["note"]})), \
        (lambda c: len([r for r in requests_of("bob") if r["note"] == c["note"]]))


def s_reqpay():
    note = mk("rqp")
    s, rq = svc.j("POST", "/requests", W.tok["bob"], key(), {"payer_handle": "ada", "amount": 30, "note": note})
    return {"rid": rq["request_id"]}, (lambda c, v: ("/requests/%s/pay" % c["rid"], "ada", {"visibility": "public" if v == 0 else "private"})), \
        (lambda c: len([p for p in activity("ada") if p.get("request_id") == c["rid"]]))


def s_splits():
    note = mk("spl")
    return {"note": note}, (lambda c, v: ("/splits", "ada", {"amount": 3000 + v, "participant_handles": ["ada", "bob", "cy"], "note": c["note"]})), \
        (lambda c: len([r for r in requests_of("bob") if r["note"] == c["note"]]) + len([r for r in requests_of("cy") if r["note"] == c["note"]]) - 0)


def s_settlements():
    note = mk("set")
    return {"note": note}, (lambda c, v: ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5 + v, "note": c["note"]}]})), \
        (lambda c: len([p for p in activity("ada") if p["note"] == c["note"]]))


def s_auths():
    note = mk("aut")
    return {"note": note}, (lambda c, v: ("/authorizations", "ada", {"to_handle": "bob", "amount": 40 + v, "note": c["note"]})), \
        (lambda c: len([a for a in auths_of("ada") if a["note"] == c["note"]]))


def s_capture():
    note = mk("cap")
    s, a = svc.j("POST", "/authorizations", W.tok["ada"], key(), {"to_handle": "bob", "amount": 100, "note": note})
    return {"aid": a["authorization_id"]}, (lambda c, v: ("/authorizations/%s/capture" % c["aid"], "bob", {"amount": 50 + v, "final": False})), \
        (lambda c: len([1 for p in activity("bob") if p.get("authorization_id") == c["aid"]]))


def s_correction():
    p = W.pay("ada", "bob", 100)["payment_id"]
    E = nowE()
    return {"p": p, "E": E}, (lambda c, v: ("/payments/%s/corrections" % c["p"], "ada", {"expected_revision": 1, "amount": 90 + v, "effective_at": c["E"], "reason": "u42"})), \
        (lambda c: len(W.revs("ada", c["p"])) - 1)


def s_refund():
    p = W.pay("ada", "bob", 100)["payment_id"]
    return {"p": p}, (lambda c, v: ("/payments/%s/refunds" % c["p"], "bob", {"amount": 30 + v})), \
        (lambda c: len([x for x in activity("ada") if x.get("refund_of") == c["p"]]))


def s_batch():
    p = W.pay("ada", "bob", 100)["payment_id"]
    q = W.pay("ada", "bob", 100)["payment_id"]
    E = nowE()
    return {"p": p, "q": q, "E": E}, (lambda c, v: ("/correction-batches", "op", {"corrections": [item(c["p"], 1, 90 + v, c["E"]), item(c["q"], 1, 80, c["E"])]})), \
        (lambda c: len(W.revs("ada", c["p"])) - 1 + len(W.revs("ada", c["q"])) - 1)


SPECS = [("POST /payments", s_payments, 1), ("POST /requests", s_requests, 1), ("POST /requests/{id}/pay", s_reqpay, 1),
         ("POST /splits", s_splits, 2), ("POST /settlements", s_settlements, 1), ("POST /authorizations", s_auths, 1),
         ("POST /authorizations/{id}/capture", s_capture, 1), ("POST /payments/{id}/corrections", s_correction, 1),
         ("POST /payments/{id}/refunds", s_refund, 1), ("POST /correction-batches", s_batch, 2)]
for name, mkspec, want in SPECS:
    ctx, call, effect = mkspec()
    path, h, body = call(ctx, 0)
    K = key("u42")
    s1, b1 = svc.call("POST", path, W.tok[h], K, body)
    check("U42 %s: first use 201" % name, s1 == 201, (s1, b1[:200]))
    s2, b2 = svc.call("POST", path, W.tok[h], K, body)
    check("U42 %s: replay -> 200, identical bytes" % name, s2 == 200 and b2 == b1, (s2, b2[:160]))
    path2, h2, body2 = call(ctx, 1)
    s3, b3 = svc.call("POST", path2, W.tok[h2], K, body2)
    check("U42 %s: same key, different body -> 409 idempotency_key_reuse" % name, s3 == 409 and code(json.loads(b3)) == "idempotency_key_reuse", (s3, b3[:160]))
    check("U42 %s: exactly one effect after first+replay+reuse (%d expected)" % (name, want), effect(ctx) == want, effect(ctx))
    # concurrent same key on a fresh context
    ctx, call, effect = mkspec()
    path, h, body = call(ctx, 0)
    K = key("u42c")
    rs = parallel([(lambda: svc.call("POST", path, W.tok[h], K, body)) for _ in range(12)])
    st = sorted(r[0] for r in rs)
    check("U42 %s: 12 concurrent same-key calls -> exactly one 201, eleven 200" % name, st == [200] * 11 + [201], st)
    check("U42 %s: ...identical bodies" % name, len({r[1] for r in rs}) == 1)
    check("U42 %s: ...exactly one effect (%d)" % (name, want), effect(ctx) == want, effect(ctx))
    # key reuse on another path is not a replay: reuse K for GET-free neighbour (payments) with different path
    if name != "POST /payments":
        s4, b4 = svc.call("POST", "/payments", W.tok["ada"], K, {"to_handle": "bob", "amount": 1, "note": mk("x")})
        check("U42 %s: its key used on POST /payments is a first use (201)" % name, s4 == 201, (s4, b4[:160]))
print("balances total conserved over U42:", W.total() == 4 * 100000)
check("U42 sum of balances conserved after all ten paths", W.total() == 4 * 100000)

print("\nPART3 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
if FAILS:
    print("FAILED: %s" % FAILS)
svc.stop()
sys.exit(1 if FAILS else 0)
