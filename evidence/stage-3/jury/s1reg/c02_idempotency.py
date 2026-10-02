"""J32, J43-J49, J57, J58: idempotency on all five write paths."""
from lib import *

UIDS = [user("ada", 100000), user("bob", 100000), user("cy", 0), user("dee", 5000),
        user("op", 0), user("op2", 0)]


def new_t():
    return setup(fx(UIDS, ops=["u_op", "u_op2"]))


def mkctx(name, t):
    """returns dict: path, tok, body, bad (invalid-field body), other (valid different body), effect(), delta, change(first)"""
    if name == "payments":
        return dict(path="/payments", tok=t["ada"], body={"to_handle": "bob", "amount": 100, "note": "n"},
                    bad={"to_handle": "bob", "amount": -5, "note": "n"}, other={"to_handle": "bob", "amount": 101, "note": "n"},
                    effect=lambda: bal(t["ada"]), delta=-100,
                    change=lambda first: call("POST", "/payments", {"to_handle": "cy", "amount": 7}, token=t["ada"], key=k()))
    if name == "requests":
        return dict(path="/requests", tok=t["ada"], body={"payer_handle": "bob", "amount": 100, "note": "n"},
                    bad={"payer_handle": "nobody_x", "amount": 0}, other={"payer_handle": "bob", "amount": 101, "note": "n"},
                    effect=lambda: len(call("GET", "/requests?direction=incoming&limit=200", token=t["bob"]).j["requests"]), delta=1,
                    change=lambda first: call("POST", "/requests/%s/cancel" % first["request_id"], {}, token=t["ada"]))
    if name == "pay":
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=t["bob"], key=k()).j["request_id"]
        return dict(path="/requests/%s/pay" % rid, tok=t["ada"], body={}, bad={"visibility": "bogus"}, other={"visibility": "private"},
                    effect=lambda: bal(t["ada"]), delta=-100, change=lambda first: None)
    if name == "splits":
        return dict(path="/splits", tok=t["ada"], body={"amount": 300, "participant_handles": ["ada", "bob", "cy"], "note": "s"},
                    bad={"amount": -1, "participant_handles": []}, other={"amount": 301, "participant_handles": ["ada", "bob", "cy"], "note": "s"},
                    effect=lambda: len(call("GET", "/requests?direction=incoming&limit=200", token=t["bob"]).j["requests"]), delta=1,
                    change=lambda first: call("POST", "/requests/%s/pay" % first["requests"][0]["request_id"], {}, token=t["bob"], key=k()))
    if name == "settlements":
        return dict(path="/settlements", tok=t["op"], body={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]},
                    bad={"transfers": []}, other={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 101}]},
                    effect=lambda: bal(t["ada"]), delta=-100,
                    change=lambda first: call("POST", "/payments", {"to_handle": "cy", "amount": 7}, token=t["ada"], key=k()))


def post(c, key, body=None, raw=None, tok=None):
    return call("POST", c["path"], body=body, raw=raw, token=tok or c["tok"], key=key)


