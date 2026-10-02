"""J39 J52 J29: concurrency - same-expected-revision races, same-key replays, correction vs payment at the funds boundary,
mixed storm with live observers, then independent oracle validation of the final history (no negative balance at any effective-time boundary)."""
import random, sys, threading, time
from lib3 import *

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else int(time.time()) % 1000
print("seed", SEED)
now = lambda: dt.datetime.now(UTC)

# ================================================================ R1 same expected_revision race
f = fx([user("ada", 100000), user("bob", 100000), user("cy", 100000)])
t = setup(f)
A, B, C = t["ada"], t["bob"], t["cy"]
TOTAL = 300000
p = pay(A, "bob", 1000).j
PID = p["payment_id"]
rounds = 8
for rd in range(rounds):
    cur = revs(A, PID)[-1]["revision"]
    N = 24
    res = parallel([(lambda i=i: correct(A, PID, cur, 100 + rd * 50 + i, p["created_at"], "race%d-%d" % (rd, i))) for i in range(N)])
    st_ = [r.s for r in res]
    n201 = st_.count(201)
    ok("J39 round %d: %d concurrent corrections with the same expected_revision=%d -> exactly one 201, others 409 stale_revision" % (rd, N, cur),
       n201 == 1 and all(r.s == 409 and r.code == "stale_revision" for r in res if r.s != 201), st_)
    rv = revs(A, PID)
    won = [r.j for r in res if r.s == 201][0]
    ok("J39 round %d: history grew by exactly one revision and the winner is the latest one; balance equals winner's amount" % rd,
       len(rv) == cur + 1 and rv[-1]["amount"] == won["amount"] and me(A)["balance"] == 100000 - won["amount"] and me(B)["balance"] == 100000 + won["amount"], (len(rv), cur, rv[-1], me(A)))
ok("J29 sum constant after R1", sum(me(t[h])["balance"] for h in t) == TOTAL)
r = revs(A, PID)
rec = [P(x["recorded_at"]) for x in r]
ok("J23 recorded_at strictly increasing across raced revisions", all(rec[i] < rec[i + 1] for i in range(len(rec) - 1)))

# ================================================================ R8 identical key concurrently
cur = revs(A, PID)[-1]["revision"]
kk = k()
body = {"expected_revision": cur, "amount": 777, "effective_at": p["created_at"], "reason": "same-key"}
res = parallel([(lambda: call("POST", "/payments/%s/corrections" % PID, body, token=A, key=kk)) for _ in range(30)])
s201 = [r for r in res if r.s == 201]
ok("J25/J52 30 concurrent identical corrections (same key) -> exactly one 201, rest 200 with the same body", len(s201) == 1 and all(r.s in (200, 201) and r.j == s201[0].j for r in res), [r.s for r in res])
ok("J25/J52 exactly one revision added, money moved once", len(revs(A, PID)) == cur + 1 and me(A)["balance"] == 100000 - 777)

# ================================================================ R3 correction vs payment at the funds boundary
for rd in range(6):
    f = fx([user("ada", 1000), user("bob", 0), user("cy", 0)])
    t = setup(f)
    A, B, C = t["ada"], t["bob"], t["cy"]
    q = pay(A, "bob", 400).j     # ada 600
    # ada has 600; correction +500 (to 900) and a payment of 500 both want the same money
    fns = [lambda: correct(A, q["payment_id"], 1, 900, q["created_at"], "up"), lambda: pay(A, "cy", 500)]
    res = parallel(fns)
    s = sorted(r.s for r in res)
    amin = me(A)["balance"]
    ok("J52 round %d: correction(+500) vs payment(500) with 600 available: not both succeed; balance never negative (%d)" % (rd, amin), amin >= 0 and not (res[0].s == 201 and res[1].s == 201), [(r.s, r.code) for r in res])
    ok("J52 round %d: exactly one wins, other 409 insufficient_funds/historical_overdraft" % rd, sorted([res[0].s, res[1].s]) == [201, 409] and (res[0].s == 201 or res[0].code in ("insufficient_funds", "historical_overdraft")) and (res[1].s == 201 or res[1].code == "insufficient_funds"), [(r.s, r.code) for r in res])
    ok("J29 sum constant", sum(me(t[h])["balance"] for h in t) == 1000)

