"""R3-N3 no seeded or imported value moves the server clock; seeded hold defaults; closed_at never in the future; views stay consistent.
Matrix: seeded hold status {open,captured,voided,expired} x expires_at {-2h,+2h} x created_at {omitted,-3h,+2h(future: spec silent, only 'no 5xx / no clock movement / consistent views' asserted)}
plus a funded-seed case (seeded payment funds a seeded open hold, both defaults) and stage-3 export -> import round trip of every case.
Requirements: stage-2 seeded status/expiry rules and 'available never negative'; stage-3 'Seeded open holds are assumed created at reset unless
created_at is supplied', 'Payment timestamps' (created_at = when money moved), 'closed_at ... event time when closed'."""
import itertools
from lib3 import *
import clk

now = lambda: dt.datetime.now(UTC)
H = lambda n: dt.timedelta(hours=n)
SL = dt.timedelta(milliseconds=30)
CASES = list(itertools.product(["open", "captured", "voided", "expired"], [-2, 2], [None, -3, 2]))
NCASE = [0]


def seeded_auth(status, exp_h, created_h, T0):
    a = {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public",
         "status": status, "expires_at": iso(T0 + H(exp_h))}
    if status == "captured":
        a["captured_amount"] = 2000
    if created_h is not None:
        a["created_at"] = iso(T0 + H(created_h))
    return a


def views(name, toks, T, total, known=None):
    """invariants and conservation at instant T for every user"""
    s = 0
    for h, tk in toks.items():
        r = me_at(tk, iso(T), known)
        if r.s != 200:
            ok("%s: GET /me?as_of=%s -> 200" % (name, iso(T)), False, r); return
        s += r.j["total"]
        ok("%s: %s view at %s consistent (balance=total, available=total-held>=0, held<=total) %s" % (name, h, iso(T), (r.j["total"], r.j["held"], r.j["available"])), inv(r.j), r.j)
    ok("%s: sum of totals at %s == seeded total" % (name, iso(T)), s == total, s)


def snapshot_state(toks):
    out = {}
    for h, tk in toks.items():
        m = me(tk)
        out[h] = (m["balance"], m["total"], m["held"], m["available"])
    out["authz"] = [(a["authorization_id"], a["status"], a["amount"], a["created_at"], a["expires_at"], a["closed_at"], a["payment_ids"], a["captured_amount"]) for a in authz(toks["ada"], limit=200)["authorizations"]]
    return out


