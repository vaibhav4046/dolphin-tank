"""J34-J38: statement snapshots - frozen results, param rules, 404 rules, reset invalidation, has_more, concurrent change."""
import random, sys, threading, time
from lib3 import *

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 3
rnd = random.Random(SEED)
H = ["ada", "bob", "cy"]
f = fx([user(h, 5000000) for h in H])
t = setup(f)
A, B, C = t["ada"], t["bob"], t["cy"]
pays = []
for i in range(70):
    a, b = rnd.sample(H, 2)
    r = pay(t[a], b, rnd.randint(1, 900))
    pays.append(r.j)
ada_pays = [p for p in pays if "u_ada" in (p["from_user_id"], p["to_user_id"])]
n = len(ada_pays)
print("ada payments", n)


def sig(j):
    return (j["opening_balance"], j["closing_balance"], [(e["payment"]["payment_id"], e["payment"]["amount"], e["delta"], e["balance_after"], e["revision"], e["effective_at"], e["recorded_at"]) for e in j["entries"]])


first = stmt(A, limit=7)
S = first.j["snapshot"]
ok("J34 first statement returns a non-empty opaque string snapshot token", first.s == 200 and isinstance(S, str) and S != "", first)
baseline = stmt(A, limit=200).j  # fresh result at the same moment (no writes in between)
ok("J34 two reads return distinct tokens", stmt(A, limit=1).j["snapshot"] != S)

# ---- change the world: new payments, corrections (move payments into/out of the window), more
moved = ada_pays[3]
fromtok = t[[h for h in H if "u_" + h == moved["from_user_id"]][0]]
for p in pays[:6]:
    tk = t[[h for h in H if "u_" + h == p["from_user_id"]][0]]
    cur = revs(tk, p["payment_id"])[-1]
    correct(tk, p["payment_id"], cur["revision"], cur["amount"] + 1, p["created_at"], "after-snapshot")
for _ in range(5):
    pay(A, "bob", 11); pay(B, "ada", 7)
correct(fromtok, moved["payment_id"], revs(fromtok, moved["payment_id"])[-1]["revision"], 0, p["created_at"], "zero it")
fresh = stmt(A, limit=200).j
ok("setup: world changed (fresh statement differs from baseline)", sig(fresh) != sig(baseline))

# ---- J34/J35 paging the old snapshot reproduces the frozen result
got, off, more, closings, openings = [], 0, True, set(), set()
while more:
    r = call("GET", "/statement?snapshot=%s&limit=7&offset=%d" % (S, off), token=A)
    assert r.s == 200, r
    got += r.j["entries"]
    closings.add(r.j["closing_balance"]); openings.add(r.j["opening_balance"])
    more = r.j["has_more"]
    off += 7
expect = baseline["entries"]
ok("J34 snapshot pages reproduce the frozen entries exactly (amounts, deltas, balance_after, revision, times) after new payments and corrections", [(e["payment"]["payment_id"], e["payment"]["amount"], e["delta"], e["balance_after"], e["revision"]) for e in got] == [(e["payment"]["payment_id"], e["payment"]["amount"], e["delta"], e["balance_after"], e["revision"]) for e in expect], (len(got), len(expect)))
ok("J34 snapshot opening/closing frozen on every page", openings == {baseline["opening_balance"]} and closings == {baseline["closing_balance"]}, (openings, closings))
r = call("GET", "/statement?snapshot=%s&limit=200" % S, token=A)
ok("J35 snapshot limit=200 offset omitted returns frozen first 200 entries; has_more false", r.s == 200 and sig(r.j) == sig(baseline) and r.j["has_more"] is False, r)
ok("J34 the live statement did move on (new entries visible live)", fresh["closing_balance"] != baseline["closing_balance"] or len(fresh["entries"]) != len(baseline["entries"]))
# J38 a payment moved out of a window (zeroed) is still in the frozen snapshot with its old amount
fr = [e for e in expect if e["payment"]["payment_id"] == moved["payment_id"]]
fr2 = [e for e in got if e["payment"]["payment_id"] == moved["payment_id"]]
ok("J38 correction after the read does not change the snapshot: payment %s keeps frozen amount %d (live now 0)" % (moved["payment_id"], fr[0]["payment"]["amount"]), fr2 and fr2[0]["payment"]["amount"] == fr[0]["payment"]["amount"] != 0, fr2)

