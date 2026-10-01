"""A08 E02 E10 G01-G07: idempotency on POST /authorizations and POST /authorizations/{id}/capture (incl. concurrent)."""
import json
from lib import *

f = fx([user("ada", 100000), user("bob", 2500), user("cy", 5000), user("dee", 5000)])
t = setup(f)
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
TOTAL = 112500

def held(): return me(A)["held"]

# ---------- authorize
key = k()
body = {"to_handle": "bob", "amount": 2000, "note": "n", "visibility": "private"}
r1 = call("POST", "/authorizations", body, token=A, key=key)
ok("G01 first use 201", r1.s == 201, r1)
r2 = call("POST", "/authorizations", raw='{"visibility":  "private", "note":"n",\n "amount":2000.0,"to_handle":"bob"}', token=A, key=key)
ok("G01 replay (reordered keys, whitespace, 2000.0) 200 identical JSON value", r2.s == 200 and r2.j == r1.j, (r1, r2))
ok("G01 one hold only", held() == 2000 and len(authz(A)["authorizations"]) == 1)
r3 = call("POST", "/authorizations", dict(body, amount=2001), token=A, key=key)
ok("G02 same key different amount 409 idempotency_key_reuse", r3.s == 409 and r3.code == "idempotency_key_reuse", r3)
r3 = call("POST", "/authorizations", dict(body, to_handle="cy"), token=A, key=key)
ok("G02 same key different handle 409", r3.s == 409 and r3.code == "idempotency_key_reuse", r3)
r3 = call("POST", "/authorizations", dict(body, visibility="public"), token=A, key=key)
ok("G02 same key different visibility 409", r3.s == 409 and r3.code == "idempotency_key_reuse", r3)
for nm, b in (("amount 0", dict(body, amount=0)), ("amount string", dict(body, amount="x")), ("unknown handle", dict(body, to_handle="nobody")), ("self", dict(body, to_handle="ada")), ("huge", dict(body, amount=10**12))):
    r = call("POST", "/authorizations", b, token=A, key=key)
    ok("G03 claimed key beats validation (%s) -> 409 idempotency_key_reuse" % nm, r.s == 409 and r.code == "idempotency_key_reuse", r)
ok("G03 nothing else created", held() == 2000)
# replay after the hold changed state
aid = r1.j["authorization_id"]
cr = capture(B, aid, amount=500, key=k())
ok("G07 setup capture", cr.s == 201)
r4 = call("POST", "/authorizations", body, token=A, key=key)
ok("G07 replay after capture returns ORIGINAL body (status open, captured 0), 200, no new hold", r4.s == 200 and r4.j == r1.j and held() == 0 and len(authz(A)["authorizations"]) == 1, r4)
# failed 4xx key reusable
k2 = k()
r = call("POST", "/authorizations", dict(body, amount=10**9), token=A, key=k2)
ok("G04 first attempt fails 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
r = call("POST", "/authorizations", dict(body, amount=700), token=A, key=k2)
ok("G04 failed key reusable as first use with other body: 201", r.s == 201 and r.j["amount"] == 700, r)
k3 = k()
r = call("POST", "/authorizations", dict(body, amount=0), token=A, key=k3)
r = call("POST", "/authorizations", dict(body, amount=700), token=A, key=k3)
ok("G04 validation-failed key reusable: 201", r.s == 201, r)
# per-user scope, different path
ks = k()
ra = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, token=A, key=ks)
rc = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, token=C, key=ks)
ok("G05 same key different users: both 201, distinct ids", ra.s == 201 and rc.s == 201 and ra.j["authorization_id"] != rc.j["authorization_id"], (ra, rc))
rp = pay(A, "bob", 100, key=ks)
ok("G05 same key on a different path (POST /payments) is not a replay: 201", rp.s == 201, rp)
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=B, key=ks)
ok("G05 same key by other user on /requests is fresh: 201", rq.s == 201, rq)