for name in ("payments", "requests", "pay", "splits", "settlements"):
    for rnd in range(3):
        tag = "%s r%d" % (name, rnd)
        t = new_t()
        c = mkctx(name, t)
        key = k()
        e0 = c["effect"]()
        res = parallel([lambda: post(c, key, c["body"]) for _ in range(20)])
        n201 = [r for r in res if getattr(r, "s", 0) == 201]
        n200 = [r for r in res if getattr(r, "s", 0) == 200]
        ok("%s: concurrent x20 -> exactly one 201, 19 x 200" % tag, len(n201) == 1 and len(n200) == 19, [getattr(r, "s", r) for r in res])
        if len(n201) != 1:
            continue
        first = n201[0].j
        ok("%s: all replay bodies identical to original as JSON value" % tag, all(r.j == first for r in n200))
        ok("%s: effect applied exactly once" % tag, c["effect"]() - e0 == c["delta"], (e0, c["effect"]()))
        tot = sum(bal(t[h]) for h in t)
        ok("%s: conservation" % tag, tot == 110000 + 5000 or tot == sum(u["balance"] for u in UIDS), tot)
        if rnd == 0:
            # state change then replay
            c["change"](first)
            e1 = c["effect"]()
            r = post(c, key, c["body"])
            ok("%s: replay after state change -> 200 original body" % tag, r.s == 200 and r.j == first, r)
            ok("%s: replay made no further change" % tag, c["effect"]() == e1)
            # claimed key beats field validation
            r = post(c, key, c["bad"])
            ok("%s: claimed key + invalid fields -> 409 idempotency_key_reuse" % tag, r.s == 409 and r.code == "idempotency_key_reuse", r)
            r = post(c, key, c["other"])
            ok("%s: claimed key + different valid body -> 409" % tag, r.s == 409 and r.code == "idempotency_key_reuse", r)
            # missing / empty key
            r = call("POST", c["path"], c["body"], token=c["tok"])
            ok("%s: no key -> 400 missing_idempotency_key" % tag, r.s == 400 and r.code == "missing_idempotency_key", r)
            r = call("POST", c["path"], c["body"], token=c["tok"], key="")
            ok("%s: empty key -> 400 missing_idempotency_key" % tag, r.s == 400 and r.code == "missing_idempotency_key", r)
            r = call("POST", c["path"], c["body"], token=c["tok"], key="k" * 256)
            ok("%s: 256-char key -> 422 validation_failed" % tag, r.s == 422 and r.code == "validation_failed", r)
            t2 = new_t(); c2 = mkctx(name, t2)
            r = post(c2, "k" * 255, c2["body"])
            ok("%s: 255-char key accepted (201)" % tag, r.s == 201, r)
            r = post(c2, "k" * 255, c2["body"])
            ok("%s: 255-char key replays (200)" % tag, r.s == 200, r)
            r = post(c2, "x", c2["body"])  # 1-char key
            ok("%s: 1-char key accepted" % tag, r.s in (201, 200, 409) and r.s != 422 and r.s != 400, r) if name != "pay" else None

# ---- scoping per user (payments, requests, splits, settlements)
t = new_t()
K = k()
ra = call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=t["ada"], key=K)
rb = call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=t["bob"], key=K)
ok("scope: same key different users both 201 (payments)", ra.s == 201 and rb.s == 201 and ra.j["payment_id"] != rb.j["payment_id"], (ra, rb))
rb2 = call("POST", "/payments", {"to_handle": "cy", "amount": 555}, token=t["bob"], key=K)
ok("scope: bob's different body on his own key -> 409, ada unaffected", rb2.s == 409 and call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=t["ada"], key=K).s == 200)
K = k()
s1 = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, token=t["op"], key=K)
s2 = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, token=t["op2"], key=K)
ok("scope: same settlement key two operators both 201", s1.s == 201 and s2.s == 201 and s1.j["settlement_id"] != s2.j["settlement_id"], (s1, s2))
K = k()
q1 = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, token=t["ada"], key=K)
q2 = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, token=t["bob"], key=K)
ok("scope: same split key two users both 201", q1.s == 201 and q2.s == 201, (q1, q2))
K = k()
a1 = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=t["ada"], key=K)
a2 = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=t["cy"], key=K)
ok("scope: same request key two users both 201", a1.s == 201 and a2.s == 201, (a1, a2))

