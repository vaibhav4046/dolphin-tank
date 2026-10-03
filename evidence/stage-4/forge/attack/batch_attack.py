"""Black-box attack on POST /correction-batches (stage 4) from forge, who did not write it.

usage: python batch_attack.py http://127.0.0.1:PORT      (a fresh binary; every scenario resets the state)

Every expectation comes from stage-4.md, not from the implementation. One line per check:
PASS / FAIL / INFO. Exit status 1 if any FAIL. Scenarios S1..S9 follow the work item's priority list; S10-S12 are extra (views, 32 items, request payments).
"""
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
FAILS = []
_seq = [0]
_seq_lock = threading.Lock()


def call(method, path, token=None, key=None, body=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def code(b):
    try:
        return json.loads(b)["error"]["code"]
    except Exception:
        return None


def ck(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))
    if not ok:
        FAILS.append(name)


def info(msg):
    print("INFO " + msg)


def key(prefix="k"):
    with _seq_lock:
        _seq[0] += 1
        return "%s%d" % (prefix, _seq[0])


def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def ago(days=0, hours=0, seconds=0):
    return iso(datetime.now(timezone.utc) - timedelta(days=days, hours=hours, seconds=seconds))


def q(v):
    return urllib.parse.quote(v, safe="")


def it(pid, rev, amount, eff, reason="attack"):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}


class Env:
    """Reset to a fixture. users: handle -> OPENING balance. pays: (id, from, to, amount, created_at) ascending."""

    def __init__(self, users, pays=(), auths=(), ops=("ada",)):
        net = {h: 0 for h in users}
        for _, f, t, a, _ in pays:
            net[f] -= a
            net[t] += a
        fx = {
            "currency": "EUR", "minor_units": 2,
            "users": [{"id": "u_" + h, "email": h + "@example.com", "password": "pw", "display_name": h.title(),
                       "handle": h, "balance": users[h] + net[h]} for h in users],
            "payments": [{"id": i, "from_user_id": "u_" + f, "to_user_id": "u_" + t, "amount": a, "created_at": c}
                         for i, f, t, a, c in pays],
            "authorizations": [{"id": i, "from_user_id": "u_" + f, "to_user_id": "u_" + t, "amount": a,
                                "status": "open", "expires_at": ago(days=-30), "created_at": c}
                               for i, f, t, a, c in auths],
            "settlement_operator_ids": ["u_" + o for o in ops],
        }
        s, b = call("POST", "/_test/reset", raw=json.dumps(fx).encode())
        assert s == 204, (s, b)
        self.users = list(users)
        self.tok = {}
        for h in users:
            s, b = call("POST", "/auth/login", body={"email": h + "@example.com", "password": "pw"})
            assert s == 200, (s, b)
            self.tok[h] = json.loads(b)["token"]

    def export(self):
        return call("GET", "/_test/export")[1]

    def me(self, h):
        return json.loads(call("GET", "/me", self.tok[h])[1])

    def balances(self):
        return {h: self.me(h)["balance"] for h in self.users}

    def total(self):
        return sum(self.balances().values())

    def post(self, h, path, body=None, k=None):
        return call("POST", path, self.tok[h], k or key(), body)

    def batch(self, items, k=None, who="ada", extra=None):
        body = {"corrections": items}
        if extra:
            body.update(extra)
        return self.post(who, "/correction-batches", body, k)

    def revs(self, pid, who):
        s, b = call("GET", "/payments/%s/revisions" % pid, self.tok[who])
        assert s == 200, (s, b)
        return json.loads(b)["revisions"]

    def activity(self, who):
        out, off = [], 0
        while True:
            s, b = call("GET", "/activity?limit=100&offset=%d" % off, self.tok[who])
            assert s == 200, (s, b)
            page = json.loads(b)
            out += page["payments"]
            if not page.get("has_more"):
                return out
            off += 100

    def refunded(self, pid, who):
        return sum(p["amount"] for p in self.activity(who) if p["refund_of"] == pid)

    def refuse(self, name, items, status, ecode, who="ada", k=None, extra=None):
        """The batch must fail with (status, code) and leave the whole exported state byte-identical."""
        before = self.export()
        s, b = self.batch(items, k, who, extra)
        ck(name + " -> %s %s" % (status, ecode), s == status and code(b) == ecode, "%s %s" % (s, b))
        ck(name + " leaves /_test/export byte-identical", self.export() == before)
        return s, b

    def accept(self, name, items, k=None, who="ada"):
        t0 = self.total()
        s, b = self.batch(items, k, who)
        ck(name + " -> 201", s == 201, "%s %s" % (s, b))
        ck(name + " conserves the sum of balances", self.total() == t0)
        return json.loads(b) if s == 201 else None


def race(fns):
    """Run callables simultaneously; return their results in order."""
    out = [None] * len(fns)
    gate = threading.Barrier(len(fns))

    def run(i):
        gate.wait()
        out[i] = fns[i]()

    ts = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


