"""H05 export/import with holds: needs two containers. PF = source, PFD = destination (fresh container)."""
import threading, time, json
from lib import *

SRC = (HOST, PORT)
f = fx([user("ada", 20000), user("bob", 2500), user("cy", 5000), user("op", 0)], ops=["u_op"])
f["authorization_ttl_seconds"] = 600
t = setup(f)
A, B, C, OP = t["ada"], t["bob"], t["cy"], t["op"]
TOTAL = 27500

# build rich state on the source
ka1, ka2 = k(), k()
a1 = call("POST", "/authorizations", {"to_handle": "bob", "amount": 3000, "note": "open-hold", "visibility": "private"}, token=A, key=ka1).j
a2 = call("POST", "/authorizations", {"to_handle": "cy", "amount": 2000, "note": "partial"}, token=A, key=ka2).j
kc2 = k(); c2 = call("POST", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 700, "final": False}, token=C, key=kc2).j
a3 = authorize(A, "bob", 1500).j; kc3 = k()
c3 = call("POST", "/authorizations/%s/capture" % a3["authorization_id"], {"amount": 1000}, token=B, key=kc3).j
a4 = authorize(A, "bob", 800).j; void(A, a4["authorization_id"])
# short-lived hold on a second fixture? use ttl via reset is global; instead make a long hold and later compare expires_at echo
failed_key = k(); call("POST", "/authorizations", {"to_handle": "bob", "amount": 10**9}, token=A, key=failed_key)
pay_key = k(); pr = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=A, key=pay_key).j
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, token=B, key=k()).j

def snap(tok_a, tok_b, tok_c, base=None):
    g = lambda p, tk: call("GET", p, token=tk, base=base)
    return {"me_a": g("/me", tok_a).j, "me_b": g("/me", tok_b).j, "me_c": g("/me", tok_c).j,
            "authz_a": g("/authorizations?limit=200", tok_a).j, "authz_b": g("/authorizations?limit=200", tok_b).j,
            "feed_a": g("/activity?limit=200", tok_a).j, "reqs": g("/requests", tok_a).j}

before = snap(A, B, C)
ex = call("GET", "/_test/export")
ok("H05 export 200 track/format_version/state", ex.s == 200 and ex.j.get("track") == "pocketful" and ex.j.get("format_version") == 1 and isinstance(ex.j.get("state"), dict), ex.s)
ex2 = call("GET", "/_test/export")
ok("H05 export is read-only: two consecutive exports identical", ex.j == ex2.j)
ok("H05 export of unchanged state mutates nothing observable", snap(A, B, C) == before)
body = ex.b

DST = (DST[0], DST[1])
def dcall(*a, **kw):
    kw["base"] = DST
    return call(*a, **kw)

