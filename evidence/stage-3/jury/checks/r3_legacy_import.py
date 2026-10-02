"""R3-N1 REAL export of the rejected 3c7c411 build (whole-second created_at + created_exact) imported into the commit under test.
PF1 = legacy 3c7c411 image (git archive 3c7c411 stage-3, built by the jury), PF2 = 5e6f83f image.
Spec: stage-3 'accept exports produced by the same team's stage-1 or stage-2 service' (a 3c7c411 export is the nearest thing a user can hold);
stage-2 'available is total - held, never negative' at every read; invariant: closed_at/expires_at/payment_ids/status unchanged by import,
imported values never move the clock, money history identical."""
import os, random, sys, time
from lib3 import *
import clk

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 5
rnd = random.Random(SEED)


def hp(n):
    h, p = os.environ[n].rsplit(":", 1); return (h, int(p))


L, N = hp("PF1"), hp("PF2")
now = lambda: dt.datetime.now(UTC)
SL = dt.timedelta(milliseconds=30)
USERS = ["ada", "bob", "cy", "dee"]
OPEN = {"ada": 10000, "bob": 0, "cy": 0, "dee": 3000}
TOTAL0 = sum(OPEN.values())


def C(base):
    return lambda m, p, b=None, tok=None, key=None: call(m, p, b, token=tok, key=key, base=base)


cl, cn = C(L), C(N)
f = fx([user(h, OPEN[h]) for h in USERS]); f["authorization_ttl_seconds"] = 3
assert cl("POST", "/_test/reset", f).s == 204
tl = {h: cl("POST", "/auth/login", {"email": h + "@example.com", "password": "correct horse"}).j["token"] for h in USERS}

