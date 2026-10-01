"""D03 E01 E09 E11 F02 F06: validation/error tables, 403 vs 404, 401, key rules on both new write paths."""
from lib import *

UNI = "h\u00e9llo \U0001F642 \u0001x"
f = fx([user("ada", 4000000000), user("bob", 2500), user("cy", 0), user("dee", 5000)])
t = setup(f)
A, B, C = t["ada"], t["bob"], t["cy"]

def err(r, s, c):
    return r.s == s and r.code == c

# ---------------- POST /authorizations
cases = [
    ("amount 0", {"to_handle": "bob", "amount": 0}, 422, "validation_failed"),
    ("amount -1", {"to_handle": "bob", "amount": -1}, 422, "validation_failed"),
    ("amount 1.5", {"to_handle": "bob", "amount": 1.5}, 422, "validation_failed"),
    ("amount string", {"to_handle": "bob", "amount": "5"}, 422, "validation_failed"),
    ("amount true", {"to_handle": "bob", "amount": True}, 422, "validation_failed"),
    ("amount null", {"to_handle": "bob", "amount": None}, 422, "validation_failed"),
    ("amount missing", {"to_handle": "bob"}, 422, "validation_failed"),
    ("amount 1e9+1", {"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
    ("self payment", {"to_handle": "ada", "amount": 5}, 422, "self_payment"),
    ("unknown handle", {"to_handle": "nobody", "amount": 5}, 404, "not_found"),
    ("note 201 chars", {"to_handle": "bob", "amount": 5, "note": "x" * 201}, 422, "validation_failed"),
    ("note null", {"to_handle": "bob", "amount": 5, "note": None}, 422, "validation_failed"),
    ("note number", {"to_handle": "bob", "amount": 5, "note": 5}, 422, "validation_failed"),
    ("visibility bad", {"to_handle": "bob", "amount": 5, "visibility": "friends"}, 422, "validation_failed"),
    ("visibility null", {"to_handle": "bob", "amount": 5, "visibility": None}, 422, "validation_failed"),
    ("to_handle missing", {"amount": 5}, 422, "validation_failed"),
    ("to_handle number", {"to_handle": 123, "amount": 5}, 400, "malformed_request"),
]
for name, body, s, c in cases:
    r = call("POST", "/authorizations", body, token=A, key=k())
    ok("D03 authorize " + name + " -> %d %s" % (s, c), err(r, s, c), r)
ok("D03 no hold created by any refusal", authz(A)["authorizations"] == [] and me(A)["held"] == 0)
r = call("POST", "/authorizations", raw="{not json", token=A, key=k())
ok("D03 unparseable body 400 malformed_request", err(r, 400, "malformed_request"), r)
r = call("POST", "/authorizations", raw="[1,2]", token=A, key=k())
ok("D03 array body 400 malformed_request", err(r, 400, "malformed_request"), r)
r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=A)
ok("D03 authorize without key 400 missing_idempotency_key", err(r, 400, "missing_idempotency_key"), r)
r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=A, key="")
ok("D03 authorize empty key 400 missing_idempotency_key", err(r, 400, "missing_idempotency_key"), r)
r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=A, key="x" * 256)
ok("D03 authorize 256-char key 422 validation_failed", err(r, 422, "validation_failed"), r)
r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=A, key="x" * 255)
ok("D03 authorize 255-char key accepted", r.s == 201, r)
# accepted amount forms / boundaries
for name, raw, expect in (("1000.0", '{"to_handle":"bob","amount":1000.0}', 1000), ("1e3", '{"to_handle":"bob","amount":1e3}', 1000), ("1", '{"to_handle":"bob","amount":1}', 1)):
    r = call("POST", "/authorizations", raw=raw, token=A, key=k())
    ok("D03 authorize integral amount %s accepted" % name, r.s == 201 and r.j["amount"] == expect, r)
r = authorize(A, "bob", 1000000000)
ok("D03 amount exactly 1e9 accepted", r.s == 201 and r.j["amount"] == 1000000000, r)
r = authorize(A, "bob", 5, note="x" * 200)
ok("D03 note exactly 200 chars accepted", r.s == 201, r)
r = authorize(A, "bob", 5, note=UNI, vis="public")
ok("D03 unicode note verbatim", r.s == 201 and r.j["note"] == UNI, r)
for h, tk in (("none", None), ("garbage", "nope")):
    r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=tk, key=k())
    ok("F06 authorize token %s -> 401 unauthenticated" % h, err(r, 401, "unauthenticated"), r)
# insufficient: available is 4e9 - holds; ask way more
r = authorize(B, "ada", 2501)
ok("D03 authorize above available 409 insufficient_funds", err(r, 409, "insufficient_funds"), r)
r = authorize(B, "ada", 2500)
ok("D03 authorize exactly available allowed", r.s == 201, r)

