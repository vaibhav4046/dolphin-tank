"""R3-N4 'Recorded times for one payment strictly increase' and 'everything known when the read begins' (read-your-write) across:
A rapid sequential corrections, B seeded payments corrected at once, C hand-built import whose revision is recorded slightly / well ahead of the clock,
D a 70 s live loop with export->import round trips while the VM wall clock steps back (see clk.py), a realistic way to meet b2d9bf3's case.
Requirement: stage-3 corrections ('Recorded times for one payment strictly increase', 'server-assigned recorded_at', replay/stale rules) and known_at semantics."""
import time
from lib3 import *
import clk

now = lambda: dt.datetime.now(UTC)
TOK = {}


def rec_list(tok, pid):
    return [P(r["recorded_at"]) for r in revs(tok, pid)]


def strictly_increasing(xs):
    return all(b > a for a, b in zip(xs, xs[1:]))


# ============================================================ A rapid sequential corrections
t = setup(fx([user("ada", 100000), user("bob", 0)]))
A = t["ada"]
p = pay(A, "bob", 100).j; pid = p["payment_id"]; created = P(p["created_at"])
cur = 100
recs = [created]
okA = True; bad = []
for n in range(2, 62):
    amt = 150 if n % 2 == 0 else 50
    r = correct(A, pid, n - 1, amt, p["created_at"], "n%d" % n)
    if r.s != 201:
        okA = False; bad.append((n, r.s, r.code)); break
    rc = P(r.j["recorded_at"])
    if not rc > recs[-1]: bad.append(("not strictly after previous", n, iso(recs[-1]), iso(rc)))
    recs.append(rc)
    m = me(A)
    if m["total"] != 100000 - amt: bad.append(("read-your-write /me", n, m["total"], 100000 - amt))
    st = stmt(A, limit=5).j
    if not st["entries"] or st["entries"][0]["revision"] != n or st["entries"][0]["payment"]["amount"] != amt: bad.append(("read-your-write /statement", n, st["entries"][:1]))
ok("A 60 rapid corrections: all 201, each recorded strictly after the previous, /me and /statement reflect each at once; bad=%s" % bad[:2], okA and not bad, bad[:4])
ok("A GET revisions: recorded_at strictly increasing over 61 revisions; revision 1 recorded_at == created_at", strictly_increasing(rec_list(A, pid)) and rec_list(A, pid)[0] == created and len(rec_list(A, pid)) == 61)
rs = revs(A, pid)
chk = []
for n in (1, 2, 30, 61):
    rn = P(rs[n - 1]["recorded_at"])
    s1 = stmt(A, known_at=iso(rn)).j["entries"]; s0 = stmt(A, known_at=iso(rn - US)).j["entries"]
    chk.append((n, s1[0]["revision"] if s1 else None, s0[0]["revision"] if s0 else None))
ok("A known_at == recorded_at selects that revision (inclusive), 1 us earlier the previous one (none before revision 1)", all(a == n and (b == n - 1 or (n == 1 and b is None)) for (n, a, b) in chk), chk)

# ============================================================ B seeded payments corrected immediately
for rep in range(4):
    T0 = now()
    fb = fx([user("ada", 9000), user("bob", 1000)], payments=[{"id": "ps", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000, "note": "", "visibility": "public"}] + ([] if rep % 2 == 0 else []))
    if rep >= 2:
        fb["payments"][0]["created_at"] = iso(T0 - dt.timedelta(seconds=1))
    tb = setup(fb)
    pid_b = call("GET", "/statement?limit=5", token=tb["ada"]).j["entries"][0]["payment"]["payment_id"]
    r = correct(tb["ada"], pid_b, 1, 400, iso(T0 - dt.timedelta(seconds=1)) if rep >= 2 else iso(now() - dt.timedelta(seconds=3)), "seeded fix")
    rl = rec_list(tb["ada"], pid_b)
    ok("B seeded payment (created_at %s) corrected immediately: 201, recorded strictly after revision 1 %s" % ("supplied" if rep >= 2 else "omitted=reset instant", [iso(x) for x in rl]), r.s == 201 and len(rl) == 2 and rl[1] > rl[0], (r, rl))
    ok("B /me reflects the correction at once (ada 9000 -> 9600)", me(tb["ada"])["total"] == 9600 and me(tb["bob"])["total"] == 400, [me(tb[h]) for h in tb])