# ---------------- build a legacy history: back-to-back fund+authorize, captures, voids, expiry, a correction
pays, auths = [], []
for i in range(30):
    a, b = rnd.sample(USERS, 2)
    amt = rnd.choice([300, 700, 1200])
    r = cl("POST", "/payments", {"to_handle": b, "amount": amt}, tl[a], k())
    if r.s != 201:
        continue
    pays.append((r.j["payment_id"], a, b))
    to = rnd.choice([u for u in USERS if u != b])
    r2 = cl("POST", "/authorizations", {"to_handle": to, "amount": amt}, tl[b], k())   # immediately after the funding payment
    if r2.s == 201:
        auths.append((r2.j["authorization_id"], b, to, amt))
    if rnd.random() < .5 and auths:
        aid, snd, rcv, am = rnd.choice(auths)
        op = rnd.choice(["partial", "final", "void"])
        if op == "partial": cl("POST", "/authorizations/%s/capture" % aid, {"amount": max(1, am // 3), "final": False}, tl[rcv], k())
        elif op == "final": cl("POST", "/authorizations/%s/capture" % aid, {}, tl[rcv], k())
        else: cl("POST", "/authorizations/%s/void" % aid, {}, tl[snd])
    if rnd.random() < .25: time.sleep(rnd.choice([0.02, 0.1, 0.4]))
# a correction on a plain payment (increase by the same sender; ada pays bob first)
pc = cl("POST", "/payments", {"to_handle": "dee", "amount": 100}, tl["ada"], k()).j
cr = cl("POST", "/payments/%s/corrections" % pc["payment_id"], {"expected_revision": 1, "amount": 160, "effective_at": pc["created_at"], "reason": "legacy fix"}, tl["ada"], k())
ok("legacy history built: correction accepted on the legacy server", cr.s == 201, cr)
pays.append((pc["payment_id"], "ada", "dee"))
time.sleep(3.6)   # let the leftover holds pass their 3 s deadline
ok("legacy history has >= 8 authorizations", len(auths) >= 8, len(auths))

# ---------------- legacy public data (control: the defect is really in this export)
def listing(c, tok):
    return c("GET", "/authorizations?limit=200", None, tok).j["authorizations"]


def pub_auths(c, toks):
    d = {}
    for h in USERS:
        for a in listing(c, toks[h]): d[a["authorization_id"]] = a
    return d


def pub_pays(c, toks):
    d = {}
    for h in USERS:
        first = c("GET", "/statement?limit=200", None, toks[h]).j
        for e in first["entries"]: d[e["payment"]["payment_id"]] = e["payment"]
    return d


la, lp = pub_auths(cl, tl), pub_pays(cl, tl)
neg = 0
for aid, a in la.items():
    snd = next(s for (i, s, _, _) in auths if i == aid)
    r = cl("GET", "/me?as_of=" + q(a["created_at"]), None, tl[snd]).j
    if r["available"] < 0: neg += 1
print("INFO control: legacy views at authorization.created_at with available<0: %d of %d" % (neg, len(la)))
ok("control: the legacy export really carries the F2 defect (>=1 legacy view with available<0 at authorization.created_at)", neg >= 1, neg)
legacy_me = {h: cl("GET", "/me", None, tl[h]).j for h in USERS}
legacy_revs = {pid: cl("GET", "/payments/%s/revisions" % pid, None, tl[a]).j for (pid, a, b) in pays}
exp = cl("GET", "/_test/export")
ok("legacy export -> 200 and carries created_exact on authorizations", exp.s == 200 and all("created_exact" in a for a in exp.j["state"]["authorizations"]) and len(exp.j["state"]["authorizations"]) == len(la), exp.s)
exact = {a["authorization_id"]: a["created_exact"] for a in exp.j["state"]["authorizations"]}

# ---------------- import into the commit under test, twice
for rep in (1, 2):
    t_imp0 = now()
    im = cn("POST", "/_test/import", exp.j)
    t_imp1 = now()
    ok("import #%d of the legacy export -> 204" % rep, im.s == 204, im)
    tn = {h: cn("POST", "/auth/login", {"email": h + "@example.com", "password": "correct horse"}).j["token"] for h in USERS}
    na, npay = pub_auths(cn, tn), pub_pays(cn, tn)
    ok("#%d same authorizations and payments after import" % rep, set(na) == set(la) and set(npay) == set(lp), (len(na), len(la), len(npay), len(lp)))
    keep = ("authorization_id", "from_user_id", "to_user_id", "amount", "captured_amount", "remaining_amount", "note", "visibility", "status", "expires_at", "payment_ids", "closed_at")
    diff = [(aid, k_, la[aid].get(k_), na[aid].get(k_)) for aid in la for k_ in keep if la[aid].get(k_) != na[aid].get(k_)]
    ok("#%d closed_at / expires_at / payment_ids / status / amounts unchanged by import (%d diffs)" % (rep, len(diff)), not diff, diff[:3])
    cdiff = [(aid, la[aid]["created_at"], na[aid]["created_at"], exact[aid]) for aid in la if P(na[aid]["created_at"]) != P(exact[aid]) or P(la[aid]["created_at"]).replace(microsecond=0) != P(na[aid]["created_at"]).replace(microsecond=0)]
    ok("#%d imported created_at == legacy created_exact (microsecond), same second as the legacy created_at (%d diffs)" % (rep, len(cdiff)), not cdiff, cdiff[:2])
    pdiff = [pid for pid in lp if lp[pid] != npay[pid]]
    ok("#%d payments (ids, created_at, amounts, links) identical" % rep, not pdiff, pdiff[:2])
    ok("#%d current /me identical for every user" % rep, all({k_: cn("GET", "/me", None, tn[h]).j[k_] for k_ in ("balance", "total", "held", "available")} == {k_: legacy_me[h][k_] for k_ in ("balance", "total", "held", "available")} for h in USERS))
    rdiff = [pid for pid in legacy_revs if cn("GET", "/payments/%s/revisions" % pid, None, tn[next(a for (p_, a, b) in pays if p_ == pid)]).j != legacy_revs[pid]]
    ok("#%d revision history identical (%d payments compared, incl. the corrected one)" % (rep, len(legacy_revs)), not rdiff, rdiff[:2])
    # views: every public instant +-1us, legacy whole-second and imported microsecond created_at included
    inst = {EPOCH, now(), dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)}
    for p in npay.values(): inst.add(P(p["created_at"]))
    for aid, a in na.items():
        inst.update([P(a["created_at"]), P(la[aid]["created_at"]), P(a["expires_at"])])
        if a["closed_at"]: inst.add(P(a["closed_at"]))
    for pid, rv in legacy_revs.items():
        for r_ in rv["revisions"]: inst.update([P(r_["effective_at"]), P(r_["recorded_at"])])
    probe = sorted({y for x in inst for y in (x - US, x, x + US)})
    bad = []; negs = 0
    sender = {aid: a["from_user_id"] for aid, a in na.items()}
    capamt = {}
    for p in npay.values():
        if p.get("authorization_id"): capamt.setdefault(p["authorization_id"], []).append((P(p["created_at"]), p["amount"]))
    uid2h = {"u_" + h: h for h in USERS}

    def held_or(h, T):
        s = 0
        for aid, a in na.items():
            if uid2h[a["from_user_id"]] != h or T < P(a["created_at"]): continue
            if a["closed_at"] and T >= P(a["closed_at"]): continue
            if T >= P(a["expires_at"]): continue
            s += a["amount"] - sum(x for (c, x) in capamt.get(aid, []) if c <= T)
        return s
    for T in probe:
        tot = 0
        for h in USERS:
            m = cn("GET", "/me?as_of=" + q(iso(T)), None, tn[h]).j
            tot += m["total"]
            if not inv(m): bad.append(("invariant", h, iso(T), m["total"], m["held"], m["available"]))
            if m["available"] < 0: negs += 1
            if m["held"] != held_or(h, T): bad.append(("held-oracle", h, iso(T), m["held"], held_or(h, T)))
            lt = cl("GET", "/me?as_of=" + q(iso(T)), None, tl[h]).j["total"]
            if m["total"] != lt: bad.append(("total-vs-legacy", h, iso(T), m["total"], lt))
        # the extra payment made after import (new, not in legacy) changes totals only after its created_at; sum stays conserved
        if tot != TOTAL0: bad.append(("sum", iso(T), tot))
    ok("#%d %d instants x 4 users: invariant, available>=0 (%d negative), held == public-field oracle, total == legacy total, conserved; first bad: %s" % (rep, len(probe), negs, bad[:2]), not bad and negs == 0, bad[:4])
    for h in USERS:
        st = cn("GET", "/statement?limit=200", None, tn[h]).j
        ok("#%d %s statement: opening + deltas == closing == /me.total" % (rep, h), st["opening_balance"] + sum(e["delta"] for e in st["entries"]) == st["closing_balance"] == cn("GET", "/me", None, tn[h]).j["total"], st["closing_balance"])
    # clock
    t0 = now(); np_ = cn("POST", "/payments", {"to_handle": "cy", "amount": 1}, tn["dee"], k()); t1 = now()
    mx = max(P(p["created_at"]) for p in lp.values())
    ok("#%d next payment stamped at its own request time (+-30 ms) and after every imported payment" % rep, np_.s == 201 and clk.inwin(P(np_.j["created_at"]), t0, t1) and P(np_.j["created_at"]) > mx, (np_, iso(t0), iso(t1), iso(mx)))
    t0 = now(); na_ = cn("POST", "/authorizations", {"to_handle": "cy", "amount": 1}, tn["bob"], k()); t1 = now()
    ok("#%d next authorization created_at within its request window" % rep, na_.s in (201, 409) and (na_.s == 409 or clk.inwin(P(na_.j["created_at"]), t0, t1)), na_)
    # correction on imported history works (historical overdraft logic uses imported holds)
    if rep == 2:
        pid = next(iter(legacy_revs))
        owner = next(a for (p_, a, b) in pays if p_ == pid)
        rv = legacy_revs[pid]["revisions"][-1]
        r = cn("POST", "/payments/%s/corrections" % pid, {"expected_revision": rv["revision"], "amount": rv["amount"], "effective_at": rv["effective_at"], "reason": "noop after import"}, tn[owner], k())
        ok("correction of an imported payment accepted or refused with a documented code (never 5xx), recorded strictly after the imported revision", r.s in (201, 409, 422) and (r.s != 201 or P(r.j["recorded_at"]) > P(rv["recorded_at"])), r)
print("INFO", clk.report())
done("r3_legacy_import seed %d (%d legacy authorizations, %d payments)" % (SEED, len(la), len(lp)))