# ---- same key, same body, different path is a different request
t = new_t(); K = k()
both = {"to_handle": "bob", "payer_handle": "bob", "amount": 100}
r1 = call("POST", "/payments", both, token=t["ada"], key=K)
r2 = call("POST", "/requests", both, token=t["ada"], key=K)
ok("path: same key+body on /payments then /requests -> both 201, separate effects", r1.s == 201 and r2.s == 201 and "payment_id" in r1.j and "request_id" in r2.j, (r1, r2))
ok("path: each replays on its own path", call("POST", "/payments", both, token=t["ada"], key=K).j == r1.j and call("POST", "/requests", both, token=t["ada"], key=K).j == r2.j)
ra = call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=t["bob"], key=k()).j["request_id"]
rb = call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=t["bob"], key=k()).j["request_id"]
K = k()
p1 = call("POST", "/requests/%s/pay" % ra, {}, token=t["ada"], key=K)
p2 = call("POST", "/requests/%s/pay" % rb, {}, token=t["ada"], key=K)
ok("path: same key+body {} on pay of two different requests -> both 201 (different path)", p1.s == 201 and p2.s == 201 and p1.j["request_id"] == ra and p2.j["request_id"] == rb, (p1, p2))

# ---- JSON-value body equality on payments
t = new_t(); K = k()
o = call("POST", "/payments", raw='{"to_handle":"bob","amount":1000,"note":"n"}', token=t["ada"], key=K)
ok("eq: first 201", o.s == 201, o)
variants = {
    "key order": '{"note":"n","amount":1000,"to_handle":"bob"}',
    "whitespace": ' {\n "to_handle" : "bob" ,\t"amount" :   1000 , "note":"n"\r\n} ',
    "1000.0": '{"to_handle":"bob","amount":1000.0,"note":"n"}',
    "1e3": '{"to_handle":"bob","amount":1e3,"note":"n"}',
    "1E3": '{"to_handle":"bob","amount":1E3,"note":"n"}',
    "escape": '{"to_handle":"bob","amount":1000,"note":"\\u006e"}',
}
for nm, raw in variants.items():
    r = call("POST", "/payments", raw=raw, token=t["ada"], key=K)
    ok("eq: %s is same JSON value -> 200 original" % nm, r.s == 200 and r.j == o.j, r)
diffs = {
    "amount 1001": '{"to_handle":"bob","amount":1001,"note":"n"}',
    "extra unknown field": '{"to_handle":"bob","amount":1000,"note":"n","zz":1}',
    "note omitted vs n": '{"to_handle":"bob","amount":1000}',
    "visibility explicit": '{"to_handle":"bob","amount":1000,"note":"n","visibility":"public"}',
}
for nm, raw in diffs.items():
    r = call("POST", "/payments", raw=raw, token=t["ada"], key=K)
    ok("eq: %s is a different JSON value -> 409 idempotency_key_reuse" % nm, r.s == 409 and r.code == "idempotency_key_reuse", r)
ok("eq: ada balance moved exactly once (1000)", bal(t["ada"]) == 100000 - 1000)

# ---- pay {} vs {"visibility":"public"}
t = new_t()
rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, token=t["bob"], key=k()).j["request_id"]
K = k()
a = call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=K)
b = call("POST", "/requests/%s/pay" % rid, {"visibility": "public"}, token=t["ada"], key=K)
c = call("POST", "/requests/%s/pay" % rid, raw="{ }", token=t["ada"], key=K)
ok("pay: {} then {visibility:public} same key -> 409; {} then '{ }' -> 200", a.s == 201 and b.s == 409 and b.code == "idempotency_key_reuse" and c.s == 200 and c.j == a.j, (a, b, c))
# replay of successful pay when request already paid must not be request_not_pending, moves nothing
r = call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=K)
ok("pay: replay on already-paid request -> 200 original, balance unchanged", r.s == 200 and r.j == a.j and bal(t["ada"]) == 100000 - 50, r)
r = call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=k())
ok("pay: new key on already-paid request -> 409 request_not_pending", r.s == 409 and r.code == "request_not_pending", r)

# ---- failed 4xx key reusable
t = new_t(); dee = t["dee"]
K = k()
r = call("POST", "/payments", {"to_handle": "bob", "amount": 999999}, token=dee, key=K)
ok("failed: 409 insufficient_funds first", r.s == 409, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=dee, key=K)
ok("failed: same key different body after 409 -> treated as first use (201)", r.s == 201, r)
K = k()
for nm, body, st in (("422 amount 0", {"to_handle": "bob", "amount": 0}, 422), ("404 unknown handle", {"to_handle": "zzz", "amount": 5}, 404),
                     ("422 self_payment", {"to_handle": "dee", "amount": 5}, 422)):
    r = call("POST", "/payments", body, token=dee, key=K)
    ok("failed: %s status" % nm, r.s == st, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=dee, key=K)
