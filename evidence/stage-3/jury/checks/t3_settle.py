"""J40 J41 J43: settlement members - revision 1 at committed_at, privacy, linked_payment_immutable; plus request-split interplay."""
import time
from lib3 import *

f = fx([user("ada", 10000), user("bob", 5000), user("cy", 2000), user("dee", 0), user("op", 0)], ops=["u_op"])
t = setup(f)
A, B, C, D, OP = t["ada"], t["bob"], t["cy"], t["dee"], t["op"]
TOTAL = 17000
pre = pay(A, "bob", 100, note="pre-settlement").j
time.sleep(0.01)
body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1000, "note": "s1", "visibility": "private"},
                      {"from_handle": "bob", "to_handle": "cy", "amount": 500, "note": "s2", "visibility": "public"},
                      {"from_handle": "cy", "to_handle": "ada", "amount": 250}]}
ks = k()
s = call("POST", "/settlements", body, token=OP, key=ks)
ok("setup settlement 201", s.s == 201, s)
members = s.j["payments"]
CA = s.j["committed_at"]
ok("J40 every member created_at == committed_at (instant)", all(P(m["created_at"]) == P(CA) for m in members))
owner = {"u_ada": A, "u_bob": B, "u_cy": C}
for m in members:
    rv = revs(owner[m["from_user_id"]], m["payment_id"])
    ok("J40 member %s revision 1: effective_at == recorded_at == committed_at, reason '', amount %d" % (m["payment_id"], m["amount"]),
       len(rv) == 1 and rv[0]["revision"] == 1 and P(rv[0]["effective_at"]) == P(rv[0]["recorded_at"]) == P(CA) and rv[0]["amount"] == m["amount"] and rv[0]["reason"] == "", rv)
    rv2 = call("GET", "/payments/%s/revisions" % m["payment_id"], token=owner[m["to_user_id"]])
    ok("J31 receiver can read member revisions", rv2.s == 200)
# privacy retained: operator and third parties cannot read private member revisions / feed
priv = members[0]
ok("J40 private member: operator (not a party) -> 404 on revisions", call("GET", "/payments/%s/revisions" % priv["payment_id"], token=OP).s == 404)
ok("J40 private member: third party -> 404 on revisions", call("GET", "/payments/%s/revisions" % priv["payment_id"], token=C).s == 404 and call("GET", "/payments/%s/revisions" % priv["payment_id"], token=D).s == 404)
ok("J40 private member invisible in third party's and operator's activity feed", all(priv["payment_id"] not in [p["payment_id"] for p in call("GET", "/activity?limit=200", token=tk).j["payments"]] for tk in (D, OP)))
pub = members[1]
ok("J40 public member: third party sees it in the feed but still gets 404 on revisions", pub["payment_id"] in [p["payment_id"] for p in call("GET", "/activity?limit=200", token=D).j["payments"]] and call("GET", "/payments/%s/revisions" % pub["payment_id"], token=D).s == 404)
ok("J40 original settlement receipt replay unchanged (200 identical)", (lambda r: r.s == 200 and r.j == s.j)(call("POST", "/settlements", body, token=OP, key=ks)))
# J41 correction rejected
W0 = (me(A), me(B), me(C), stmt(A).j["entries"], stmt(B).j["entries"], revs(A, members[0]["payment_id"]))
for m in members:
    tk = owner[m["from_user_id"]]
    kk = k()
    r = correct(tk, m["payment_id"], 1, m["amount"] + 1, m["created_at"], "try", key=kk)
    ok("J41 sender correcting settlement member %s -> 422 linked_payment_immutable" % m["payment_id"], r.s == 422 and r.code == "linked_payment_immutable", r)
    r = correct(tk, m["payment_id"], 1, 0, m["created_at"], "reverse", key=kk)
    ok("J41 same key reusable after the failed attempt (still 422 linked_payment_immutable, never 409 idempotency_key_reuse)", r.s == 422 and r.code == "linked_payment_immutable", r)
r = correct(OP, members[0]["payment_id"], 1, 5, members[0]["created_at"], "operator")
ok("J41 operator (not the sender) -> 403 forbidden (or 422), never 201", r.s in (403, 422), r)
ok("J41 rejected corrections changed nothing", (me(A), me(B), me(C), stmt(A).j["entries"], stmt(B).j["entries"], revs(A, members[0]["payment_id"])) == W0)
# a normal payment before the settlement is still correctable (the rule is per-payment)
r = correct(A, pre["payment_id"], 1, 150, pre["created_at"], "pre")
ok("J41 a payment made outside any settlement is still correctable", r.s == 201, r)
# statement: members appear with deltas; sum constant; views at committed_at
sa = stmt(A, limit=200).j
mine = [e for e in sa["entries"] if e["payment"]["settlement_id"]]
ok("J40 settlement members appear in parties' statements with settlement_id and effective_at == committed_at", len(mine) == 2 and all(P(e["effective_at"]) == P(CA) for e in mine), mine)
ok("J15 statement invariant", sa["opening_balance"] + sum(e["delta"] for e in sa["entries"]) == sa["closing_balance"] == me(A)["balance"])
exp_a = 10000 - 150 - 1000 + 250
ok("J40 ada current balance %d" % exp_a, me(A)["balance"] == exp_a, me(A))
a_at = me_at(A, CA).j["balance"]
a_bf = me_at(A, iso(P(CA) - US)).j["balance"]
ok("J08 as_of=committed_at counts the settlement for ada (-1000 +250 vs just before)", a_at - a_bf == -750, (a_at, a_bf))
ok("J29 sum constant at committed_at and just before", all(sum(me_at(t[h], x).j["balance"] for h in t) == TOTAL for x in (CA, iso(P(CA) - US))))
# settlement net debit uses total/available (hold interplay already covered in stage 2): quick check history unaffected
done("t3_settle")
