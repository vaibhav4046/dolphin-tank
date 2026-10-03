"""S4-TRACE-ATTACK-REFUND: forge's refund code attacked in combination with trace's POST /correction-batches.

usage: python refund_attack.py path/to/pocketful.exe [iterations]

Starts its own server processes (HTTP only, no access to the sources), one fixture per case. Every expectation comes from
the written stage-4 requirements, not from the implementation:
  money conserved; refunded <= the payment's current corrected amount; settlement membership unchanged by refunds;
  a rejected operation leaves GET /_test/export byte-identical; concurrent corrections sharing an expected revision
  cannot both succeed; captures and refund payments cannot be corrected (linked_payment_immutable).
audit() re-derives every wallet from the export (opening balance + every payment at its latest revision) and compares it
with the stored balance, so "ledger exact" is checked against an independent recomputation, not against /me.
Exit status 1 if any check failed.
"""
import collections
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

EXE = sys.argv[1]
ITER = int(sys.argv[2]) if len(sys.argv) > 2 else 60
NAMES = ["ada", "bob", "cy", "dee"]
T1 = "2026-09-20T10:00:00+00:00"
EFF = "2026-09-27T10:00:00+00:00"
failures = []


class Srv:
    def __init__(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.proc = subprocess.Popen([EXE], env={**os.environ, "PORT": str(self.port)},
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = "http://127.0.0.1:%d" % self.port
        for _ in range(100):
            try:
                urllib.request.urlopen(self.base + "/health", timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def call(self, method, path, token=None, key=None, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        if key:
            req.add_header("Idempotency-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def export(self):
        s, b = self.call("GET", "/_test/export")
        assert s == 200, s
        return b

    def restore(self, raw):
        s, b = self.call("POST", "/_test/import", raw=raw)
        assert s == 204, (s, b)

    def stop(self):
        self.proc.kill()


def code(b):
    try:
        return json.loads(b)["error"]["code"]
    except Exception:
        return None


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if (detail and not ok) else ""))
    if not ok:
        failures.append(name)
    return ok


def short(b, n=240):
    return b.decode(errors="replace")[:n] if isinstance(b, bytes) else str(b)[:n]


def fixture(bal, pays):
    users = [{"id": "u_" + n, "email": n + "@example.com", "password": "correct horse", "display_name": n.title(),
              "handle": n, "balance": b} for n, b in zip(NAMES, bal)]
    ps = [{"id": i, "from_user_id": "u_" + f, "to_user_id": "u_" + t, "amount": a, "created_at": at, "note": "seed-" + i}
          for i, f, t, a, at in pays]
    return {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_ada"], "users": users, "payments": ps}


def world(srv, bal=(1000, 500, 100, 0), pays=()):
    s, b = srv.call("POST", "/_test/reset", raw=json.dumps(fixture(bal, pays)).encode())
    assert s == 204, (s, b)
    tok = {}
    for n in NAMES:
        s, b = srv.call("POST", "/auth/login", body={"email": n + "@example.com", "password": "correct horse"})
        assert s == 200, (s, b)
        tok[n] = json.loads(b)["token"]
    return tok


def item(pid, rev, amount, eff=EFF):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "attack"}


def batch(srv, tok, key, *items):
    return srv.call("POST", "/correction-batches", tok["ada"], key, {"corrections": list(items)})


def refund(srv, tok, who, pid, amount, key):
    return srv.call("POST", "/payments/%s/refunds" % pid, tok[who], key, {"amount": amount})


def audit(srv, total0):
    """Independent recomputation of the ledger from the export. Returns a list of problems (empty = exact)."""
    st = json.loads(srv.export())["state"]
    latest = {}
    for r in st.get("revisions", []):
        if r["payment_id"] not in latest or r["revision"] > latest[r["payment_id"]][0]:
            latest[r["payment_id"]] = (r["revision"], r["amount"])
    pays = {p["payment_id"]: p for p in st["payments"]}
    amt = lambda p: latest.get(p["payment_id"], (1, p["amount"]))[1]
    bal = {u["id"]: u["opening_balance"] for u in st["users"]}
    refunded = collections.Counter()
    problems = []
    for p in st["payments"]:
        bal[p["from_user_id"]] -= amt(p)
        bal[p["to_user_id"]] += amt(p)
        if p.get("refund_of") is None:
            continue
        refunded[p["refund_of"]] += p["amount"]
        t = pays.get(p["refund_of"])
        if t is None:
            problems.append("%s refund_of unknown %s" % (p["payment_id"], p["refund_of"]))
            continue
        if (p["from_user_id"], p["to_user_id"]) != (t["to_user_id"], t["from_user_id"]):
            problems.append("%s not the opposite direction of %s" % (p["payment_id"], t["payment_id"]))
        if t.get("refund_of") is not None:
            problems.append("%s refunds a refund" % p["payment_id"])
        if p.get("request_id") is not None or p.get("authorization_id") is not None or p.get("settlement_id") is not None:
            problems.append("%s carries request/authorization/settlement" % p["payment_id"])
        if len(latest.get(p["payment_id"], (1,))) and latest.get(p["payment_id"], (1,))[0] != 1:
            problems.append("%s refund payment was corrected" % p["payment_id"])
    for pid, r in refunded.items():
        if pid in pays and r > amt(pays[pid]):
            problems.append("%s refunded %d > current amount %d" % (pid, r, amt(pays[pid])))
    for u in st["users"]:
        if u["balance"] != bal[u["id"]]:
            problems.append("%s stored balance %d != derived %d" % (u["id"], u["balance"], bal[u["id"]]))
    if sum(u["balance"] for u in st["users"]) != total0:
        problems.append("money not conserved: %d != %d" % (sum(u["balance"] for u in st["users"]), total0))
    return problems


def balances(srv):
    st = json.loads(srv.export())["state"]
    return {u["handle"]: u["balance"] for u in st["users"]}


def amounts(srv):
    st = json.loads(srv.export())["state"]
    latest = {}
    for r in st.get("revisions", []):
        if r["payment_id"] not in latest or r["revision"] > latest[r["payment_id"]][0]:
            latest[r["payment_id"]] = (r["revision"], r["amount"])
    return {p["payment_id"]: latest.get(p["payment_id"], (1, p["amount"])) for p in st["payments"]}


def race(fns):
    bar = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def w(i):
        bar.wait()
        time.sleep(random.random() * 0.003)
        out[i] = fns[i]()

    ts = [threading.Thread(target=w, args=(i,)) for i in range(len(fns))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def refuse(srv, name, call_fn, status, errcode):
    """The call must be refused with status/code and leave /_test/export byte-identical."""
    before = srv.export()
    s, b = call_fn()
    ok = s == status and code(b) == errcode
    ok2 = srv.export() == before
    return check(name, ok and ok2, "got %s %s; export unchanged=%s" % (s, short(b), ok2))


# ---------------------------------------------------------------- case 1
def case1(srv):
    print("== (1) refund vs batch race on one payment: refund 60 vs batch correct to 50 (p_1 = 100)")
    tok = world(srv, pays=[("p_1", "ada", "bob", 100, T1)])
    base = srv.export()
    tally = collections.Counter()
    bad = []
    for i in range(ITER):
        srv.restore(base)
        (rs, rb), (bs, bb) = race([lambda: refund(srv, tok, "bob", "p_1", 60, "r%d" % i),
                                   lambda: batch(srv, tok, "b%d" % i, item("p_1", 1, 50))])
        if rs == 201 and bs == 422 and code(bb) == "refund_exceeds_payment":
            want, tag = {"ada": 1060, "bob": 440, "cy": 100, "dee": 0}, "refund-won"
        elif bs == 201 and rs == 422 and code(rb) == "refund_exceeds_payment":
            want, tag = {"ada": 1050, "bob": 450, "cy": 100, "dee": 0}, "batch-won"
        else:
            tally["BAD"] += 1
            bad.append((i, rs, short(rb, 120), bs, short(bb, 120)))
            continue
        tally[tag] += 1
        got, prob = balances(srv), audit(srv, 1600)
        if got != want or prob:
            bad.append((i, tag, got, prob))
    check("exactly one of refund/batch wins every time, loser 422 refund_exceeds_payment, balances exact (%d runs: %s)"
          % (ITER, dict(tally)), not bad and tally["BAD"] == 0, str(bad[:3]))
    check("both interleavings were exercised", tally["refund-won"] > 0 and tally["batch-won"] > 0, str(dict(tally)))

    # 1b: three refunds of 40 and a batch to 50 on p_1=100, all at once. Only the invariants decide.
    tally = collections.Counter()
    bad = []
    for i in range(ITER):
        srv.restore(base)
        res = race([lambda k=k: refund(srv, tok, "bob", "p_1", 40, "m%d-%d" % (i, k)) for k in range(3)]
                   + [lambda: batch(srv, tok, "mb%d" % i, item("p_1", 1, 50))])
        rs, bs = [r[0] for r in res[:3]], res[3][0]
        okcodes = all(s == 201 or (s == 422 and code(b) == "refund_exceeds_payment") for s, b in res[:3])
        okb = bs == 201 or (bs == 422 and code(res[3][1]) == "refund_exceeds_payment")
        prob = audit(srv, 1600)
        amt = amounts(srv)["p_1"][1]
        n = rs.count(201)
        if not (okcodes and okb) or prob or (bs == 201 and (n > 1 or amt != 50)) or (bs != 201 and (n != 2 or amt != 100)):
            bad.append((i, rs, bs, n, amt, prob))
        tally["batch201-refunds%d" % n if bs == 201 else "batch422-refunds%d" % n] += 1
    check("3 refunds of 40 + batch to 50: only 201/422 refund_exceeds_payment, refunded <= amount, ledger exact (%s)"
          % dict(tally), not bad, str(bad[:3]))


# ---------------------------------------------------------------- shared prelude for cases 2, 3, 5, 6
def settlement_prelude(srv, with_p1=False):
    """ada,bob,cy,dee = 1000,500,100,0. settlement ada>bob 40, bob>cy 30, ada>cy 25, then partial refunds of every member."""
    pays = [("p_1", "ada", "bob", 100, T1)] if with_p1 else []
    tok = world(srv, pays=pays)
    s, b = srv.call("POST", "/settlements", tok["ada"], "st-1", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 40},
        {"from_handle": "bob", "to_handle": "cy", "amount": 30},
        {"from_handle": "ada", "to_handle": "cy", "amount": 25}]})
    assert s == 201, (s, b)
    out = json.loads(b)
    members = [p["payment_id"] for p in out["payments"]]
    sid = out["payments"][0]["settlement_id"]
    assert sid and all(p["settlement_id"] == sid for p in out["payments"])
    refunds = {}
    for who, pid, amount in (("bob", members[0], 30), ("cy", members[1], 10), ("cy", members[2], 20)):
        s, b = refund(srv, tok, who, pid, amount, "rf-" + pid)
        assert s == 201, (s, b)
        refunds[pid] = (json.loads(b), b)
    if with_p1:
        s, b = refund(srv, tok, "bob", "p_1", 60, "rf-p_1")
        assert s == 201, (s, b)
        refunds["p_1"] = (json.loads(b), b)
    return tok, sid, members, refunds


# ---------------------------------------------------------------- case 2
def case2(srv):
    print("== (2) refund of settlement members, then a batch over the whole settlement below / at the refunded amounts")
    tok, sid, (m1, m2, m3), refunds = settlement_prelude(srv)
    check("prelude: refunds 201, refund_of names the member, request/authorization/settlement null",
          all(r[0]["refund_of"] == pid and r[0]["request_id"] is None and r[0]["authorization_id"] is None
              and r[0]["settlement_id"] is None for pid, r in refunds.items()))
    check("prelude audit exact (m1 40 refunded 30, m2 30 refunded 10, m3 25 refunded 20)", not audit(srv, 1600), str(audit(srv, 1600)))
    check("prelude balances", balances(srv) == {"ada": 985, "bob": 490, "cy": 125, "dee": 0}, str(balances(srv)))
    refuse(srv, "batch with every member below its refunded amount -> 422 refund_exceeds_payment, nothing changes",
           lambda: batch(srv, tok, "lo", item(m1, 1, 20), item(m2, 1, 5), item(m3, 1, 10)), 422, "refund_exceeds_payment")
    refuse(srv, "batch, only m1 one below (29 < 30) -> 422 refund_exceeds_payment",
           lambda: batch(srv, tok, "lo1", item(m1, 1, 29), item(m2, 1, 10), item(m3, 1, 20)), 422, "refund_exceeds_payment")
    refuse(srv, "batch, only m2 one below (9 < 10) -> 422 refund_exceeds_payment",
           lambda: batch(srv, tok, "lo2", item(m1, 1, 30), item(m2, 1, 9), item(m3, 1, 20)), 422, "refund_exceeds_payment")
    refuse(srv, "batch, only m3 one below (19 < 20) -> 422 refund_exceeds_payment",
           lambda: batch(srv, tok, "lo3", item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 19)), 422, "refund_exceeds_payment")
    s, b = batch(srv, tok, "exact", item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 20))
    check("batch at exactly the refunded amounts -> 201", s == 201, "%s %s" % (s, short(b)))
    if s == 201:
        out = json.loads(b)
        check("201 carries one batch id on 3 revisions of revision 2, input order",
              [r["payment_id"] for r in out["revisions"]] == [m1, m2, m3] and all(r["revision"] == 2 and r["correction_batch_id"] == out["correction_batch_id"] for r in out["revisions"]))
    check("money after: every payment equals what was refunded, so wallets are back to 1000/500/100/0",
          balances(srv) == {"ada": 1000, "bob": 500, "cy": 100, "dee": 0}, str(balances(srv)))
    check("audit exact after the batch (refunded <= current amount, wallets re-derived from the export)", not audit(srv, 1600), str(audit(srv, 1600)))
    s2, b2 = batch(srv, tok, "exact", item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 20))
    check("replay of the batch -> 200 identical bytes", s2 == 200 and b2 == b, "%s" % s2)
    for pid in (m1, m2, m3):
        refuse(srv, "refund 1 more of %s (refunded == current amount) -> 422 refund_exceeds_payment" % pid,
               lambda pid=pid: refund(srv, tok, "bob" if pid == m1 else "cy", pid, 1, "more-" + pid), 422, "refund_exceeds_payment")
    s, b = batch(srv, tok, "again", item(m1, 2, 29), item(m2, 2, 10), item(m3, 2, 20))
    check("batch on revision 2 below the (unchanged) refunded amount -> 422 refund_exceeds_payment", s == 422 and code(b) == "refund_exceeds_payment", "%s %s" % (s, short(b)))
    s, b = srv.call("POST", "/payments/%s/refunds" % m1, tok["bob"], "rf-" + m1, body={"amount": 30})
    check("replay of an earlier refund after the batch -> 200 original body", s == 200 and b == refunds[m1][1], "%s %s" % (s, short(b)))


