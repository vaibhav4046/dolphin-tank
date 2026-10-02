"""resource limits: large seeded history (reset <= 10 s, requests <= 5 s, 50 in flight), plus odd-but-valid instant spellings (no 5xx)."""
import random, time
from lib3 import *

rnd = random.Random(5)
NU, NP = 6, 20000
H = ["u%d" % i for i in range(NU)]
open_ = {h: 10_000_000 for h in H}
bal = dict(open_)
now = dt.datetime.now(UTC)
t0 = now - dt.timedelta(days=30)
stamps = sorted(rnd.random() for _ in range(NP))
seeded = []
for i, s in enumerate(stamps):
    a, b = rnd.sample(H, 2)
    amt = rnd.randint(1, 2000)
    bal[a] -= amt; bal[b] += amt
    seeded.append({"id": "p_%06d" % i, "from_user_id": "u_" + a, "to_user_id": "u_" + b, "amount": amt, "note": "", "visibility": rnd.choice(["public", "private"]),
                   "created_at": iso(t0 + (now - dt.timedelta(minutes=5) - t0) * s)})
f = fx([user(h, bal[h]) for h in H], payments=seeded)
t_ = time.time()
r = call("POST", "/_test/reset", f, timeout=30)
dt_reset = time.time() - t_
ok("reset with %d seeded payments returns 204 within the 10 s limit (took %.2f s)" % (NP, dt_reset), r.s == 204 and dt_reset < 10, (r.s, dt_reset))
tk = {h: login(h + "@example.com") for h in H}
TOT = sum(bal.values())
# oracle straight from the seeded list
def direct(h, as_of=None):
    uid = "u_" + h
    b = open_[h]
    for p in seeded:
        if as_of is not None and P(p["created_at"]) > as_of:
            break
        if p["from_user_id"] == uid: b -= p["amount"]
        elif p["to_user_id"] == uid: b += p["amount"]
    return b
lat = []
bad = []
for _ in range(25):
    x = t0 + (now - t0) * rnd.random()
    for h in H:
        t_ = time.time(); rr_ = me_at(tk[h], iso(x)); lat.append(time.time() - t_)
        if rr_.j["balance"] != direct(h, x): bad.append((h, iso(x), rr_.j["balance"], direct(h, x)))
ok("as_of over %d seeded payments == direct computation (150 views); max latency %.3f s" % (NP, max(lat)), not bad and max(lat) < 2, bad[:2])
t_ = time.time(); s = stmt(tk["u0"]); lt = time.time() - t_
ok("default statement over 20000-payment history: 200, opening/closing right, latency %.2f s" % lt, s.s == 200 and s.j["closing_balance"] == bal["u0"] and s.j["opening_balance"] == open_["u0"] and lt < 5, (s.s, lt))
t_ = time.time(); s2 = stmt(tk["u0"], limit=200, offset=3000); lt = time.time() - t_
exp_entries = [p for p in seeded if "u_u0" in (p["from_user_id"], p["to_user_id"])]
ok("deep offset page matches the seeded order (latency %.2f s)" % lt, s2.s == 200 and [e["payment"]["payment_id"] for e in s2.j["entries"]] == [p["id"] for p in exp_entries[3000:3200]] and lt < 5, (s2.s, lt))
# corrections latency + 50-way concurrency on distinct payments
lats = []
for i in range(40):
    p = exp_entries[rnd.randrange(len(exp_entries))]
    sender = [h for h in H if "u_" + h == p["from_user_id"]][0]
    t_ = time.time(); r = correct(tk[sender], p["id"], 1, p["amount"] + 1, p["created_at"], "scale"); lats.append(time.time() - t_)
    if r.s not in (201, 409): bad.append(("corr status", r.s))
ok("40 sequential corrections over a 20000-payment history: all 201/409, max latency %.2f s (limit 5 s)" % max(lats), max(lats) < 5 and not [b for b in bad if b[0] == "corr status"], (max(lats), lats[:3]))
cands = {}
for p in seeded:
    cands.setdefault(p["from_user_id"], []).append(p)
fns = []
for j in range(50):
    uid = "u_u%d" % (j % NU)
    p = cands[uid][100 + j * 7]
    h = uid[2:]
    fns.append(lambda p=p, h=h: (time.time(), correct(tk[h], p["id"], 1, p["amount"] + 2, p["created_at"], "burst"), time.time()))
res = parallel(fns)
lat50 = [r_[2] - r_[0] for r_ in res if isinstance(r_, tuple)]
ok("50 simultaneous corrections: no errors, statuses 201/409 only, max latency %.2f s (limit 5 s)" % max(lat50), len(lat50) == 50 and all(r_[1].s in (201, 409) for r_ in res) and max(lat50) < 5, [r_[1].s if isinstance(r_, tuple) else repr(r_) for r_ in res][:10])
ok("J29 sum of balances constant after the burst", sum(me(tk[h])["balance"] for h in H) == TOT)
# odd instant spellings: never a 5xx; consistent accept/reject
for sp in ["0001-01-01T00:00:00Z", "1969-12-31T23:59:59-00:00", "2016-12-31T23:59:60Z", "2026-10-02T07:00:00.123456789Z", "2026-10-02t07:00:00z", "2026-10-02 07:00:00Z", "2026-10-02T07:00:00.1234567890123Z", "9999-12-31T23:59:59.999999999+23:59"]:
    r1 = me_at(tk["u0"], sp); r2 = stmt(tk["u0"], limit=1, **{"from": sp}); r3 = me_at(tk["u0"], None, sp)
    print("INFO instant %-40s /me %s  statement %s  known_at %s" % (sp, r1.s, r2.s, r3.s))
    ok("no 5xx for instant spelling %r" % sp, max(r1.s, r2.s, r3.s) < 500, (r1, r2, r3))
for q_ in ["offset=9223372036854775807", "offset=99999999999999999999", "limit=200&offset=4294967296"]:
    r = call("GET", "/statement?" + q_, token=tk["u0"])
    ok("huge offset %s: no 5xx, 200 empty or 422" % q_, r.s in (200, 422) and (r.s == 422 or (r.j["entries"] == [] and r.j["has_more"] is False)), r)
# non-UTC spellings equal UTC
x = t0 + (now - t0) * .5
alt = x.astimezone(dt.timezone(dt.timedelta(hours=-9, minutes=-30))).isoformat(timespec="microseconds")
a_, b_ = stmt(tk["u1"], limit=200, **{"from": iso(x)}).j, stmt(tk["u1"], limit=200, **{"from": alt}).j
ok("statement `from` in another offset spelling == same instant in UTC", a_["opening_balance"] == b_["opening_balance"] and [e["payment"]["payment_id"] for e in a_["entries"]] == [e["payment"]["payment_id"] for e in b_["entries"]])
a_, b_ = stmt(tk["u1"], limit=200, to=iso(x)).j, stmt(tk["u1"], limit=200, to=alt.replace("-09:30", "-09:30")).j
ok("statement `to` in another offset spelling == same instant in UTC", a_["closing_balance"] == b_["closing_balance"])
done("t3_scale")
