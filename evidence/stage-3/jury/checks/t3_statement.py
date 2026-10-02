"""J10-J17 J33(no-known_at part) J13: statement vs independent oracle with random payments, corrections, windows, pages, ties."""
import random, sys, time
from lib3 import *

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 7
rnd = random.Random(SEED)
print("seed", SEED)
H = ["ada", "bob", "cy", "dee"]
OPENB = {"ada": 1000000, "bob": 800000, "cy": 600000, "dee": 400000}
f = fx([user(h, OPENB[h]) for h in H])
t = setup(f)
UID = {h: "u_" + h for h in H}
o = Oracle({UID[h]: OPENB[h] for h in H})
TOTAL = sum(OPENB.values())

pays = []
for i in range(60):
    a, b = rnd.sample(H, 2)
    r = pay(t[a], b, rnd.randint(1, 5000), note="n%d" % i, visibility=rnd.choice(["public", "private"]))
    assert r.s == 201, r
    pays.append(r.j)
    if i % 9 == 0:
        time.sleep(0.003)
stamps = sorted(P(p["created_at"]) for p in pays)
# corrections: random effective_at (past, between payments, sometimes equal to another payment's instant / to each other)
tie_at = iso(stamps[10] + dt.timedelta(microseconds=500))
ncorr = 0
for j in range(30):
    p = rnd.choice(pays)
    cur = revs(t[[h for h in H if UID[h] == p["from_user_id"]][0]], p["payment_id"])[-1]
    if j < 6:
        eff = tie_at
    elif j < 10:
        eff = pays[rnd.randrange(len(pays))]["created_at"]
    else:
        eff = iso(stamps[0] + (stamps[-1] - stamps[0]) * rnd.random() - dt.timedelta(microseconds=rnd.choice([0, 0, 1, 7])))
    amt = rnd.choice([0, cur["amount"] + rnd.randint(1, 50), max(0, cur["amount"] - rnd.randint(1, 50)), rnd.randint(1, 5000)])
    r = correct(t[[h for h in H if UID[h] == p["from_user_id"]][0]], p["payment_id"], cur["revision"], amt, eff, "c%d" % j)
    assert r.s == 201, (r, p, cur, eff, amt)
    ncorr += 1
print("payments", len(pays), "corrections", ncorr)
for p in pays:
    tk = t[[h for h in H if UID[h] == p["from_user_id"]][0]]
    o.add(p["payment_id"], p["from_user_id"], p["to_user_id"], revs(tk, p["payment_id"]))