# ---------------------------------------------------------------- case 3
def case3():
    print("== (3) import of a state that already holds refunds (fresh process), then a batch over it")
    a, b_ = Srv(), Srv()
    try:
        tok, sid, (m1, m2, m3), refunds = settlement_prelude(a, with_p1=True)
        ea = a.export()
        b_.restore(ea)
        check("export of the imported state is byte-identical (refund_of, ids, keys survive)", b_.export() == ea)
        check("audit exact on the imported state", not audit(b_, 1600), str(audit(b_, 1600)))
        for pid, who in (("p_1", "bob"), (m1, "bob"), (m2, "cy"), (m3, "cy")):
            s, b = b_.call("POST", "/payments/%s/refunds" % pid, tok[who], "rf-" + pid, body={"amount": refunds[pid][0]["amount"]})
            check("refund replay for %s after import -> 200 original body" % pid, s == 200 and b == refunds[pid][1], "%s %s" % (s, short(b)))
        refuse(b_, "after import: batch p_1 to 59 (refunded 60) -> 422 refund_exceeds_payment",
               lambda: batch(b_, tok, "i1", item("p_1", 1, 59)), 422, "refund_exceeds_payment")
        refuse(b_, "after import: batch over the settlement, m3 at 19 (refunded 20) -> 422 refund_exceeds_payment",
               lambda: batch(b_, tok, "i2", item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 19)), 422, "refund_exceeds_payment")
        refuse(b_, "after import: single correction of p_1 to 59 (refunded 60) -> 422 refund_exceeds_payment",
               lambda: b_.call("POST", "/payments/p_1/corrections", tok["ada"], "i3", {"expected_revision": 1, "amount": 59, "effective_at": EFF, "reason": "x"}), 422, "refund_exceeds_payment")
        refuse(b_, "after import: refund p_1 41 more (60+41 > 100) -> 422 refund_exceeds_payment",
               lambda: refund(b_, tok, "bob", "p_1", 41, "i4"), 422, "refund_exceeds_payment")
        refuse(b_, "after import: refund of an imported refund -> 422 invalid_refund_target",
               lambda: refund(b_, tok, "ada", refunds["p_1"][0]["payment_id"], 1, "i5"), 422, "invalid_refund_target")
        rid = refunds[m1][0]["payment_id"]
        refuse(b_, "after import: batch naming an imported refund payment -> 422 linked_payment_immutable",
               lambda: batch(b_, tok, "i6", item(rid, 1, 1)), 422, "linked_payment_immutable")
        refuse(b_, "after import: single correction of an imported refund payment -> 422 linked_payment_immutable",
               lambda: b_.call("POST", "/payments/%s/corrections" % rid, tok["bob"], "i7", {"expected_revision": 1, "amount": 1, "effective_at": EFF, "reason": "x"}), 422, "linked_payment_immutable")
        s, bb = batch(b_, tok, "i8", item("p_1", 1, 60), item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 20))
        check("after import: batch at exactly the refunded amounts (p_1 + whole settlement) -> 201", s == 201, "%s %s" % (s, short(bb)))
        check("after import + batch: audit exact", not audit(b_, 1600), str(audit(b_, 1600)))
        check("after import + batch: every payment equals its refunded amount, so ada/bob hold opening 1100/400 (p_1 seeded 100 before the fixture balances)",
              balances(b_) == {"ada": 1100, "bob": 400, "cy": 100, "dee": 0}, str(balances(b_)))
        for pid, who in (("p_1", "bob"), (m1, "bob"), (m2, "cy"), (m3, "cy")):
            refuse(b_, "after import + batch: refund 1 more of %s -> 422 refund_exceeds_payment" % pid,
                   lambda pid=pid, who=who: refund(b_, tok, who, pid, 1, "i9-" + pid), 422, "refund_exceeds_payment")
        # second round trip: export the corrected state with refunds, import it again elsewhere
        eb = b_.export()
        a.restore(eb)
        check("second round trip (state with refunds AND batch revisions) byte-identical", a.export() == eb)
        refuse(a, "second round trip: batch p_1 to 59 on revision 2 -> 422 refund_exceeds_payment",
               lambda: batch(a, tok, "j1", item("p_1", 2, 59)), 422, "refund_exceeds_payment")
        s, bb2 = batch(a, tok, "i8", item("p_1", 1, 60), item(m1, 1, 30), item(m2, 1, 10), item(m3, 1, 20))
        check("second round trip: batch replay -> 200 identical bytes", s == 200 and bb2 == bb, "%s" % s)
        # remainder: a state imported with room left lets the exact remainder through and no more
        a.restore(ea)
        refuse(a, "limit after import: refund m1 remainder + 1 (10+1) -> 422 refund_exceeds_payment",
               lambda: refund(a, tok, "bob", m1, 11, "k11"), 422, "refund_exceeds_payment")
        s, bb = refund(a, tok, "bob", m1, 10, "k10")
        check("limit after import: refund exactly the remainder (10) -> 201", s == 201, "%s %s" % (s, short(bb)))
        refuse(a, "limit after import: then 1 more -> 422 refund_exceeds_payment",
               lambda: refund(a, tok, "bob", m1, 1, "k1"), 422, "refund_exceeds_payment")
        check("audit exact after the remainder refund", not audit(a, 1600), str(audit(a, 1600)))
    finally:
        a.stop()
        b_.stop()


