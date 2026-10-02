"""trace: focused attack on forge's R-L1 fix (5e6f83f placeAtCreatedExact). stdlib only, persistent connections, servers started/killed by PID.
env F2BIN = dir with s3-5e6f83f.exe (HEAD under attack), s3-ac96360.exe (previous HEAD, comparison only), s3-legacy-3c7c411.exe, s2.exe; F2S3 = HEAD exe name.
usage: python rl1_attack.py <case> [...]   cases: edges mix ttl1 offsets subus bad dup nullabs allafter stage2 ahead corr rand"""
import copy, json, os, random, re, sys, time
import datetime as dt
import f2_attack as F
from f2_attack import (Srv, alist, authorize, capture, compare_views, inv_ok, iso, k, login, mkusers, now_us, ok, pay, setup, us, view, void, wait_until, Oracle, MICRO, EPOCH)

NAMES = ["ada", "bob", "cy", "dee"]
PORT = 18240
SHAPE = re.compile(r"^(\d{4}-\d\d-\d\d)[Tt ](\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|z|[+-]\d\d:\d\d)$")


def ns(s):
    """RFC 3339 string -> integer nanoseconds since the epoch (any number of fraction digits)"""
    m = SHAPE.match(s)
    assert m, s
    zone = m.group(4)
    d = dt.datetime.fromisoformat(m.group(1) + "T" + m.group(2) + ("+00:00" if zone in "Zz" else zone))
    sec = (d - EPOCH) // dt.timedelta(seconds=1)
    return sec * 1_000_000_000 + int((m.group(3) or "").ljust(9, "0")[:9])


def fmt_tz(u, offmin=0, digits=0, extra=""):
    d = (EPOCH + dt.timedelta(microseconds=u)).astimezone(dt.timezone(dt.timedelta(minutes=offmin)))
    s = d.isoformat(timespec="seconds" if digits == 0 else "microseconds")
    return s[:26] + extra + s[26:] if extra else s