# --------------------------------------------------------------------------------------------------
def s1_settlement_member_below_refund():
    print("== S1 settlement member lowered below an existing refund")
    env = Env({"ada": 100000, "bob": 5000, "cy": 5000})
    ada, bob = env.tok["ada"], env.tok["bob"]
    stb = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 500},
                         {"from_handle": "ada", "to_handle": "cy", "amount": 300}]}
    s, b = call("POST", "/settlements", ada, "st1", stb)
    ck("S1 settlement 201", s == 201, b)
    st_bytes = b
    m1, m2 = [p["payment_id"] for p in json.loads(b)["payments"]]
    total0 = env.total()
    s, b = env.post("bob", "/payments/%s/refunds" % m1, {"amount": 200}, "rf1")
    ck("S1 refund of a settlement member -> 201", s == 201, b)
    rf = json.loads(b)
    ck("S1 refund has settlement_id null and refund_of = member", rf["settlement_id"] is None and rf["refund_of"] == m1)
    ck("S1 settlement retry still returns the original bytes", call("POST", "/settlements", ada, "st1", stb) == (200, st_bytes))
    E1 = ago(hours=1)
    # (1) below the refund: item error, nothing changes
    env.refuse("S1 batch lowers member below its refund (complete settlement)", [it(m1, 1, 100, E1), it(m2, 1, 300, E1)],
               422, "refund_exceeds_payment")
    env.refuse("S1 same, only the refunded member named (item error beats incomplete_settlement)", [it(m1, 1, 100, E1)],
               422, "refund_exceeds_payment")
    env.refuse("S1 stale item 0 beats refund_exceeds item 1", [it(m2, 9, 300, E1), it(m1, 1, 100, E1)], 409, "stale_revision")
    env.refuse("S1 refund_exceeds item 0 beats stale item 1", [it(m1, 1, 100, E1), it(m2, 9, 300, E1)], 422, "refund_exceeds_payment")
    # (2) completeness before funds / instants
    env.refuse("S1 incomplete beats unaffordable", [it(m1, 1, 900000000, E1)], 422, "incomplete_settlement")
    env.refuse("S1 differing instants (1 microsecond apart)", [it(m1, 1, 200, "2026-09-01T10:00:00.000001+00:00"),
                                                              it(m2, 1, 300, "2026-09-01T10:00:00+00:00")], 422, "validation_failed")
    # (3) exactly the refunded amount, spelled with different offsets
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    e_utc = iso(t0)
    e_off = t0.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%dT%H:%M:%S.%f+05:30")
    out = env.accept("S1 batch lowers member exactly to its refund (offset spellings differ)",
                     [it(m1, 1, 200, e_utc), it(m2, 1, 300, e_off)])
    if out:
        ck("S1 revisions carry the batch id and share recorded_at", all(r["correction_batch_id"] == out["correction_batch_id"]
           and r["recorded_at"] == out["recorded_at"] for r in out["revisions"]))
        bal = env.balances()
        ck("S1 ada = opening 100000 - 200 - 300 + 200 refund", bal["ada"] == 100000 - 200 - 300 + 200, bal)
        ck("S1 bob = opening 5000 + 200 - 200", bal["bob"] == 5000, bal)
        ck("S1 cy = opening 5000 + 300", bal["cy"] == 5300, bal)
    s, b = env.post("bob", "/payments/%s/refunds" % m1, {"amount": 1}, key())
    ck("S1 refund 1 more beyond the corrected amount -> 422 refund_exceeds_payment", s == 422 and code(b) == "refund_exceeds_payment", "%s %s" % (s, b))
    act = {p["payment_id"]: p for p in env.activity("bob")}
    ck("S1 original payment record unchanged (m1 amount 500)", act[m1]["amount"] == 500 and act[m1]["settlement_id"] is not None)
    ck("S1 settlement retry after the batch still original bytes", call("POST", "/settlements", ada, "st1", stb) == (200, st_bytes))
    # raise m1 and refund again within the new limit
    now_i = ago(seconds=1)
    out = env.accept("S1 raise m1 to 700 (members share one instant)", [it(m1, 2, 700, now_i), it(m2, 2, 300, now_i)])
    s, b = env.post("bob", "/payments/%s/refunds" % m1, {"amount": 500}, key())
    ck("S1 refund 500 more (200+500 <= 700) -> 201", s == 201, "%s %s" % (s, b))
    s, b = env.post("bob", "/payments/%s/refunds" % m1, {"amount": 1}, key())
    ck("S1 one more -> 422 refund_exceeds_payment", s == 422 and code(b) == "refund_exceeds_payment", "%s %s" % (s, b))
    env.refuse("S1 below the new refunded 700 -> refund_exceeds_payment", [it(m1, 3, 699, ago(seconds=1)), it(m2, 3, 300, ago(seconds=1))],
               422, "refund_exceeds_payment")
    s, b = env.batch([it(m1, 3, 900000000, ago(hours=1)), it(m2, 3, 300, ago(hours=2))])
    info("S1 ambiguity: differing member instants + unaffordable amount -> %s %s (spec lists no slot for the instants check)" % (s, code(b)))
    ck("S1 total conserved over the whole scenario", env.total() == total0)
    ck("S1 refunds never changed settlement membership", [p["settlement_id"] for p in env.activity("ada")
       if p["payment_id"] in (m1, m2)] == [json.loads(st_bytes)["settlement_id"]] * 2)