# ================================================================ R7 mixed storm with live observers + oracle validation
H = ["ada", "bob", "cy"]
OPENB = {"ada": 3000, "bob": 3000, "cy": 3000}
f = fx([user(h, OPENB[h]) for h in H])
t = setup(f)
UID = {h: "u_" + h for h in H}
TOT = 9000
K0 = iso(now())
t_start = now()
stop = threading.Event()
plock = threading.Lock()
plist = []  # (pid, sender handle, created_at)
stats = {"pay": 0, "corr_ok": 0, "corr_fail": {}, "pay_fail": 0}
viol = []
reads = [0, 0, 0]


def rr(seed):
    return random.Random(SEED * 1000 + seed)


def writer(i):
    rnd = rr(i)
    while not stop.is_set():
        if len(plist) < 10 or (rnd.random() < .35 and len(plist) < 400):
            a, b = rnd.sample(H, 2)
            r = pay(t[a], b, rnd.randint(1, 400))
            if r.s == 201:
                with plock:
                    plist.append((r.j["payment_id"], a, r.j["created_at"]))
                stats["pay"] += 1
            elif r.s == 409:
                stats["pay_fail"] += 1
            else:
                viol.append(("pay status", r.s, r.b[:100]))
        else:
            with plock:
                pid, a, ca = rnd.choice(plist)
                times = [x[2] for x in plist]
            rv = revs(t[a], pid)
            cur = rv[-1]["revision"]
            eff = rnd.choice(times) if rnd.random() < .6 else iso(max(P(ca) - dt.timedelta(milliseconds=rnd.randint(0, 800)), t_start - dt.timedelta(seconds=1)))
            if P(eff) > now():
                eff = ca
            r = correct(t[a], pid, cur, rnd.choice([0, rnd.randint(1, 500), rv[-1]["amount"] + rnd.randint(1, 200)]), eff, "storm")
            if r.s == 201:
                stats["corr_ok"] += 1
            elif r.s == 409:
                stats["corr_fail"][r.code] = stats["corr_fail"].get(r.code, 0) + 1
            else:
                viol.append(("corr status", r.s, r.b[:100]))


def observer_const(i):
    rnd = rr(500 + i)
    while not stop.is_set():
        # immutable view: known_at = K0 (before any storm record), as_of in the past
        as_of = iso(t_start - dt.timedelta(seconds=rnd.randint(0, 3)))
        tot = sum(me_at(t[h], as_of, K0).j["balance"] for h in H)
        reads[0] += 1
        if tot != TOT:
            viol.append(("const view sum", as_of, tot))


def observer_cur(i):
    rnd = rr(700 + i)
    while not stop.is_set():
        h = rnd.choice(H)
        m = me(t[h])
        reads[1] += 1
        if m["total"] < 0 or m["available"] < 0 or m["balance"] != m["total"] or m["held"] != 0:
            viol.append(("current /me", m))
        s = stmt(t[h], limit=200)
        if s.s != 200:
            viol.append(("statement status", s.s)); continue
        j = s.j
        if not j["has_more"]:
            bal = j["opening_balance"]
            for e in j["entries"]:
                bal += e["delta"]
                if bal != e["balance_after"]:
                    viol.append(("balance_after chain", h, e["payment"]["payment_id"], bal, e["balance_after"])); break
            if bal != j["closing_balance"]:
                viol.append(("opening+deltas != closing", h, bal, j["closing_balance"]))
            ents = j["entries"]
            if j["opening_balance"] < 0:
                viol.append(("negative opening in a statement", h))
            for n_, e in enumerate(ents):
                end_of_group = n_ == len(ents) - 1 or P(ents[n_ + 1]["effective_at"]) != P(e["effective_at"])
                if end_of_group and e["balance_after"] < 0:
                    viol.append(("negative balance at an effective-time boundary", h, e["payment"]["payment_id"], e["effective_at"], e["balance_after"]))
                    break
        reads[2] += 1


