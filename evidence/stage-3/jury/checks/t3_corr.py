"""J18 J20-J31 J33: corrections - auth, validation, shape, money, overdraft rules, atomic failure, idempotency, revisions endpoint."""
import time, json
from lib3 import *

now = lambda: dt.datetime.now(UTC)


def scn(bal):
    f = fx([user(h, b) for h, b in bal.items()], ops=["u_op"] if "op" in bal else None)
    t = setup(f)
    return t, sum(bal.values())


def world(t, pids=()):
    w = {h: me(t[h]) for h in t}
    w["stmt"] = {h: stmt(t[h], limit=200).j["entries"] for h in t}
    w["act"] = call("GET", "/activity?limit=200", token=list(t.values())[0]).j
    w["revs"] = {}
    for pid in pids:
        for tk in t.values():
            r = call("GET", "/payments/%s/revisions" % pid, token=tk)
            if r.s == 200:
                w["revs"][pid] = r.j
                break
    return w


# =============================================================== C1 auth + validation table
t, TOTAL = scn({"ada": 5000, "bob": 1000, "cy": 300, "dee": 0})
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
p1 = pay(A, "bob", 1000, vis="public") if False else call("POST", "/payments", {"to_handle": "bob", "amount": 1000, "visibility": "public", "note": "x"}, token=A, key=k()).j
PID = p1["payment_id"]
good = {"expected_revision": 1, "amount": 900, "effective_at": p1["created_at"], "reason": "fix"}
W0 = world(t, [PID])
ok("J20 no token -> 401", call("POST", "/payments/%s/corrections" % PID, good, key=k()).s == 401)
r = call("POST", "/payments/%s/corrections" % PID, good, token=A)
ok("J20 missing Idempotency-Key -> 400 missing_idempotency_key", r.s == 400 and r.code == "missing_idempotency_key", r)
r = call("POST", "/payments/%s/corrections" % PID, good, token=A, key="")
ok("J20 empty Idempotency-Key -> 400", r.s == 400 and r.code == "missing_idempotency_key", r)
r = call("POST", "/payments/%s/corrections" % PID, good, token=A, key="x" * 256)
ok("J20 Idempotency-Key 256 chars -> 422 validation_failed", r.s == 422 and r.code == "validation_failed", r)
for who, tk in [("receiver", B), ("stranger", C)]:
    r = call("POST", "/payments/%s/corrections" % PID, good, token=tk, key=k())
    ok("J20 %s correcting -> 403 forbidden" % who, r.s == 403 and r.code == "forbidden", r)
r = call("POST", "/payments/p_nope/corrections", good, token=A, key=k())
ok("J20 unknown payment -> 404 not_found", r.s == 404 and r.code == "not_found", r)
r = call("POST", "/payments/p_nope/corrections", good, token=C, key=k())
ok("J20 unknown payment as other user -> 404", r.s == 404, r)
ok("J20 failed auth/permission attempts changed nothing", world(t, [PID]) == W0)

FUT = iso(now() + dt.timedelta(hours=1))
FUT2 = iso(now() + dt.timedelta(seconds=30))
cases = [
    ("missing expected_revision", {k_: v for k_, v in good.items() if k_ != "expected_revision"}),
    ("missing amount", {k_: v for k_, v in good.items() if k_ != "amount"}),
    ("missing effective_at", {k_: v for k_, v in good.items() if k_ != "effective_at"}),
    ("missing reason", {k_: v for k_, v in good.items() if k_ != "reason"}),
    ("expected_revision 0", dict(good, expected_revision=0)),
    ("expected_revision -1", dict(good, expected_revision=-1)),
    ("expected_revision 1.5", dict(good, expected_revision=1.5)),
    ("amount -1", dict(good, amount=-1)),
    ("amount 1e9+1", dict(good, amount=1000000001)),
    ("amount 1.5", dict(good, amount=1.5)),
    ("amount '900'", dict(good, amount="900")),
    ("amount true", dict(good, amount=True)),
    ("amount null", dict(good, amount=None)),
    ("reason ''", dict(good, reason="")),
    ("reason 201 chars", dict(good, reason="r" * 201)),
    ("effective_at future +1h", dict(good, effective_at=FUT)),
    ("effective_at future +30s", dict(good, effective_at=FUT2)),
    ("effective_at naive", dict(good, effective_at="2026-01-01T00:00:00")),
    ("effective_at date only", dict(good, effective_at="2026-01-01")),
    ("effective_at garbage", dict(good, effective_at="garbage")),
    ("effective_at ''", dict(good, effective_at="")),
]
for name, body in cases:
    r = call("POST", "/payments/%s/corrections" % PID, body, token=A, key=k())
    ok("J21 %s -> 422 validation_failed" % name, r.s == 422 and r.code == "validation_failed", r)