# --------------------------------------------------------------------------------------------------
def s2_refund_races_batch():
    print("== S2 refunds racing batches and single corrections over HTTP")
    env = Env({"ada": 110000, "bob": 50000}, [("p_1", "ada", "bob", 10000, ago(days=5))])
    t0 = env.total()
    rev = 1
    r_prev = 0
    for rnd in range(3):
        eff = ago(hours=1)
        fns = []
        for i in range(12):
            fns.append(lambda: env.post("bob", "/payments/p_1/refunds", {"amount": 700}))
        for amt in (20000, 25000, 3000, 5000):
            fns.append(lambda a=amt: env.batch([it("p_1", rev, a, eff)]))
        for amt in (30000, 4000):
            fns.append(lambda a=amt: env.post("ada", "/payments/p_1/corrections",
                                              {"expected_revision": rev, "amount": a, "effective_at": eff, "reason": "single"}))
        res = race(fns)
        refunds = res[:12]
        corr = res[12:]
        wins = [r for r in corr if r[0] == 201]
        ck("S2 round %d exactly one correction (batch or single) wins the shared revision" % rnd, len(wins) == 1,
           [(r[0], code(r[1])) for r in corr])
        others = [r for r in corr if r[0] != 201]
        ck("S2 round %d losers are stale_revision or refund_exceeds_payment only" % rnd,
           all((r[0], code(r[1])) in ((409, "stale_revision"), (422, "refund_exceeds_payment")) for r in others),
           [(r[0], code(r[1])) for r in others])
        revs = env.revs("p_1", "ada")
        rev = revs[-1]["revision"]
        L = revs[-1]["amount"]
        R = env.refunded("p_1", "bob")
        ok_sum = sum(700 for r in refunds if r[0] == 201)
        ck("S2 round %d 201 refund responses add up to the refunded total grown this round" % rnd, ok_sum == R - r_prev, (ok_sum, R, r_prev))
        r_prev = R
        bad = [(r[0], code(r[1])) for r in refunds if r[0] != 201 and (r[0], code(r[1])) not in
               ((422, "refund_exceeds_payment"), (409, "insufficient_funds"))]
        ck("S2 round %d refund failures are limit/funds only" % rnd, not bad, bad)
        ck("S2 round %d refunded %d <= current amount %d" % (rnd, R, L), R <= L)
        bal = env.balances()
        ck("S2 round %d balances exact (ada=110000-L+R, bob=50000+L-R)" % rnd,
           bal["ada"] == 110000 - L + R and bal["bob"] == 50000 + L - R, (bal, L, R))
        ck("S2 round %d sum conserved" % rnd, env.total() == t0)
        ck("S2 round %d p_1 gained exactly one revision" % rnd, rev == 2 + rnd, rev)


# --------------------------------------------------------------------------------------------------
def s3_batch_vs_batch_vs_single():
    print("== S3 batches and single corrections racing on shared expected revisions")
    pays = [("p_%d" % i, "ada", "bob", 100, ago(days=5)) for i in range(1, 7)]
    env = Env({"ada": 100000, "bob": 100000}, pays)
    t0 = env.total()
    cur = {"p_%d" % i: 1 for i in range(1, 7)}
    for rnd in range(5):
        eff = ago(hours=1)
        a = 200 + 10 * rnd

        def B(*pids, off=0):
            return lambda: env.batch([it(p, cur[p], a + off + j, eff) for j, p in enumerate(pids)])

        def S(pid):
            return lambda: env.post("ada", "/payments/%s/corrections" % pid,
                                    {"expected_revision": cur[pid], "amount": a + 7, "effective_at": eff, "reason": "s"})
        ops = [("A", ["p_1", "p_2"], B("p_1", "p_2")), ("B", ["p_2", "p_3"], B("p_2", "p_3", off=1)),
               ("C", ["p_3", "p_4"], B("p_3", "p_4", off=2)), ("S2", ["p_2"], S("p_2")),
               ("D", ["p_5", "p_6"], B("p_5", "p_6", off=3)), ("E", ["p_5"], S("p_5")), ("F", ["p_5"], B("p_5", off=4))]
        res = race([o[2] for o in ops])
        won = {o[0] for o, r in zip(ops, res) if r[0] == 201}
        share = lambda x, y: bool(set(x[1]) & set(y[1]))
        conflict = [(x[0], y[0]) for i, x in enumerate(ops) for y in ops[i + 1:] if share(x, y) and x[0] in won and y[0] in won]
        ck("S3 round %d no two operations sharing a revision both succeeded (won=%s)" % (rnd, sorted(won)), not conflict, conflict)
        lost_bad = [(o[0], r[0], code(r[1])) for o, r in zip(ops, res) if r[0] != 201 and (r[0], code(r[1])) != (409, "stale_revision")]
        ck("S3 round %d every loser is a plain stale_revision" % rnd, not lost_bad, lost_bad)
        unexplained = [o[0] for o, r in zip(ops, res) if r[0] != 201 and not any(
            share(o, w) for w in ops if w[0] in won)]
        ck("S3 round %d every loser conflicts with a winner (no spurious refusal)" % rnd, not unexplained, unexplained)
        for p in cur:
            touched = sum(1 for o in ops if o[0] in won and p in o[1])
            n = len(env.revs(p, "ada"))
            ck("S3 round %d %s revisions == %d" % (rnd, p, cur[p] + touched), n == cur[p] + touched, n)
            cur[p] = n
        ck("S3 round %d sum conserved" % rnd, env.total() == t0)
    # identical retries of one batch: one 201, the rest 200 with the same bytes
    items = [it("p_1", cur["p_1"], 77, ago(hours=1)), it("p_2", cur["p_2"], 78, ago(hours=1))]
    k = key("same")
    res = race([lambda: env.batch(items, k) for _ in range(12)])
    ck("S3 12 identical retries -> one 201, eleven 200",
       sorted(r[0] for r in res) == [200] * 11 + [201], sorted(r[0] for r in res))
    ck("S3 all retries carry identical bytes", len({r[1] for r in res}) == 1)
    ck("S3 retries moved money once", len(env.revs("p_1", "ada")) == cur["p_1"] + 1)