# ---------- capture
t = setup(f)
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
aid = authorize(A, "bob", 2000, note="n", vis="public").j["authorization_id"]
kc = k()
c1 = call("POST", "/authorizations/%s/capture" % aid, {}, token=B, key=kc)
ok("E02 capture {} first use 201 captures full remainder 2000", c1.s == 201 and c1.j["amount"] == 2000, c1)
c2 = call("POST", "/authorizations/%s/capture" % aid, {}, token=B, key=kc)
ok("E02 replay {} -> 200 identical payment", c2.s == 200 and c2.j == c1.j, c2)
c3 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 2000}, token=B, key=kc)
ok("E02 {} then {\"amount\":2000} same key -> 409 idempotency_key_reuse", c3.s == 409 and c3.code == "idempotency_key_reuse", c3)
c3 = call("POST", "/authorizations/%s/capture" % aid, {"final": True}, token=B, key=kc)
ok("E02 {} then {\"final\":true} same key -> 409 idempotency_key_reuse", c3.s == 409 and c3.code == "idempotency_key_reuse", c3)
c3 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 5}, token=B, key=kc)
ok("E02 {} then amount 5 same key -> 409", c3.s == 409 and c3.code == "idempotency_key_reuse", c3)
c3 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 0}, token=B, key=kc)
ok("G03 claimed capture key beats validation (amount 0) -> 409 idempotency_key_reuse", c3.s == 409 and c3.code == "idempotency_key_reuse", c3)
ok("G01 capture moved money once", me(B)["total"] == 4500 and me(A)["total"] == 98000 and len(authz(B, aid)["payment_ids"]) == 1)
# replay of capture by the stranger/payer with the same key: per-user scope => not a replay
c4 = call("POST", "/authorizations/%s/capture" % aid, {}, token=A, key=kc)
ok("G05 capture key is per user: payer using receiver's key gets 403, not the cached 200", c4.s == 403 and c4.code == "forbidden", c4)
# G07: replay after hold closed/voided/captured
vk = authorize(A, "bob", 800).j["authorization_id"]
kv = k(); cv = call("POST", "/authorizations/%s/capture" % vk, {"amount": 300, "final": False}, token=B, key=kv)
void(A, vk)
cv2 = call("POST", "/authorizations/%s/capture" % vk, {"amount": 300, "final": False}, token=B, key=kv)
ok("G07 capture replay after void returns original 200 payment, no extra money", cv.s == 201 and cv2.s == 200 and cv2.j == cv.j and authz(B, vk)["captured_amount"] == 300, (cv, cv2))
# failed capture key reusable
fk = authorize(A, "bob", 600).j["authorization_id"]
kf = k()
r = call("POST", "/authorizations/%s/capture" % fk, {"amount": 601}, token=B, key=kf)
ok("G04 capture exceeding remaining 422", r.s == 422 and r.code == "capture_exceeds_authorization", r)
r = call("POST", "/authorizations/%s/capture" % fk, {"amount": 600}, token=B, key=kf)
ok("G04 failed capture key reusable with another body: 201", r.s == 201, r)
# same key different authorization = different path
a1 = authorize(A, "bob", 100).j["authorization_id"]; a2 = authorize(A, "bob", 100).j["authorization_id"]
ks = k()
x1 = call("POST", "/authorizations/%s/capture" % a1, {}, token=B, key=ks)
x2 = call("POST", "/authorizations/%s/capture" % a2, {}, token=B, key=ks)
ok("G05 same key on a different authorization path is a fresh capture", x1.s == 201 and x2.s == 201 and x1.j["payment_id"] != x2.j["payment_id"], (x1, x2))
# unknown-field / extra fields: ignored by value comparison? (stage-1: unknown fields ignored) new response fields never enter equality
c5 = call("POST", "/authorizations/%s/capture" % a1, {}, token=B, key=ks)
ok("E10 replay after response fields grew still matches body equality", c5.s == 200 and c5.j == x1.j, c5)

# ---------- concurrent identical (3 rounds each)
for rnd in range(3):
    t = setup(f); A, B = t["ada"], t["bob"]
    kk = k()
    res = parallel([lambda: call("POST", "/authorizations", {"to_handle": "bob", "amount": 4000, "note": "c"}, token=A, key=kk) for _ in range(24)])
    n201 = [r for r in res if r.s == 201]; n200 = [r for r in res if r.s == 200]
    ok("G06 authorize r%d: exactly one 201 of 24, the rest 200 with identical body" % rnd, len(n201) == 1 and len(n200) == 23 and all(r.j == n201[0].j for r in n200), [r.s for r in res])
    ok("G06 authorize r%d: one hold only (held 4000)" % rnd, me(A)["held"] == 4000 and len(authz(A)["authorizations"]) == 1)
    aid = n201[0].j["authorization_id"]
    kk = k()
    res = parallel([lambda: call("POST", "/authorizations/%s/capture" % aid, {"amount": 1500}, token=B, key=kk) for _ in range(24)])
    n201 = [r for r in res if r.s == 201]; n200 = [r for r in res if r.s == 200]
    ok("G06 capture r%d: exactly one 201 of 24, the rest 200 identical" % rnd, len(n201) == 1 and len(n200) == 23 and all(r.j == n201[0].j for r in n200), [(r.s, r.code) for r in res][:6])
    x = authz(B, aid)
    ok("G06 capture r%d: money moved once (captured 1500, bob 4000, ada 98500)" % rnd, (x["captured_amount"], me(B)["total"], me(A)["total"], len(x["payment_ids"])) == (1500, 4000, 98500, 1), x)
    # concurrent same key, two different bodies
    t2 = setup(f); A, B = t2["ada"], t2["bob"]
    kk = k()
    fns = [(lambda a=a: call("POST", "/authorizations", {"to_handle": "bob", "amount": a}, token=A, key=kk)) for a in (1000, 2000) * 12]
    res = parallel(fns)
    ok1 = [r for r in res if r.s == 201]
    win = ok1[0].j["amount"] if ok1 else None
    good = len(ok1) == 1 and all((r.s == 200 and r.j == ok1[0].j) if r.j.get("amount") == win else (r.s == 409) for r in res if r.s != 201 and r.j and "authorization_id" in r.j) \
        and all(r.s in (200, 201, 409) for r in res)
    n409 = [r for r in res if r.s == 409 and r.code == "idempotency_key_reuse"]
    ok("G06 authorize r%d same key two bodies: one 201; losers 200(same body)/409 reuse; one hold" % rnd,
       len(ok1) == 1 and len(n409) == 12 and me(A)["held"] == win and len(authz(A)["authorizations"]) == 1, ([r.s for r in res], win, me(A)))

# ---------- different keys, same effect: capture storm of the whole remainder
t = setup(f); A, B = t["ada"], t["bob"]
aid = authorize(A, "bob", 3000).j["authorization_id"]
res = parallel([lambda: capture(B, aid, key=k()) for _ in range(20)])
n201 = [r for r in res if r.s == 201]; rest = [r for r in res if r.s != 201]
ok("A03 20 distinct-key default captures: exactly one 201, others 409 authorization_not_open", len(n201) == 1 and all(r.s == 409 and r.code == "authorization_not_open" for r in rest), [(r.s, r.code) for r in res])
ok("A03 moved 3000 once", me(B)["total"] == 5500 and me(A)["total"] == 97000 and me(A)["held"] == 0)
done("s2_idem")
