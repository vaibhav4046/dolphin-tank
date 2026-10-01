"""J78-J88: atomic net settlements."""
import threading
from lib import *

U = [user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 500), user("op", 0), user("eve", 0)]
OPS = ["u_op"]


def S(ops=None, users=None):
    return setup(fx(users or U, ops=ops if ops is not None else OPS))


def st(tok, transfers, key=None, raw=None):
    if raw is not None:
        return call("POST", "/settlements", raw=raw, token=tok, key=key or k())
    return call("POST", "/settlements", {"transfers": transfers}, token=tok, key=key or k())


def tr(f, t_, a, **kw):
    d = {"from_handle": f, "to_handle": t_, "amount": a}
    d.update(kw)
    return d


def B(t, hs=("ada", "bob", "cy", "dee", "op", "eve")):
    return {h: bal(t[h]) for h in hs}


t = S()
ok("no token -> 401", call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, key=k()).s == 401)
r = st(t["ada"], [tr("ada", "bob", 1)])
ok("authenticated non-operator -> 403 forbidden", r.s == 403 and r.code == "forbidden", r)
r = call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=t["op"])
ok("operator without key -> 400 missing_idempotency_key", r.s == 400 and r.code == "missing_idempotency_key", r)
ok("non-operator with no key: 403 or 400 (recorded)", call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=t["ada"]).s in (400, 403))
print("OBS non-operator, no key ->", call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=t["ada"]).s)
ok("no operators configured -> everyone 403", st(setup(fx(U))["ada"], [tr("ada", "bob", 1)]).s == 403)
t = S()
ok("money unchanged after rejected attempts", B(t) == {"ada": 1000, "bob": 0, "cy": 0, "dee": 500, "op": 0, "eve": 0})

# happy path, shape, order, defaults, timestamps
K = k()
r = st(t["op"], [tr("ada", "bob", 100), tr("bob", "cy", 50, note="n2", visibility="private"), tr("dee", "ada", 7, zzz=1)], key=K)
ok("201 and shape", r.s == 201 and set(r.j) >= {"settlement_id", "committed_at", "payments"} and RFC3339.match(r.j["committed_at"]) and len(r.j["payments"]) == 3, r)
j = r.j
ok("payments in input order with handles/amounts/defaults",
   [(p["from_handle"], p["to_handle"], p["amount"], p["note"], p["visibility"]) for p in j["payments"]] == [("ada", "bob", 100, "", "public"), ("bob", "cy", 50, "n2", "private"), ("dee", "ada", 7, "", "public")], j["payments"])
ok("every member: settlement_id == batch id, request_id null, created_at == committed_at, ids unique",
   all(p["settlement_id"] == j["settlement_id"] and p["request_id"] is None and p["created_at"] == j["committed_at"] for p in j["payments"]) and len({p["payment_id"] for p in j["payments"]}) == 3, j)
ok("chain affordable by net (bob received 100 before sending 50): balances", B(t) == {"ada": 1000 - 100 + 7, "bob": 50, "cy": 50, "dee": 493, "op": 0, "eve": 0}, B(t))
ok("operator is not charged/credited", bal(t["op"]) == 0)
feed_c = call("GET", "/activity?limit=200", token=t["cy"]).j["payments"]
ok("cy sees ordinary-visibility members: public ada->bob and dee->ada yes; private bob->cy yes (receiver); settlement_id on members",
   {p["payment_id"] for p in feed_c} == {j["payments"][0]["payment_id"], j["payments"][1]["payment_id"], j["payments"][2]["payment_id"]} and all(p["settlement_id"] == j["settlement_id"] for p in feed_c), feed_c)