# ---- J12 shape + J13/J14/J15 full statements vs oracle
def cmp(h, resp, frm, to, label):
    exp_open, exp_entries, exp_close = o.window(UID[h], frm, to)
    j = resp.j
    if resp.s != 200:
        return "status %s %s" % (resp.s, resp.b[:150])
    if set(j) != {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"}:
        return "keys %s" % sorted(j)
    if j["opening_balance"] != exp_open or j["closing_balance"] != exp_close:
        return "open/close %s/%s != %s/%s" % (j["opening_balance"], j["closing_balance"], exp_open, exp_close)
    got = [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"], e["payment"]["amount"], P(e["effective_at"])) for e in j["entries"]]
    return None if got == exp_entries[:len(got)] and (len(got) == len(exp_entries) or j["has_more"]) else "entries %d/%d first diff %s" % (len(got), len(exp_entries), next(((a, b) for a, b in zip(got, exp_entries) if a != b), None))

for h in H:
    r = stmt(t[h], limit=200)
    e = cmp(h, r, None, None, "full")
    ok("J13/J14/J15 %s full statement equals oracle (order by selected effective_at then id, delta, balance_after, revision, amount, open/close)" % h, e is None, e)
    ents = r.j["entries"]
    ok("J12 %s entry keys payment/delta/balance_after/revision/effective_at/recorded_at; payment.amount selected amount" % h,
       all(set(["payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"]) <= set(x) for x in ents) and all(RFC3339.match(x["effective_at"]) and RFC3339.match(x["recorded_at"]) for x in ents))
    ok("J15 %s opening + sum(delta) == closing; sent negative, received positive" % h,
       r.j["opening_balance"] + sum(x["delta"] for x in ents) == r.j["closing_balance"] and all((x["delta"] <= 0) == (x["payment"]["from_user_id"] == UID[h]) or x["delta"] == 0 for x in ents))
    ok("J13 %s keys: effective_at asc, ties by payment id bytewise asc" % h,
       all((P(ents[i]["effective_at"]), ents[i]["payment"]["payment_id"].encode()) <= (P(ents[i + 1]["effective_at"]), ents[i + 1]["payment"]["payment_id"].encode()) for i in range(len(ents) - 1)))
    ok("J15 %s closing_balance equals current /me balance" % h, r.j["closing_balance"] == me(t[h])["balance"])
ok("J29 sum of current balances constant after corrections", sum(me(t[h])["balance"] for h in H) == TOTAL)

# zero-amount revisions appear as entries with delta 0
zero = [p for p in pays if o.selected(p["payment_id"], None)["amount"] == 0]
print("INFO payments currently at zero amount:", len(zero))
for p in zero[:3]:
    hs = [h for h in H if UID[h] in (p["from_user_id"], p["to_user_id"])]
    for h in hs:
        full = stmt(t[h], limit=200).j["entries"]
        ok("J33 zero-amount revision of %s appears for %s with delta 0 and payment.amount 0" % (p["payment_id"], h),
           any(e["payment"]["payment_id"] == p["payment_id"] and e["delta"] == 0 and e["payment"]["amount"] == 0 for e in full), full[:2])

# ---- J11/J14 random windows incl. exact instants +-1us, from-only, to-only
instants = sorted({o.moves(UID[h], None)[i][0] for h in H for i in range(len(o.moves(UID[h], None)))})
cand = []
for x in instants[::3]:
    cand += [x - US, x, x + US]
bad = []
n = 0
for h in H:
    for _ in range(60):
        frm = rnd.choice(cand) if rnd.random() < .85 else None
        to = rnd.choice(cand) if rnd.random() < .85 else None
        if frm and to and to < frm:
            frm, to = to, frm
        kw = {}
        if frm:
            kw["from"] = iso(frm)
        if to:
            kw["to"] = iso(to)
        r = stmt(t[h], limit=200, **kw)
        n += 1
        e = cmp(h, r, frm, to, "win")
        if e:
            bad.append((h, kw, e))
ok("J11/J14 %d random windows (incl. from-only/to-only/empty/inverted pairs excluded, exact instants +-1us): opening/closing/entries/balance_after equal oracle" % n, not bad, bad[:2])
# inverted window from > to: spec silent -> must not 5xx, entries empty or 422
x = instants[len(instants) // 2]
r = stmt(t["ada"], **{"from": iso(x + dt.timedelta(seconds=1)), "to": iso(x)})
ok("J11 inverted window (from > to): no 5xx (spec silent)", r.s < 500, r)
# half-open: from exact is included, to exact is excluded
mv = o.moves(UID["ada"], None)
eff, pid, d, s = mv[len(mv) // 2]
r = stmt(t["ada"], limit=200, **{"from": iso(eff)})
ok("J11 payment effective exactly at `from` is INCLUDED", r.s == 200 and r.j["entries"] and r.j["entries"][0]["effective_at"] and P(r.j["entries"][0]["effective_at"]) == eff, r.j["entries"][:1])
r = stmt(t["ada"], limit=200, to=iso(eff))
ok("J11 payment effective exactly at `to` is EXCLUDED (window half-open)", r.s == 200 and all(P(e["effective_at"]) < eff for e in r.j["entries"]) and r.j["closing_balance"] == o.window(UID["ada"], None, eff)[2], r.j["closing_balance"])
r = stmt(t["ada"], limit=200, **{"from": iso(eff), "to": iso(eff)})
ok("J11 from == to is an empty window; opening == closing", r.s == 200 and r.j["entries"] == [] and r.j["opening_balance"] == r.j["closing_balance"], r)

# ---- J16 pagination never changes balance_after/open/close
full = stmt(t["ada"], limit=200).j
FE = full["entries"]
chain = []
bad = []
for limit in (1, 2, 3, 7, 50, 200):
    got, off, more = [], 0, True
    while more:
        r = stmt(t["ada"], limit=limit, offset=off)
        if r.s != 200 or r.j["opening_balance"] != full["opening_balance"] or r.j["closing_balance"] != full["closing_balance"]:
            bad.append((limit, off, r.s, r.j.get("opening_balance"), r.j.get("closing_balance")))
            break
        got += r.j["entries"]
        more = r.j["has_more"]
        if more and len(r.j["entries"]) != limit:
            bad.append(("short page with has_more", limit, off))
        off += limit
        if off > 1000:
            break
    if [(e["payment"]["payment_id"], e["balance_after"], e["delta"]) for e in got] != [(e["payment"]["payment_id"], e["balance_after"], e["delta"]) for e in FE]:
        bad.append(("concat", limit))
ok("J16 pages of every size concatenate to the full result with identical balance_after/opening/closing; has_more only when more exists", not bad, bad[:3])
n = len(FE)
for off, lim, exp_more, exp_len in [(0, n, False, n), (0, n - 1, True, n - 1), (n - 1, 1, False, 1), (n, 5, False, 0), (n + 50, 5, False, 0), (n - 2, 5, False, 2), (n - 2, 2, False, 2), (n - 3, 2, True, 2)]:
    r = stmt(t["ada"], limit=lim, offset=off)
    ok("J16 offset=%d limit=%d of %d: has_more=%s, %d entries, balances unchanged" % (off, lim, n, exp_more, exp_len),
       r.s == 200 and r.j["has_more"] == exp_more and len(r.j["entries"]) == exp_len and r.j["opening_balance"] == full["opening_balance"] and r.j["closing_balance"] == full["closing_balance"], (r.s, r.j.get("has_more"), len(r.j.get("entries", []))))
r = stmt(t["ada"])
ok("J10 default limit is 50 (entries <= 50, has_more consistent with %d total)" % n, r.s == 200 and len(r.j["entries"]) == min(50, n) and r.j["has_more"] == (n > 50), (len(r.j["entries"]), r.j["has_more"]))

# ---- J10 limit/offset validation (plain digits, ranges)
for q_, bad_ in [("limit=0", 1), ("limit=201", 1), ("limit=-1", 1), ("limit=abc", 1), ("limit=1e1", 1), ("limit=%2B4", 1), ("limit=4.0", 1), ("limit=", 1), ("offset=-1", 1), ("offset=1.5", 1), ("offset=x", 1), ("offset=1e0", 1)]:
    r = call("GET", "/statement?" + q_, token=t["ada"])
    ok("J10 %s -> 422 validation_failed" % q_, r.s == 422 and r.code == "validation_failed", r)
for q_ in ["limit=1", "limit=200", "offset=0", "limit=50&offset=3"]:
    ok("J10 %s accepted" % q_, call("GET", "/statement?" + q_, token=t["ada"]).s == 200)
ok("J10 unknown parameters ignored", call("GET", "/statement?zzz=1&limit=3", token=t["ada"]).s == 200)
for q_ in ["from=", "from=garbage", "to=2026-01-01", "from=2026-01-01T00:00:00", "to=", "known_at=", "known_at=x"]:
    r = call("GET", "/statement?" + q_, token=t["ada"])
    ok("J10 %s -> 422 validation_failed" % q_, r.s == 422 and r.code == "validation_failed", r)
ok("J10 statement requires auth (401)", call("GET", "/statement").s == 401)

# ---- J17 visibility rules do not apply: third parties' public payments absent, own private present
for h in H:
    ents = stmt(t[h], limit=200).j["entries"]
    ok("J17 %s statement contains only payments sent/received by %s (public of others excluded), incl. private ones" % (h, h),
       all(UID[h] in (e["payment"]["from_user_id"], e["payment"]["to_user_id"]) for e in ents)
       and len(ents) == len([p for p in pays if UID[h] in (p["from_user_id"], p["to_user_id"])])
       and any(e["payment"]["visibility"] == "private" for e in ents))

# ---- J13 explicit tie: three payments corrected to one effective instant -> id order
tie_ids = sorted(p["payment_id"] for p in pays[:0])  # placeholder (ties already exercised by tie_at corrections)
ties = {}
for p in pays:
    s_ = o.selected(p["payment_id"], None)
    ties.setdefault((s_["eff"], p["from_user_id"]), []).append(p["payment_id"])
multi = [(k_, v) for k_, v in ties.items() if len(v) > 1]
print("INFO tie groups (same effective instant, same payer):", len(multi))
ok("J13 at least one effective-time tie exercised", len(multi) >= 1)
done("t3_statement")