for name, body in [("expected_revision '1'", dict(good, expected_revision="1")), ("expected_revision true", dict(good, expected_revision=True)), ("expected_revision null", dict(good, expected_revision=None)),
                   ("reason 5", dict(good, reason=5)), ("reason null", dict(good, reason=None)), ("effective_at 5", dict(good, effective_at=5)), ("effective_at null", dict(good, effective_at=None))]:
    r = call("POST", "/payments/%s/corrections" % PID, body, token=A, key=k())
    ok("J21 %s -> 400 malformed_request or 422 validation_failed (no change)" % name, (r.s == 400 and r.code == "malformed_request") or (r.s == 422 and r.code == "validation_failed"), r)
    if r.s == 422:
        print("INFO wrong-typed %s answered 422" % name)
for name, raw in [("not json", "{nope"), ("array body", "[1]"), ("empty body", "")]:
    r = call("POST", "/payments/%s/corrections" % PID, raw=raw, token=A, key=k())
    ok("J21 %s -> 400 malformed_request" % name, r.s == 400 and r.code == "malformed_request", r)
ok("J21 all invalid attempts changed nothing", world(t, [PID]) == W0)
# failed 4xx key is reusable (J28): same key used with a bad body then valid body
kk = k()
r = call("POST", "/payments/%s/corrections" % PID, dict(good, amount=-1), token=A, key=kk)
r2 = call("POST", "/payments/%s/corrections" % PID, good, token=A, key=kk)
ok("J28 key that failed 422 is reusable: first valid use is 201 (not 200/409)", r.s == 422 and r2.s == 201 and r2.j["revision"] == 2, (r, r2))
# amount spelled 1000.0 and 1e3 are integral
r = call("POST", "/payments/%s/corrections" % PID, raw='{"expected_revision":2,"amount":9e2,"effective_at":"%s","reason":"sci","extra":1}' % p1["created_at"], token=A, key=k())
ok("J21 integral amount 9e2 accepted, unknown field ignored", r.s == 201 and r.j["amount"] == 900 and r.j["revision"] == 3, r)

