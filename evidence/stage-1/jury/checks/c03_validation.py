"""J04, J14, J16, J25, J31, J35-J37, J51, J52, J54: amount forms, bounds, types, note, visibility, query ints."""
import json
from urllib.parse import quote
from lib import *

t = setup(fx([user("ada", 4 * 10 ** 9), user("bob", 0), user("cy", 0), user("dee", 0), user("op", 0)], ops=["u_op"]))
A, DEE = t["ada"], t["dee"]


def pay(raw):
    return call("POST", "/payments", raw=raw, token=A, key=k())


AM = '{"to_handle":"bob","amount":%s}'
before = bal(A)
for a, want in (("1", 1), ("1000", 1000), ("1000.0", 1000), ("1e3", 1000), ("1E3", 1000), ("1.0e3", 1000), ("10e2", 1000),
                ("0.1e4", 1000), ("1000000000", 10 ** 9), ("1e9", 10 ** 9), ("1.0E9", 10 ** 9)):
    r = pay(AM % a)
    ok("payments amount %s -> 201 amount==%d (int)" % (a, want), r.s == 201 and r.j["amount"] == want and type(r.j["amount"]) is int, r)
for a in ("0", "-1", "1000000001", "1.5", "0.5", "1000.5", "true", "false", '"1000"', '"abc"', '""', "null", "[1]", "{}", "1e10", "9007199254740993",
          "-0", "0.0", "1e-1", "1e400", "-1e400", "123456789012345678901234567890"):
    r = pay(AM % a)
    ok("payments amount %s -> 422 validation_failed" % a, r.s == 422 and r.code == "validation_failed", r)
r = pay('{"to_handle":"bob"}')
ok("payments amount missing -> 422", r.s == 422 and r.code == "validation_failed", r)
ok("balances only reflect the accepted payments", bal(A) == before - (1 + 1000 * 7 + 3 * 10 ** 9) and bal(t["bob"]) == 1 + 7000 + 3 * 10 ** 9, (bal(A), bal(t["bob"])))

# same amount forms on the other amount-taking paths
for a in ("1e3", "1000.0"):
    r = call("POST", "/requests", raw='{"payer_handle":"bob","amount":%s}' % a, token=A, key=k())
    ok("requests amount %s -> 201 int" % a, r.s == 201 and r.j["amount"] == 1000 and type(r.j["amount"]) is int, r)
    r = call("POST", "/splits", raw='{"amount":%s,"participant_handles":["ada","bob"]}' % a, token=A, key=k())
    ok("splits amount %s -> 201, shares 500/500" % a, r.s == 201 and [s["amount"] for s in r.j["shares"]] == [500, 500], r)
    r = call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}' % a, token=t["op"], key=k())
    ok("settlements amount %s -> 201 int" % a, r.s == 201 and r.j["payments"][0]["amount"] == 1000 and type(r.j["payments"][0]["amount"]) is int, r)
for a in ("0", "1000000001", "true", '"1000"', "1.5", "null"):
    r = call("POST", "/requests", raw='{"payer_handle":"bob","amount":%s}' % a, token=A, key=k())
    ok("requests amount %s -> 422" % a, r.s == 422 and r.code == "validation_failed", r)
    r = call("POST", "/splits", raw='{"amount":%s,"participant_handles":["ada","bob"]}' % a, token=A, key=k())
    ok("splits amount %s -> 422" % a, r.s == 422 and r.code == "validation_failed", r)
    r = call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}' % a, token=t["op"], key=k())
    ok("settlements amount %s -> 422" % a, r.s == 422 and r.code == "validation_failed", r)
r = call("POST", "/requests", raw='{"payer_handle":"bob","amount":1000000000}', token=A, key=k())
ok("requests amount 1e9 boundary -> 201", r.s == 201, r)
r = call("POST", "/splits", raw='{"amount":1000000000,"participant_handles":["ada","bob","cy"]}', token=A, key=k())
ok("splits amount 1e9 -> shares 333333334/333333333/333333333", r.s == 201 and [s["amount"] for s in r.j["shares"]] == [333333334, 333333333, 333333333], r)