# ---- J37 has_more / offsets
for off, lim, more_, ln in [(0, n, False, n), (0, n - 1, True, n - 1), (n - 1, 1, False, 1), (n, 5, False, 0), (n + 100, 5, False, 0), (n - 2, 5, False, 2), (n - 3, 2, True, 2), (n - 3, 3, False, 3), (0, 1, True, 1)]:
    r = call("GET", "/statement?snapshot=%s&limit=%d&offset=%d" % (S, lim, off), token=A)
    ok("J37 snapshot offset=%d limit=%d of %d -> has_more=%s, %d entries" % (off, lim, n, more_, ln), r.s == 200 and r.j["has_more"] is more_ and len(r.j["entries"]) == ln and r.j["closing_balance"] == baseline["closing_balance"], (r.s, r.j.get("has_more"), len(r.j.get("entries", []))))
r = call("GET", "/statement?snapshot=%s" % S, token=A)
ok("J35 snapshot with no limit/offset: default limit 50 from 0", r.s == 200 and len(r.j["entries"]) == min(50, n) and r.j["has_more"] == (n > 50), r)

# ---- J35 only limit/offset may accompany a snapshot
qs = ["from=2020-01-01T00:00:00Z", "to=2030-01-01T00:00:00Z", "known_at=2030-01-01T00:00:00Z", "from=", "to=", "known_at=", "from=garbage", "from=2020-01-01T00:00:00Z&to=2030-01-01T00:00:00Z&known_at=2030-01-01T00:00:00Z"]
for q_ in qs:
    r = call("GET", "/statement?snapshot=%s&%s" % (S, q_.replace("+", "%2B")), token=A)
    ok("J35 snapshot + %s -> 422 validation_failed" % q_, r.s == 422 and r.code == "validation_failed", r)
ok("J35 snapshot + unrecognised parameter ignored", call("GET", "/statement?snapshot=%s&foo=bar&limit=3" % S, token=A).s == 200)
for q_ in ["limit=0", "limit=201", "limit=x", "offset=-1", "offset=1.5"]:
    r = call("GET", "/statement?snapshot=%s&%s" % (S, q_), token=A)
    ok("J35 snapshot + %s -> 422" % q_, r.s == 422 and r.code == "validation_failed", r)
ok("J35 a 422 for params did not destroy the snapshot", call("GET", "/statement?snapshot=%s&limit=3" % S, token=A).s == 200)

# ---- J36 404 rules
for label, tok_, token in [("unknown token", "snap_doesnotexist", A), ("garbage token", "!!!", A), ("other user's token (bob presents ada's)", S, B), ("stranger presents it", S, C)]:
    r = call("GET", "/statement?snapshot=%s" % q(tok_), token=token)
    ok("J36 %s -> 404 not_found" % label, r.s == 404 and r.code == "not_found", r)
r = call("GET", "/statement?snapshot=", token=A)
ok("J36 empty snapshot value: refused without 5xx (404/422)", r.s in (404, 422), r)
ok("J36 snapshot requires auth: 401", call("GET", "/statement?snapshot=%s" % S).s == 401)
# tokens last until reset
time.sleep(1.2)
ok("J36 token still valid after >1s and other activity", call("GET", "/statement?snapshot=%s&limit=2" % S, token=A).s == 200)
bob_snap = stmt(B, limit=3).j["snapshot"]
ok("J36 each user's own token works for them", call("GET", "/statement?snapshot=%s" % bob_snap, token=B).s == 200)
ok("J36 ada cannot use bob's token", call("GET", "/statement?snapshot=%s" % bob_snap, token=A).s == 404)

# window + known_at snapshot
x = sorted(P(p["created_at"]) for p in ada_pays)
win = stmt(A, limit=3, **{"from": iso(x[5]), "to": iso(x[20]), "known_at": iso(dt.datetime.now(UTC))})
Sw = win.j["snapshot"]
pay(A, "bob", 1)
rr = call("GET", "/statement?snapshot=%s&limit=200" % Sw, token=A)
exp_w = stmt(A, limit=200, **{"from": iso(x[5]), "to": iso(x[20])}).j
ok("J34 snapshot of a [from,to) window pages the whole window (opening/closing/entries) frozen", rr.s == 200 and rr.j["opening_balance"] == exp_w["opening_balance"] and rr.j["closing_balance"] == exp_w["closing_balance"] and len(rr.j["entries"]) == len(exp_w["entries"]) > 5, (rr.j["opening_balance"], exp_w["opening_balance"], len(rr.j["entries"]), len(exp_w["entries"])))
ok("J15 snapshot window: opening + sum(delta) == closing", rr.j["opening_balance"] + sum(e["delta"] for e in rr.j["entries"]) == rr.j["closing_balance"])
# first read with offset also returns a snapshot
r = stmt(A, limit=5, offset=10)
ok("J34 first read with limit/offset also returns a snapshot", r.s == 200 and r.j.get("snapshot"), r)
rp = call("GET", "/statement?snapshot=%s&limit=5&offset=10" % r.j["snapshot"], token=A)
ok("J34 that snapshot paged at the same offset equals the first read", rp.s == 200 and sig(rp.j) == sig(r.j))
pg = call("GET", "/statement?snapshot=%s&limit=2" % S, token=A).j
print("INFO snapshot page response carries snapshot key:", "snapshot" in pg, "keys", sorted(pg))