def whole(u, offmin=0):
    return fmt_tz(u // 1_000_000 * 1_000_000, offmin, 0)


def base_second(back=6):
    return (now_us() // 1_000_000 - back) * 1_000_000


# ----------------------------------------------------------------------------------------- payload builder
def skeleton(SL):
    setup(SL.c, {h: 0 for h in NAMES}, 600)
    return SL.c.req("GET", "/_test/export").j


def mk_auth(aid, frm, to, amt, status, created_at, exact, expires_at, closed_at=None, cap=0, pids=()):
    a = {"authorization_id": aid, "from_user_id": "u_" + frm, "to_user_id": "u_" + to, "amount": amt, "captured_amount": cap,
         "note": "", "visibility": "public", "status": status, "expires_at": expires_at, "payment_ids": list(pids),
         "created_at": created_at, "closed_at": closed_at}
    if exact is not None:
        a["created_exact"] = exact
    return a


def mk_pay(pid, frm, to, amt, at, aid=None):
    return dict(id=pid, frm=frm, to=to, amt=amt, at=at, aid=aid)


def payload(skel, opening, payments, auths, ttl=600):
    ex = copy.deepcopy(skel)
    st = ex["state"]
    st["authorization_ttl_seconds"] = ttl
    st["sys"]["idem"] = {}
    net = {h: 0 for h in NAMES}
    pl, revs = [], []
    for p in sorted(payments, key=lambda p: p["at"]):
        pl.append({"payment_id": p["id"], "from_user_id": "u_" + p["frm"], "from_handle": p["frm"], "to_user_id": "u_" + p["to"],
                   "to_handle": p["to"], "amount": p["amt"], "currency": "EUR", "note": "", "visibility": "public", "request_id": None,
                   "settlement_id": None, "authorization_id": p["aid"], "created_at": iso(p["at"])})
        revs.append({"payment_id": p["id"], "revision": 1, "amount": p["amt"], "effective_at": iso(p["at"]), "recorded_at": iso(p["at"]), "reason": ""})
        net[p["frm"]] -= p["amt"]
        net[p["to"]] += p["amt"]
    for u in st["users"]:
        u["opening_balance"] = opening.get(u["handle"], 0)
        u["balance"] = u["opening_balance"] + net[u["handle"]]
    st["payments"], st["revisions"], st["authorizations"] = pl, revs, auths
    st["seq"] = {"a": len(auths) + 1, "p": len(pl) + 1}
    return ex


def oracle_state(ex):
    """spec-side expectation: a hold starts at its created_exact instant (microsecond) when one is given"""
    o = copy.deepcopy(ex)
    for a in o["state"]["authorizations"]:
        if a.get("created_exact"):
            a["created_at"] = iso(ns(a["created_exact"]) // 1000)
        else:
            a["created_at"] = iso(ns(a["created_at"]) // 1000)
        a["expires_at"] = iso(ns(a["expires_at"]) // 1000)
        if a.get("closed_at"):
            a["closed_at"] = iso(ns(a["closed_at"]) // 1000)
    return o


def expect_created(a0):
    """None = untouched; 'REJECT'; else the expected micro created_at"""
    ce = a0.get("created_exact")
    if ce is None:
        return None
    try:
        e, c = ns(ce), ns(a0["created_at"])
    except AssertionError:
        return "REJECT"
    if e // 1_000_000_000 != c // 1_000_000_000:
        return "REJECT"
    return None if e == c else iso(e // 1000)


# ----------------------------------------------------------------------------------------- case runner
def exp_json(c):
    return json.dumps(c.req("GET", "/_test/export").j, sort_keys=True)


def post_ops(c3, t, label, payer, payee, third, imported=None, ttl=600):
    """pay/authorize/capture/void on the imported state; `imported` = (aid, payer, payee) of an imported OPEN hold to capture then void"""
    a = authorize(c3, t[payer], payee, 700)
    ok(label + ": authorize after import 201", a.s == 201, (a.s, a.b))
    if a.s != 201:
        return
    a = a.j
    C = us(a["created_at"])
    ok(label + ": new hold tracks the real clock and carries the exact ttl", abs(C - now_us()) < 3_000_000 and us(a["expires_at"]) - C == ttl * 1_000_000 and bool(MICRO.match(a["created_at"])), a)
    cp = capture(c3, t[payee], a["authorization_id"], 200, False)
    fc = capture(c3, t[payee], a["authorization_id"], None, True)
    ok(label + ": nonfinal + final capture 201, each later than its hold", cp.s == 201 and fc.s == 201 and C < us(cp.j["created_at"]) < us(fc.j["created_at"]), (cp.s, cp.b, fc.s, fc.b))
    b = authorize(c3, t[payer], third, 300).j
    vv = void(c3, t[payer], b["authorization_id"])
    pp = pay(c3, t[payer], payee, 11)
    ok(label + ": void 200 and pay 201 after import", vv.s == 200 and pp.s == 201, (vv.s, vv.b, pp.s, pp.b))
    inst = {C, us(cp.j["created_at"]), us(fc.j["created_at"]), us(b["created_at"]), us(vv.j["closed_at"]), us(pp.j["created_at"])}
    if imported:
        aid, ip, ie = imported
        h0 = us(alist(c3, t[ip])[aid]["created_at"]) if aid in alist(c3, t[ip]) else None
        c2 = capture(c3, t[ie], aid, 1, False)
        ok(label + ": capture of the imported open hold 201, recorded after the hold's created_at", c2.s == 201 and (h0 is None or us(c2.j["created_at"]) > h0), (c2.s, c2.b, h0))
        v2 = void(c3, t[ip], aid)
        ok(label + ": void of the imported open hold 200", v2.s == 200, (v2.s, v2.b))
        if c2.s == 201 and v2.s == 200:
            inst |= {us(c2.j["created_at"]), us(v2.j["closed_at"])}
    ex = c3.req("GET", "/_test/export").j
    n, bad = compare_views(c3, t, NAMES, Oracle(ex), label, instants=inst)
    ok(label + ": views around every new event (%d) satisfy the invariants and equal the spec rules computed from the export" % n, not bad, bad[:3])


def run_case(S3, skel, name, opening, payments, auths, ttl=600, expect=204, act=None, extra_instants=None, quiet=False):
    c3 = S3.c
    pre = exp_json(c3)
    ex0 = payload(skel, opening, payments, auths, ttl)
    r = c3.req("POST", "/_test/import", raw=json.dumps(ex0).encode())
    if expect != 204:
        ok("%s: import refused with %d" % (name, expect), r.s == expect, (r.s, r.b[:200]))
        ok("%s: refused import left the previous state byte-identical" % name, exp_json(c3) == pre)
        return None
    ok("%s: import 204" % name, r.s == 204, (r.s, r.b[:300]))
    if r.s != 204:
        return None
    t = {h: login(c3, h) for h in NAMES}
    ex1 = c3.req("GET", "/_test/export").j
    got = {a["authorization_id"]: a for a in ex1["state"]["authorizations"]}
    bad = []
    for a0 in auths:
        a1 = got[a0["authorization_id"]]
        want = expect_created(a0)
        if want is None:
            if a1["created_at"] != a0["created_at"] or a1.get("created_exact") != a0.get("created_exact"):
                bad.append(("untouched", a0["authorization_id"], a0["created_at"], a0.get("created_exact"), a1["created_at"], a1.get("created_exact")))
        elif not (a1["created_at"] == want and a1.get("created_exact") == want):
            bad.append(("rewritten", a0["authorization_id"], want, a1["created_at"], a1.get("created_exact")))
        for f in ("expires_at", "payment_ids", "amount", "captured_amount", "from_user_id", "to_user_id"):
            if a1[f] != a0[f]:
                bad.append((f, a0["authorization_id"], a0[f], a1[f]))
        if a0["status"] == "open" and a1["status"] == "expired":
            if a1["closed_at"] != a0["expires_at"]:
                bad.append(("expired closed_at", a0["authorization_id"], a1["closed_at"]))
        elif a1["status"] != a0["status"] or a1["closed_at"] != a0["closed_at"]:
            bad.append(("status/closed_at", a0["authorization_id"], a0["status"], a0["closed_at"], a1["status"], a1["closed_at"]))
    ok("%s: created_at/created_exact rewritten exactly when they differ; expires_at, closed_at, payment_ids, status not rewritten (%d holds)" % (name, len(auths)), not bad, bad[:3])
    orc = Oracle(oracle_state(ex0))
    n, bad = compare_views(c3, t, NAMES, orc, name, instants=set(orc.instants) | set(extra_instants or ()))
    ok("%s: %d views (every instant -1us/0/+1us x 4 users): balance == total, available == total - held >= 0, equal the spec rules" % (name, n), not bad, bad[:4])
    ok("%s: Σ balances preserved by import" % name, sum(u["balance"] for u in ex1["state"]["users"]) == sum(u["balance"] for u in ex0["state"]["users"]))
    r = c3.req("POST", "/_test/import", raw=json.dumps(ex1).encode())
    ex2 = exp_json(c3)
    ok("%s: export -> import -> export byte-identical" % name, r.s == 204 and json.dumps(ex1, sort_keys=True) == ex2, (r.s, len(ex2)))
    if act:
        t = {h: login(c3, h) for h in NAMES}
        act(c3, t, name)
    return t


def act_dee(imported=None, ttl=600):
    return lambda c3, t, name: post_ops(c3, t, name + " post-import", "dee", "bob", "cy", imported, ttl)


# ----------------------------------------------------------------------------------------- the cases
def case_edges(S3, skel):
    B = base_second()
    for label, ex_off, ttl_s in (("exact == created_at (:00.000000, equal -> untouched)", 0, 600), ("created_exact :00.000001", 1, 600), ("created_exact :59.999999", 999_999, 600),
                                 ("created_exact :59.999999, ttl 1 s (hold lives 1 us)", 999_999, 1), ("created_exact :00.000000, ttl 1 s", 0, 1)):
        ca = whole(B)
        pays = [mk_pay("p_1", "bob", "ada", 2000, B + max(ex_off - 1, 0) if ex_off else B)]
        exp = fmt_tz(B + ex_off, 0, 6)
        auths = [mk_auth("a_1", "ada", "cy", 7000, "open" if ttl_s == 600 else "expired", ca, exp, whole(B + ttl_s * 1_000_000),
                         None if ttl_s == 600 else whole(B + ttl_s * 1_000_000))]
        if ex_off == 999_999:  # capture of the hold lands in the NEXT second, 1 us after the hold
            pays.append(mk_pay("p_2", "ada", "cy", 1500, B + 1_000_000, "a_1"))
            auths[0]["captured_amount"], auths[0]["payment_ids"] = 1500, ["p_2"]
        t = run_case(S3, skel, "EDGE[%s]" % label, {"ada": 6000, "bob": 3000, "dee": 50000}, pays, auths, ttl_s, act=act_dee(("a_1", "ada", "cy") if ttl_s == 600 else None, ttl_s),
                     extra_instants={B + ex_off - 1, B + ex_off, B + ex_off + 1})
        if t:
            exa = {x["authorization_id"]: x for x in alist(S3.c, t["ada"]).values()}
            a = alist(S3.c, t["ada"])["a_1"]
            ok("EDGE[%s]: GET /authorizations created_at is the microsecond instant" % label, bool(MICRO.match(a["created_at"])) and us(a["created_at"]) == B + ex_off or ex_off == 0, a)


def case_mix(S3, skel):
    B = base_second(3)
    ca = whole(B)
    exp_ahead = whole(B + 600_000_000)
    pays = [mk_pay("p_1", "bob", "ada", 5000, B + 100_000),
            mk_pay("p_2", "ada", "cy", 2000, B + 400_000, "a_1")]
    auths = [mk_auth("a_1", "ada", "cy", 7000, "open", ca, fmt_tz(B + 300_000, 0, 6), exp_ahead, None, 2000, ["p_2"]),            # partly captured, deadline ahead
             mk_auth("a_2", "ada", "cy", 1500, "voided", ca, fmt_tz(B + 500_000, 0, 6), exp_ahead, fmt_tz(B + 700_000, 0, 6)),   # voided
             mk_auth("a_3", "ada", "bob", 500, "expired", ca, fmt_tz(B + 600_000, 0, 6), whole(B + 1_000_000), whole(B + 1_000_000)),  # expired, closed_at == expires_at
             mk_auth("a_4", "ada", "bob", 1500, "open", ca, fmt_tz(B + 800_000, 0, 6), exp_ahead)]                                 # open, deadline ahead
    return run_case(S3, skel, "MIX[partly captured/voided/expired/open in one second]", {"ada": 4000, "bob": 6000, "dee": 50000}, pays, auths, 600,
                    act=act_dee(("a_1", "ada", "cy")))


def case_ttl1(S3, skel):
    B = base_second(4)
    for stored in ("open", "expired"):
        ca = whole(B)
        pays = [mk_pay("p_1", "bob", "ada", 3000, B + 850_000), mk_pay("p_2", "ada", "cy", 1000, B + 950_000, "a_1")]
        auths = [mk_auth("a_1", "ada", "cy", 4000, stored, ca, fmt_tz(B + 900_000, 0, 6), whole(B + 1_000_000), whole(B + 1_000_000) if stored == "expired" else None, 1000, ["p_2"])]
        t = run_case(S3, skel, "TTL1[exact .9 s, expires_at = whole+1 s is 100 ms away, stored %s]" % stored, {"ada": 2000, "bob": 3000, "dee": 50000}, pays, auths, 1)
        if t:
            ix = {d: view(S3.c, t["ada"], B + d)[1] for d in (899_999, 900_000, 999_999, 1_000_000)}
            if stored == "open":
                ok("TTL1[open]: held at .899999 / .9 / .999999 / whole+1 s == 0 / 4000 / 3000 (capture 1000 at .95) / 0", ix == {899_999: 0, 900_000: 4000, 999_999: 3000, 1_000_000: 0}, ix)
            else:
                print("   OBSERVATION O-1 TTL1[stored expired]: held at .899999 / .9 / .999999 / whole+1 s = %s (documented HeldAt rule: a stored-expired hold holds nothing)" % list(ix.values()), flush=True)
                ok("TTL1[expired]: stored-expired hold holds nothing at every instant (O-1, pre-existing HeldAt rule, not R-L1)", all(v == 0 for v in ix.values()), ix)
            a = alist(S3.c, t["ada"])["a_1"]
            ok("TTL1[%s]: GET /authorizations expires_at unchanged (whole+1 s), status expired, closed_at == expires_at" % stored,
               a["expires_at"] == whole(B + 1_000_000) and a["status"] == "expired" and a["closed_at"] == a["expires_at"], a)


def case_offsets(S3, skel):
    B = base_second(5)
    specs = [("+02:00 created_at / +00:00 exact", 120, 0, "", 123_456), ("+00:00 created_at / +05:30 exact", 0, 330, "", 234_567), ("-08:00 both", -480, -480, "", 345_678),
             ("Z exact", 0, None, "Z", 456_789), ("+02:00 created_at / Z-shifted exact 1us before whole second end", 120, 0, "", 999_999)]
    auths, pays = [], []
    for i, (lab, off_c, off_e, z, frac) in enumerate(specs, 1):
        ca = whole(B, off_c)
        ex = iso(B + frac).replace("+00:00", "Z") if off_e is None else fmt_tz(B + frac, off_e, 6)
        pays.append(mk_pay("p_%d" % i, "bob", "ada", 100 * i, B + frac - 1))
        auths.append(mk_auth("a_%d" % i, "ada", "cy", 90 * i, "open", ca, ex, whole(B + 600_000_000), None))
    run_case(S3, skel, "OFFSETS[5 holds: non-UTC created_at/created_exact, Z]", {"ada": 100, "bob": 5000, "dee": 50000}, pays, auths, 600, act=act_dee(("a_1", "ada", "cy")))


def case_subus(S3, skel):
    B = base_second(5)
    for lab, extra in (("7 digits .6096069", "9"), ("9 digits .609606999", "999"), ("sub-us only .000000400 (truncates to the whole second)", None)):
        if extra is None:
            ex = fmt_tz(B, 0, 6).replace(".000000", ".000000400")
        else:
            ex = fmt_tz(B + 609_606, 0, 6, extra)
        pays = [mk_pay("p_1", "bob", "ada", 2000, B + 609_605 if extra else B)]
        auths = [mk_auth("a_1", "ada", "cy", 2500, "open", whole(B), ex, whole(B + 600_000_000), None)]
        ex0 = payload(F.json and skeleton_cache[0], {"ada": 1000, "bob": 3000, "dee": 50000}, pays, auths, 600)
        pre = exp_json(S3.c)
        r = S3.c.req("POST", "/_test/import", raw=json.dumps(ex0).encode())
        if r.s == 422:
            ok("SUBUS[%s]: server refuses the extra digits with 422 (not a rewrite) and keeps the old state" % lab, exp_json(S3.c) == pre, r.b[:200])
        else:
            run_case(S3, skeleton_cache[0], "SUBUS[%s]" % lab, {"ada": 1000, "bob": 3000, "dee": 50000}, pays, auths, 600, act=act_dee(("a_1", "ada", "cy")))


def case_bad(S3, skel):
    B = base_second(5)
    ca = whole(B)
    for lab, ex in (("next second :00.000000", fmt_tz(B + 1_000_000, 0, 6)), ("1 us before the second", fmt_tz(B - 1, 0, 6)), ("garbage", "garbage"), ("empty string", ""),
                    ("no offset", "2026-10-02T18:16:13.5"), ("space separator inside second but other day", fmt_tz(B + 86_400_000_000, 0, 6))):
        a = mk_auth("a_1", "ada", "cy", 10, "open", ca, ex, whole(B + 600_000_000), None)
        run_case(S3, skel, "BAD[created_exact %s]" % lab, {"ada": 1000, "dee": 5000}, [], [a], 600, expect=422)


def case_dup(S3, skel):
    B = base_second(5)
    a1 = mk_auth("a_1", "ada", "cy", 10, "open", whole(B), fmt_tz(B + 100_000, 0, 6), whole(B + 600_000_000))
    a2 = mk_auth("a_1", "ada", "cy", 10, "open", whole(B), fmt_tz(B + 900_000, 0, 6), whole(B + 600_000_000))
    run_case(S3, skel, "DUP[same authorization id, different created_exact]", {"ada": 1000, "dee": 5000}, [], [a1, a2], 600, expect=422)
    b = mk_auth("a_2", "ada", "cy", 10, "open", whole(B), fmt_tz(B + 100_000, 0, 6), whole(B + 600_000_000))
    b["captured_amount"] = 11  # invalid field after the created_exact step: the whole import must still fail atomically
    run_case(S3, skel, "DUP[valid created_exact then captured_amount > amount: atomic refusal]", {"ada": 1000, "dee": 5000}, [], [b], 600, expect=422)


def case_nullabs(S3, skel):
    B = base_second(5)
    mk = lambda n, ex: mk_auth("a_%d" % n, "ada", "cy", 100, "open", whole(B), ex, whole(B + 600_000_000))
    a1 = mk(1, None)                              # absent
    a2 = mk(2, fmt_tz(B, 0, 6))                   # equal instant, micro spelling
    a3 = mk(3, whole(B))                          # equal, whole-second spelling
    a2["created_at"] = whole(B)
    a4 = mk(4, None); a4["created_at"] = fmt_tz(B + 500_000, 0, 6)   # micro created_at, absent exact
    a5 = mk(5, fmt_tz(B + 500_000, 0, 6)); a5["created_at"] = fmt_tz(B + 500_000, 0, 6)  # micro created_at, equal exact
    a6 = mk(6, fmt_tz(B + 900_000, 0, 6)); a6["created_at"] = fmt_tz(B + 100_000, 0, 6)  # micro created_at differs from exact in the same second
    a7 = mk(7, None); a7["created_exact"] = None  # explicit JSON null
    run_case(S3, skel, "NULLABS[absent / null / equal exact / micro created_at / differing micro]", {"ada": 100_000, "dee": 5000}, [], [a1, a2, a3, a4, a5, a6, a7], 600)


def case_allafter(S3, skel):
    B = base_second(5)
    pays = [mk_pay("p_1", "ada", "bob", 1000, B + 300_000), mk_pay("p_2", "bob", "ada", 200, B + 350_000), mk_pay("p_3", "ada", "bob", 700, B + 450_000)]
    auths = [mk_auth("a_1", "ada", "cy", 4000, "open", whole(B), fmt_tz(B + 100_000, 0, 6), whole(B + 600_000_000)),  # exact BEFORE every payment of the second
             mk_auth("a_2", "ada", "cy", 500, "open", whole(B), fmt_tz(B + 500_000, 0, 6), whole(B + 600_000_000))]   # exact AFTER every payment of the second
    run_case(S3, skel, "ALLAFTER[all payments later than created_at (floor); exact before and after them]", {"ada": 9000, "bob": 1000, "dee": 50000}, pays, auths, 600,
             act=act_dee(("a_1", "ada", "cy")))


def case_corr(S3, skel):
    t = case_mix(S3, skel)
    c = S3.c
    if not t:
        return
    eff = next(p["created_at"] for p in c.req("GET", "/_test/export").j["state"]["payments"] if p["payment_id"] == "p_1")
    rev = 1
    for label, amt, want in (("decrease 5000 -> 4499: ada's available would be -1 at the a_2 boundary (.5-.7 s) -> 409 historical_overdraft", 4499, (409, "historical_overdraft")),
                             ("decrease 5000 -> 4500: ada's available is exactly 0 at that boundary -> 201", 4500, (201, None)),
                             ("increase 4500 -> 5001: nothing negative at any boundary -> 201", 5001, (201, None))):
        before = exp_json(c)
        r = c.req("POST", "/payments/p_1/corrections", {"expected_revision": rev, "amount": amt, "effective_at": eff, "reason": "fix"}, t["bob"], key=k())
        ok("CORR[%s]: got %s" % (label, (r.s, r.code)), (r.s, r.code) == want, (r.s, r.b[:300]))
        if want[0] == 409:
            ok("CORR[%s]: refused correction changed nothing" % label, exp_json(c) == before)
        else:
            rev += 1
            ex = c.req("GET", "/_test/export").j
            amts = {}
            for rv in ex["state"]["revisions"]:
                if rv["payment_id"] not in amts or rv["revision"] > amts[rv["payment_id"]][0]:
                    amts[rv["payment_id"]] = (rv["revision"], rv["amount"])
            o = oracle_state(ex)
            for p in o["state"]["payments"]:
                p["amount"] = amts[p["payment_id"]][1]
            n, bad = compare_views(c, {h: login(c, h) for h in NAMES}, NAMES, Oracle(o), label, nthreads=2)
            ok("CORR[%s]: %d views after the correction satisfy the invariants and equal the spec rules (latest revision amounts)" % (label, n), not bad, bad[:3])


skeleton_cache = []


def case_stage2(S3, skel, S2):
    c2, c3 = S2.c, S3.c
    t = setup(c2, {"ada": 10000, "bob": 2500, "cy": 3000, "dee": 50000}, 600)
    ao = authorize(c2, t["ada"], "bob", 2500).j
    ac = authorize(c2, t["ada"], "cy", 800).j
    assert capture(c2, t["cy"], ac["authorization_id"], 300, False).s == 201
    af = authorize(c2, t["ada"], "cy", 600).j
    assert capture(c2, t["cy"], af["authorization_id"], None, True).s == 201
    av = authorize(c2, t["ada"], "bob", 400).j
    assert void(c2, t["ada"], av["authorization_id"]).s == 200
    assert pay(c2, t["bob"], "ada", 77).s == 201
    ex = c2.req("GET", "/_test/export").j
    auths = ex["state"]["authorizations"]
    for a in auths:  # inject created_exact into stage-2 holds: 400 ms into the creation second
        a["created_exact"] = fmt_tz(ns(a["created_at"]) // 1000 + 400_000, 0, 6)
    pre = exp_json(c3)
    r = c3.req("POST", "/_test/import", raw=json.dumps(ex).encode())
    ok("STAGE2+exact: real stage-2 export with created_exact injected imports: 204", r.s == 204, (r.s, r.b[:300]))
    if r.s != 204:
        return
    tk = {h: login(c3, h) for h in NAMES}
    got = {a["authorization_id"]: a for a in c3.req("GET", "/_test/export").j["state"]["authorizations"]}
    bad = [(aid, a["created_at"], a["created_exact"], got[aid]["created_at"], got[aid].get("created_exact")) for aid, a in ((x["authorization_id"], x) for x in auths)
           if got[aid]["created_at"] != iso(ns(a["created_exact"]) // 1000) or got[aid].get("created_exact") != got[aid]["created_at"]]
    ok("STAGE2+exact: every hold re-placed at its created_exact (microsecond), created_exact rewritten equal", not bad, bad[:2])
    e3 = c3.req("GET", "/_test/export").j["state"]
    opening = {u["id"]: u["opening_balance"] for u in e3["users"]}
    for u in ex["state"]["users"]:
        u.setdefault("opening_balance", opening[u["id"]])
    for a in ex["state"]["authorizations"]:  # stage-2 exports carry no closed_at: take the one import derived
        g = next(x for x in e3["authorizations"] if x["authorization_id"] == a["authorization_id"])
        a.setdefault("closed_at", g["closed_at"])
        if g["closed_at"] and us(g["closed_at"]) < us(g["created_at"]):
            print("   OBSERVATION O-2 STAGE2+exact: %s %s closed_at %s precedes created_at %s (injected created_exact moved created_at, closed_at kept)" % (a["authorization_id"], g["status"], g["closed_at"], g["created_at"]), flush=True)
    orc = Oracle(oracle_state(ex))
    n, bad = compare_views(c3, tk, NAMES, orc, "STAGE2+exact")
    ok("STAGE2+exact: %d views satisfy the invariants and equal the spec rules" % n, not bad, bad[:3])
    post_ops(c3, tk, "STAGE2+exact post-import", "dee", "bob", "cy", (ao["authorization_id"], "ada", "bob"))
    ex1 = json.dumps(c3.req("GET", "/_test/export").j, sort_keys=True)
    ok("STAGE2+exact: export -> import -> export byte-identical", c3.req("POST", "/_test/import", raw=ex1.encode()).s == 204 and exp_json(c3) == ex1)


def case_ahead(S3, skel, ahead_ms):
    label = "AHEAD[created_exact = now + %d ms, same second]" % ahead_ms
    while now_us() % 1_000_000 > 400_000:
        time.sleep(0.01)
    X = now_us() + ahead_ms * 1000
    B = X // 1_000_000 * 1_000_000
    auths = [mk_auth("a_1", "ada", "cy", 9000, "open", whole(B), fmt_tz(X, 0, 6), whole(B + 600_000_000))]
    ex0 = payload(skel, {"ada": 10000, "bob": 1000, "dee": 50000}, [], auths, 600)
    c = S3.c
    r = c.req("POST", "/_test/import", raw=json.dumps(ex0).encode())
    ok(label + ": import 204", r.s == 204, (r.s, r.b[:300]))
    t = {h: login(c, h) for h in NAMES}
    t_imp = now_us()
    cur = view(c, t["ada"])
    asof_now = view(c, t["ada"], now_us())
    print("   %s: X=%s import returned at +%d ms from X-%d ms; /me=%s  /me?as_of=now=%s" % (label, iso(X), (t_imp - X) // 1000, ahead_ms, cur, asof_now), flush=True)
    ok(label + ": /me never shows available < 0 and balance == total, available == total - held", inv_ok(cur), cur)
    ok(label + ": /me?as_of=now never shows available < 0", inv_ok(asof_now), asof_now)
    p = pay(c, t["ada"], "bob", 5000)  # would leave 5000 < 9000 held once the hold starts
    ok(label + ": a payment that would undercut the (future-placed) hold is refused 409", p.s == 409, (p.s, p.b[:200]))
    cp = capture(c, t["cy"], "a_1", 100, False)
    hold_c = us(alist(c, t["ada"])["a_1"]["created_at"])
    ok(label + ": capture 201", cp.s == 201, (cp.s, cp.b[:200]))
    if cp.s == 201:
        cap_c = us(cp.j["created_at"])
        print("   %s: capture recorded %+d us relative to the hold's created_at" % (label, cap_c - hold_c), flush=True)
        if ahead_ms <= 10:
            ok(label + ": (inside the 50 ms slack, the clock follows the hold) capture recorded after the imported hold", cap_c > hold_c, (iso(cap_c), iso(hold_c)))
        else:
            ok(label + ": OBSERVATION beyond the slack: capture recorded before the imported hold's created_at (clock rule: imported instants past now+50 ms are ignored)", cap_c < hold_c, (iso(cap_c), iso(hold_c)))
    ex = c.req("GET", "/_test/export").j
    wait_until(X + 60_000)
    orc = Oracle(oracle_state(ex))
    n, bad = compare_views(c, t, NAMES, orc, label, instants=set(orc.instants) | {X})
    ok("%s: %d views (incl. after the hold started) satisfy the invariants and equal the spec rules; current /me included" % (label, n), not bad, bad[:4])
    after = [view(c, t[h]) for h in NAMES]
    ok(label + ": current /me of every user after the hold started: no available < 0", all(inv_ok(v) for v in after), after)


def case_rand(S3, SL, bursts, seed):
    """real 3c7c411 server, bursts of random ops that share one wall-clock second -> export -> HEAD import; spec rules from the legacy export with created = created_exact"""
    rng = random.Random(seed)
    tot = {"holds": 0, "views": 0, "same_second_holds": 0, "rewritten": 0}
    for i in range(bursts):
        ttl = rng.choice([1, 2, 600])
        bal = {"ada": rng.randint(2000, 9000), "bob": rng.randint(1000, 6000), "cy": rng.randint(0, 3000), "dee": rng.randint(0, 3000)}
        t = setup(SL.c, bal, ttl)
        while not 20_000 < now_us() % 1_000_000 < 120_000:
            time.sleep(0.004)
        openh = []
        for _ in range(rng.randint(16, 26)):
            x = rng.random()
            a, b = rng.sample(NAMES, 2)
            if x < 0.30:
                pay(SL.c, t[a], b, rng.randint(1, 1500))
            elif x < 0.58 or not openh:
                r = authorize(SL.c, t[a], b, rng.randint(1, 2500))
                if r.s == 201:
                    openh.append((r.j["authorization_id"], a, b))
            else:
                aid, fa, fb = rng.choice(openh)
                y = rng.random()
                if y < 0.4:
                    capture(SL.c, t[fb], aid, rng.randint(1, 800), False)
                elif y < 0.7:
                    capture(SL.c, t[fb], aid, None, True)
                else:
                    void(SL.c, t[fa], aid)
        if ttl <= 2 and rng.random() < 0.6:
            time.sleep(ttl + 0.15)
        exl = SL.c.req("GET", "/_test/export").j
        auths = exl["state"]["authorizations"]
        tot["holds"] += len(auths)
        diff = [a for a in auths if a.get("created_exact") and a["created_exact"] != a["created_at"]]
        tot["rewritten"] += len(diff)
        tot["same_second_holds"] += len([a for a in auths if any(us(p["created_at"]) // 1_000_000 == us(a["created_at"]) // 1_000_000 for p in exl["state"]["payments"])])
        r = S3.c.req("POST", "/_test/import", raw=json.dumps(exl).encode())
        silent = F.silent_ok
        silent("RAND#%d import 204" % i, r.s == 204, (r.s, r.b[:300]))
        if r.s != 204:
            continue
        tk = {h: login(S3.c, h) for h in NAMES}
        n, bad = compare_views(S3.c, tk, NAMES, Oracle(oracle_state(exl)), "rand", nthreads=2)
        tot["views"] += n
        silent("RAND#%d (ttl %d, %d holds, %d re-placed) %d views: invariants + spec rules" % (i, ttl, len(auths), len(diff), n), not bad, bad[:3])
        e1 = S3.c.req("GET", "/_test/export").j
        got = {a["authorization_id"]: a for a in e1["state"]["authorizations"]}
        silent("RAND#%d every legacy hold: created_at == created_exact == the legacy microsecond; expires_at/closed_at/payment_ids unchanged" % i,
               all(got[a["authorization_id"]]["created_at"] == iso(ns(a["created_exact"]) // 1000) == got[a["authorization_id"]]["created_exact"] and got[a["authorization_id"]]["expires_at"] == a["expires_at"]
                   and got[a["authorization_id"]]["payment_ids"] == a["payment_ids"] for a in auths), None)
        r = S3.c.req("POST", "/_test/import", raw=json.dumps(e1).encode())
        silent("RAND#%d export -> import -> export byte-identical" % i, r.s == 204 and json.dumps(e1, sort_keys=True) == exp_json(S3.c), None)
    ok("RAND: %d legacy bursts (real 3c7c411 exports), %d holds (%d with created_exact != created_at, %d sharing a second with a payment), %d views: all hold" % (bursts, tot["holds"], tot["rewritten"], tot["same_second_holds"], tot["views"]),
       not F.FAILS and tot["rewritten"] > bursts * 3, tot)


def main():
    which = sys.argv[1:] or ["edges", "mix", "ttl1", "offsets", "subus", "bad", "dup", "nullabs", "allafter", "stage2", "ahead", "corr", "rand"]
    srv = {}
    try:
        S3 = Srv(F.S3EXE, PORT)
        srv["s3"] = S3
        SL = srv["sl"] = Srv("s3-legacy-3c7c411.exe", PORT + 3)
        skel = skeleton(SL)
        skeleton_cache.append(skel)
        for w in which:
            t0 = time.time()
            print("#### %s" % w, flush=True)
            if w == "stage2":
                s = srv["s2"] = Srv("s2.exe", PORT + 2)
                case_stage2(S3, skel, s)
                s.stop()
            elif w == "ahead":
                case_ahead(S3, skel, 10)
                case_ahead(S3, skel, 400)
            elif w == "rand":
                case_rand(S3, SL, int(os.environ.get("RL1_BURSTS", "30")), int(os.environ.get("RL1_SEED", "11")))
            else:
                globals()["case_" + w](S3, skel)
            print("#### %s done in %.1fs" % (w, time.time() - t0), flush=True)
    finally:
        for s in srv.values():
            s.stop()
    print("== rl1_attack %s: %d pass, %d fail, %d requests" % (",".join(which), F.NPASS[0], len(F.FAILS), F.NREQ[0]))
    if F.FAILS:
        print("FAILED:", F.FAILS)
        sys.exit(1)


if __name__ == "__main__":
    main()