# validation precedes balance check
r = call("POST", "/payments", {"to_handle": "bob", "amount": 1000000001}, token=DEE, key=k())
ok("poor user amount>1e9 -> 422 (not 409)", r.s == 422, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 50}, token=DEE, key=k())
ok("poor user amount 50 -> 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 50, "note": "x" * 201}, token=DEE, key=k())
ok("poor user note>200 -> 422 (not 409)", r.s == 422 and r.code == "validation_failed", r)
r = call("POST", "/payments", {"to_handle": "dee", "amount": 50}, token=DEE, key=k())
ok("self payment -> 422 self_payment", r.s == 422 and r.code == "self_payment", r)
r = call("POST", "/payments", {"to_handle": "nobody", "amount": 5}, token=A, key=k())
ok("unknown handle -> 404 not_found", r.s == 404 and r.code == "not_found", r)
for h in ("", "BOB", "Bob", "b o b", "x" * 1000, "bob "):
    r = call("POST", "/payments", {"to_handle": h, "amount": 5}, token=A, key=k())
    print("OBS to_handle=%r -> %s %s" % (h[:20], r.s, r.code))
    ok("non-matching handle %r -> 404 (no user has that handle)" % h[:20], r.s == 404, r)

# ---- note
for nm, note in (("empty", ""), ("200 ascii", "a" * 200), ("200 emoji (code points)", "\U0001F600" * 200), ("200 e-acute", "é" * 200)):
    raw = json.dumps({"to_handle": "bob", "amount": 1, "note": note}, ensure_ascii=False).encode("utf-8")
    r = call("POST", "/payments", raw=raw, token=A, key=k())
    ok("note %s accepted" % nm, r.s == 201 and r.j["note"] == note, r)
for nm, note in (("201 ascii", "a" * 201), ("201 emoji", "\U0001F600" * 201), ("201 e-acute", "é" * 201)):
    raw = json.dumps({"to_handle": "bob", "amount": 1, "note": note}, ensure_ascii=False).encode("utf-8")
    r = call("POST", "/payments", raw=raw, token=A, key=k())
    ok("note %s -> 422" % nm, r.s == 422 and r.code == "validation_failed", r)
for nm, nv in (("null", "null"), ("5", "5"), ("true", "true"), ("[]", "[]"), ("{}", "{}")):
    r = pay('{"to_handle":"bob","amount":1,"note":%s}' % nv)
    ok("note %s -> 422" % nm, r.s == 422 and r.code == "validation_failed", r)
note = "  <b>x</b> & é\U0001F600 \"q\" \\ / \n\ttab   end  "
for ea in (False, True):
    body = json.dumps({"to_handle": "bob", "amount": 1, "note": note}, ensure_ascii=ea).encode("utf-8")
    r = call("POST", "/payments", raw=body, token=A, key=k())
    ok("note verbatim round trip in response (ensure_ascii=%s)" % ea, r.s == 201 and r.j["note"] == note, r)
    feed = call("GET", "/activity?limit=5", token=t["bob"]).j["payments"]
    ok("note verbatim in GET /activity (ensure_ascii=%s)" % ea, feed[0]["note"] == note, feed[0]["note"])
r = call("POST", "/requests", {"payer_handle": "bob", "amount": 5, "note": note}, token=A, key=k())
ok("request note verbatim", r.s == 201 and r.j["note"] == note, r)
ok("request note verbatim in GET /requests", call("GET", "/requests?limit=1", token=A).j["requests"][0]["note"] == note)
r = pay('{"to_handle":"bob","amount":1}')
ok("note defaults to '' and visibility to public", r.s == 201 and r.j["note"] == "" and r.j["visibility"] == "public" and r.j["request_id"] is None, r)
ok("payment body exact key set (incl. settlement_id null for non-members)",
   set(r.j) >= {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "created_at"}
   and r.j.get("settlement_id", "MISSING") is None, sorted(r.j))
ok("timestamp RFC3339 with offset; ids <=64", bool(RFC3339.match(r.j["created_at"])) and len(r.j["payment_id"]) <= 64, r.j)

# ---- visibility
for v, want in (('"public"', 201), ('"private"', 201), ('"PUBLIC"', 422), ('""', 422), ('"x"', 422), ("null", 422), ("1", 422), ("true", 422)):
    r = pay('{"to_handle":"bob","amount":1,"visibility":%s}' % v)
    ok("visibility %s -> %d" % (v, want), r.s == want and (want == 201 or r.code == "validation_failed"), r)

# ---- wrong types / unparseable (400 malformed_request)
for nm, raw in (("to_handle number", '{"to_handle":5,"amount":1}'), ("to_handle array", '{"to_handle":[],"amount":1}'),
                ("to_handle object", '{"to_handle":{},"amount":1}'), ("to_handle bool", '{"to_handle":true,"amount":1}'),
                ("truncated json", '{"to_handle":"bob","amount":'), ("not json", "hello"), ("empty body", ""),
                ("trailing garbage", '{"to_handle":"bob","amount":1}xx'), ("array body", "[]"), ("null body", "null"),
                ("string body", '"x"'), ("number body", "5"), ("invalid utf-8", b'{"to_handle":"b\xff\xfe","amount":1}'),
                ("BOM prefix", b'\xef\xbb\xbf{"to_handle":"bob","amount":1}')):
    r = call("POST", "/payments", raw=raw, token=A, key=k())
    print("OBS payments %-16s -> %s %s" % (nm, r.s, r.code))
    ok("payments %s -> 400 malformed_request" % nm, r.s == 400 and r.code == "malformed_request", r)
r = pay('{"amount":1}')
ok("payments to_handle missing -> 422", r.s == 422 and r.code == "validation_failed", r)
r = pay('{"to_handle":null,"amount":1}')
print("OBS payments to_handle null ->", r.s, r.code)
ok("payments to_handle null -> 400 or 422 (never 2xx/5xx)", r.s in (400, 422), r)
r = pay('{"to_handle":"bob","amount":1,"zzz":{"a":[1,2]},"note":"n"}')
ok("unknown body fields ignored", r.s == 201, r)
r = call("POST", "/requests", raw='{"payer_handle":5,"amount":1}', token=A, key=k())
ok("requests payer_handle number -> 400", r.s == 400 and r.code == "malformed_request", r)
r = call("POST", "/splits", raw='{"amount":10,"participant_handles":"bob"}', token=A, key=k())
ok("splits participant_handles string -> 400 malformed_request", r.s == 400 and r.code == "malformed_request", r)
r = call("POST", "/splits", raw='{"amount":10,"participant_handles":[5]}', token=A, key=k())
print("OBS splits participant_handles [5] ->", r.s, r.code)
ok("splits participant_handles [5] -> 400 or 422", r.s in (400, 422), r)
r = call("POST", "/splits", raw='{"amount":10}', token=A, key=k())
ok("splits participant_handles missing -> 422", r.s == 422 and r.code == "validation_failed", r)

# ---- query ints
for path in ("/activity", "/requests"):
    key_name = "payments" if path == "/activity" else "requests"
    for lim in ("1", "50", "200", "007"):
        r = call("GET", path + "?limit=" + lim, token=A)
        if lim == "007":
            print("OBS %s limit=007 -> %s" % (path, r.s))
            continue
        ok("%s limit=%s -> 200" % (path, lim), r.s == 200 and isinstance(r.j[key_name], list) and len(r.j[key_name]) <= int(lim), r)
    for lim in ("0", "201", "-1", "1e9", "4.0", "+4", "%2B4", "abc", "", "1%20", "%20", "0x10", "9999999999999999999999", "%D9%A4"):
        r = call("GET", path + "?limit=" + lim, token=A)
        ok("%s limit=%r -> 422 validation_failed" % (path, lim), r.s == 422 and r.code == "validation_failed", r)
    for off in ("0", "5", "1000000"):
        r = call("GET", path + "?offset=" + off, token=A)
        ok("%s offset=%s -> 200" % (path, off), r.s == 200 and r.j["has_more"] is False or off != "1000000", r)
    for off in ("-1", "1e9", "4.0", "+4", "%2B4", "abc", "", "0x1"):
        r = call("GET", path + "?offset=" + off, token=A)
        ok("%s offset=%r -> 422" % (path, off), r.s == 422 and r.code == "validation_failed", r)
    r = call("GET", path + "?foo=bar&limit=3&zzz=", token=A)
    ok("%s unknown query params ignored" % path, r.s == 200, r)
for q in ("direction=sideways", "direction=INCOMING", "status=unknown", "status=PENDING", "direction=", "status="):
    r = call("GET", "/requests?" + q, token=A)
    ok("/requests?%s -> 422" % q, r.s == 422 and r.code == "validation_failed", r)
for q in ("direction=incoming", "direction=outgoing", "status=pending", "status=paid", "status=declined", "status=cancelled", "direction=incoming&status=pending"):
    r = call("GET", "/requests?" + q, token=A)
    ok("/requests?%s -> 200" % q, r.s == 200, r)

# ---- exactness near 2^53: balances stay exact integers
big = 9007199254740001
t2 = setup(fx([user("ada", big), user("bob", 0), user("cy", 0), user("dee", 0)]))
for i in range(5):
    r = call("POST", "/payments", {"to_handle": "bob", "amount": 999999999}, token=t2["ada"], key=k())
    assert r.s == 201
ok("exact minor-unit arithmetic near 2^53 (%d - 5*999999999)" % big, bal(t2["ada"]) == big - 5 * 999999999 and bal(t2["bob"]) == 5 * 999999999, (bal(t2["ada"]), bal(t2["bob"])))
me_raw = call("GET", "/me", token=t2["ada"]).b.decode()
ok("/me serialises balance as integer literal (no float/exponent)", '"balance":%d' % (big - 5 * 999999999) in me_raw.replace(" ", ""), me_raw)

done("c03_validation")
