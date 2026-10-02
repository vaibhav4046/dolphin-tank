"""J32 J33: known_at x as_of grid on /me and statement vs independent oracle, recorded-time boundaries, future instants, echo."""
import random, sys, time
from lib3 import *

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 11
rnd = random.Random(SEED)
print("seed", SEED)
H = ["ada", "bob", "cy"]
OPENB = {"ada": 1000000, "bob": 1000000, "cy": 1000000}
f = fx([user(h, OPENB[h]) for h in H])
t = setup(f)
UID = {h: "u_" + h for h in H}
o = Oracle({UID[h]: OPENB[h] for h in H})
TOTAL = sum(OPENB.values())
tok_of = {UID[h]: t[h] for h in H}

pays = []
log = []
for i in range(14):
    a, b = rnd.sample(H, 2)
    r = pay(t[a], b, rnd.randint(10, 900))
    assert r.s == 201, r
    pays.append(r.j)
    time.sleep(0.004)
    if i % 2 == 1:
        for _ in range(rnd.randint(1, 3)):
            p = rnd.choice(pays)
            tk = tok_of[p["from_user_id"]]
            cur = revs(tk, p["payment_id"])[-1]
            eff = iso(P(pays[rnd.randrange(len(pays))]["created_at"]) + dt.timedelta(microseconds=rnd.choice([0, 0, 1, 3000])))
            if P(eff) > dt.datetime.now(UTC):
                eff = p["created_at"]
            rr = correct(tk, p["payment_id"], cur["revision"], rnd.choice([0, rnd.randint(1, 900), cur["amount"] + 5]), eff, "k")
            assert rr.s == 201, (rr, eff)
            time.sleep(0.003)
for p in pays:
    o.add(p["payment_id"], p["from_user_id"], p["to_user_id"], revs(tok_of[p["from_user_id"]], p["payment_id"]))
nrev = sum(len(v) for v in o.revs.values())
print("payments", len(pays), "revisions", nrev)
recs = sorted({r["rec"] for v in o.revs.values() for r in v})
effs = sorted({r["eff"] for v in o.revs.values() for r in v})
Ks = [None]
for x in recs[::2]:
    Ks += [x - US, x, x + US]
Ks += [P("1970-01-01T00:00:00Z"), recs[0] - dt.timedelta(seconds=5), recs[-1] + dt.timedelta(seconds=5), P("9999-12-31T23:59:59Z")]
As = [None]
for x in effs[::2]:
    As += [x - US, x, x + US]
As += [P("1970-01-01T00:00:00Z"), P("9999-12-31T23:59:59Z")]

bad, n, badstmt, ns = [], 0, [], 0
for h in H:
    for _ in range(220):
        A_, K_ = rnd.choice(As), rnd.choice(Ks)
        sa = iso(A_) if A_ else None
        sk = iso(K_) if K_ else None
        r = me_at(t[h], sa, sk)
        n += 1
        exp = o.total(UID[h], A_, K_)
        if r.s != 200 or r.j["balance"] != exp or r.j["total"] != exp or r.j["available"] != exp or r.j["held"] != 0 or r.j.get("as_of") != sa or r.j.get("known_at") != sk:
            bad.append((h, sa, sk, exp, r.j if r.s == 200 else r.s))
ok("J32 %d random (as_of, known_at) /me views (incl. recorded_at -1us/exact/+1us, before first record, future): total == oracle, echoes exact, balance=total=available, held 0" % n, not bad, bad[:2])
tots = []
for _ in range(60):
    A_, K_ = rnd.choice(As), rnd.choice(Ks)
    s_ = sum(me_at(t[h], iso(A_) if A_ else None, iso(K_) if K_ else None).j["balance"] for h in H)
    tots.append(s_)
ok("J29 sum of balances == seeded total in every sampled (as_of, known_at) view", all(x == TOTAL for x in tots), [x for x in tots if x != TOTAL][:3])

# statements with known_at (+ optional window)
for h in H:
    for _ in range(40):
        K_ = rnd.choice(Ks)
        frm = rnd.choice(As) if rnd.random() < .5 else None
        to = rnd.choice(As) if rnd.random() < .5 else None
        if frm and to and to < frm:
            frm, to = to, frm
        kw = {}
        if K_: kw["known_at"] = iso(K_)
        if frm: kw["from"] = iso(frm)
        if to: kw["to"] = iso(to)
        r = stmt(t[h], limit=200, **kw)
        ns += 1
        eo, ee, ec = o.window(UID[h], frm, to, K_)
        if r.s != 200:
            badstmt.append((h, kw, r.s)); continue
        got = [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"], e["payment"]["amount"], P(e["effective_at"])) for e in r.j["entries"]]
        recok = all(P(e["recorded_at"]) <= (K_ if K_ else dt.datetime.now(UTC)) for e in r.j["entries"])
        if r.j["opening_balance"] != eo or r.j["closing_balance"] != ec or got != ee or not recok:
            badstmt.append((h, kw, r.j["opening_balance"], eo, r.j["closing_balance"], ec, len(got), len(ee), recok))
        if "known_at" in kw and ns % 25 == 0:
            print("INFO statement echoes known_at:", r.j.get("known_at") == kw["known_at"])
ok("J32/J33 %d statements with known_at (+ windows): selected revisions (latest recorded <= known_at), payments not yet recorded absent, ordering by selected effective_at, amount/delta/balance_after/opening/closing == oracle, entry.recorded_at <= known_at" % ns, not badstmt, badstmt[:2])

# none recorded yet contributes nothing: known_at just before the first payment's rev1
p0 = min(pays, key=lambda p: P(p["created_at"]))
Kb = iso(P(revs(tok_of[p0["from_user_id"]], p0["payment_id"])[0]["recorded_at"]) - US)
for h in H:
    r = stmt(t[h], limit=200, known_at=Kb)
    ok("J32 known_at before any record: %s statement empty, opening == closing == opening balance" % h, r.s == 200 and r.j["entries"] == [] and r.j["opening_balance"] == r.j["closing_balance"] == OPENB[h], r)
    ok("J32 known_at before any record: /me total == opening for %s" % h, me_at(t[h], None, Kb).j["balance"] == OPENB[h])
r = stmt(t["ada"], limit=200, known_at="9999-01-01T00:00:00Z")
cur = stmt(t["ada"], limit=200)
ok("J32 known_at far future == omitted known_at", r.j["entries"] == cur.j["entries"] and r.j["closing_balance"] == cur.j["closing_balance"])
# a payment never counted alongside the revision that replaced it
for p in pays:
    fr = [h for h in H if UID[h] == p["from_user_id"]][0]
    ents = [e for e in stmt(t[fr], limit=200).j["entries"] if e["payment"]["payment_id"] == p["payment_id"]]
    if len(ents) != 1:
        ok("J33 exactly one entry per payment (no correction counted with the revision it replaces) %s" % p["payment_id"], False, ents)
        break
else:
    ok("J33 every payment appears exactly once in its sender's current statement", True)
# invalid known_at and snapshot combos handled elsewhere (t3_snap)
ok("J32 known_at far-future for /me allowed", me_at(t["ada"], None, "9999-12-31T23:59:59Z").s == 200)
ok("J32 known_at empty / naive -> 422 on statement and me", all(call("GET", "/statement?known_at=" + v, token=t["ada"]).s == 422 and call("GET", "/me?known_at=" + v, token=t["ada"]).s == 422 for v in ("", "2026-01-01T00:00:00", "2026-01-01")))
done("t3_known")
