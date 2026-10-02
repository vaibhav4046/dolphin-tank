"""R3-N2 one-clock sweep (stage-2 "available is total - held, never negative" at every read; stage-3 "Historical holds").
Random back-to-back lifecycle (fund+authorize pairs, pays, partial/final captures, voids, deadline expiry), then every user is
read at every public event instant (+-1us) with /me?as_of= and compared with an oracle built ONLY from public timestamps:
  total(u,T) = opening + payments with created_at <= T (sender negative, receiver positive)
  held(u,T)  = own authorizations: 0 before created_at; 0 from closed_at; 0 from expires_at; else amount - captures with created_at <= T
usage: r3_sweep.py [seed]"""
import random, sys, time
from lib3 import *
import clk

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1
rnd = random.Random(SEED)
USERS = ["ada", "bob", "cy", "dee"]
OPEN = {h: rnd.choice([3000, 5000, 8000]) for h in USERS}
TOTAL0 = sum(OPEN.values())
f = fx([user(h, OPEN[h]) for h in USERS])
f["authorization_ttl_seconds"] = 2
t = setup(f)
now = lambda: dt.datetime.now(UTC)
SLACK = dt.timedelta(milliseconds=30)

pays = {}    # payment_id -> (from, to, amount, created_at dt)
auths = {}   # authorization_id -> dict(sender, receiver, amount, caps=[(dt, amt)])
stamps_bad = []


def stamp_ok(label, t0, created, t1):
    if not clk.inwin(created, t0, t1):
        stamps_bad.append((label, iso(t0), iso(created), iso(t1)))


def do_pay(a, b, amt):
    t0 = now(); r = pay(t[a], b, amt); t1 = now()
    if r.s == 201:
        c = P(r.j["created_at"]); stamp_ok("pay", t0, c, t1)
        pays[r.j["payment_id"]] = (a, b, amt, c)
    return r


def do_auth(a, b, amt):
    t0 = now(); r = authorize(t[a], b, amt); t1 = now()
    if r.s == 201:
        c = P(r.j["created_at"]); stamp_ok("authorize", t0, c, t1)
        ex = P(r.j["expires_at"])
        ok("one clock: expires_at - created_at == ttl exactly (2 s), same precision", ex - c == dt.timedelta(seconds=2), (r.j["created_at"], r.j["expires_at"]))
        auths[r.j["authorization_id"]] = dict(sender=a, receiver=b, amount=amt, caps=[], created=c)
    return r


def do_capture(aid, amt, final):
    A_ = auths[aid]; t0 = now(); r = capture(t[A_["receiver"]], aid, amount=amt, final=final); t1 = now()
    if r.s == 201:
        c = P(r.j["created_at"]); stamp_ok("capture", t0, c, t1)
        pays[r.j["payment_id"]] = (A_["sender"], A_["receiver"], r.j["amount"], c)
        A_["caps"].append((c, r.j["amount"]))
    return r


def pause():
    x = rnd.random()
    if x < .6: return
    time.sleep(rnd.choice([0.001, 0.003, 0.01, 0.03]) if x < .97 else 0.7)


# ---- phase 1: random lifecycle
for i in range(90):
    op = rnd.choice(["fund_auth", "fund_auth", "pay", "auth", "cap", "cap", "void"])
    names = rnd.sample(USERS, 2)
    if op == "fund_auth":   # the F2 pattern: money in, then immediately held against it
        amt = rnd.choice([200, 500, 900])
        if do_pay(names[0], names[1], amt).s == 201:
            do_auth(names[1], rnd.choice([u for u in USERS if u != names[1]]), amt)
    elif op == "pay":
        do_pay(names[0], names[1], rnd.choice([10, 150, 700]))
    elif op == "auth":
        do_auth(names[0], names[1], rnd.choice([100, 400, 1500]))
    elif op == "cap" and auths:
        aid = rnd.choice(list(auths)); do_capture(aid, rnd.choice([None, 50, 300]), rnd.choice([None, False, True]))
    elif op == "void" and auths:
        aid = rnd.choice(list(auths)); call("POST", "/authorizations/%s/void" % aid, {}, token=t[auths[aid]["sender"]])
    pause()
