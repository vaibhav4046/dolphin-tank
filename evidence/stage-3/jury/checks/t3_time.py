"""J01 J02 J06 J07 J08 J09: payment created_at everywhere, /me as_of boundaries, echo, validation. Oracle from spec."""
import time
from lib3 import *

f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0), user("op", 5000)], ops=["u_op"])
t = setup(f)
A, B, C, OP = t["ada"], t["bob"], t["cy"], t["op"]
TOTAL = 17500
UID = {"ada": "u_ada", "bob": "u_bob", "cy": "u_cy", "op": "u_op"}
OPEN = {"u_ada": 10000, "u_bob": 2500, "u_cy": 0, "u_op": 5000}
o = Oracle(OPEN)


def track(p, tok_from):
    rv = revs(tok_from, p["payment_id"])
    o.add(p["payment_id"], p["from_user_id"], p["to_user_id"], rv)
    return rv


# ---- J01 created_at on every payment-returning endpoint
pays = []
for frm, to, amt in [(A, "bob", 1000), (A, "bob", 500), (B, "cy", 200), (A, "cy", 50)]:
    p = pay(frm, to, amt, note="n%d" % amt)
    assert p.s == 201, p
    pays.append(p.j)
    time.sleep(0.012)
rq = call("POST", "/requests", {"payer_handle": "bob", "amount": 100}, token=C, key=k()).j
rp = call("POST", "/requests/%s/pay" % rq["request_id"], {}, token=B, key=k())
st = call("POST", "/settlements", {"transfers": [{"from_handle": "op", "to_handle": "cy", "amount": 10}, {"from_handle": "cy", "to_handle": "ada", "amount": 5}]}, token=OP, key=k())
for name, r in [("POST /payments", pays[0] and call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=A, key=k())), ("request pay", rp)]:
    cj = r.j
    ok("J01 %s: created_at RFC3339 with offset" % name, r.s == 201 and isinstance(cj.get("created_at"), str) and RFC3339.match(cj["created_at"]), r)
ok("J01 settlement members: created_at RFC3339 with offset, equal to committed_at", st.s == 201 and all(m["created_at"] == st.j["committed_at"] and RFC3339.match(m["created_at"]) for m in st.j["payments"]), st)
act = call("GET", "/activity?limit=200", token=A)
ok("J01 /activity payments all carry created_at", act.s == 200 and all(RFC3339.match(p.get("created_at", "")) for p in act.j["payments"]) and len(act.j["payments"]) >= 8, act)
s = call("GET", "/statement", token=A)
ok("J01 statement entry payments carry created_at", s.s == 200 and all(RFC3339.match(e["payment"].get("created_at", "")) for e in s.j["entries"]) and s.j["entries"], s)

# ---- J02 activity ordering newest-first by created_at
ca = [p["created_at"] for p in act.j["payments"]]
ok("J02 /activity ordered newest first by created_at", all(P(ca[i]) >= P(ca[i + 1]) for i in range(len(ca) - 1)), ca)

# collect all payments for oracle
every = {}
for p in act.j["payments"]:
    every[p["payment_id"]] = p
for m in st.j["payments"]:
    every[m["payment_id"]] = m
for pid, p in every.items():
    tok = {"u_ada": A, "u_bob": B, "u_cy": C, "u_op": OP}[p["from_user_id"]]
    track(p, tok)
cur = {h: me(t[h]) for h in UID}
ok("J07 current /me unchanged shape and fields (no corrections)", all(set(["user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"]) <= set(v) and "as_of" not in v and "known_at" not in v for v in cur.values()), cur["ada"])
ok("J07 balance == total == available, held 0 without holds", all(v["balance"] == v["total"] == v["available"] and v["held"] == 0 for v in cur.values()), cur)
ok("J29-base current balances sum to seeded total", sum(v["balance"] for v in cur.values()) == TOTAL)

# ---- J08/J09 as_of boundaries against the oracle at every payment instant +-1us and a few extra instants
stamps = sorted({P(p["created_at"]) for p in every.values()})
instants = []
for s_ in stamps:
    instants += [s_ - US, s_, s_ + US]