# ============================================================ C hand-built import: revision recorded ahead of the clock
def build_ahead(delta_s):
    tc = setup(fx([user("ada", 10000), user("bob", 0)]))
    pc = pay(tc["ada"], "bob", 500).j
    exs = call("GET", "/_test/export").j
    x = iso(now() + dt.timedelta(seconds=delta_s))
    st_ = exs["state"]
    st_["payments"][0]["created_at"] = x
    st_["revisions"][0]["effective_at"] = x; st_["revisions"][0]["recorded_at"] = x
    return tc, pc, exs, x


for delta in (0.03, 0.6):
    tc, pc, exs, x = build_ahead(delta)
    im = call("POST", "/_test/import", exs)
    if im.s != 204:
        print("INFO import of a payment recorded %.2f s ahead -> %s (hand-built state; spec silent, not asserted)" % (delta, im.s)); continue
    tc = {h: login(h + "@example.com") for h in ("ada", "bob")}
    r = correct(tc["ada"], pc["payment_id"], 1, 800, iso(now() - dt.timedelta(seconds=3)), "after ahead-import")
    rl = rec_list(tc["ada"], pc["payment_id"])
    ok("C import with revision 1 recorded %.2f s ahead: correction 201 and recorded strictly after it %s" % (delta, [iso(v) for v in rl]), r.s == 201 and len(rl) == 2 and rl[1] > rl[0], (r, rl))
    ok("C ... and the correction is visible to the very next read (/me ada 9200, statement shows revision 2)", me(tc["ada"])["total"] == 9200 and (stmt(tc["ada"]).j["entries"] or [{}])[0].get("revision") == 2, (me(tc["ada"]), stmt(tc["ada"]).j["entries"][:1]))
    ok("C sum of totals unchanged", me(tc["ada"])["total"] + me(tc["bob"])["total"] == 10000)

# ============================================================ D 70 s live loop with import round trips across wall-clock steps
t = setup(fx([user("ada", 1000000), user("bob", 0)]))
A, B = t["ada"], t["bob"]
model = {}     # pid -> current amount
last_rec = {}  # pid -> last recorded_at
bad = []; nimp = 0; ncor = 0
t_end = time.monotonic() + 70
i = 0
while time.monotonic() < t_end:
    i += 1
    pp = pay(A, "bob", 100)
    if pp.s != 201:
        bad.append(("pay", pp.s, pp.code)); break
    pid = pp.j["payment_id"]; model[pid] = 100; last_rec[pid] = P(pp.j["created_at"])
    pairs = [(pid, 1)]
    if i % 5 == 0:   # export -> import round trip of the live state, then correct several payments at once
        ex = call("GET", "/_test/export").j
        im = call("POST", "/_test/import", ex)
        nimp += 1
        if im.s != 204: bad.append(("import", im.s)); break
        A = login("ada@example.com"); B = login("bob@example.com")
        pairs = [(q_, len(rec_list(A, q_))) for q_ in list(model)[-3:]]
    for q_, rv in pairs:
        amt = 100 + (7 * (ncor % 5)) + 1
        r = correct(A, q_, rv, amt, iso(now() - dt.timedelta(seconds=3)), "loop")
        ncor += 1
        if r.s != 201:
            bad.append(("correct", q_, rv, r.s, r.code)); continue
        rc = P(r.j["recorded_at"])
        if not rc > last_rec[q_]: bad.append(("not strictly after", q_, iso(last_rec[q_]), iso(rc)))
        last_rec[q_] = rc; model[q_] = amt
        got = me(A)["total"]
        if got != 1000000 - sum(model.values()): bad.append(("read-your-write", q_, got, 1000000 - sum(model.values())))
    time.sleep(0.12)
ok("D 70 s loop: %d payments, %d corrections, %d import round trips: every correction 201, strictly after the previous revision, visible to the next read; first bad %s" % (len(model), ncor, nimp, bad[:2]), not bad and ncor > 100 and nimp >= 8, bad[:4])
allrec = all(strictly_increasing(rec_list(A, q_)) for q_ in model)
ok("D every payment's recorded_at strictly increasing in GET revisions at the end (%d payments)" % len(model), allrec)
ok("D sum of totals == 1000000", me(A)["total"] + me(B)["total"] == 1000000, (me(A)["total"], me(B)["total"]))
print("INFO", clk.report())
done("r3_corr_order")