ok("failed: key reusable after 422/404/422 -> 201", r.s == 201, r)
K = k()
call("POST", "/payments", {"to_handle": "bob", "amount": 4000}, token=dee, key=k())  # dee now ~900
r1 = call("POST", "/payments", {"to_handle": "bob", "amount": 4000}, token=dee, key=K)
call("POST", "/payments", {"to_handle": "dee", "amount": 4000}, token=t["ada"], key=k())  # refund dee
r2 = call("POST", "/payments", {"to_handle": "bob", "amount": 4000}, token=dee, key=K)
ok("failed: same key+body after insufficient_funds then funded -> 201 (not 200/409)", r1.s == 409 and r2.s == 201, (r1, r2))
rid = call("POST", "/requests", {"payer_handle": "dee", "amount": 100000}, token=t["bob"], key=k()).j["request_id"]
K = k()
p1 = call("POST", "/requests/%s/pay" % rid, {}, token=dee, key=K)
call("POST", "/payments", {"to_handle": "dee", "amount": 100000}, token=t["bob"], key=k())
p2 = call("POST", "/requests/%s/pay" % rid, {}, token=dee, key=K)
ok("failed: pay 409 insufficient then funded, same key -> 201", p1.s == 409 and p2.s == 201, (p1, p2))
K = k()
rq1 = call("POST", "/requests", {"payer_handle": "dee", "amount": 5}, token=dee, key=K)
rq2 = call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, token=dee, key=K)
ok("failed: self_request 422 then valid same key -> 201", rq1.s == 422 and rq1.code == "self_request" and rq2.s == 201, (rq1, rq2))
K = k()
s1 = call("POST", "/splits", {"amount": 5, "participant_handles": ["dee", "zzzz"]}, token=dee, key=K)
s2 = call("POST", "/splits", {"amount": 5, "participant_handles": ["dee", "bob"]}, token=dee, key=K)
ok("failed: split 404 then valid same key -> 201; 404 created no requests", s1.s == 404 and s2.s == 201 and len(s2.j["requests"]) == 1, (s1, s2))
K = k()
s1 = call("POST", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "bob", "amount": 10 ** 8}]}, token=t["op"], key=K)
s2 = call("POST", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "bob", "amount": 1}]}, token=t["op"], key=K)
ok("failed: settlement 409 then different body same key -> 201", s1.s == 409 and s1.code == "insufficient_funds" and s2.s == 201, (s1, s2))

# ---- key-before-auth/validation ordering observations (spec-silent precedence; recorded, not asserted)
t = new_t()
r_noauth_nokey = call("POST", "/payments", {"to_handle": "bob", "amount": 1})
r_noauth_key = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, key=k())
r_badjson_key = call("POST", "/payments", raw="{bad", token=t["ada"], key=k())
r_badjson_nokey = call("POST", "/payments", raw="{bad", token=t["ada"])
r_invalid_nokey = call("POST", "/payments", {"to_handle": "bob", "amount": -1}, token=t["ada"])
print("OBS no token,no key ->", r_noauth_nokey.s, r_noauth_nokey.code, "| no token,key ->", r_noauth_key.s, r_noauth_key.code)
print("OBS bad JSON,key ->", r_badjson_key.s, r_badjson_key.code, "| bad JSON,no key ->", r_badjson_nokey.s, r_badjson_nokey.code, "| invalid amount,no key ->", r_invalid_nokey.s, r_invalid_nokey.code)
ok("unauthenticated (no token) -> 401", r_noauth_key.s == 401 and r_noauth_key.code == "unauthenticated", r_noauth_key)

done("c02_idempotency")