# =============================================================== C2 shape / revisions / immutability of original
t, TOTAL = scn({"ada": 5000, "bob": 1000, "cy": 300, "dee": 0})
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
k1 = k()
orig = call("POST", "/payments", {"to_handle": "bob", "amount": 1000, "note": "orig-note", "visibility": "private"}, token=A, key=k1)
p1 = orig.j
PID = p1["payment_id"]
r = correct(A, PID, 1, 600, p1["created_at"], "shrink")
ok("J22 correction 201 with exactly payment_id/revision/amount/effective_at/recorded_at/reason", r.s == 201 and set(r.j) == {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"} and r.j["revision"] == 2 and r.j["amount"] == 600 and r.j["reason"] == "shrink" and r.j["payment_id"] == PID and P(r.j["effective_at"]) == P(p1["created_at"]) and RFC3339.match(r.j["recorded_at"]) and RFC3339.match(r.j["effective_at"]), r)
rv = revs(A, PID)
ok("J18 revisions in order, rev1 = original (amount 1000, reason '', effective_at=recorded_at=created_at)", [x["revision"] for x in rv] == [1, 2] and rv[0]["amount"] == 1000 and rv[0]["reason"] == "" and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(p1["created_at"]), rv)
ok("J22 revisions entries carry payment_id, revision, amount, effective_at, recorded_at, reason", all(set(x) >= {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"} for x in rv))
ok("J30 parties/visibility unchanged: replay of ORIGINAL payment request returns 200 with the original body", (lambda rr: rr.s == 200 and rr.j == p1)(call("POST", "/payments", {"to_handle": "bob", "amount": 1000, "note": "orig-note", "visibility": "private"}, token=A, key=k1)))
act = call("GET", "/activity?limit=200", token=A).j["payments"]
ok("J30 /activity still shows the ORIGINAL payment (amount 1000, same parties/visibility/note/created_at), one item, no correction records", [x for x in act] == [p1], act)
ok("J30 stranger's /activity does not show private payment, still none for corrections", call("GET", "/activity", token=C).j["payments"] == [])
ok("J26 decrease debited original receiver: ada 5000-600=4400, bob 1000+600=1600, others untouched; sum constant",
   [me(t[h])["balance"] for h in ("ada", "bob", "cy", "dee")] == [4400, 1600, 300, 0] and sum(me(t[h])["balance"] for h in t) == TOTAL)
# J23 strictly increasing recorded times over rapid corrections
cur = 2
for i in range(25):
    r = correct(A, PID, cur, 500 + (i % 7) * 10, p1["created_at"], "rapid%d" % i)
    assert r.s == 201, r
    cur = r.j["revision"]
rv = revs(A, PID)
recs = [P(x["recorded_at"]) for x in rv]
ok("J23 recorded_at strictly increases over 27 revisions (25 back-to-back corrections)", all(recs[i] < recs[i + 1] for i in range(len(recs) - 1)) and [x["revision"] for x in rv] == list(range(1, len(rv) + 1)), [x["recorded_at"] for x in rv][:5])
ok("J22 earlier revisions immutable after later ones (rev1 unchanged)", rv[0]["amount"] == 1000 and rv[0]["reason"] == "" and rv[1]["amount"] == 600 and rv[1]["reason"] == "shrink")
# zero reverses entire payment; then increase from zero
bal_before = [me(t[h])["balance"] for h in ("ada", "bob")]
r = correct(A, PID, cur, 0, p1["created_at"], "reverse"); cur = r.j["revision"] if r.s == 201 else cur
ok("J21/J26 amount 0 reverses the entire payment (ada back to 5000, bob 1000)", r.s == 201 and r.j["amount"] == 0 and [me(t[h])["balance"] for h in ("ada", "bob")] == [5000, 1000], r)
r = correct(A, PID, cur, 700, p1["created_at"], "again"); cur = r.j["revision"] if r.s == 201 else cur
ok("J26 increase from 0 debits sender 700 (ada 4300, bob 1700)", r.s == 201 and [me(t[h])["balance"] for h in ("ada", "bob")] == [4300, 1700], r)
ok("J29 sum constant", sum(me(t[h])["balance"] for h in t) == TOTAL)
# J24 stale expected_revision
for ex in (1, cur - 1):
    r = correct(A, PID, ex, 650, p1["created_at"], "stale")
    ok("J24 stale expected_revision=%d (current %d) -> 409 stale_revision" % (ex, cur), r.s == 409 and r.code == "stale_revision", r)
r = correct(A, PID, cur + 1, 650, p1["created_at"], "ahead")
print("INFO expected_revision ahead of current answered", r.s, r.code)
ok("J24 expected_revision ahead of current is not accepted as success", r.s in (409, 422), r)
ok("J24 stale attempts left history unchanged", len(revs(A, PID)) == cur)

# =============================================================== C3 insufficient / historical overdraft / atomic failure
t, TOTAL = scn({"ada": 1500, "bob": 400, "cy": 0, "dee": 0})
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
q1 = pay(A, "bob", 600).j
time.sleep(0.01)
q2 = pay(A, "cy", 400).j
time.sleep(0.01)
q3 = pay(B, "ada", 1000).j  # bob 400+600=1000 -> 0 ; ada 500 -> 1500
ok("setup: ada 1500 bob 0 cy 400", [me(t[h])["balance"] for h in ("ada", "bob", "cy")] == [1500, 0, 400])
PIDS = [q1["payment_id"], q2["payment_id"], q3["payment_id"]]
W0 = world(t, PIDS)
r = correct(A, q1["payment_id"], 1, 1800, q1["created_at"], "bigger")
ok("J27 historically unaffordable increase (+1200 affordable now: ada 1500; ada would be 1500-1800-400<0 at q2) -> 409 historical_overdraft", r.s == 409 and r.code == "historical_overdraft", r)
ok("J28 historical_overdraft preserved balances, revisions, statements, activity", world(t, PIDS) == W0)
r = correct(A, q1["payment_id"], 1, 2200, q1["created_at"], "way bigger")
ok("J27 currently unaffordable increase (+1600 > ada 1500) -> 409 insufficient_funds (precedence over historical)", r.s == 409 and r.code == "insufficient_funds", r)
r = correct(A, q1["payment_id"], 1, 300, q1["created_at"], "smaller")
ok("J27 currently unaffordable decrease (bob holds 0, owes back 300) -> 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("J28 failures left everything unchanged", world(t, PIDS) == W0)
kF = k()
r1_ = correct(A, q1["payment_id"], 1, 2200, q1["created_at"], "too big", key=kF)
r2_ = correct(A, q1["payment_id"], 1, 700, q1["created_at"], "affordable", key=kF)
ok("J28 key that failed 409 insufficient_funds is reusable with a different body: 201 (first use), not 409 idempotency_key_reuse", r1_.s == 409 and r2_.s == 201 and r2_.j["revision"] == 2, (r1_, r2_))
ok("J26 increase 600->700 at original instant debits sender 100, credits receiver 100 (ada 1400, bob 100, cy 400); sum constant", [me(t[h])["balance"] for h in ("ada", "bob", "cy")] == [1400, 100, 400] and sum(me(t[h])["balance"] for h in t) == TOTAL)
kS = k()
r1_ = correct(A, q1["payment_id"], 1, 710, q1["created_at"], "stale", key=kS)
r2_ = correct(A, q1["payment_id"], 2, 710, q1["created_at"], "now current", key=kS)
ok("J28 key that failed 409 stale_revision is reusable (different body): 201", r1_.s == 409 and r1_.code == "stale_revision" and r2_.s == 201, (r1_, r2_))
# receiver historical overdraft: bob receives 600 more then ada shrinks q1 to 100 at t1 => bob's t3 payment (1000) impossible
call("POST", "/payments", {"to_handle": "bob", "amount": 1000}, token=D, key=k()) if me(D)["balance"] else None
# fresh scenario for the receiver-side rule
t, TOTAL = scn({"ada": 1000, "bob": 400, "cy": 0, "dee": 1000})
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
q1 = pay(A, "bob", 600).j; time.sleep(0.01)
q2 = pay(A, "cy", 400).j; time.sleep(0.01)
q3 = pay(B, "ada", 1000).j; time.sleep(0.01)
pay(D, "bob", 600)  # bob can afford the decrease now (600)
W0 = world(t, [q1["payment_id"]])
r = correct(A, q1["payment_id"], 1, 100, q1["created_at"], "shrink")
ok("J27 decrease affordable now (bob 600 >= 500) but bob would be -500 at his 1000 payment instant -> 409 historical_overdraft (receiver side)", r.s == 409 and r.code == "historical_overdraft", r)
ok("J28 receiver-side failure left everything unchanged", world(t, [q1["payment_id"]]) == W0)

# combined-effect boundary: bob opens 0
t, TOTAL = scn({"ada": 1000, "bob": 0, "cy": 0})
A, B, C = t["ada"], t["bob"], t["cy"]
a1 = pay(A, "bob", 100).j; time.sleep(0.01)
a2 = pay(B, "cy", 100).j; time.sleep(0.01)
a3 = pay(A, "bob", 100).j
r = correct(B, a2["payment_id"], 1, 100, a3["created_at"], "same instant as a3")
ok("J27 move outflow a2 (id lower) to a3's exact instant: bob never negative (a1 inflow earlier): 201", r.s == 201, r)
r = correct(A, a1["payment_id"], 1, 0, a1["created_at"], "drop a1")
ok("J27 boundary includes COMBINED effect of all movements at that instant: bob 0 before X, -100 (a2) and +100 (a3) at X => net 0 => accepted (sequential-by-id would be -100)", r.s == 201, r)
inst = P(a3["created_at"])
ok("J27 resulting views: bob 0 just before X, 0 at X; cy 100 at X; ada 1000-100(a3)=900", me_at(B, iso(inst - US)).j["balance"] == 0 and me_at(B, a3["created_at"]).j["balance"] == 0 and me_at(C, a3["created_at"]).j["balance"] == 100 and me_at(A, a3["created_at"]).j["balance"] == 900)
ok("J29 sum constant at X-1us, X, now", all(sum(me_at(t[h], x).j["balance"] for h in t) == TOTAL for x in (iso(inst - US), a3["created_at"], None) if x) and sum(me(t[h])["balance"] for h in t) == TOTAL)
# now remove the inflow: current bob balance 0 so debit unaffordable -> insufficient_funds takes precedence
r = correct(A, a3["payment_id"], 1, 0, a3["created_at"], "drop a3")
ok("J27 removing the instant's inflow: current bob balance 0 cannot give back 100 => 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
# a2 moved to before any funding: pure historical overdraft where current funds exist
t, TOTAL = scn({"ada": 1000, "bob": 0, "cy": 0})
A, B, C = t["ada"], t["bob"], t["cy"]
b1 = pay(A, "bob", 500).j; time.sleep(0.01)
b2 = pay(B, "cy", 500).j; time.sleep(0.01)
b3 = pay(A, "bob", 500).j  # bob has 500 now
W0 = world(t, [b2["payment_id"]])
r = correct(B, b2["payment_id"], 1, 500, iso(P(b1["created_at"]) - dt.timedelta(milliseconds=5)), "before funding")
ok("J27 effective_at moved before any funding: currently affordable (net 0 change) but bob -500 at that instant -> 409 historical_overdraft", r.s == 409 and r.code == "historical_overdraft", r)
ok("J28 unchanged after historical overdraft by effective_at move", world(t, [b2["payment_id"]]) == W0)
r = correct(B, b2["payment_id"], 1, 500, iso(P(b1["created_at"]) + US), "just after funding")
ok("J27 effective_at just after the funding payment: accepted", r.s == 201, r)

# =============================================================== C5 idempotency on corrections
t, TOTAL = scn({"ada": 5000, "bob": 1000, "cy": 300, "dee": 0})
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
x1 = pay(A, "bob", 1000).j
x2 = pay(A, "cy", 100).j
kk = k()
body = {"expected_revision": 1, "amount": 800, "effective_at": x1["created_at"], "reason": "idem"}
r1_ = call("POST", "/payments/%s/corrections" % x1["payment_id"], body, token=A, key=kk)
ok("J25 first use 201", r1_.s == 201 and r1_.j["revision"] == 2, r1_)
r_ = correct(A, x1["payment_id"], 2, 700, x1["created_at"], "newer")
r_ = correct(A, x1["payment_id"], 3, 600, x1["created_at"], "newer2")
bal_now = me(A)["balance"]
rr = call("POST", "/payments/%s/corrections" % x1["payment_id"], raw='{ "reason":"idem",  "amount":800.0, "effective_at":"%s", "expected_revision":1 }' % x1["created_at"], token=A, key=kk)
ok("J25 replay (reordered, whitespace, 800.0) after newer revisions -> 200 and the ORIGINAL revision-2 body", rr.s == 200 and rr.j == r1_.j, (rr, r1_))
ok("J25 replay moved no money and appended nothing", me(A)["balance"] == bal_now and len(revs(A, x1["payment_id"])) == 4)
for name, b2_ in [("amount", dict(body, amount=801)), ("effective_at", dict(body, effective_at=iso(P(x1["created_at"]) + US))), ("reason", dict(body, reason="other")), ("expected_revision", dict(body, expected_revision=2))]:
    rr = call("POST", "/payments/%s/corrections" % x1["payment_id"], b2_, token=A, key=kk)
    ok("J25 same key different %s -> 409 idempotency_key_reuse" % name, rr.s == 409 and rr.code == "idempotency_key_reuse", rr)
rr = call("POST", "/payments/%s/corrections" % x1["payment_id"], dict(body, amount=-5), token=A, key=kk)
ok("J25 claimed key beats validation: invalid body with a claimed key -> 409 idempotency_key_reuse", rr.s == 409 and rr.code == "idempotency_key_reuse", rr)
rr = call("POST", "/payments/%s/corrections" % x2["payment_id"], body, token=A, key=kk)
print("INFO same key+body on another payment path answered", rr.s, rr.code)
ok("J25 same key + same body on a DIFFERENT path is not a replay (not 200/409 reuse of the first)", not (rr.s == 200 and rr.j.get("payment_id") == x1["payment_id"]) and rr.code != "idempotency_key_reuse" or rr.s in (409, 422), rr)
# per-user scope: bob uses same key string on his own payment
y = call("POST", "/payments", {"to_handle": "ada", "amount": 50}, token=B, key=k()).j
rr = call("POST", "/payments/%s/corrections" % y["payment_id"], {"expected_revision": 1, "amount": 40, "effective_at": y["created_at"], "reason": "b"}, token=B, key=kk)
ok("J25 key scope is per user: bob using the same key string -> 201", rr.s == 201, rr)
# original payment idempotent responses unchanged
ok("J30 original payment still shows original amount in activity after 4 revisions", [p for p in call("GET", "/activity?limit=200", token=A).j["payments"] if p["payment_id"] == x1["payment_id"]][0]["amount"] == 1000)

# =============================================================== C7 revisions endpoint
ok("J31 sender 200 {'revisions':[...]}", (lambda r: r.s == 200 and set(r.j) == {"revisions"} and [x["revision"] for x in r.j["revisions"]] == [1, 2, 3, 4])(call("GET", "/payments/%s/revisions" % x1["payment_id"], token=A)))
ok("J31 receiver 200", call("GET", "/payments/%s/revisions" % x1["payment_id"], token=B).s == 200)
r = call("GET", "/payments/%s/revisions" % x1["payment_id"], token=C)
ok("J31 third party -> 404 not_found even though the payment is public (and visible in their feed)", r.s == 404 and r.code == "not_found" and x1["payment_id"] in [p["payment_id"] for p in call("GET", "/activity?limit=200", token=C).j["payments"]], r)
ok("J31 no token -> 401", call("GET", "/payments/%s/revisions" % x1["payment_id"]).s == 401)
ok("J31 unknown payment -> 404", call("GET", "/payments/p_zzz/revisions", token=A).s == 404)
ok("J20 unknown payment correction as stranger of existing: 403 not 404? (stranger on existing payment)", correct(D, x1["payment_id"], 4, 5, x1["created_at"]).s == 403)

# =============================================================== C16 payments created by requests are correctable; request record stays
t, TOTAL = scn({"ada": 5000, "bob": 1000})
A, B = t["ada"], t["bob"]
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 300}, token=B, key=k()).j
rp = call("POST", "/requests/%s/pay" % rq["request_id"], {}, token=A, key=k()).j
r = correct(A, rp["payment_id"], 1, 200, rp["created_at"], "request payment fix")
ok("J22 request-paid payment may be corrected (sender is payer): 201", r.s == 201, r)
rq2 = call("GET", "/requests", token=A).j["requests"][0]
ok("J30 request record unchanged by correction (status paid, amount 300, payment_id kept)", rq2["status"] == "paid" and rq2["amount"] == 300 and rq2["payment_id"] == rp["payment_id"], rq2)
done("t3_corr")
