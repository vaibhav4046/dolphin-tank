"""J01-J03, J53: conservation, never negative (concurrent observer), one payment per request."""
import threading, time
from lib import *


def observers(t, pairs, total_hi_lo, stop, viol, counts):
    """pairs: list of (first, second). Transfers are first=ada->bob monotone, so
    read order (credit-side first) must give sum <= total; (debit-side first) sum >= total."""
    def run(order, kind):
        while not stop.is_set():
            try:
                v = {h: bal(t[h]) for h in order}
            except Exception as e:
                viol.append("observer error %r" % e)
                return
            counts[0] += 1
            if any(x < 0 for x in v.values()):
                viol.append("NEGATIVE %s" % v)
            s = sum(v.values())
            if kind == "credit_first" and s > total_hi_lo:
                viol.append("credit visible before debit: %s" % v)
            if kind == "debit_first" and s < total_hi_lo:
                viol.append("debit visible before credit: %s" % v)
    ths = [threading.Thread(target=run, args=(o, kind)) for (o, kind) in pairs for _ in range(2)]
    [x.start() for x in ths]
    return ths


# ---- A: 50 concurrent payments of 100 from ada(1000) to bob(0) with distinct keys
for rnd in range(3):
    t = setup(fx([user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 0)]))
    stop = threading.Event(); viol = []; cnt = [0]
    ths = observers(t, [(("bob", "ada"), "credit_first"), (("ada", "bob"), "debit_first")], 1000, stop, viol, cnt)
    res = parallel([lambda: call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=t["ada"], key=k()) for _ in range(50)])
    stop.set(); [x.join() for x in ths]
    n201 = sum(1 for r in res if getattr(r, "s", 0) == 201)
    n409 = [r for r in res if getattr(r, "s", 0) == 409 and r.code == "insufficient_funds"]
    ok("A%d exactly 10 payments succeed of 50 (balance 1000)" % rnd, n201 == 10 and len(n409) == 40, [getattr(r, "s", r) for r in res])
    ok("A%d final balances ada 0 bob 1000" % rnd, (bal(t["ada"]), bal(t["bob"])) == (0, 1000))
    ok("A%d conservation" % rnd, sum(bal(t[h]) for h in t) == 1000)
    ok("A%d observers saw no negative/torn state (%d samples)" % (rnd, cnt[0]), not viol and cnt[0] > 20, viol[:3])
    feed = call("GET", "/activity?limit=200", token=t["ada"]).j["payments"]
    ok("A%d ledger has exactly 10 payments" % rnd, len(feed) == 10, len(feed))

# ---- B: one request paid concurrently by distinct keys -> one payment
for rnd in range(3):
    f = fx(requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}])
    t = setup(f)
    res = parallel([lambda: call("POST", "/requests/rq_1/pay", {}, token=t["ada"], key=k()) for _ in range(30)])
    n201 = [r for r in res if r.s == 201]
    rest = [r for r in res if r.s != 201]
    ok("B%d one 201 among 30 distinct-key pays" % rnd, len(n201) == 1, [r.s for r in res])
    ok("B%d others 409 request_not_pending" % rnd, all(r.s == 409 and r.code == "request_not_pending" for r in rest), [(r.s, r.code) for r in rest][:5])
    ok("B%d money moved once" % rnd, (bal(t["ada"]), bal(t["bob"])) == (8800, 3700))
    rq = call("GET", "/requests", token=t["ada"]).j["requests"][0]
    ok("B%d request paid w/ payment_id" % rnd, rq["status"] == "paid" and rq["payment_id"] == n201[0].j["payment_id"] and n201[0].j["request_id"] == "rq_1", rq)

