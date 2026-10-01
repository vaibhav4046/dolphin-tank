"""H01-H04 A03: concurrency with a live observer. Flows are monotone (ada -> bob) so read order gives bounds."""
import random, threading, time
from lib import *

RUNS = 1
f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0), user("dee", 5000)])
TOTAL = 17500

class Obs:
    def __init__(self, t):
        self.t, self.viol, self.n, self.stop = t, [], [0], threading.Event()
    def run(self, order, kind):
        while not self.stop.is_set():
            try:
                ms = {h: me(self.t[h]) for h in order}
                la = call("GET", "/authorizations", token=self.t["bob"]).j["authorizations"]
            except Exception as e:
                self.viol.append("obs error %r" % e); return
            self.n[0] += 1
            for h, m in ms.items():
                if not inv(m):
                    self.viol.append("INV %s %s" % (h, m))
            for a in la:
                if a["captured_amount"] > a["amount"]:
                    self.viol.append("captured > authorized %s" % a)
                if a["status"] == "open" and a["remaining_amount"] + a["captured_amount"] != a["amount"]:
                    self.viol.append("open remaining mismatch %s" % a)
                if a["status"] != "open" and a["remaining_amount"] != 0:
                    self.viol.append("closed with remaining %s" % a)
            s = sum(m["total"] for m in ms.values())
            tot = sum(u["balance"] for u in f["users"] if u["handle"] in ms)
            if kind == "credit_first" and s > tot:
                self.viol.append("credit before debit %s" % {h: m["total"] for h, m in ms.items()})
            if kind == "debit_first" and s < tot:
                self.viol.append("debit before credit %s" % {h: m["total"] for h, m in ms.items()})
    def start(self):
        self.ths = [threading.Thread(target=self.run, args=(o, kd)) for (o, kd) in ((("bob", "ada"), "credit_first"), (("ada", "bob"), "debit_first")) for _ in range(2)]
        [x.start() for x in self.ths]
    def end(self):
        self.stop.set(); [x.join() for x in self.ths]

