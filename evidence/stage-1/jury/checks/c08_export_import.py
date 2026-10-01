"""J42, J69-J77, J87, J88: export/import round trip into a FRESH container (PFD, default 127.0.0.1:18081), garbage imports,
replacement semantics, reset clears imported state, export atomic under concurrent writers, import racing writers, size/time."""
import json, random, threading, time
from lib import *

D = DST


def dc(m, p, body=None, **kw):
    return call(m, p, body, base=D, **kw)


def allpages(path, key, tok, base=None):
    out, off = [], 0
    while True:
        j = call("GET", "%s?limit=200&offset=%d" % (path, off), token=tok, base=base).j
        out += j[key]
        if not j["has_more"]:
            return out
        off += 200


def snap(tokens, base=None):
    return {n: (call("GET", "/me", token=tk, base=base).j, allpages("/activity", "payments", tk, base), allpages("/requests", "requests", tk, base)) for n, tk in tokens.items()}


F = fx([user("ada", 10000), user("bob", 2500), user("cy", 0), user("dee", 5000), user("op", 0)], ops=["u_op"],
       payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                 {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "hush", "visibility": "private"}],
       requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                 {"id": "rq_2", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 5, "note": "d", "status": "declined"}])
assert call("POST", "/_test/reset", F).s == 204
T = {u["handle"]: login(u["email"]) for u in F["users"]}
assert call("GET", "/health", base=D).s == 200
ok("destination is fresh: has no ada account", dc("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).s == 401)
NT = call("POST", "/auth/signup", {"email": "newbie@x.com", "password": "password1", "display_name": "Nb"}).j["token"]
L1, L2 = login("ada@example.com"), login("ada@example.com")
TOK = dict(T, newbie=NT, ada_l1=L1, ada_l2=L2)
rec = []


def w(method, path, tok, body, key, expect=None):
    r = call(method, path, body, token=tok, key=key)
    rec.append((method, path, tok, body, key, r.s, r.j))
    if expect:
        assert r.s == expect, (path, r)
    return r


NOTE = "héllo \U0001F600 <&>  \"q\" "
w("POST", "/payments", T["ada"], {"to_handle": "bob", "amount": 100, "note": NOTE}, "K1", 201)
w("POST", "/payments", T["ada"], {"to_handle": "cy", "amount": 50, "visibility": "private"}, "K2", 201)
w("POST", "/requests", T["bob"], {"payer_handle": "ada", "amount": 300}, "K3", 201)
w("POST", "/requests/rq_1/pay", T["ada"], {"visibility": "private"}, "K4", 201)
r5 = w("POST", "/requests", T["cy"], {"payer_handle": "dee", "amount": 40}, "K5", 201)
call("POST", "/requests/%s/cancel" % r5.j["request_id"], {}, token=T["cy"])
r5b = call("POST", "/requests", {"payer_handle": "dee", "amount": 10}, token=T["bob"], key=k())
call("POST", "/requests/%s/decline" % r5b.j["request_id"], {}, token=T["dee"])
w("POST", "/splits", T["ada"], {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "sp"}, "K6", 201)
w("POST", "/settlements", T["op"], {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10, "note": "a"},
                                                   {"from_handle": "bob", "to_handle": "cy", "amount": 5, "visibility": "private"}]}, "K7", 201)