ths = [threading.Thread(target=writer, args=(i,)) for i in range(8)] + [threading.Thread(target=observer_const, args=(i,)) for i in range(2)] + [threading.Thread(target=observer_cur, args=(i,)) for i in range(3)]
[x.start() for x in ths]
time.sleep(5.0)
stop.set()
[x.join() for x in ths]
print("storm stats", stats, "reads", reads, "payments", len(plist))
ok("J52 storm: no status other than 201/409 from writers", not [v for v in viol if v[0] in ("pay status", "corr status")], viol[:3])
ok("J52 storm: every immutable (known_at fixed) historical view summed to the seeded total while writers ran (%d reads)" % reads[0], not [v for v in viol if v[0] == "const view sum"], [v for v in viol if v[0] == "const view sum"][:3])
ok("J52 storm: current /me never negative, balance==total==available, held 0 (%d reads)" % reads[1], not [v for v in viol if v[0] == "current /me"], [v for v in viol if v[0] == "current /me"][:3])
ok("J15/J52 storm: every complete statement read is self-consistent (balance_after chain, opening+deltas==closing, never negative) (%d reads)" % reads[2], not [v for v in viol if v[0] not in ("pay status", "corr status", "const view sum", "current /me")], [v for v in viol if v[0] not in ("pay status", "corr status", "const view sum", "current /me")][:3])
ok("J52 storm exercised both corrections accepted (%d) and rejected %s" % (stats["corr_ok"], stats["corr_fail"]), stats["corr_ok"] > 20 and sum(stats["corr_fail"].values()) > 5)
# final oracle validation from the API's own revision lists
o = Oracle({UID[h]: OPENB[h] for h in H})
sendtok = {UID[h]: t[h] for h in H}
allp = {}
for h in H:
    s, ents_ = all_stmt(t[h])
    for e in ents_:
        allp[e["payment"]["payment_id"]] = e["payment"]
for pid, p_ in allp.items():
    o.add(pid, p_["from_user_id"], p_["to_user_id"], revs(sendtok[p_["from_user_id"]], pid))
ok("J52 final: /me current == oracle for each user", all(me(t[h])["balance"] == o.total(UID[h]) for h in H), [(h, me(t[h])["balance"], o.total(UID[h])) for h in H])
ok("J29 final: sum == seeded", sum(me(t[h])["balance"] for h in H) == TOT)
# historical nonnegativity: every effective-time boundary (combined effect of all movements at that instant) for every user
neg = []
instants = sorted({m_[0] for h in H for m_ in o.moves(UID[h], None)})
for h in H:
    mv = o.moves(UID[h], None)
    bal = OPENB[h]
    i = 0
    while i < len(mv):
        j = i
        while j < len(mv) and mv[j][0] == mv[i][0]:
            bal += mv[j][2]; j += 1
        if bal < 0:
            neg.append((h, iso(mv[i][0]), bal))
        i = j
ok("J27/J52 final history: no user negative at ANY effective-time boundary (%d boundaries) after %d accepted corrections" % (len(instants), stats["corr_ok"]), not neg, neg[:3])
bad = []
for x in instants[::max(1, len(instants) // 40)]:
    for h in H:
        r = me_at(t[h], iso(x))
        if r.j["balance"] != o.total(UID[h], x):
            bad.append((h, iso(x), r.j["balance"], o.total(UID[h], x)))
ok("J52 final: /me?as_of at ~40 instants == oracle for every user", not bad, bad[:3])
bad = []
for h in H:
    s, ents_ = all_stmt(t[h])
    eo, ee, ec = o.window(UID[h])
    got = [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"], e["payment"]["amount"], P(e["effective_at"])) for e in ents_]
    if got != ee or s["opening_balance"] != eo or s["closing_balance"] != ec:
        bad.append(h)
ok("J52 final: statements == oracle after the storm", not bad, bad)
done("t3_race")