# ---------------------------------------------------------------- case 4
def case4(srv):
    print("== (4) batch below refunded + single correction on the same payment, concurrently (p_1 = 100, refunded 60)")
    tok = world(srv, pays=[("p_1", "ada", "bob", 100, T1)])
    s, b = refund(srv, tok, "bob", "p_1", 60, "pre")
    assert s == 201, (s, b)
    base = srv.export()
    corr = lambda key, amount: srv.call("POST", "/payments/p_1/corrections", tok["ada"], key,
                                        {"expected_revision": 1, "amount": amount, "effective_at": EFF, "reason": "single"})

    def scenario(label, fb, fs, verdict):
        tally = collections.Counter()
        bad = []
        for i in range(ITER):
            srv.restore(base)
            (bs, bb), (ss, sb) = race([lambda: fb(i), lambda: fs(i)])
            tag, why = verdict(bs, bb, ss, sb)
            tally[tag] += 1
            prob = audit(srv, 1600)
            if why or prob:
                bad.append((i, tag, why, prob, bs, short(bb, 100), ss, short(sb, 100)))
        check("%s (%d runs: %s)" % (label, ITER, dict(tally)), not bad, str(bad[:3]))
        return tally

    # 4a: batch to 50 (< 60) vs single to 80 (>= 60): batch never succeeds, single exactly once, wallets exact
    def v4a(bs, bb, ss, sb):
        okb = (bs == 422 and code(bb) == "refund_exceeds_payment") or (bs == 409 and code(bb) == "stale_revision")
        if ss != 201 or not okb:
            return "BAD", "single %s batch %s" % (ss, bs)
        got, want = balances(srv), {"ada": 1080, "bob": 420, "cy": 100, "dee": 0}
        return "single-won-batch-" + str(bs), (None if got == want and amounts(srv)["p_1"] == (2, 80) else "state %s %s" % (got, amounts(srv)["p_1"]))

    scenario("4a batch to 50 (below refunded) vs single correction to 80: single wins once, batch never, ledger exact",
             lambda i: batch(srv, tok, "ba%d" % i, item("p_1", 1, 50)), lambda i: corr("sa%d" % i, 80), v4a)

    # 4b: both below refunded: both refused, no revision written
    def v4b(bs, bb, ss, sb):
        ok = bs == 422 and code(bb) == "refund_exceeds_payment" and ss == 422 and code(sb) == "refund_exceeds_payment"
        return ("both-422" if ok else "BAD"), (None if ok and srv.export() == base else "batch %s single %s" % (bs, ss))

    scenario("4b batch to 50 vs single correction to 55, both below refunded: both 422, export byte-identical",
             lambda i: batch(srv, tok, "bb%d" % i, item("p_1", 1, 50)), lambda i: corr("sb%d" % i, 55), v4b)

    # 4c: both above refunded, same expected revision: exactly one wins
    def v4c(bs, bb, ss, sb):
        if bs == 201 and ss == 409 and code(sb) == "stale_revision":
            want, tag = {"ada": 1060 + 35, "bob": 440 - 35, "cy": 100, "dee": 0}, "batch-won"
            amt = 65
        elif ss == 201 and bs == 409 and code(bb) == "stale_revision":
            want, tag = {"ada": 1060 + 30, "bob": 440 - 30, "cy": 100, "dee": 0}, "single-won"
            amt = 70
        else:
            return "BAD", "batch %s single %s" % (bs, ss)
        return tag, (None if balances(srv) == want and amounts(srv)["p_1"] == (2, amt) else "state %s %s" % (balances(srv), amounts(srv)["p_1"]))

    t = scenario("4c batch to 65 vs single correction to 70 (both >= refunded, same expected_revision): exactly one wins, loser 409 stale_revision",
                 lambda i: batch(srv, tok, "bc%d" % i, item("p_1", 1, 65)), lambda i: corr("sc%d" % i, 70), v4c)
    check("4c both interleavings exercised", t["batch-won"] > 0 and t["single-won"] > 0, str(dict(t)))

    # 4d: single correction down to exactly the refunded amount vs a further refund of 10
    def v4d(bs, bb, ss, sb):
        if ss == 201 and bs == 422 and code(bb) == "refund_exceeds_payment":
            return "correction-won", None if amounts(srv)["p_1"] == (2, 60) and balances(srv) == {"ada": 1060 + 40, "bob": 440 - 40, "cy": 100, "dee": 0} else "state"
        if bs == 201 and ss == 422 and code(sb) == "refund_exceeds_payment":
            return "refund-won", None if amounts(srv)["p_1"] == (1, 100) and balances(srv) == {"ada": 1070, "bob": 430, "cy": 100, "dee": 0} else "state"
        return "BAD", "refund %s correction %s" % (bs, ss)

    t = scenario("4d single correction to 60 (= refunded) vs refund of 10 more: exactly one wins, loser 422 refund_exceeds_payment",
                 lambda i: refund(srv, tok, "bob", "p_1", 10, "rd%d" % i), lambda i: corr("sd%d" % i, 60), v4d)
    check("4d both interleavings exercised", t["correction-won"] > 0 and t["refund-won"] > 0, str(dict(t)))