# --------------------------------------------------------------------------------------------------
def s4_affordability():
    print("== S4 combined affordability per wallet, held funds")

    def mk():
        # bob: opening 500, p1 -300 (to cy), p2 +800 (from dee) -> balance 1000; hold 600 placed 1h ago -> available 400
        return Env({"ada": 100000, "bob": 500, "cy": 1000, "dee": 5000},
                   [("p1", "bob", "cy", 300, ago(days=5)), ("p2", "dee", "bob", 800, ago(days=5)),
                    ("p3", "dee", "cy", 100, ago(days=5))],
                   [("a_1", "bob", "cy", 600, ago(hours=1))])

    eff = ago(hours=3)
    e = mk()
    m = e.me("bob")
    ck("S4 fixture: bob balance 1000, held 600, available 400", (m["balance"], m["held"], m["available"]) == (1000, 600, 400), m)
    e.refuse("S4 raise p1 by 500 alone (balance covers it, held funds do not)", [it("p1", 1, 800, eff)], 409, "insufficient_funds")
    e.accept("S4 raise p1 by 500 together with raise p2 by 200 (bob net -300; p1 alone failed)",
             [it("p1", 1, 800, eff), it("p2", 1, 1000, eff)])
    e = mk()
    e.refuse("S4 one over: bob net -401", [it("p1", 1, 901, eff), it("p2", 1, 1000, eff)], 409, "insufficient_funds")
    e = mk()
    out = e.accept("S4 exactly available: bob net -400", [it("p1", 1, 900, eff), it("p2", 1, 1000, eff)])
    if out:
        m = e.me("bob")
        ck("S4 bob ends balance 600 held 600 available 0", (m["balance"], m["held"], m["available"]) == (600, 600, 0), m)
    e = mk()
    e.refuse("S4 lower p2 by 600 alone (bob -600 > available 400)", [it("p2", 1, 200, eff)], 409, "insufficient_funds")
    e.accept("S4 lower p2 by 600 with lower p1 by 300 (bob net -300, cy -300, dee +600)", [it("p2", 1, 200, eff), it("p1", 1, 0, eff)])
    e = mk()
    e.refuse("S4 dee cannot fund +99200", [it("p2", 1, 100000, eff)], 409, "insufficient_funds")
    e = mk()
    e.refuse("S4 funds fault and historical fault together -> insufficient_funds first",
             [it("p1", 1, 900, ago(days=3))], 409, "insufficient_funds")
    e.refuse("S4 stale item before funds fault", [it("p1", 7, 900, eff)], 409, "stale_revision")
    e.refuse("S4 item 0 would fail funds, item 1 unknown payment -> 404 (item errors first)",
             [it("p1", 1, 900, eff), it("p_nope", 1, 1, eff)], 404, "not_found")


# --------------------------------------------------------------------------------------------------
def hist_ok(opening, moves, now_i):
    """Independent oracle: total >= 0 after every instant a movement takes effect. moves: (eff_iso, delta)."""
    evs = sorted(moves)
    t = opening
    i = 0
    while i < len(evs):
        j = i
        while j < len(evs) and evs[j][0] == evs[i][0]:
            t += evs[j][1]
            j += 1
        if evs[i][0] <= now_i and t < 0:
            return False
        i = j
    return True


def s5_intermediate_boundary():
    print("== S5 historical_overdraft only visible with several backdated effective instants")
    d = lambda n: iso(datetime.now(timezone.utc) - timedelta(days=n))
    D1, D2, C, D3 = d(10), d(9), d(8), d(2)
    base = {"d1": ("bob", -50, D1), "d2": ("bob", -50, D2), "c": ("bob", 100, C), "d3": ("bob", -50, D3)}
    moves = {"m1": ("c", d(3), 100), "m2": ("d3", d(6), 50), "m3": ("d1", d(4), 50)}
    names = ["m1", "m2", "m3"]
    for mask in range(1, 8):
        chosen = [n for i, n in enumerate(names) if mask >> i & 1]
        override = {moves[n][0]: moves[n][1] for n in chosen}
        mv = [(override.get(pid, v[2]), v[1]) for pid, v in base.items()]
        expect_ok = hist_ok(100, mv, iso(datetime.now(timezone.utc)))
        env = Env({"ada": 100000, "bob": 100, "cy": 1000},
                  [("d1", "bob", "cy", 50, D1), ("d2", "bob", "cy", 50, D2), ("c", "ada", "bob", 100, C), ("d3", "bob", "cy", 50, D3)])
        items = [it(moves[n][0], 1, moves[n][2], moves[n][1]) for n in chosen]
        label = "S5 moves %s oracle=%s" % ("+".join(chosen), "ok" if expect_ok else "overdraft")
        if expect_ok:
            env.accept(label, items)
        else:
            env.refuse(label, items, 409, "historical_overdraft")