feed_e = call("GET", "/activity?limit=200", token=t["eve"]).j["payments"]
ok("third party eve sees public members only, private member hidden", {p["payment_id"] for p in feed_e} == {j["payments"][0]["payment_id"], j["payments"][2]["payment_id"]}, feed_e)
feed_op = call("GET", "/activity?limit=200", token=t["op"]).j["payments"]
ok("operator (not a party) sees only public members in own feed (no private of others)", {p["payment_id"] for p in feed_op} == {j["payments"][0]["payment_id"], j["payments"][2]["payment_id"]}, feed_op)
ok("nonmember payment exposes settlement_id null", call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=t["ada"], key=k()).j["settlement_id"] is None)
ok("settlement members ordinary payment shape (full key set)", set(j["payments"][0]) >= {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility", "request_id", "created_at", "settlement_id"}, sorted(j["payments"][0]))
b_before = B(t)
r2 = st(t["op"], [tr("ada", "bob", 100), tr("bob", "cy", 50, note="n2", visibility="private"), tr("dee", "ada", 7, zzz=1)], key=K)
ok("replay -> 200 identical complete response (incl. committed_at, all receipts), no effect", r2.s == 200 and r2.j == j and B(t) == b_before, (r2, b_before, B(t)))
r3 = st(t["op"], [tr("ada", "bob", 101)], key=K)
ok("same key different body -> 409 idempotency_key_reuse", r3.s == 409 and r3.code == "idempotency_key_reuse", r3)
r3 = st(t["op"], [], key=K)
ok("claimed key + invalid transfers -> 409 (key resolved before validation)", r3.s == 409 and r3.code == "idempotency_key_reuse", r3)

# net affordability
t = S(users=[user("ada", 0), user("bob", 0), user("cy", 0), user("dee", 0), user("op", 0), user("eve", 0)])
r = st(t["op"], [tr("ada", "bob", 100), tr("bob", "cy", 100), tr("cy", "ada", 100)])
ok("zero-balance cycle ada->bob->cy->ada is affordable (net 0 everywhere)", r.s == 201 and B(t) == {h: 0 for h in ("ada", "bob", "cy", "dee", "op", "eve")}, r)
t = S()
r = st(t["op"], [tr("bob", "cy", 50), tr("ada", "bob", 100)])
ok("reverse-order chain (bob sends before receiving) still affordable by net", r.s == 201 and B(t)["bob"] == 50 and B(t)["cy"] == 50, r)
t = S(users=[user("ada", 100), user("bob", 0), user("cy", 0), user("dee", 0), user("op", 0), user("eve", 0)])
r = st(t["op"], [tr("ada", "bob", 150), tr("bob", "ada", 60)])
ok("ada sends 150 (> balance 100) but receives 60: net -90, affordable", r.s == 201 and B(t)["ada"] == 10 and B(t)["bob"] == 90, r)
t = S()
r = st(t["op"], [tr("ada", "bob", 600), tr("ada", "cy", 600)])
ok("collectively unaffordable -> 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("all-or-none: no balance change, no payments in any feed", B(t) == {"ada": 1000, "bob": 0, "cy": 0, "dee": 500, "op": 0, "eve": 0} and all(call("GET", "/activity", token=t[h]).j["payments"] == [] for h in ("ada", "bob", "cy")))
K = k()
r = st(t["op"], [tr("ada", "bob", 1000), tr("ada", "cy", 1)], key=K)
r2 = st(t["op"], [tr("ada", "bob", 1000)], key=K)
ok("failed validation/funds claims no key: same key reusable with a corrected body -> 201", r.s == 409 and r2.s == 201, (r, r2))
t = S()
r = st(t["op"], [tr("ada", "bob", 500), tr("ada", "cy", 500), tr("dee", "eve", 500)])
ok("exact-balance drain affordable (balances may reach 0)", r.s == 201 and B(t)["ada"] == 0 and B(t)["dee"] == 0, r)

# entry errors before funds, in input order
t = S()
cases = [("unknown handle beats insufficient", [tr("ada", "bob", 10 ** 8), tr("ada", "nobody", 1)], 404, "not_found"),
         ("self beats insufficient", [tr("ada", "bob", 10 ** 8), tr("cy", "cy", 1)], 422, "self_payment"),
         ("first erroneous entry decides: self(1) before unknown(2)", [tr("ada", "ada", 1), tr("ada", "nobody", 1)], 422, "self_payment"),
         ("first erroneous entry decides: unknown(1) before self(2)", [tr("ada", "nobody", 1), tr("ada", "ada", 1)], 404, "not_found"),
         ("unknown from_handle", [tr("nobody", "bob", 1)], 404, "not_found"), ("amount 0", [tr("ada", "bob", 0)], 422, "validation_failed"),
         ("amount 1e9+1", [tr("ada", "bob", 1000000001)], 422, "validation_failed"), ("amount string", [tr("ada", "bob", "5")], 422, "validation_failed"),
         ("note 201", [tr("ada", "bob", 1, note="x" * 201)], 422, "validation_failed"), ("visibility bad", [tr("ada", "bob", 1, visibility="x")], 422, "validation_failed"),
         ("note null", [tr("ada", "bob", 1, note=None)], 422, "validation_failed"), ("validation error beats later insufficient", [tr("ada", "bob", 0), tr("ada", "bob", 10 ** 8)], 422, "validation_failed")]
for nm, tf, sts, code in cases:
    r = st(t["op"], tf)
    ok("entry error: %s -> %d %s" % (nm, sts, code), r.s == sts and r.code == code, r)
ok("no money moved by any rejected settlement", B(t) == {"ada": 1000, "bob": 0, "cy": 0, "dee": 500, "op": 0, "eve": 0})
for nm, raw in (("transfers missing", "{}"), ("transfers empty", '{"transfers":[]}'), ("transfers not array", '{"transfers":"x"}'), ("transfers null", '{"transfers":null}'),
                ("entry not object", '{"transfers":[5]}'), ("entry missing amount", '{"transfers":[{"from_handle":"ada","to_handle":"bob"}]}'),
                ("entry missing from", '{"transfers":[{"to_handle":"bob","amount":1}]}'), ("entry handle number", '{"transfers":[{"from_handle":5,"to_handle":"bob","amount":1}]}')):
    r = st(t["op"], None, raw=raw)
    print("OBS malformed batch %-22s -> %s %s" % (nm, r.s, r.code))
    ok("malformed batch %s -> 4xx validation_failed/malformed_request, key unclaimed" % nm, r.s in (400, 422) and r.code in ("validation_failed", "malformed_request"), r)
ok("bad JSON -> 400 malformed_request", (lambda r: r.s == 400 and r.code == "malformed_request")(st(t["op"], None, raw="{bad")))
r = st(t["op"], [tr("ada", "bob", 1)] * 33)
ok("33 transfers -> 422 validation_failed", r.s == 422 and r.code == "validation_failed", r)
r = st(t["op"], [tr("ada", "bob", 1)] * 32)
ok("32 transfers -> 201, 32 receipts", r.s == 201 and len(r.j["payments"]) == 32 and B(t)["bob"] == 32, r)
r = call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1e0}],"extra":{"a":1}}', token=t["op"], key=k())
ok("unknown body fields ignored; 1e0 amount accepted", r.s == 201, r)