w("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 10 ** 6}, "K8", 409)
w("POST", "/payments", T["dee"], {"to_handle": "nobody", "amount": 5}, "K9", 404)
w("POST", "/payments", T["dee"], {"to_handle": "bob", "amount": 0}, "K10", 422)
SIG = snap(TOK)

ex = call("GET", "/_test/export")
E = ex.j
ok("export 200 {track:'pocketful',format_version:1,state:object}", ex.s == 200 and E["track"] == "pocketful" and E["format_version"] == 1 and isinstance(E["state"], dict) and set(E) >= {"track", "format_version", "state"}, (ex.s, list(E or {})))
ok("export is read-only and repeatable: two exports identical as JSON, state unchanged", call("GET", "/_test/export").j == E and snap(TOK) == SIG)
ok("export has no plaintext passwords", b"correct horse" not in ex.b and b"password1" not in ex.b)
print("OBS export size bytes:", len(ex.b), "state keys:", sorted(E["state"])[:12])

imp = dc("POST", "/_test/import", raw=ex.b)
ok("import unchanged export into fresh container -> 204 empty", imp.s == 204 and imp.b == b"", imp)
DS = snap(TOK, D)
for n in SIG:
    ok("dst %s: /me, feed, requests identical to source (tokens, ids, timestamps, visibility)" % n, DS[n] == SIG[n], (n,))
ok("hashed-password logins work on dst (seeded + signup user)", all(dc("POST", "/auth/login", {"email": e, "password": p}).s == 200 for e, p in (("ada@example.com", "correct horse"), ("newbie@x.com", "password1"), ("op@example.com", "correct horse")))
   and dc("POST", "/auth/login", {"email": "ada@example.com", "password": "nope nope"}).s == 401)
ok("login on dst returns the same user_id", dc("POST", "/auth/login", {"email": "newbie@x.com", "password": "password1"}).j["user_id"] == call("GET", "/me", token=NT).j["user_id"])
ok("dst old tokens (incl. 2 extra ada sessions) all valid", all(dc("GET", "/me", token=x).s == 200 for x in TOK.values()))

# replays on dst
okay = 0
for method, path, tok, body, key, st, rj in rec:
    r = dc(method, path, body, token=tok, key=key)
    if st == 201:
        ok("dst replay %s %s key %s -> 200 original body" % (method, path, key), r.s == 200 and r.j == rj, (r.s, r.b[:200]))
    else:
        print("OBS dst failed-key %s (orig %d) first-use ->" % (key, st), r.s, r.code)
        ok("dst failed-key %s is treated as first use (same error again, not 200/409-reuse)" % key, r.s == st, (r.s, r.b[:200]))
ok("replays changed nothing", snap(TOK, D) == SIG)
ok("dst same key + different body -> 409 idempotency_key_reuse", (lambda r: r.s == 409 and r.code == "idempotency_key_reuse")(dc("POST", "/payments", {"to_handle": "bob", "amount": 101, "note": NOTE}, token=T["ada"], key="K1")))
r = dc("POST", "/payments", {"to_handle": "bob", "amount": 20}, token=T["dee"], key="K8")
ok("dst failed key K8 reusable with a valid body -> 201", r.s == 201, r)
r = dc("POST", "/payments", {"to_handle": "bob", "amount": 21}, token=T["dee"], key="K9")
ok("dst failed key K9 reusable -> 201", r.s == 201, r)
# operator permission and ids
r = dc("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, token=T["op"], key=k())
ok("dst operator permission preserved (settlement 201)", r.s == 201, r)
ok("dst non-operator settlement -> 403", dc("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, token=T["ada"], key=k()).s == 403)
ok("dst operator sees none of others' requests", dc("GET", "/requests", token=T["op"]).j["requests"] == [])
seen = set()
for n, (m_, f_, q_) in SIG.items():
    seen |= {p["payment_id"] for p in f_} | {x["request_id"] for x in q_} | {m_["user_id"]}
newp = dc("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=T["ada"], key=k()).j["payment_id"]
newq = dc("POST", "/requests", {"payer_handle": "cy", "amount": 1}, token=T["ada"], key=k()).j["request_id"]
news = dc("POST", "/splits", {"amount": 3, "participant_handles": ["ada", "cy"]}, token=T["ada"], key=k()).j
newu = dc("POST", "/auth/signup", {"email": "later@x.com", "password": "password1", "display_name": "L"}).j["user_id"]
ok("ids generated after import never collide with imported ids", newp not in seen and newq not in seen and news["requests"][0]["request_id"] not in seen and newu not in seen, (newp, newq, newu))

# repeat import restores exactly, no duplicates; import is replacement
for i in range(3):
    imp = dc("POST", "/_test/import", raw=ex.b)
    ok("re-import #%d -> 204 and state equals exported snapshot (mutations discarded, nothing duplicated)" % i, imp.s == 204 and snap(TOK, D) == SIG)
    dc("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=T["ada"], key=k())
    dc("POST", "/auth/signup", {"email": "tmp%d@x.com" % i, "password": "password1", "display_name": "L"})
dc("POST", "/_test/import", raw=ex.b)
ok("after re-import tmp users gone", dc("POST", "/auth/login", {"email": "tmp2@x.com", "password": "password1"}).s == 401 and dc("POST", "/auth/login", {"email": "later@x.com", "password": "password1"}).s == 401)
ok("replay K1 still 200 after repeated imports", dc("POST", "/payments", rec[0][3], token=T["ada"], key="K1").s == 200)

# import removes previous destination data and credentials
assert dc("POST", "/_test/reset", fx([user("zed", 777), user("ada", 1, uid="u_zzz")])).s == 204
Z = dc("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}).j["token"]
zk = k()
dc("POST", "/payments", {"to_handle": "ada", "amount": 7}, token=Z, key=zk)
ok("dst import over other state: 204", dc("POST", "/_test/import", raw=ex.b).s == 204)
ok("  previous destination tokens/credentials gone", dc("GET", "/me", token=Z).s == 401 and dc("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}).s == 401)
ok("  previous data gone, exported state fully restored", snap(TOK, D) == SIG)
ok("  previous idempotency key gone (unknown to imported state)", dc("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=T["ada"], key=zk).s == 201)
assert dc("POST", "/_test/import", raw=ex.b).s == 204

# garbage imports leave state intact
base_snap = snap(TOK, D)
good = E["state"]
cases = [("invalid JSON", "{bad", 400), ("empty body", "", 400), ("array", "[]", 422), ("null", "null", 422), ("{}", "{}", 422),
         ("no state", json.dumps({"track": "pocketful", "format_version": 1}), 422), ("no track", json.dumps({"format_version": 1, "state": good}), 422),
         ("no version", json.dumps({"track": "pocketful", "state": good}), 422), ("wrong track", json.dumps({"track": "other", "format_version": 1, "state": good}), 422),
         ("version 2", json.dumps({"track": "pocketful", "format_version": 2, "state": good}), 422), ("version '1'", json.dumps({"track": "pocketful", "format_version": "1", "state": good}), 422),
         ("state []", json.dumps({"track": "pocketful", "format_version": 1, "state": []}), 422), ("state string", json.dumps({"track": "pocketful", "format_version": 1, "state": "x"}), 422),
         ("state {}", json.dumps({"track": "pocketful", "format_version": 1, "state": {}}), 422), ("state null", json.dumps({"track": "pocketful", "format_version": 1, "state": None}), 422),
         ("state {x:1}", json.dumps({"track": "pocketful", "format_version": 1, "state": {"x": 1}}), 422)]
for nm, raw, st in cases:
    r = dc("POST", "/_test/import", raw=raw)
    ok("garbage import %s -> %d and state intact" % (nm, st), r.s == st and (r.code in ("validation_failed", "malformed_request")) and snap(TOK, D) == base_snap, (r.s, r.b[:200]))
for key_ in sorted(good):
    st2 = {kk: vv for kk, vv in good.items() if kk != key_}
    r = dc("POST", "/_test/import", raw=json.dumps({"track": "pocketful", "format_version": 1, "state": st2}))
    print("OBS import state minus key %r -> %s %s" % (key_, r.s, r.code))
    if r.s == 204:
        dc("POST", "/_test/import", raw=ex.b)
    else:
        ok("state missing %r rejected 422 and state intact" % key_, r.s == 422 and snap(TOK, D) == base_snap, (r.s, r.b[:160]))
        if snap(TOK, D) != base_snap:
            dc("POST", "/_test/import", raw=ex.b)

# blind type-corruption fuzz of the opaque state: never 5xx; accepted states must leave a serving system
fz = {"5xx": 0, "204": 0, "rej": 0}
for key_ in sorted(good):
    for badv in (None, "x", [], {}, 5, -1, True):
        if good[key_] == badv and type(good[key_]) is type(badv):
            continue
        st2 = dict(good); st2[key_] = badv
        r = dc("POST", "/_test/import", raw=json.dumps({"track": "pocketful", "format_version": 1, "state": st2}))
        if r.s >= 500:
            fz["5xx"] += 1
        elif r.s == 204:
            fz["204"] += 1
            probes = [dc("GET", "/me", token=tk).s for tk in list(T.values())[:2]] + [dc("GET", "/_test/export").s, dc("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=T["ada"], key=k()).s]
            if any(p >= 500 for p in probes):
                fz["5xx"] += 1
                print("  5xx after accepting corrupt %r=%r: %s" % (key_, badv, probes))
            dc("POST", "/_test/import", raw=ex.b)
        else:
            fz["rej"] += 1
            if snap(TOK, D) != base_snap:
                ok("rejected corrupt import %r=%r left state intact" % (key_, badv), False)
                dc("POST", "/_test/import", raw=ex.b)
print("OBS state-corruption fuzz:", fz)
ok("blind corruption of opaque state never produces 5xx, rejected imports never change state", fz["5xx"] == 0, fz)
dc("POST", "/_test/import", raw=ex.b)

# reset clears imported state
assert dc("POST", "/_test/reset", fx()).s == 204
ok("reset after import clears imported state (old tokens 401, newbie gone, keys reusable)", dc("GET", "/me", token=NT).s == 401 and dc("POST", "/auth/login", {"email": "newbie@x.com", "password": "password1"}).s == 401)
assert dc("POST", "/_test/import", raw=ex.b).s == 204
assert dc("POST", "/_test/reset", fx()).s == 204
T2 = {u["handle"]: dc("POST", "/auth/login", {"email": u["email"], "password": u["password"]}).j["token"] for u in fx()["users"]}
r = call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": NOTE}, token=T2["ada"], key="K1", base=D)
ok("reset after import: key K1 of imported state is unknown (201)", r.s == 201, r)

# import into the SOURCE after it moved on restores Σ
call("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=T["ada"], key=k())
ok("import into source after more writes restores exported state", call("POST", "/_test/import", raw=ex.b).s == 204 and snap(TOK) == SIG)

# ---- export atomic under concurrent writers: each snapshot importable, ledger == balances, sum == total
U4 = [user("ada", 100000), user("bob", 0), user("cy", 0), user("dee", 0)]
B0 = {u["handle"]: u["balance"] for u in U4}
t4 = setup(fx(U4))
stop = threading.Event(); cnt = [0]
ring = ["ada", "bob", "cy", "dee"]


def writer(i):
    rnd = random.Random(i)
    for n in range(120):
        if stop.is_set():
            return
        a = rnd.choice(ring); b = rnd.choice([x for x in ring if x != a])
        r = call("POST", "/payments", {"to_handle": b, "amount": rnd.randint(1, 5)}, token=t4[a], key=k())
        if n % 6 == 0:
            q = call("POST", "/requests", {"payer_handle": b, "amount": rnd.randint(1, 9)}, token=t4[a], key=k())
            if q.s == 201:
                call("POST", "/requests/%s/pay" % q.j["request_id"], {}, token=t4[b], key=k())
        if n % 10 == 0:
            call("POST", "/splits", {"amount": 10, "participant_handles": [a, b]}, token=t4[a], key=k())
        cnt[0] += 1


ws = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
[x.start() for x in ws]
snaps = []
while any(x.is_alive() for x in ws) and len(snaps) < 25:
    r = call("GET", "/_test/export")
    assert r.s == 200, r
    snaps.append(r.b)
    time.sleep(0.05)
stop.set(); [x.join() for x in ws]
bad = 0
for i, raw in enumerate(snaps):
    assert dc("POST", "/_test/import", raw=raw).s == 204
    feed = allpages("/activity", "payments", t4["ada"], D)
    derived = dict(B0)
    for p in feed:
        derived[p["from_handle"]] -= p["amount"]; derived[p["to_handle"]] += p["amount"]
    actual = {h: call("GET", "/me", token=t4[h], base=D).j["balance"] for h in ring}
    if actual != derived or sum(actual.values()) != 100000 or min(actual.values()) < 0:
        bad += 1
        print("  torn snapshot", i, actual, derived)
ok("export atomic: %d snapshots taken during %d concurrent write ops each importable; balances == initial +/- ledger; sum == total; none negative" % (len(snaps), cnt[0]), bad == 0 and len(snaps) >= 3, (bad, len(snaps)))

# ---- writers racing import on destination: no 5xx, final state == exported
assert call("POST", "/_test/reset", F).s == 204
T = {u["handle"]: login(u["email"]) for u in F["users"]}
call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=T["ada"], key=k())
ex2 = call("GET", "/_test/export")
assert dc("POST", "/_test/import", raw=ex2.b).s == 204
base2 = snap(T, D)
stop = threading.Event(); odd = []


def dw(i):
    while not stop.is_set():
        r = dc("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=T["ada"], key=k())
        if r.s not in (201, 409, 401):
            odd.append((r.s, r.code))


ws = [threading.Thread(target=dw, args=(i,)) for i in range(8)]
[x.start() for x in ws]
st_ = []
for i in range(8):
    st_.append(dc("POST", "/_test/import", raw=ex2.b).s)
stop.set(); [x.join() for x in ws]
ok("import racing 8 writers: all imports 204, no unexpected statuses/5xx", st_ == [204] * 8 and not odd, (st_, odd[:5]))
assert dc("POST", "/_test/import", raw=ex2.b).s == 204
ok("after the race, one more import yields exactly the exported state", snap(T, D) == base2)

# ---- size / time: 3000 payments among 50 users
us = [user("m%02d" % i, 10 ** 6) for i in range(50)]
tm = setup(fx(us))
hs = [u["handle"] for u in us]


def bulk(i):
    rnd = random.Random(i)
    for _ in range(94):
        a = rnd.choice(hs); b = rnd.choice([x for x in hs if x != a])
        call("POST", "/payments", {"to_handle": b, "amount": rnd.randint(1, 50), "visibility": rnd.choice(["public", "private"])}, token=tm[a], key=k())


ths = [threading.Thread(target=bulk, args=(i,)) for i in range(32)]
[x.start() for x in ths]; [x.join() for x in ths]
t0 = time.time(); big = call("GET", "/_test/export", timeout=30); te = time.time() - t0
t0 = time.time(); bi = dc("POST", "/_test/import", raw=big.b, timeout=30); ti = time.time() - t0
ok("large state (%d bytes): export %.2fs, import %.2fs both < 10s" % (len(big.b), te, ti), big.s == 200 and bi.s == 204 and te < 10 and ti < 10, (te, ti))
ok("large state round trip: /me identical for all 50 users", all(call("GET", "/me", token=tm[h]).j == call("GET", "/me", token=tm[h], base=D).j for h in hs))
ok("large state: conservation on destination", sum(call("GET", "/me", token=tm[h], base=D).j["balance"] for h in hs) == 50 * 10 ** 6)

done("c08_export_import")