def case(status, exp_h, created_h):
    NCASE[0] += 1
    name = "[%s exp%+dh created %s]" % (status, exp_h, "omitted" if created_h is None else "%+dh" % created_h)
    T0 = now()
    f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0)])
    f["authorizations"] = [seeded_auth(status, exp_h, created_h, T0)]
    r = call("POST", "/_test/reset", f)
    T1 = now()
    ok("%s reset -> 204 or 422 (never 5xx)" % name, r.s in (204, 422), r)
    if r.s != 204:
        return
    toks = {h: login(h + "@example.com") for h in ("ada", "bob", "cy")}
    TOTAL = 12500
    az = authz(toks["ada"], "a1") or authz(toks["ada"], limit=200)["authorizations"][0]
    # ---- the seeded values never move the clock: new payment / authorization / capture are stamped at their own request time
    t0 = now(); p = pay(toks["ada"], "cy", 1); t1 = now()
    ok("%s clock: new payment created_at within its request window (+-30 ms), not ratcheted by seeded values" % name, p.s == 201 and clk.inwin(P(p.j["created_at"]), t0, t1), (p, iso(t0), iso(t1)))
    t0 = now(); au = authorize(toks["cy"], "bob", 1); t1 = now()
    ok("%s clock: new authorization (cy has 1) created_at within its request window" % name, au.s == 201 and clk.inwin(P(au.j["created_at"]), t0, t1), (au, iso(t0), iso(t1)))
    # ---- seeded hold defaults and closed_at
    created = P(az["created_at"])
    if created_h is None:
        ok("%s hold created_at omitted -> the reset instant (between request start and end), not a truncated second" % name, clk.inwin(created, T0, T1), (az["created_at"], iso(T0), iso(T1)))
    else:
        ok("%s supplied created_at kept" % name, created == P(iso(T0 + H(created_h))), az["created_at"])
    if az["closed_at"] is not None:
        c = P(az["closed_at"])
        ok("%s closed_at is never in the future (an event time)" % name, clk.inwin(c, dt.datetime(1970, 1, 1, tzinfo=UTC), now()), az["closed_at"])
        if status == "expired" and exp_h < 0:
            ok("%s stored-expired with a past deadline: closed_at == expires_at (expiry takes effect at expires_at)" % name, c == P(az["expires_at"]), az)
    live = status == "open" and exp_h > 0 and (created_h is None or created_h < 0)
    ok("%s open status iff closed_at null (status shown %s)" % (name, az["status"]), (az["closed_at"] is None) == (az["status"] == "open"), az)
    m = me(toks["ada"])
    spent = 1   # the 1 paid above
    ok("%s current /me held == 2000 exactly for a live seeded open hold, else 0 %s" % (name, (m["held"], m["available"])), m["held"] == (2000 if live else 0) and inv(m), m)
    # ---- views at every public instant, +-1us
    insts = {created, P(az["expires_at"]), T0, T1, now()}
    if az["closed_at"]:
        insts.add(P(az["closed_at"]))
    for x in sorted(insts):
        for y in (x - US, x, x + US):
            views(name, toks, y, TOTAL)
    views(name, toks, EPOCH, TOTAL); views(name, toks, dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC), TOTAL)
    # ---- stage-2 behaviour intact: a live seeded open hold funds nothing, can be captured; a closed/expired one cannot
    m = me(toks["ada"])
    over = pay(toks["ada"], "cy", m["available"] + 1)
    ok("%s a payment above available is refused (409 insufficient_funds) %s" % (name, m["available"]), over.s == 409 and over.code == "insufficient_funds", over)
    t0 = now(); cap = capture(toks["bob"], "a1", amount=500, final=False); t1 = now()
    if live:
        ok("%s capture of the seeded live open hold -> 201, created_at now" % name, cap.s == 201 and clk.inwin(P(cap.j["created_at"]), t0, t1), cap)
    elif status in ("captured", "voided", "expired") or exp_h < 0:
        ok("%s capture of a closed/expired seeded hold -> 409, never 201 (%s)" % (name, cap.code), cap.s == 409, cap)
    else:
        ok("%s capture of a not-yet-created seeded hold: no 5xx (%s %s)" % (name, cap.s, cap.code), cap.s < 500, cap)
    ok("%s after the capture attempt: balances conserved, all views still consistent" % name, sum(me(toks[h])["total"] for h in toks) == TOTAL, [me(toks[h]) for h in toks])
    # ---- export / import round trip keeps the state and does not move the clock
    before = snapshot_state(toks)
    ex = call("GET", "/_test/export")
    ok("%s export -> 200" % name, ex.s == 200, ex)
    for rep in (1, 2):
        im = call("POST", "/_test/import", ex.j)
        ok("%s import #%d of its own export -> 204" % (name, rep), im.s == 204, im)
        toks2 = {h: login(h + "@example.com") for h in ("ada", "bob", "cy")}
        after = snapshot_state(toks2)
        ok("%s import #%d: balances/held/available and every authorization field (closed_at, expires_at, payment_ids, status, created_at) unchanged" % (name, rep), before == after, (before, after))
        t0 = now(); p2 = pay(toks2["bob"], "cy", 1); t1 = now()
        ok("%s import #%d: next payment stamped at its own request time (clock not moved by imported values)" % (name, rep), p2.s == 201 and clk.inwin(P(p2.j["created_at"]), t0, t1), (p2, iso(t0), iso(t1)))
        toks = toks2


for c in CASES:
    case(*c)

# ---- funded seed: seeded payment ada->bob 2000 funds a seeded open hold bob->cy 1500; both created_at omitted
T0 = now()
f = fx([user("ada", 8000), user("bob", 2000), user("cy", 0)], payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public"}])
f["authorizations"] = [{"id": "a1", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 1500, "note": "", "visibility": "public", "status": "open", "expires_at": iso(T0 + H(2))}]
reset(f)
toks = {h: login(h + "@example.com") for h in ("ada", "bob", "cy")}
az = authz(toks["bob"], "a1"); sp = [e for e in all_stmt(toks["bob"])[1]][0]["payment"]
cr, pc = P(az["created_at"]), P(sp["created_at"])
ok("funded seed: seeded payment and seeded hold both default to the reset instant; the payment is not later than the hold it funds", pc <= cr, (sp["created_at"], az["created_at"]))
for y in (cr - US, cr, cr + US, pc - US, pc, pc + US):
    views("funded seed", toks, y, 10000)
v = me_at(toks["bob"], iso(cr)).j
ok("funded seed: at as_of = authorization.created_at bob has total 2000 held 1500 available 500", (v["total"], v["held"], v["available"]) == (2000, 1500, 500), v)
# seeded payment with created_at supplied in the past + hold omitted
f["payments"][0]["created_at"] = iso(T0 - H(1)); reset(f)
toks = {h: login(h + "@example.com") for h in ("ada", "bob", "cy")}
az = authz(toks["bob"], "a1"); cr = P(az["created_at"])
v = me_at(toks["bob"], iso(cr)).j
ok("funded seed (payment 1h ago): view at hold creation total 2000 held 1500 available 500", (v["total"], v["held"], v["available"]) == (2000, 1500, 500), v)
print("INFO", clk.report())
done("r3_seedmatrix (%d cases)" % NCASE[0])