# ---------------------------------------------------------------- case 5
def case5(srv):
    print("== (5) refund of a capture, then a batch containing that capture")
    tok = world(srv, pays=[("p_1", "ada", "bob", 100, T1)])
    s, b = srv.call("POST", "/authorizations", tok["ada"], "au-1", {"to_handle": "bob", "amount": 200})
    assert s == 201, (s, b)
    aid = json.loads(b)["authorization_id"]
    s, b = srv.call("POST", "/authorizations/%s/capture" % aid, tok["bob"], "cap-1", {"amount": 150, "final": True})
    assert s == 201, (s, b)
    cap = json.loads(b)
    cid = cap["payment_id"]
    check("capture payment carries the authorization id", cap["authorization_id"] == aid, short(b))
    ledger_before = {n: srv.call("GET", "/me", tok[n])[1] for n in NAMES}
    auths_before = {n: srv.call("GET", "/authorizations?limit=100", tok[n])[1] for n in ("ada", "bob")}
    s, b = refund(srv, tok, "bob", cid, 50, "rf-cap")
    check("refund of a capture -> 201, refund_of names the capture, authorization_id null, request_id null",
          s == 201 and json.loads(b)["refund_of"] == cid and json.loads(b)["authorization_id"] is None and json.loads(b)["request_id"] is None, "%s %s" % (s, short(b)))
    rid = json.loads(b)["payment_id"] if s == 201 else None
    refuse(srv, "refund of the capture above its amount (50 + 101 > 150) -> 422 refund_exceeds_payment",
           lambda: refund(srv, tok, "bob", cid, 101, "rf-cap2"), 422, "refund_exceeds_payment")
    check("authorization records unchanged by the refund (no reopen, status kept)",
          all(srv.call("GET", "/authorizations?limit=100", tok[n])[1] == auths_before[n] for n in ("ada", "bob")))
    me_ada = json.loads(srv.call("GET", "/me", tok["ada"])[1])
    check("released hold not restored: ada held is 0 and available == balance", me_ada["held"] == 0 and me_ada["available"] == me_ada["balance"], str(me_ada))
    check("audit exact after capture + refund", not audit(srv, 1600), str(audit(srv, 1600)))
    refuse(srv, "batch containing the refunded capture -> 422 linked_payment_immutable",
           lambda: batch(srv, tok, "c1", item(cid, 1, 100)), 422, "linked_payment_immutable")
    refuse(srv, "batch of an ordinary payment then the capture -> 422 linked_payment_immutable, p_1 untouched",
           lambda: batch(srv, tok, "c2", item("p_1", 1, 90), item(cid, 1, 100)), 422, "linked_payment_immutable")
    refuse(srv, "batch of the capture then a stale ordinary item: input order, first failure wins -> linked_payment_immutable",
           lambda: batch(srv, tok, "c3", item(cid, 1, 100), item("p_1", 9, 90)), 422, "linked_payment_immutable")
    refuse(srv, "batch of a stale ordinary item then the capture -> 409 stale_revision (input order)",
           lambda: batch(srv, tok, "c4", item("p_1", 9, 90), item(cid, 1, 100)), 409, "stale_revision")
    refuse(srv, "batch containing the refund payment of the capture -> 422 linked_payment_immutable",
           lambda: batch(srv, tok, "c5", item(rid, 1, 10)), 422, "linked_payment_immutable")
    refuse(srv, "batch of the capture to the refunded amount or below is still immutable (not refund_exceeds_payment)",
           lambda: batch(srv, tok, "c6", item(cid, 1, 10)), 422, "linked_payment_immutable")
    refuse(srv, "single correction of the capture -> 422 linked_payment_immutable",
           lambda: srv.call("POST", "/payments/%s/corrections" % cid, tok["ada"], "c7", {"expected_revision": 1, "amount": 100, "effective_at": EFF, "reason": "x"}), 422, "linked_payment_immutable")
    refuse(srv, "refund of the refund payment -> 422 invalid_refund_target",
           lambda: refund(srv, tok, "ada", rid, 1, "c8"), 422, "invalid_refund_target")
    check("ledger and authorizations unchanged after all refused batches",
          all(json.loads(srv.call("GET", "/me", tok[n])[1])["balance"] == json.loads(ledger_before[n])["balance"] + d
              for n, d in (("ada", 50), ("bob", -50), ("cy", 0), ("dee", 0))))
    s, b = batch(srv, tok, "c9", item("p_1", 1, 90))
    check("control: an ordinary payment alone in a batch is still accepted -> 201", s == 201, "%s %s" % (s, short(b)))
    check("audit exact at the end", not audit(srv, 1600), str(audit(srv, 1600)))