r = dcall("POST", "/_test/import", raw=body)
ok("H05 import into FRESH container 204", r.s == 204, r)
after = snap(A, B, C, base=DST)
ok("H05 source tokens valid on destination; /me identical (balance,total,available,held)", after["me_a"] == before["me_a"] and after["me_b"] == before["me_b"] and after["me_c"] == before["me_c"], (after["me_a"], before["me_a"]))
ok("H05 authorizations lists identical JSON values (ids, statuses, captured, payment_ids, expires_at, created_at)", after["authz_a"] == before["authz_a"] and after["authz_b"] == before["authz_b"], (after["authz_a"], before["authz_a"]))
ok("H05 activity + requests identical", after["feed_a"] == before["feed_a"] and after["reqs"] == before["reqs"])
ok("H05 imported holds counted: ada held == 3000 + 1300", after["me_a"]["held"] == 3000 + 1300 and after["me_a"]["available"] == 20000 - 700 - 1000 - 100 - 3000 - 1300 and after["me_a"]["total"] == 20000 - 700 - 1000 - 100, after["me_a"])
# replays on destination
rr = dcall("POST", "/authorizations", {"to_handle": "bob", "amount": 3000, "note": "open-hold", "visibility": "private"}, token=A, key=ka1)
ok("H05 authorize replay on destination: 200 identical original body, no new hold", rr.s == 200 and rr.j == a1 and len(dcall("GET", "/authorizations?limit=200", token=A).j["authorizations"]) == len(before["authz_a"]["authorizations"]), rr)
rr = dcall("POST", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 700, "final": False}, token=C, key=kc2)
ok("H05 capture replay on destination: 200 identical payment, money not moved twice", rr.s == 200 and rr.j == c2 and dcall("GET", "/me", token=C).j == before["me_c"], rr)
rr = dcall("POST", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 701, "final": False}, token=C, key=kc2)
ok("H05 same key different body on destination: 409 idempotency_key_reuse", rr.s == 409 and rr.code == "idempotency_key_reuse", rr)
rr = dcall("POST", "/authorizations/%s/capture" % a3["authorization_id"], {"amount": 1000}, token=B, key=kc3)
ok("H05 capture replay of CLOSED hold on destination: 200 original", rr.s == 200 and rr.j == c3, rr)
rr = dcall("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=A, key=pay_key)
ok("H05 stage-1 payment replay survives import: 200 original", rr.s == 200 and rr.j == pr, rr)
rr = dcall("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, token=A, key=failed_key)
ok("H05 failed (409) key remains reusable after import: 201", rr.s == 201, rr)
# continue operating on imported state
rc = dcall("POST", "/authorizations/%s/capture" % a1["authorization_id"], {"amount": 1000, "final": False}, token=B, key=k())
ok("H05 capture of imported OPEN hold works; remaining 2000", rc.s == 201 and dcall("GET", "/authorizations?limit=200", token=A).j["authorizations"][-1] is not None, rc)
x = [a for a in dcall("GET", "/authorizations?limit=200", token=B).j["authorizations"] if a["authorization_id"] == a1["authorization_id"]][0]
ok("H05 imported hold partially captured on destination: captured 1000 remaining 2000, still open", (x["captured_amount"], x["remaining_amount"], x["status"]) == (1000, 2000, "open"), x)
rv = dcall("POST", "/authorizations/%s/void" % a2["authorization_id"], {}, token=A)
ok("H05 void of imported partially captured hold: voided, remainder released, payment_ids kept", rv.s == 200 and rv.j["status"] == "voided" and rv.j["payment_ids"] == [c2["payment_id"]] and rv.j["captured_amount"] == 700, rv)
rs = dcall("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 100}]}, token=OP, key=k())
ok("H05 operator permission survived import", rs.s == 201, rs)
new = dcall("POST", "/authorizations", {"to_handle": "cy", "amount": 100}, token=A, key=k())
ok("H05 new authorization on destination: fresh id not colliding with imported ids", new.s == 201 and new.j["authorization_id"] not in {a["authorization_id"] for a in before["authz_a"]["authorizations"]}, new)
tot = sum(dcall("GET", "/me", token=x_).j["total"] for x_ in (A, B, C, OP))
ok("A01 conservation on destination after continuing", tot == TOTAL, tot)

# repeated import is replacement, not merge
r = dcall("POST", "/_test/import", raw=body)
after2 = snap(A, B, C, base=DST)
ok("H05 re-import restores exported state exactly (no duplication)", r.s == 204 and after2 == before)
# garbage imports leave destination untouched
for desc, raw_ in (("not json", "{nope"), ("wrong track", json.dumps(dict(ex.j, track="other"))), ("wrong version", json.dumps(dict(ex.j, format_version=2))),
                   ("missing state", json.dumps({"track": "pocketful", "format_version": 1})), ("state not object", json.dumps({"track": "pocketful", "format_version": 1, "state": 5})),
                   ("empty state", json.dumps({"track": "pocketful", "format_version": 1, "state": {}}))):
    r = dcall("POST", "/_test/import", raw=raw_)
    ok("H05 import %s -> 4xx (400/422), destination unchanged" % desc, r.s in (400, 422) and snap(A, B, C, base=DST) == before, r)
# corrupt the hold set inside a valid state: must not 5xx; if 204 invariants must hold
st = json.loads(body)
def walk_find_auth(o, path=""):
    out = []
    if isinstance(o, dict):
        for kk, vv in o.items():
            if "author" in kk.lower(): out.append(path + "/" + kk)
            out += walk_find_auth(vv, path + "/" + kk)
    elif isinstance(o, list):
        for i, vv in enumerate(o): out += walk_find_auth(vv, path + "/%d" % i)
    return out
print("INFO export authorization-related state paths:", walk_find_auth(st)[:12])

# ---------- atomic export under concurrent writers: invariants in every snapshot (checked by importing into the destination)
t = setup(f)  # source reset
stop = threading.Event(); errs = []
def writer(i):
    r_ = __import__("random").Random(i)
    ids = []
    while not stop.is_set():
        try:
            op = r_.choice(["auth", "cap", "pay", "void"])
            if op == "auth":
                r = authorize(t["ada"], "bob", r_.randint(1, 400))
                if r.s == 201: ids.append(r.j["authorization_id"])
            elif op == "pay": pay(t["ada"], "bob", r_.randint(1, 200))
            elif ids and op == "cap": capture(t["bob"], r_.choice(ids), amount=r_.randint(1, 150), final=False)
            elif ids: void(t["ada"], r_.choice(ids))
        except Exception as e:
            errs.append(repr(e))
ths = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
[x.start() for x in ths]
snaps = []
for i in range(8):
    snaps.append(call("GET", "/_test/export").b); time.sleep(0.15)
stop.set(); [x.join() for x in ths]
ok("H05 writers ran without errors", not errs, errs[:2])
bad = []
for i, sb in enumerate(snaps):
    r = dcall("POST", "/_test/import", raw=sb)
    if r.s != 204: bad.append((i, "import", r.s)); continue
    ms = {h: dcall("GET", "/me", token=t[h]).j for h in ("ada", "bob", "cy", "op")}
    if sum(m["total"] for m in ms.values()) != TOTAL: bad.append((i, "sum", {h: m["total"] for h, m in ms.items()}))
    if not all(inv(m) for m in ms.values()): bad.append((i, "inv", ms))
    L = dcall("GET", "/authorizations?limit=200", token=t["bob"]).j["authorizations"]
    held_sum = sum(a["remaining_amount"] for a in L if a["status"] == "open")
    if held_sum != ms["ada"]["held"]: bad.append((i, "held!=open remaining", held_sum, ms["ada"]))
    if any(a["captured_amount"] > a["amount"] for a in L): bad.append((i, "captured>amount"))
ok("H05 8 exports taken under 12 concurrent writers: each is a consistent snapshot (sum constant, invariants, held == open remainders)", not bad, bad[:3])

# ---------- expiry is absolute across export/import
f2 = fx([user("ada", 10000), user("bob", 0)]); f2["authorization_ttl_seconds"] = 3
reset(f2); ta = login("ada@example.com"); tb = login("bob@example.com")
ra = authorize(ta, "bob", 4000); ex = call("GET", "/_test/export").b
sleep_until(ra.j["expires_at"], 0.5)
dcall("POST", "/_test/import", raw=ex)
x = [a for a in dcall("GET", "/authorizations", token=tb).j["authorizations"]][0]
ok("H05 imported open hold whose deadline passed meanwhile is expired immediately (expires_at not regenerated)", x["status"] == "expired" and x["expires_at"] == ra.j["expires_at"] and dcall("GET", "/me", token=ta).j["held"] == 0, x)
done("s2_export")