# ---------------- capture / void errors
t = setup(f)
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
a = authorize(A, "bob", 1000, note="n", vis="public").j
aid = a["authorization_id"]
r = call("POST", "/authorizations/%s/capture" % aid, {}, token=B)
ok("E01 capture without key 400 missing_idempotency_key", err(r, 400, "missing_idempotency_key"), r)
r = call("POST", "/authorizations/%s/capture" % aid, {}, token=B, key="")
ok("E01 capture empty key 400", err(r, 400, "missing_idempotency_key"), r)
r = call("POST", "/authorizations/%s/capture" % aid, {}, token=B, key="y" * 256)
ok("E01 capture 256-char key 422", err(r, 422, "validation_failed"), r)
r = capture(A, aid, amount=10)
ok("E01 payer cannot capture 403 forbidden", err(r, 403, "forbidden"), r)
r = capture(C, aid, amount=10)
ok("F02 stranger capture 403 forbidden (not 404)", err(r, 403, "forbidden"), r)
r = void(B, aid)
ok("F02 receiver void 403 forbidden", err(r, 403, "forbidden"), r)
r = void(C, aid)
ok("F02 stranger void 403 forbidden", err(r, 403, "forbidden"), r)
r = capture(B, "a_nope", amount=10)
ok("E09 unknown authorization capture 404 not_found", err(r, 404, "not_found"), r)
r = void(A, "a_nope")
ok("E09 unknown authorization void 404 not_found", err(r, 404, "not_found"), r)
ok("F02 refused calls changed nothing", me(A)["held"] == 1000 and authz(B, aid)["status"] == "open")
for name, body in (("amount 0", {"amount": 0}), ("amount -3", {"amount": -3}), ("amount 1.5", {"amount": 1.5}), ("amount string", {"amount": "5"}), ("amount true", {"amount": True})):
    r = call("POST", "/authorizations/%s/capture" % aid, body, token=B, key=k())
    ok("E09 capture " + name + " -> 422 validation_failed", err(r, 422, "validation_failed"), r)
r = capture(B, aid, amount=1001)
ok("E09 capture above remaining 422 capture_exceeds_authorization", err(r, 422, "capture_exceeds_authorization"), r)
# non-boolean final
for name, v in (("string false", "false"), ("zero", 0), ("null", None), ("string true", "true"), ("one", 1)):
    r = call("POST", "/authorizations/%s/capture" % aid, {"amount": 10, "final": v}, token=B, key=k())
    ok("E11 capture final=%s rejected (400 malformed_request per section 5, wrong type) [got %s %s]" % (name, r.s, r.code), r.s == 400 and r.code == "malformed_request", r)
ok("E11 refused finals captured nothing", authz(B, aid)["captured_amount"] == 0 and me(A)["held"] == 1000)
r = call("POST", "/authorizations/%s/capture" % aid, raw="{bad", token=B, key=k())
ok("E09 capture unparseable body 400 malformed_request", err(r, 400, "malformed_request"), r)
r = call("POST", "/authorizations/%s/capture" % aid, raw="[1]", token=B, key=k())
ok("E09 capture array body 400 malformed_request", err(r, 400, "malformed_request"), r)
# empty body entirely
r = call("POST", "/authorizations/%s/capture" % aid, token=B, key=k())
print("INFO capture with no body at all ->", r.s, r.code)
for tk, nm in ((None, "no token"), ("junk", "bad token")):
    r = call("POST", "/authorizations/%s/capture" % aid, {}, token=tk, key=k())
    ok("F06 capture %s -> 401" % nm, err(r, 401, "unauthenticated"), r)
    r = call("POST", "/authorizations/%s/void" % aid, {}, token=tk)
    ok("F06 void %s -> 401" % nm, err(r, 401, "unauthenticated"), r)
    r = call("GET", "/authorizations", token=tk)
    ok("F06 GET /authorizations %s -> 401 JSON envelope" % nm, err(r, 401, "unauthenticated"), r)
# null amount behaviour (spec silent): must not 5xx and must not capture more than amount
r = call("POST", "/authorizations/%s/capture" % aid, {"amount": None}, token=B, key=k())
print("INFO capture amount:null ->", r.s, r.code)
ok("E09 amount:null does not 5xx", r.s < 500, r)
# void then capture states
rv = void(A, aid)
r = capture(B, aid, amount=10)
ok("E09 capture voided -> 409 authorization_not_open", err(r, 409, "authorization_not_open"), r)
r = capture(C, aid, amount=10)
ok("F02 stranger capture on closed hold still 403 (permission before state)", err(r, 403, "forbidden"), r)
r = capture(A, aid, amount=10)
ok("F02 payer capture on closed hold 403", err(r, 403, "forbidden"), r)
# unknown-id forms
for bad in ("", "x" * 200, "a%20b", "../me"):
    r = call("POST", "/authorizations/%s/capture" % bad, {}, token=B, key=k())
    ok("E09 odd id %r does not 5xx (got %s)" % (bad[:12], r.s), r.s in (404, 400, 405), r)
r = call("GET", "/authorizations/%s" % aid, token=A)
print("INFO GET /authorizations/{id} ->", r.s)
ok("E09 method not allowed paths are JSON 4xx not 5xx", r.s < 500 and (r.j is None or "error" in r.j), r)
done("s2_errors")