instants += [P("0001-01-01T00:00:00Z"), P("1970-01-01T00:00:00Z"), stamps[0] - dt.timedelta(days=400), stamps[-1] + dt.timedelta(days=400), P("9999-12-31T23:59:59Z")]
bad = []
sumbad = []
for inst in instants:
    s_inst = iso(inst)
    tot = 0
    for h, uid in UID.items():
        r = me_at(t[h], s_inst)
        exp = o.total(uid, inst)
        if r.s != 200 or r.j["balance"] != exp or r.j["total"] != exp or r.j["available"] != exp or r.j["held"] != 0 or r.j.get("as_of") != s_inst:
            bad.append((h, s_inst, exp, r.s, r.j if r.s == 200 else r.b[:100]))
        else:
            tot += r.j["balance"]
    if tot != TOTAL:
        sumbad.append((s_inst, tot))
ok("J08/J09 as_of at/around %d instants (each payment -1us, exact, +1us, far past/future): oracle balance/total/available/held and exact echo for 4 users" % len(instants), not bad, bad[:3])
ok("J29 sum of balances == seeded total at every historical instant", not sumbad, sumbad[:3])

first, last = stamps[0], stamps[-1]
r = me_at(t["ada"], iso(first - US))
ok("J09 as_of before earliest payment returns the opening balance (10000)", r.j["balance"] == 10000, r)
r = me_at(t["ada"], iso(last))
ok("J09 as_of at latest payment == current balance", r.j["balance"] == cur["ada"]["balance"], (r, cur["ada"]))
r = me_at(t["cy"], iso(first - US))
ok("J09 new/empty-history wallet opens at its seeded balance (cy 0)", r.j["balance"] == 0)

# exact boundary with the user's own first payment
p0 = pays[0]
r_before = me_at(A, iso(P(p0["created_at"]) - US)).j["balance"]
r_at = me_at(A, p0["created_at"]).j["balance"]
ok("J08 payment made at exactly as_of counts as happened (before %d, at %d)" % (r_before, r_at), r_before == 10000 and r_at == 9000, (r_before, r_at))

# ---- J09 echo exactly as given, including non-UTC forms and Z
p0u = P(p0["created_at"])
forms = ["2030-01-01T00:00:00Z", "2030-01-01T05:30:00+05:30", "2030-01-01T00:00:00-08:00", "2030-01-01T00:00:00.123456Z", "2030-01-01T00:00:00.5+00:00", "2030-01-01T00:00:00+00:00"]
for fm in forms:
    r = me_at(A, fm)
    ok("J09 echo as_of exactly as given: %s" % fm, r.s == 200 and r.j.get("as_of") == fm, r)
# same instant in another offset gives the same answer
inst = P(p0["created_at"])
alt = inst.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="microseconds")
ok("J08 offset-shifted spelling of the same instant gives the same balance", me_at(A, alt).j["balance"] == 9000 and me_at(A, alt).j["as_of"] == alt)

# ---- J06 validation
BAD = ["", "2026-09-24T13:20:00", "2026-09-24", "13:20:00Z", "garbage", "1700000000", "2026-09-24T13:20:00+0000", "2026-13-45T00:00:00Z", "2026-09-24T25:00:00Z", "2026-02-30T00:00:00Z", " ", "2026-09-24T13:20:00+25:00", "2026-09-24T13:20Z", "null"]
for b in BAD:
    r = me_at(A, b)
    ok("J06 as_of=%r -> 422 validation_failed" % b, r.s == 422 and r.code == "validation_failed", r)
for b in BAD[:6]:
    r = me_at(A, None, b)
    ok("J32 known_at=%r -> 422 validation_failed" % b, r.s == 422 and r.code == "validation_failed", r)
r = call("GET", "/me?as_of=", token=A)
ok("J06 empty as_of (raw ?as_of=) 422", r.s == 422 and r.code == "validation_failed", r)
r = call("GET", "/me?as_of", token=A)
ok("J06 bare as_of key 422", r.s == 422, r)
ok("J06 unauthenticated /me?as_of=bad is 401", call("GET", "/me?as_of=bad").s == 401)
ok("J06 unknown query parameter ignored", call("GET", "/me?zzz=1&balance=5", token=A).s == 200)

# ---- J07: statement J01-ish
done("t3_time")