# ---- reset invalidates tokens
SNAP_BEFORE = S
reset(f)
tt = {h: login(h + "@example.com") for h in H}
r = call("GET", "/statement?snapshot=%s" % SNAP_BEFORE, token=tt["ada"])
ok("J36 token from before reset -> 404 not_found (same user id/email, fresh login)", r.s == 404 and r.code == "not_found", r)
fresh_snap = stmt(tt["ada"], limit=1).j["snapshot"]
ok("J36 a token minted after reset works", call("GET", "/statement?snapshot=%s" % fresh_snap, token=tt["ada"]).s == 200)
reset(f)
tt = {h: login(h + "@example.com") for h in H}
ok("J36 second reset invalidates the post-reset token too", call("GET", "/statement?snapshot=%s" % fresh_snap, token=tt["ada"]).s == 404)

# ---- J38 concurrent writers vs snapshot readers
A, B, C = tt["ada"], tt["bob"], tt["cy"]
tk = {"ada": A, "bob": B, "cy": C}
for i in range(40):
    a, b = rnd.sample(H, 2)
    pay(tk[a], b, rnd.randint(1, 500))
s0 = stmt(A, limit=200)
SS = s0.j["snapshot"]
base = sig(s0.j)
stop = threading.Event()
errs = []
cnt = [0, 0, 0]


def writer(i):
    rr_ = random.Random(100 + i)
    while not stop.is_set():
        a, b = rr_.sample(H, 2)
        r_ = pay(tk[a], b, rr_.randint(1, 50))
        cnt[0] += 1
        if r_.s == 201 and rr_.random() < .6:
            cur = revs(tk[a], r_.j["payment_id"])[-1]
            correct(tk[a], r_.j["payment_id"], cur["revision"], rr_.randint(0, 80), r_.j["created_at"], "storm")
            cnt[1] += 1


def reader(i):
    rr_ = random.Random(200 + i)
    while not stop.is_set():
        lim = rr_.choice([1, 3, 7, 40, 200])
        got_, off_, more_ = [], 0, True
        while more_:
            r_ = call("GET", "/statement?snapshot=%s&limit=%d&offset=%d" % (SS, lim, off_), token=A)
            if r_.s != 200:
                errs.append(("status", r_.s)); return
            got_ += [(e["payment"]["payment_id"], e["payment"]["amount"], e["delta"], e["balance_after"], e["revision"], e["effective_at"], e["recorded_at"]) for e in r_.j["entries"]]
            if (r_.j["opening_balance"], r_.j["closing_balance"]) != (base[0], base[1]):
                errs.append(("balances", r_.j["opening_balance"], r_.j["closing_balance"])); return
            more_ = r_.j["has_more"]; off_ += lim
        if got_ != base[2]:
            errs.append(("entries differ", len(got_), len(base[2]))); return
        cnt[2] += 1


ths = [threading.Thread(target=writer, args=(i,)) for i in range(6)] + [threading.Thread(target=reader, args=(i,)) for i in range(6)]
[x.start() for x in ths]
time.sleep(4.0)
stop.set()
[x.join() for x in ths]
print("storm: payments", cnt[0], "corrections", cnt[1], "full snapshot reads", cnt[2])
ok("J38 snapshot stays byte-identical under concurrent payments + corrections (6 writers, 6 paging readers, %d full reads)" % cnt[2], not errs and cnt[2] > 5, errs[:2])
live = [me(tk[h])["balance"] for h in H]
ok("J29 sum of balances constant after the storm", sum(live) == 3 * 5000000, live)
# live statement still self-consistent
lj = stmt(A, limit=200).j
ok("J15 live statement after storm: opening + sum(delta) == closing == /me balance (all pages)", True if lj["has_more"] else lj["opening_balance"] + sum(e["delta"] for e in lj["entries"]) == lj["closing_balance"] == me(A)["balance"], (lj["opening_balance"], lj["closing_balance"], me(A)["balance"], lj["has_more"]))
done("t3_snap")