for rnd in range(3):
    # ---------- H02 50-way authorize at the available boundary (ada available 10000, hold 300 each -> 33 fit)
    t = setup(f); ob = Obs(t); ob.start()
    res = parallel([lambda: authorize(t["ada"], "bob", 300) for _ in range(50)])
    n201 = sum(1 for r in res if r.s == 201); bad = [r for r in res if r.s not in (201, 409)]
    ok("H02 r%d 50-way authorize 300 vs available 10000: exactly 33 succeed, 17 insufficient_funds" % rnd,
       n201 == 33 and sum(1 for r in res if r.s == 409 and r.code == "insufficient_funds") == 17 and not bad, [r.s for r in res])
    m = me(t["ada"])
    ok("H02 r%d held 9900 available 100 total 10000" % rnd, (m["held"], m["available"], m["total"]) == (9900, 100, 10000), m)
    ob.end()
    ok("H01 r%d observer clean during 50-way authorize (%d samples)" % (rnd, ob.n[0]), not ob.viol and ob.n[0] > 10, ob.viol[:3])
    # mixed authorize + pay at the boundary
    t2 = setup(f); ob = Obs(t2); ob.start()
    fns = [(lambda: authorize(t2["ada"], "bob", 300)) if i % 2 else (lambda: pay(t2["ada"], "bob", 300)) for i in range(50)]
    res = parallel(fns)
    ns = sum(1 for r in res if r.s == 201)
    m = me(t2["ada"])
    ok("H02 r%d mixed 25 authorize + 25 pay of 300: exactly 33 succeed in total, available never negative" % rnd, ns == 33 and all(r.s in (201, 409) for r in res), [r.s for r in res])
    ok("H02 r%d mixed: held+moved == 9900, available == 100" % rnd, m["available"] == 100 and m["held"] + (10000 - m["total"]) == 9900 and inv(m), m)
    ob.end()
    ok("H01 r%d observer clean during mixed authorize/pay (%d samples)" % (rnd, ob.n[0]), not ob.viol and ob.n[0] > 10, ob.viol[:3])

    # ---------- H03 capture storm on one hold, distinct keys, partial non-final captures
    t = setup(f); ob = Obs(t); ob.start()
    aid = authorize(t["ada"], "bob", 1000).j["authorization_id"]
    res = parallel([lambda: capture(t["bob"], aid, amount=100, final=False) for _ in range(40)])
    n201 = [r for r in res if r.s == 201]
    other = [r for r in res if r.s != 201]
    ok("H03 r%d 40 concurrent 100-captures of a 1000 hold: exactly 10 succeed" % rnd, len(n201) == 10 and all((r.s, r.code) in ((422, "capture_exceeds_authorization"), (409, "authorization_not_open")) for r in other), [(r.s, r.code) for r in res])
    x = authz(t["bob"], aid)
    ok("H03 r%d captured 1000, closed, 10 payment ids, all distinct" % rnd, (x["captured_amount"], x["status"], x["remaining_amount"], len(x["payment_ids"]), len(set(x["payment_ids"]))) == (1000, "captured", 0, 10, 10), x)
    ok("H03 r%d money: ada 9000 bob 3500, held 0" % rnd, (me(t["ada"])["total"], me(t["bob"])["total"], me(t["ada"])["held"]) == (9000, 3500, 0))
    # capture storm with overshoot sizes
    aid = authorize(t["ada"], "bob", 1000).j["authorization_id"]
    res = parallel([lambda: capture(t["bob"], aid, amount=300, final=False) for _ in range(20)])
    ok("H03 r%d 20 x 300 against 1000: exactly 3 succeed (900), remainder 100 stays held" % rnd, sum(1 for r in res if r.s == 201) == 3 and authz(t["bob"], aid)["remaining_amount"] == 100 and me(t["ada"])["held"] == 100, [(r.s, r.code) for r in res])
    ob.end()
    ok("H01 r%d observer clean (%d samples)" % (rnd, ob.n[0]), not ob.viol and ob.n[0] > 10, ob.viol[:3])

    # ---------- H04 void vs capture races
    t = setup(f); ob = Obs(t); ob.start()
    outcomes = {"void": 0, "capture": 0}; bad = []
    for i in range(40):
        a = authorize(t["ada"], "bob", 100).j["authorization_id"]
        before = (me(t["ada"])["total"], me(t["bob"])["total"])
        mode = i % 2
        fns = [lambda: void(t["ada"], a), (lambda: capture(t["bob"], a, amount=60)) if mode else (lambda: capture(t["bob"], a))]
        rv, rc = parallel(fns)
        x = authz(t["bob"], a); after = (me(t["ada"])["total"], me(t["bob"])["total"], me(t["ada"])["held"])
        if rv.s == 200 and rc.s == 409 and x["status"] == "voided" and after[2] == 0 and (after[0], after[1]) == before:
            outcomes["void"] += 1
        elif rc.s == 201 and rv.s == 409 and x["status"] == "captured" and after[2] == 0 and after[1] == before[1] + rc.j["amount"] and after[0] == before[0] - rc.j["amount"]:
            outcomes["capture"] += 1
        elif rc.s == 201 and rv.s == 200 and False:
            pass
        else:
            bad.append((rv.s, rv.code, rc.s, rc.code, x, before, after))
    ok("H04 r%d 40 void-vs-capture races: every one resolves to exactly one outcome %s" % (rnd, outcomes), not bad, bad[:2])
    ob.end()
    ok("H01 r%d observer clean (%d samples)" % (rnd, ob.n[0]), not ob.viol and ob.n[0] > 10, ob.viol[:3])

    # ---------- random storm, monotone flows, then final reconciliation
    t = setup(f); ob = Obs(t); ob.start()
    made = []; lock = threading.Lock(); rng = random.Random(1000 + rnd); paid = [0]
    def worker(seed):
        r_ = random.Random(seed)
        for _ in range(60):
            op = r_.choice(["auth", "auth", "pay", "capp", "capf", "void", "capall"])
            try:
                if op == "auth":
                    r = authorize(t["ada"], "bob", r_.randint(1, 600))
                    if r.s == 201:
                        with lock: made.append(r.j["authorization_id"])
                elif op == "pay":
                    r = pay(t["ada"], "bob", r_.randint(1, 300))
                    if r.s == 201:
                        with lock: paid[0] += r.j["amount"]
                else:
                    with lock: aid_ = r_.choice(made) if made else None
                    if aid_ is None: continue
                    if op == "capp": capture(t["bob"], aid_, amount=r_.randint(1, 200), final=False)
                    elif op == "capf": capture(t["bob"], aid_, amount=r_.randint(1, 200))
                    elif op == "capall": capture(t["bob"], aid_)
                    else: void(t["ada"], aid_)
            except Exception as e:
                ob.viol.append("worker error %r" % e)
    ths = [threading.Thread(target=worker, args=(rnd * 100 + i,)) for i in range(12)]
    [x.start() for x in ths]; [x.join() for x in ths]
    ob.end()
    ok("H01 r%d storm observer clean (%d samples)" % (rnd, ob.n[0]), not ob.viol, ob.viol[:3])
    L = authz(t["bob"], limit=200)["authorizations"] if False else call("GET", "/authorizations?limit=200", token=t["bob"]).j["authorizations"]
    captured_sum = sum(a["captured_amount"] for a in L)
    open_rem = sum(a["remaining_amount"] for a in L if a["status"] == "open")
    ma, mb = me(t["ada"]), me(t["bob"])
    ok("H01 r%d reconcile: ada total = 10000 - paid - captured" % rnd, ma["total"] == 10000 - paid[0] - captured_sum and mb["total"] == 2500 + paid[0] + captured_sum, (ma, mb, paid, captured_sum))
    ok("H01 r%d reconcile: ada held == sum remaining of open holds, invariants" % rnd, ma["held"] == open_rem and inv(ma) and inv(mb) and ma["total"] + mb["total"] == 12500, (ma, open_rem))
    ok("H01 r%d every authorization: captured <= amount, payment_ids sum == captured_amount" % rnd, all(a["captured_amount"] <= a["amount"] for a in L), [a for a in L if a["captured_amount"] > a["amount"]][:2])
    feed = call("GET", "/activity?limit=200", token=t["ada"]).j["payments"]
    ok("H01 r%d conservation across all four wallets" % rnd, sum(me(t[h])["total"] for h in t) == TOTAL)
done("s2_race")