# ---- B2: pay / decline / cancel race on fresh requests
viol = 0
for rnd in range(15):
    t = setup(fx(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 0)]))
    r = call("POST", "/requests", {"payer_handle": "ada", "amount": 500}, token=t["bob"], key=k())
    rid = r.j["request_id"]
    fns = [lambda: call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=k()) for _ in range(4)]
    fns += [lambda: call("POST", "/requests/%s/decline" % rid, {}, token=t["ada"]) for _ in range(3)]
    fns += [lambda: call("POST", "/requests/%s/cancel" % rid, {}, token=t["bob"]) for _ in range(3)]
    res = parallel(fns)
    final = call("GET", "/requests", token=t["ada"]).j["requests"][0]
    a, b = bal(t["ada"]), bal(t["bob"])
    paid201 = sum(1 for x in res[:4] if x.s == 201)
    good = (
        final["status"] in ("paid", "declined", "cancelled")
        and paid201 <= 1
        and ((final["status"] == "paid" and paid201 == 1 and (a, b) == (500, 500) and final["payment_id"])
             or (final["status"] != "paid" and paid201 == 0 and (a, b) == (1000, 0) and final["payment_id"] is None))
        and sum([a, b, bal(t["cy"]), bal(t["dee"])]) == 1000
    )
    # exactly one terminal winner: the other-kind calls must not report success after it lost
    winners = {final["status"]}
    if final["status"] != "paid":
        good = good and all(x.s == 409 for x in res[:4])
    if final["status"] != "declined":
        good = good and all(x.s in (409,) for x in res[4:7])
    if final["status"] != "cancelled":
        good = good and all(x.s in (409,) for x in res[7:])
    if not good:
        viol += 1
        print("  B2 round", rnd, "final", final["status"], "bal", a, b, [x.s for x in res])
ok("B2 15 rounds pay/decline/cancel race: single terminal state, money at most once, consistent responses", viol == 0, viol)

# ---- C: requests above combined balance all paid concurrently; also direct payments
for rnd in range(3):
    t = setup(fx(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 0)]))
    rids = []
    for h in ("bob", "cy", "dee", "bob", "cy", "dee", "bob", "cy", "dee", "bob"):
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 600}, token=t[h], key=k())
        assert r.s == 201, r
        rids.append(r.j["request_id"])
    stop = threading.Event(); viol = []; cnt = [0]
    ths = observers(t, [(("bob", "cy", "dee", "ada"), "credit_first")], 1000, stop, viol, cnt)
    fns = [lambda rid=rid: call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=k()) for rid in rids]
    fns += [lambda: call("POST", "/payments", {"to_handle": "cy", "amount": 600}, token=t["ada"], key=k()) for _ in range(5)]
    res = parallel(fns)
    stop.set(); [x.join() for x in ths]
    n201 = sum(1 for r in res if r.s == 201)
    ok("C%d at most one 600 debit from balance 1000 (got %d)" % (rnd, n201), n201 == 1, [r.s for r in res])
    ok("C%d ada=400, conservation" % rnd, bal(t["ada"]) == 400 and sum(bal(t[h]) for h in t) == 1000)
    ok("C%d failures are 409 insufficient_funds" % rnd, all(r.s == 201 or (r.s == 409 and r.code == "insufficient_funds") for r in res), [(r.s, r.code) for r in res])
    ok("C%d observers clean (%d samples)" % (rnd, cnt[0]), not viol, viol[:3])

# ---- D: sustained churn 4 s, ada->bob unit payments (monotone) with observers in both read orders
t = setup(fx([user("ada", 3000), user("bob", 0), user("cy", 0), user("dee", 0)]))
stop = threading.Event(); wstop = threading.Event(); viol = []; cnt = [0]; sent = [0]
ths = observers(t, [(("bob", "ada"), "credit_first"), (("ada", "bob"), "debit_first")], 3000, stop, viol, cnt)
lock = threading.Lock()


def writer():
    while not wstop.is_set():
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=t["ada"], key=k())
        if r.s == 201:
            with lock:
                sent[0] += 1


ws = [threading.Thread(target=writer) for _ in range(8)]
[w.start() for w in ws]
time.sleep(4)
wstop.set(); [w.join() for w in ws]
stop.set(); [x.join() for x in ths]
ok("D churn: %d payments, %d observer samples, no torn/negative reads" % (sent[0], cnt[0]), not viol and cnt[0] > 100 and sent[0] > 100, (viol[:3], cnt[0], sent[0]))
ok("D final ada=3000-sent, bob=sent, sum 3000", (bal(t["ada"]), bal(t["bob"])) == (3000 - sent[0], sent[0]), (bal(t["ada"]), bal(t["bob"]), sent[0]))

done("c01_conservation")