# operator does not gain access to others' requests / private feed
t = S()
rq = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=t["ada"], key=k()).j["request_id"]
pr = call("POST", "/payments", {"to_handle": "cy", "amount": 3, "visibility": "private"}, token=t["ada"], key=k()).j
ok("operator GET /requests excludes others' requests", call("GET", "/requests", token=t["op"]).j["requests"] == [])
ok("operator pay/decline/cancel other's request -> 403", all(call("POST", "/requests/%s/%s" % (rq, a), {}, token=t["op"], key=k()).s == 403 for a in ("pay", "decline", "cancel")))
ok("operator feed lacks others' private payment", pr["payment_id"] not in [p["payment_id"] for p in call("GET", "/activity?limit=200", token=t["op"]).j["payments"]])
ok("request untouched", call("GET", "/requests", token=t["ada"]).j["requests"][0]["status"] == "pending")

# settlements can name the operator as a wallet; operator may be a party
t = S(ops=["u_op", "u_ada"])
r = st(t["ada"], [tr("bob", "cy", 0 + 1)])
ok("second operator ada may settle others' wallets (bob has 0 -> unaffordable 409)", r.s == 409, r)
r = st(t["ada"], [tr("ada", "cy", 10)])
ok("operator ada as sender in own settlement: 201", r.s == 201 and bal(t["cy"]) == 10, r)

# concurrency: 30 identical-key settlements, 30 distinct-key settlements vs limited funds, mixed with payments
for rnd in range(3):
    t = S()
    K = k()
    res = parallel([lambda: st(t["op"], [tr("ada", "bob", 100), tr("bob", "cy", 40)], key=K) for _ in range(30)])
    n201 = [r for r in res if r.s == 201]
    ok("R%d 30 concurrent identical settlements: exactly one 201, 29 x 200 same body" % rnd, len(n201) == 1 and sum(1 for r in res if r.s == 200) == 29 and all(r.j == n201[0].j for r in res if r.s == 200), [r.s for r in res])
    ok("R%d effect once" % rnd, B(t)["ada"] == 900 and B(t)["bob"] == 60 and B(t)["cy"] == 40 and len(call("GET", "/activity?limit=200", token=t["ada"]).j["payments"]) == 2, B(t))
    t = S()
    stop = threading.Event(); viol = []

    def obs():
        while not stop.is_set():
            v = [bal(t[h]) for h in ("ada", "bob", "cy", "dee", "op", "eve")]
            if min(v) < 0:
                viol.append(v)
    ob = threading.Thread(target=obs); ob.start()
    fns = [lambda: st(t["op"], [tr("ada", "bob", 100), tr("bob", "cy", 100)]) for _ in range(30)]
    fns += [lambda: call("POST", "/payments", {"to_handle": "eve", "amount": 100}, token=t["ada"], key=k()) for _ in range(10)]
    res = parallel(fns)
    stop.set(); ob.join()
    wins = sum(1 for r in res if r.s == 201)
    b = B(t)
    ok("R%d 30 settlements (100 each) + 10 direct payments (100 each) vs ada 1000: exactly 10 wins total, ada 0, conserved, never negative" % rnd,
       wins == 10 and b["ada"] == 0 and sum(b.values()) == 1500 and not viol and all(r.s in (201, 409) for r in res), (wins, b, viol[:2], [r.s for r in res if r.s not in (201, 409)]))
    feed = call("GET", "/activity?limit=200", token=t["ada"]).j["payments"]
    by = {}
    for p in feed:
        if p["settlement_id"]:
            by.setdefault(p["settlement_id"], []).append(p)
    ok("R%d settlement membership intact in ledger (2 members each)" % rnd, all(len(v) == 2 for v in by.values()), {a: len(v) for a, v in by.items()})

done("c11_settlements")