# --------------------------------------------------------------------------------------------------
def s6_parity():
    print("== S6 one-item batch vs single correction, same fault, same fixture")
    EFF_OK = ago(days=5, hours=2)
    T_A, T_B = ago(days=5), ago(days=4)

    def setup():
        e = Env({"ada": 5000, "bob": 0, "cy": 0}, [("pA", "ada", "bob", 1000, T_A), ("pB", "bob", "cy", 200, T_B)])
        s, b = e.post("bob", "/payments/pA/refunds", {"amount": 300}, "rf")
        assert s == 201, (s, b)
        e.rf = json.loads(b)["payment_id"]
        return e

    def single(e, who, pid, rev, amount, eff, reason):
        body = {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}
        return e.post(who, "/payments/%s/corrections" % pid, body, key())

    def batched(e, pid, rev, amount, eff, reason):
        return e.batch([{"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}])

    cases = [
        ("lower to 600", "pA", 1, 600, EFF_OK, "r"), ("raise to 2000", "pA", 1, 2000, EFF_OK, "r"),
        ("same amount new instant", "pA", 1, 1000, EFF_OK, "r"), ("exactly the refunded 300", "pA", 1, 300, EFF_OK, "r"),
        ("below refunded 299", "pA", 1, 299, EFF_OK, "r"), ("zero below refunded", "pA", 1, 0, EFF_OK, "r"),
        ("raise beyond funds", "pA", 1, 9000, EFF_OK, "r"), ("raise to funds limit", "pA", 1, 5300, EFF_OK, "r"),
        ("historical: move later than pB", "pA", 1, 700, ago(hours=1), "r"),
        ("negative amount", "pA", 1, -1, EFF_OK, "r"), ("amount over 1e9", "pA", 1, 1000000001, EFF_OK, "r"),
        ("empty reason", "pA", 1, 600, EFF_OK, ""), ("201-char reason", "pA", 1, 600, EFF_OK, "x" * 201),
        ("200-char reason", "pA", 1, 600, EFF_OK, "x" * 200), ("naive instant", "pA", 1, 600, "2026-09-01T10:00:00", "r"),
        ("future instant", "pA", 1, 600, ago(days=-1), "r"), ("expected 0", "pA", 0, 600, EFF_OK, "r"),
        ("stale expected 3", "pA", 3, 600, EFF_OK, "r"), ("unknown payment", "p_nope", 1, 600, EFF_OK, "r"),
        ("amount as string", "pA", 1, "5", EFF_OK, "r"), ("amount as float", "pA", 1, 5.5, EFF_OK, "r"),
    ]
    def snap(e, s, b):
        """What an observer sees after the call: status, code, balances, the payment's revisions."""
        return {"status": s, "code": code(b), "body": b, "balances": e.balances(), "revs": e.revs("pA", "ada")}

    for name, pid, rev, amount, eff, reason in cases:
        e = setup()
        s1, b1 = single(e, "ada", pid, rev, amount, eff, reason)
        r1 = snap(e, s1, b1)
        e = setup()
        s2, b2 = batched(e, pid, rev, amount, eff, reason)
        r2 = snap(e, s2, b2)
        ck("S6 %s: single %s/%s == batch %s/%s" % (name, s1, r1["code"], s2, r2["code"]),
           (s1, r1["code"]) == (s2, r2["code"]), (b1, b2))
        ck("S6 %s: balances equal after the call" % name, r1["balances"] == r2["balances"], (r1["balances"], r2["balances"]))
        f = ("revision", "amount", "effective_at", "reason")
        ck("S6 %s: revision history equal (fields %s)" % (name, ",".join(f)),
           [[x[k] for k in f] for x in r1["revs"]] == [[x[k] for k in f] for x in r2["revs"]], (r1["revs"], r2["revs"]))
        if s1 == 201 and s2 == 201:
            v1, v2 = json.loads(b1), json.loads(b2)["revisions"][0]
            ck("S6 %s: single revision has correction_batch_id null, batch has an id" % name,
               v1["correction_batch_id"] is None and v2["correction_batch_id"] is not None)
            ck("S6 %s: recorded_at is 6-digit UTC micro in both" % name,
               all(len(v["recorded_at"]) == 32 and v["recorded_at"].endswith("+00:00") for v in (v1, v2)), (v1, v2))
    e = setup()
    s1, b1 = single(e, "bob", e.rf, 1, 100, EFF_OK, "r")
    e = setup()
    s2, b2 = batched(e, e.rf, 1, 100, EFF_OK, "r")
    ck("S6 refund payment: single %s/%s and batch %s/%s are both 422 linked_payment_immutable" % (s1, code(b1), s2, code(b2)),
       (s1, code(b1)) == (s2, code(b2)) == (422, "linked_payment_immutable"))


# --------------------------------------------------------------------------------------------------
def s7_capture_and_refund_items():
    print("== S7 capture or refund item mixed with valid items")
    env = Env({"ada": 100000, "bob": 5000, "cy": 5000},
              [("p1", "ada", "bob", 500, ago(days=5)), ("p2", "ada", "cy", 300, ago(days=5))])
    s, b = env.post("ada", "/authorizations", {"to_handle": "bob", "amount": 200})
    assert s == 201, (s, b)
    aid = json.loads(b)["authorization_id"]
    s, b = env.post("bob", "/authorizations/%s/capture" % aid, {})
    assert s == 201, (s, b)
    cap = json.loads(b)["payment_id"]
    ck("S7 the capture payment names its authorization", json.loads(b)["authorization_id"] == aid)
    s, b = env.post("bob", "/payments/p1/refunds", {"amount": 100})
    assert s == 201, (s, b)
    rf = json.loads(b)["payment_id"]
    eff = ago(hours=1)
    good = lambda: [it("p1", 1, 400, eff), it("p2", 1, 200, eff)]
    env.refuse("S7 capture mixed with valid items", good() + [it(cap, 1, 100, eff)], 422, "linked_payment_immutable")
    env.refuse("S7 refund mixed with valid items", [it("p1", 1, 400, eff), it(rf, 1, 50, eff), it("p2", 1, 200, eff)],
               422, "linked_payment_immutable")
    env.refuse("S7 linked item 0 before a stale item 1", [it(cap, 1, 100, eff), it("p1", 9, 400, eff)], 422, "linked_payment_immutable")
    env.refuse("S7 stale item 0 before a linked item 1", [it("p1", 9, 400, eff), it(cap, 1, 100, eff)], 409, "stale_revision")
    env.refuse("S7 linked item 0 before an unknown item 1", [it(rf, 1, 50, eff), it("p_x", 1, 1, eff)], 422, "linked_payment_immutable")
    env.refuse("S7 unknown item 0 before a linked item 1", [it("p_x", 1, 1, eff), it(rf, 1, 50, eff)], 404, "not_found")
    env.refuse("S7 validation fault at item 1 before linked item 2", [it("p1", 1, 400, eff), it("p2", 1, 200, eff, reason=""), it(cap, 1, 1, eff)],
               422, "validation_failed")
    env.refuse("S7 linked item before incomplete/unaffordable", [it(cap, 1, 900000000, eff)], 422, "linked_payment_immutable")
    k = key("rej")
    env.refuse("S7 rejected batch under a key", good() + [it(cap, 1, 100, eff)], 422, "linked_payment_immutable", k=k)
    s, b = env.batch(good(), k)
    ck("S7 same key after a rejection can still succeed (key not burned)", s == 201, "%s %s" % (s, b))
    s2, b2 = env.batch(good(), k)
    ck("S7 and its retry replays the 201 body as 200", s2 == 200 and b2 == b)


# --------------------------------------------------------------------------------------------------
def micro(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f+00:00")


def s8_recorded_at():
    print("== S8 recorded_at strictly later than every member's previous recorded_at; clock ratchet")
    env = Env({"ada": 100000, "bob": 100000})
    ada = env.tok["ada"]
    pb = {"to_handle": "bob", "amount": 100}
    s, b1 = call("POST", "/payments", ada, "pay1", pb)
    s, b2 = call("POST", "/payments", ada, "pay2", {"to_handle": "bob", "amount": 200})
    p, q = json.loads(b1)["payment_id"], json.loads(b2)["payment_id"]
    eff = ago(hours=1)
    s, b = env.post("ada", "/payments/%s/corrections" % p, {"expected_revision": 1, "amount": 150, "effective_at": eff, "reason": "single"})
    r2 = json.loads(b)["recorded_at"]
    out = env.accept("S8 batch after a single correction of a member", [it(p, 2, 160, eff), it(q, 1, 210, eff)])
    last = r2
    if out:
        rec = out["recorded_at"]
        q1 = env.revs(q, "ada")[0]["recorded_at"]
        ck("S8 batch recorded_at > p's previous (single) recorded_at and > q's original", rec > r2 and rec > q1, (rec, r2, q1))
        ck("S8 every revision shares recorded_at", all(r["recorded_at"] == rec for r in out["revisions"]))
        last = rec
    cur = {p: 3, q: 2}
    ok = True
    for i in range(25):
        o = env.batch([it(p, cur[p], 1000 + i, eff), it(q, cur[q], 2000 + i, eff)])
        if o[0] != 201:
            ck("S8 rapid batch %d" % i, False, o)
            ok = False
            break
        body = json.loads(o[1])
        rec = body["recorded_at"]
        ok = ok and rec > last and all(r["recorded_at"] == rec for r in body["revisions"])
        last = rec
        cur[p] += 1
        cur[q] += 1
        o = env.post("ada", "/payments/%s/corrections" % p, {"expected_revision": cur[p], "amount": 90 + i, "effective_at": eff, "reason": "s"})
        if o[0] == 201:
            cur[p] += 1
            ok = ok and json.loads(o[1])["recorded_at"] > last
            last = json.loads(o[1])["recorded_at"]
        else:
            ok = False
    ck("S8 25 rapid batch+single rounds: one strictly increasing clock for every operation", ok)
    ck("S8 original payment retries return their original bytes after batches",
       call("POST", "/payments", ada, "pay1", pb) == (200, b1))
    for pid in (p, q):
        rs = env.revs(pid, "ada")
        ck("S8 %s recorded_at strictly increasing across all its revisions" % pid,
           all(rs[i]["recorded_at"] < rs[i + 1]["recorded_at"] for i in range(len(rs) - 1)))
    # ratchet: an imported revision recorded in the future
    exp = json.loads(env.export())
    fut = iso(datetime.now(timezone.utc) + timedelta(hours=2))
    st = exp["state"]
    n = max(r["revision"] for r in st["revisions"] if r["payment_id"] == p)
    st["revisions"].append({"payment_id": p, "revision": n + 1, "amount": 321, "effective_at": ago(hours=2),
                            "recorded_at": fut, "reason": "future", "correction_batch_id": None})
    # keep balances consistent with the new latest revision (321 instead of the previous amount)
    prev_amt = [r for r in st["revisions"] if r["payment_id"] == p and r["revision"] == n][0]["amount"]
    for u in st["users"]:
        if u["handle"] == "ada":
            u["balance"] -= 321 - prev_amt
        if u["handle"] == "bob":
            u["balance"] += 321 - prev_amt
    s, b = call("POST", "/_test/import", raw=json.dumps(exp).encode())
    if s != 204:
        info("S8 ratchet: import of a future-recorded revision refused (%s %s); ratchet states skipped" % (s, b[:120]))
        return
    nq = len(env.revs(q, "ada"))
    out = env.accept("S8 batch over a member recorded in the future", [it(p, n + 1, 330, ago(hours=1)), it(q, nq, 7, ago(hours=1))])
    if out:
        ck("S8 recorded_at later than the imported future revision's", out["recorded_at"] > fut, (out["recorded_at"], fut))
        ck("S8 and shared by every revision (q's earlier rev was in the past)", all(r["recorded_at"] == out["recorded_at"] for r in out["revisions"]))
        s, b = env.post("ada", "/payments/%s/corrections" % q, {"expected_revision": nq + 1, "amount": 9, "effective_at": ago(hours=1), "reason": "s"})
        ck("S8 a later single correction is later still", s == 201 and json.loads(b)["recorded_at"] > out["recorded_at"], (s, b))


# --------------------------------------------------------------------------------------------------
def s10_views_and_snapshots():
    print("== S10 snapshots and known_at/as_of views around a batch")
    env = Env({"ada": 100000, "bob": 1000}, [("p1", "ada", "bob", 500, ago(days=5)), ("p2", "ada", "bob", 300, ago(days=4))])
    bob = env.tok["bob"]
    s, b = call("GET", "/statement?limit=1", bob)
    tok = json.loads(b)["snapshot"]
    page_before = call("GET", "/statement?snapshot=%s&limit=1&offset=1" % tok, bob)
    first_before = call("GET", "/statement?snapshot=%s&limit=1&offset=0" % tok, bob)
    me_before = env.me("bob")
    t_before = ago()
    eff = ago(hours=2)
    out = env.accept("S10 batch lowers p1 to 100 and raises p2 to 900", [it("p1", 1, 100, eff), it("p2", 1, 900, eff)])
    ck("S10 earlier snapshot token pages the same frozen entries (offset 1)",
       call("GET", "/statement?snapshot=%s&limit=1&offset=1" % tok, bob) == page_before)
    ck("S10 and offset 0", call("GET", "/statement?snapshot=%s&limit=1&offset=0" % tok, bob) == first_before)
    s, b = call("GET", "/statement?limit=100", bob)
    st = json.loads(b)
    ck("S10 a new statement reflects the new revisions (revision 2, amounts 100 and 900)",
       sorted((e["payment"]["payment_id"], e["revision"], e["payment"]["amount"]) for e in st["entries"]) ==
       [("p1", 2, 100), ("p2", 2, 900)], st["entries"])
    ck("S10 and closes at bob's balance", st["closing_balance"] == env.me("bob")["balance"] == 1000 + 100 + 900, st)
    old = json.loads(call("GET", "/me?known_at=%s" % q(t_before), bob)[1])
    ck("S10 /me known_at before the batch is the old balance", old["balance"] == me_before["balance"] == 1800, old)
    ck("S10 /me known_at after the batch is the new balance",
       json.loads(call("GET", "/me?known_at=%s" % q(out["recorded_at"]), bob)[1])["balance"] == 2000)
    a1 = ago(days=1)
    ck("S10 as_of 1 day ago under current knowledge: payments moved to -2h are not yet in",
       json.loads(call("GET", "/me?as_of=%s" % q(a1), bob)[1])["total"] == 1000)
    ck("S10 as_of 1 day ago under pre-batch knowledge: both payments counted",
       json.loads(call("GET", "/me?as_of=%s&known_at=%s" % (q(a1), q(t_before)), bob)[1])["total"] == 1800)
    ck("S10 payment records keep their original amounts", {p["payment_id"]: p["amount"] for p in env.activity("bob")} == {"p1": 500, "p2": 300})


# --------------------------------------------------------------------------------------------------
def s11_full_size_batch():
    print("== S11 32 items and 33 items")
    pays = [("q%02d" % i, "ada", "bob", 100, ago(days=5)) for i in range(33)]
    env = Env({"ada": 100000, "bob": 1000}, pays)
    eff = ago(hours=1)
    env.refuse("S11 33 items", [it("q%02d" % i, 1, 50, eff) for i in range(33)], 422, "validation_failed")
    out = env.accept("S11 32 items", [it("q%02d" % i, 1, 50, eff) for i in range(32)])
    if out:
        ck("S11 revisions in input order, one recorded_at, one batch id",
           [r["payment_id"] for r in out["revisions"]] == ["q%02d" % i for i in range(32)]
           and len({r["recorded_at"] for r in out["revisions"]}) == 1
           and all(r["correction_batch_id"] == out["correction_batch_id"] for r in out["revisions"]))
        ck("S11 bob balance exact: opening 1000 + q32 100 + 32 lowered payments of 50", env.me("bob")["balance"] == 1000 + 100 + 32 * 50)


# --------------------------------------------------------------------------------------------------
def s12_request_payment():
    print("== S12 request payment: batch correction and refund leave the request closed")
    env = Env({"ada": 100000, "bob": 5000, "cy": 5000})
    s, b = env.post("cy", "/requests", {"payer_handle": "bob", "amount": 400})
    assert s == 201, (s, b)
    rid = json.loads(b)["request_id"]
    s, b = env.post("bob", "/requests/%s/pay" % rid, {})
    assert s == 201, (s, b)
    P = json.loads(b)
    ck("S12 request payment carries request_id", P["request_id"] == rid)

    def status():
        s, b = call("GET", "/requests", env.tok["bob"])
        found = [r for v in json.loads(b).values() if isinstance(v, list) for r in v if isinstance(r, dict) and r.get("request_id") == rid]
        return found[0]["status"] if found else None
    ck("S12 request is paid", status() == "paid", status())
    pid = P["payment_id"]
    s, b = env.post("cy", "/payments/%s/refunds" % pid, {"amount": 100})
    ck("S12 refund of the request payment -> 201, request_id null, request still paid",
       s == 201 and json.loads(b)["request_id"] is None and json.loads(b)["refund_of"] == pid and status() == "paid", (s, b))
    eff = ago(hours=1)
    env.refuse("S12 operator lowers the request payment below its refund", [it(pid, 1, 99, eff)], 422, "refund_exceeds_payment")
    env.accept("S12 operator (not a party) lowers the request payment to 250", [it(pid, 1, 250, eff)])
    ck("S12 request still paid after the batch", status() == "paid", status())
    s, b = env.post("bob", "/requests/%s/pay" % rid, {})
    ck("S12 the paid request cannot be paid again", s >= 400, (s, b))
    s, b = env.post("cy", "/payments/%s/refunds" % pid, {"amount": 151})
    ck("S12 refund 151 more (100+151 > 250) -> 422 refund_exceeds_payment", s == 422 and code(b) == "refund_exceeds_payment", (s, b))
    s, b = env.post("cy", "/payments/%s/refunds" % pid, {"amount": 150})
    ck("S12 refund the remaining 150 -> 201", s == 201, (s, b))
    ck("S12 request still paid after refunds", status() == "paid", status())


# --------------------------------------------------------------------------------------------------
def s9_refund_with_history():
    print("== S9 refund created_at is a history boundary for the batch")
    for settle in (False, True):
        tag = "member" if settle else "ordinary"
        env = Env({"ada": 100000, "bob": 0, "cy": 0}, [] if settle else [("P", "ada", "bob", 1000, ago(days=5))])
        P, Q = "P", None
        if settle:
            s, b = env.post("ada", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1000},
                                                                  {"from_handle": "ada", "to_handle": "cy", "amount": 500}]})
            P, Q = [p["payment_id"] for p in json.loads(b)["payments"]]
        s, b = env.post("bob", "/payments/%s/refunds" % P, {"amount": 600})
        ck("S9 %s refund 201" % tag, s == 201, b)
        # effective instant after the refund was created: bob would be at -600 when the refund happens
        late = iso(datetime.now(timezone.utc))
        extra = [it(Q, 1, 500, late)] if settle else []
        env.refuse("S9 %s: payment moved to just after its refund" % tag, [it(P, 1, 1000, late)] + extra, 409, "historical_overdraft")
        early = ago(hours=1)
        extra = [it(Q, 1, 500, early)] if settle else []
        env.refuse("S9 %s: lower to 599 < refunded 600" % tag, [it(P, 1, 599, early)] + extra, 422, "refund_exceeds_payment")
        env.accept("S9 %s: lower to exactly the refunded 600, instant before the refund" % tag,
                   [it(P, 1, 600, early)] + ([it(Q, 1, 500, early)] if settle else []))
        bal = env.balances()
        ck("S9 %s: bob is whole (600 received - 600 refunded)" % tag, bal["bob"] == 0, bal)


if __name__ == "__main__":
    for fn in (s1_settlement_member_below_refund, s2_refund_races_batch, s3_batch_vs_batch_vs_single, s4_affordability,
               s5_intermediate_boundary, s6_parity, s7_capture_and_refund_items, s8_recorded_at, s9_refund_with_history, s10_views_and_snapshots, s11_full_size_batch, s12_request_payment):
        try:
            fn()
        except AssertionError as e:
            ck(fn.__name__ + " setup", False, repr(e))
    print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
    sys.exit(1 if FAILS else 0)