ok("phase 1 produced a useful mix (>=20 payments, >=15 authorizations, >=3 captures)", len(pays) >= 20 and len(auths) >= 15 and sum(len(a["caps"]) for a in auths.values()) >= 3, (len(pays), len(auths)))
ok("every payment/authorization created_at lies within its own request window (+-30 ms): one wall clock, no ratchet", not stamps_bad, stamps_bad[:3])

# wait until every hold's deadline has passed
last_exp = max(P(authz(t[a["sender"]], aid)["expires_at"]) for aid, a in auths.items())
sleep_until(iso(last_exp), 0.2)

# ---- public data
pub = {}
for h in USERS:
    for a in authz(t[h], limit=200)["authorizations"]:
        pub[a["authorization_id"]] = a
ok("every authorization is visible to its sender", set(auths) <= set(pub), (len(auths), len(pub)))
soft = []
for aid, a in auths.items():
    p = pub[aid]
    a["closed"] = P(p["closed_at"]) if p["closed_at"] else None
    a["exp"] = P(p["expires_at"]); a["status"] = p["status"]
    ok("closed_at: null only while open; every terminal authorization carries it", (p["closed_at"] is None) == (p["status"] == "open"), (aid, p))
    if p["status"] == "captured" and a["caps"]:
        if a["closed"] != max(c for c, _ in a["caps"]):
            soft.append(("closed_at != last capture created_at", aid, p["closed_at"], iso(max(c for c, _ in a["caps"]))))
    if a["closed"] is not None:
        ok("closed_at never before created_at (a hold cannot be released before it is placed)", a["closed"] >= a["created"], (aid, p))
print("INFO closed_at vs capture created_at differences:", len(soft), soft[:3])

instants = {EPOCH, now(), dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)}
for (_, _, _, c) in pays.values(): instants.add(c)
for a in auths.values():
    instants.add(a["created"]); instants.add(a["exp"])
    if a["closed"]: instants.add(a["closed"])
probe = set()
for x in instants:
    probe.update([x - US, x, x + US])


def total_at(h, T):
    v = OPEN[h]
    for (a, b, amt, c) in pays.values():
        if c <= T:
            v += -amt if a == h else amt if b == h else 0
    return v


def held_at(h, T):
    s = 0
    for a in auths.values():
        if a["sender"] != h or T < a["created"]: continue
        if a["closed"] is not None and T >= a["closed"]: continue
        if T >= a["exp"]: continue
        s += a["amount"] - sum(x for (c, x) in a["caps"] if c <= T)
    return s


bad = []
nviews = 0
neg_avail = 0
for T in sorted(probe):
    tot = 0
    for h in USERS:
        r = me_at(t[h], iso(T))
        nviews += 1
        if r.s != 200:
            bad.append(("status", h, iso(T), r.s)); continue
        m = r.j
        got = (m["total"], m["held"], m["available"], m["balance"])
        exp_t, exp_h = total_at(h, T), held_at(h, T)
        if not inv(m): bad.append(("invariant", h, iso(T), got))
        if m["available"] < 0: neg_avail += 1
        if (m["total"], m["held"]) != (exp_t, exp_h): bad.append(("oracle", h, iso(T), got, (exp_t, exp_h)))
        if m.get("as_of") != iso(T): bad.append(("echo", h, iso(T), m.get("as_of")))
        tot += m["total"]
    if tot != TOTAL0: bad.append(("sum", iso(T), tot, TOTAL0))
ok("%d historical views (%d instants x 4 users): invariants, oracle equality, echo, conservation; first bad: %s" % (nviews, len(probe), bad[:2]), not bad, bad[:4])
ok("no view anywhere had available < 0", neg_avail == 0, neg_avail)

# known_at = now must equal omission for a sample; current /me equals as_of=now
for h in USERS:
    cur = me(t[h]); n_ = me_at(t[h], iso(now()), iso(now())).j
    ok("%s current /me == /me?as_of=now&known_at=now (money fields)" % h, all(cur[k_] == n_[k_] for k_ in ("balance", "total", "held", "available")) and cur["held"] == 0, (cur, n_))
    st = all_stmt(t[h])[0]
    ok("%s statement closing_balance == /me.total" % h, st["closing_balance"] == cur["total"], (st["closing_balance"], cur["total"]))
print("INFO", clk.report())
done("r3_sweep seed %d (%d payments, %d authorizations)" % (SEED, len(pays), len(auths)))