# ---------------------------------------------------------------- case 6
def case6(srv):
    print("== (6) refunds of settlement members do not change membership")
    tok, sid, (m1, m2, m3), refunds = settlement_prelude(srv)
    st = json.loads(srv.export())["state"]
    members = sorted(p["payment_id"] for p in st["payments"] if p.get("settlement_id") == sid)
    check("membership after refunds is exactly the three original payments", members == sorted([m1, m2, m3]), str(members))
    check("every refund payment has settlement_id null in the export",
          all(p["settlement_id"] is None for p in st["payments"] if p.get("refund_of")) and sum(1 for p in st["payments"] if p.get("refund_of")) == 3)
    refuse(srv, "batch with two of three members (refunds exist) -> 422 incomplete_settlement",
           lambda: batch(srv, tok, "m1", item(m1, 1, 35), item(m2, 1, 20)), 422, "incomplete_settlement")
    refuse(srv, "batch naming the three members and one refund payment -> 422 linked_payment_immutable",
           lambda: batch(srv, tok, "m2", item(m1, 1, 35), item(m2, 1, 20), item(m3, 1, 22), item(refunds[m1][0]["payment_id"], 1, 5)), 422, "linked_payment_immutable")
    refuse(srv, "batch with different instants over the members -> 422 validation_failed (instants rule still applies)",
           lambda: batch(srv, tok, "m3", item(m1, 1, 35), item(m2, 1, 20, "2026-09-27T10:00:01+00:00"), item(m3, 1, 22)), 422, "validation_failed")
    s, b = batch(srv, tok, "m4", item(m1, 1, 35, "2026-09-27T12:00:00+02:00"), item(m2, 1, 20, "2026-09-27T10:00:00Z"), item(m3, 1, 22, EFF))
    check("batch with only the original members (still complete, mixed offset spellings of one instant) -> 201", s == 201, "%s %s" % (s, short(b)))
    st2 = json.loads(srv.export())["state"]
    check("membership unchanged after the batch", sorted(p["payment_id"] for p in st2["payments"] if p.get("settlement_id") == sid) == sorted([m1, m2, m3]))
    check("refund payments still settlement_id null after the batch", all(p["settlement_id"] is None for p in st2["payments"] if p.get("refund_of")))
    check("audit exact", not audit(srv, 1600), str(audit(srv, 1600)))
    s, b = refund(srv, tok, "bob", m1, 5, "m-more")
    check("a further refund of a corrected member (35 - 30 = 5 left) -> 201 and its settlement_id is null", s == 201 and json.loads(b)["settlement_id"] is None, "%s %s" % (s, short(b)))
    st3 = json.loads(srv.export())["state"]
    check("membership still the three after the further refund", sorted(p["payment_id"] for p in st3["payments"] if p.get("settlement_id") == sid) == sorted([m1, m2, m3]))
    s, b = batch(srv, tok, "m5", item(m1, 2, 35), item(m2, 2, 15), item(m3, 2, 21))
    check("second batch over the members after the further refund -> 201 (membership still complete)", s == 201, "%s %s" % (s, short(b)))
    check("audit exact at the end", not audit(srv, 1600), str(audit(srv, 1600)))


def main():
    print("binary:", EXE)
    srv = Srv()
    try:
        case1(srv)
        case2(srv)
        case4(srv)
        case5(srv)
        case6(srv)
    finally:
        srv.stop()
    case3()
    print("FAILED: %s" % failures if failures else "ALL PASSED")
    sys.exit(1 if failures else 0)


main()
