"""J20-J23, J34, J56, J59-J61, J65: requests lifecycle, feed visibility, paging, roles."""
import time
from lib import *

t = setup(fx(requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]))
ADA, BOB, CY, DEE = t["ada"], t["bob"], t["cy"], t["dee"]


def feed(tok, q="limit=200"):
    return call("GET", "/activity?" + q, token=tok).j["payments"]


def reqs(tok, q="limit=200"):
    return call("GET", "/requests?" + q, token=tok).j["requests"]


def mk(tok, payer, amt, note=""):
    r = call("POST", "/requests", {"payer_handle": payer, "amount": amt, "note": note}, token=tok, key=k())
    assert r.s == 201, r
    return r.j


# ---- request shape
q = mk(BOB, "ada", 300, "lunch")
ok("request body exact shape, status pending, payment_id null, no visibility field",
   set(q) == {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount", "currency", "note", "status", "payment_id", "created_at"}
   and q["status"] == "pending" and q["payment_id"] is None and q["requester_id"] == "u_bob" and q["payer_id"] == "u_ada" and q["currency"] == "EUR" and RFC3339.match(q["created_at"]), q)
ok("self_request 422", (lambda r: r.s == 422 and r.code == "self_request")(call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, token=BOB, key=k())))
ok("unknown payer 404", (lambda r: r.s == 404 and r.code == "not_found")(call("POST", "/requests", {"payer_handle": "zz", "amount": 5}, token=BOB, key=k())))
ok("note>200 -> 422", call("POST", "/requests", {"payer_handle": "ada", "amount": 5, "note": "x" * 201}, token=BOB, key=k()).s == 422)
big = mk(CY, "dee", 10 ** 9)
ok("request of 1e9 from a payer holding 5000 is created pending (no balance check)", big["status"] == "pending" and bal(DEE) == 5000)

# ---- request visibility / listing
ok("third party cy sees neither bob->ada request", all(x["request_id"] not in (q["request_id"], "rq_1") for x in reqs(CY)))
ok("ada (payer) and bob (requester) both see it", q["request_id"] in [x["request_id"] for x in reqs(ADA)] and q["request_id"] in [x["request_id"] for x in reqs(BOB)])
ok("requests never appear in any feed", all(set(p) >= {"payment_id", "amount"} and "status" not in p for h in (ADA, BOB, CY, DEE) for p in feed(h)))
ok("incoming/outgoing split", q["request_id"] in [x["request_id"] for x in reqs(ADA, "direction=incoming")] and q["request_id"] not in [x["request_id"] for x in reqs(ADA, "direction=outgoing")]
   and q["request_id"] in [x["request_id"] for x in reqs(BOB, "direction=outgoing")])
ok("GET /requests returns only caller's requests (cy: 1e9 outgoing only)", [x["request_id"] for x in reqs(CY)] == [big["request_id"]])

# ---- ordering (same-second) and paging
t2 = setup(fx())
BOB2, ADA2 = t2["bob"], t2["ada"]
ids = [mk(BOB2, "ada", 10 + i)["request_id"] for i in range(7)]
lst = reqs(ADA2)
ok("GET /requests newest first (deterministic even within one second)", [x["request_id"] for x in lst] == ids[::-1], [x["request_id"] for x in lst])
ok("created_at non-increasing", all(lst[i]["created_at"] >= lst[i + 1]["created_at"] for i in range(len(lst) - 1)))
p1 = call("GET", "/requests?limit=3&offset=0", token=ADA2).j
p2 = call("GET", "/requests?limit=3&offset=3", token=ADA2).j
p3 = call("GET", "/requests?limit=3&offset=6", token=ADA2).j
p4 = call("GET", "/requests?limit=7&offset=0", token=ADA2).j
p5 = call("GET", "/requests?limit=6&offset=0", token=ADA2).j
p6 = call("GET", "/requests?limit=3&offset=7", token=ADA2).j
ok("paging: 3+3+1 pages, has_more true,true,false, no overlap, union == all",
   [len(p["requests"]) for p in (p1, p2, p3)] == [3, 3, 1] and [p["has_more"] for p in (p1, p2, p3)] == [True, True, False]
   and [x["request_id"] for p in (p1, p2, p3) for x in p["requests"]] == ids[::-1])
ok("paging: limit==total -> has_more false; limit=total-1 -> true; offset==total -> empty,false",
   p4["has_more"] is False and len(p4["requests"]) == 7 and p5["has_more"] is True and p6["requests"] == [] and p6["has_more"] is False)
pay1 = call("POST", "/requests/%s/pay" % ids[0], {}, token=ADA2, key=k())
call("POST", "/requests/%s/decline" % ids[1], {}, token=ADA2)
ok("status filter", [x["request_id"] for x in reqs(ADA2, "status=paid")] == [ids[0]] and [x["request_id"] for x in reqs(ADA2, "status=declined")] == [ids[1]]
   and len(reqs(ADA2, "status=pending")) == 5 and reqs(ADA2, "status=cancelled") == [])

# ---- lifecycle matrix
def fresh():
    tt = setup(fx(requests=[]))
    return tt


tt = fresh(); A, B, C, D = tt["ada"], tt["bob"], tt["cy"], tt["dee"]
r = mk(B, "ada", 500, "n")
rid = r["request_id"]
for nm, who, act, st, code in (("requester pays", B, "pay", 403, "forbidden"), ("stranger pays", C, "pay", 403, "forbidden"), ("requester declines", B, "decline", 403, "forbidden"),
                               ("stranger declines", C, "decline", 403, "forbidden"), ("payer cancels", A, "cancel", 403, "forbidden"), ("stranger cancels", C, "cancel", 403, "forbidden")):
    x = call("POST", "/requests/%s/%s" % (rid, act), {}, token=who, key=k())
    ok("%s -> %d %s" % (nm, st, code), x.s == st and x.code == code, x)
ok("403s changed nothing", reqs(A)[0]["status"] == "pending" and bal(A) == 10000 and bal(B) == 2500)
for act, who in (("pay", A), ("decline", A), ("cancel", B)):
    x = call("POST", "/requests/rq_nope/%s" % act, {}, token=who, key=k())
    ok("unknown request %s -> 404 not_found" % act, x.s == 404 and x.code == "not_found", x)
x = call("POST", "/requests/%s/decline" % rid, {}, token=A)
ok("decline -> 200 status declined, same shape", x.s == 200 and x.j["status"] == "declined" and x.j["request_id"] == rid and x.j["payment_id"] is None, x)
x2 = call("POST", "/requests/%s/decline" % rid, {}, token=A)
ok("decline twice -> 200 current state", x2.s == 200 and x2.j == x.j, x2)
x = call("POST", "/requests/%s/pay" % rid, {}, token=A, key=k())
ok("pay after decline -> 409 request_not_pending, no money", x.s == 409 and x.code == "request_not_pending" and bal(A) == 10000, x)
x = call("POST", "/requests/%s/cancel" % rid, {}, token=B)
ok("cancel declined -> 409 request_not_pending", x.s == 409 and x.code == "request_not_pending", x)
r2 = mk(B, "ada", 500)["request_id"]
x = call("POST", "/requests/%s/cancel" % r2, {}, token=B)
ok("cancel -> 200 status cancelled", x.s == 200 and x.j["status"] == "cancelled", x)
ok("cancel twice -> 200", call("POST", "/requests/%s/cancel" % r2, {}, token=B).j == x.j)
ok("pay cancelled -> 409; decline cancelled -> 409", call("POST", "/requests/%s/pay" % r2, {}, token=A, key=k()).code == "request_not_pending" and call("POST", "/requests/%s/decline" % r2, {}, token=A).code == "request_not_pending")
r3 = mk(B, "ada", 500, "memo")["request_id"]
p = call("POST", "/requests/%s/pay" % r3, {"visibility": "private"}, token=A, key=k())
ok("pay -> 201 payment with request_id, private, amount, parties", p.s == 201 and p.j["request_id"] == r3 and p.j["visibility"] == "private" and p.j["from_handle"] == "ada" and p.j["to_handle"] == "bob" and p.j["amount"] == 500, p)
ok("balances moved once", (bal(A), bal(B)) == (9500, 3000))
got = [x for x in reqs(A) if x["request_id"] == r3][0]
ok("request paid with payment_id", got["status"] == "paid" and got["payment_id"] == p.j["payment_id"], got)
ok("decline/cancel paid -> 409", call("POST", "/requests/%s/decline" % r3, {}, token=A).code == "request_not_pending" and call("POST", "/requests/%s/cancel" % r3, {}, token=B).code == "request_not_pending")
ok("private payment from request hidden from cy, visible to ada and bob, same body", all(p.j["payment_id"] not in [x["payment_id"] for x in feed(C)] for _ in [0])
   and [x for x in feed(A) if x["payment_id"] == p.j["payment_id"]] == [x for x in feed(B) if x["payment_id"] == p.j["payment_id"]] == [p.j])
x = call("POST", "/requests/%s/pay" % r3, {}, token=A, key=k())
ok("pay already paid (new key) -> 409 request_not_pending", x.s == 409 and x.code == "request_not_pending", x)
# decline/cancel need no key, tolerate empty/odd bodies
r4 = mk(B, "ada", 5)["request_id"]
ok("decline with empty body and no key -> 200", call("POST", "/requests/%s/decline" % r4, raw="", token=A).s == 200)
r5 = mk(B, "ada", 5)["request_id"]
ok("cancel with no body, junk key header -> 200", call("POST", "/requests/%s/cancel" % r5, token=B, key="whatever").s == 200)

# ---- pay with payer short, then funded
tt = fresh(); A, B, C, D = tt["ada"], tt["bob"], tt["cy"], tt["dee"]
rq = mk(B, "ada", 12000)["request_id"]
x = call("POST", "/requests/%s/pay" % rq, {}, token=A, key=k())
ok("pay above balance -> 409 insufficient_funds, nothing changed", x.s == 409 and x.code == "insufficient_funds" and bal(A) == 10000 and reqs(A)[0]["status"] == "pending" and reqs(A)[0]["payment_id"] is None)
call("POST", "/payments", {"to_handle": "ada", "amount": 5000}, token=D, key=k())
x = call("POST", "/requests/%s/pay" % rq, {}, token=A, key=k())
ok("after funding the same request is payable (201), balance 3000", x.s == 201 and bal(A) == 3000 and bal(B) == 14500, x)
ok("money conserved", sum(bal(z) for z in (A, B, C, D)) == 17500)

# ---- public/private matrix + feed contract
tt = fresh(); A, B, C, D = tt["ada"], tt["bob"], tt["cy"], tt["dee"]
pub = call("POST", "/payments", {"to_handle": "bob", "amount": 10, "visibility": "public", "note": "pub"}, token=A, key=k()).j
prv = call("POST", "/payments", {"to_handle": "bob", "amount": 11, "visibility": "private", "note": "prv"}, token=A, key=k()).j
dft = call("POST", "/payments", {"to_handle": "bob", "amount": 12}, token=A, key=k()).j
ids_ = lambda tok: [x["payment_id"] for x in feed(tok)]
ok("cy (third party) sees public+default, not private", set(ids_(C)) == {pub["payment_id"], dft["payment_id"]}, ids_(C))
ok("sender and receiver both see the private payment; identical body", prv["payment_id"] in ids_(A) and prv["payment_id"] in ids_(B)
   and [x for x in feed(A) if x["payment_id"] == prv["payment_id"]] == [x for x in feed(B) if x["payment_id"] == prv["payment_id"]] == [prv])
ok("feed newest first (reverse creation)", ids_(A) == [dft["payment_id"], prv["payment_id"], pub["payment_id"]] and ids_(C) == [dft["payment_id"], pub["payment_id"]])
pg = call("GET", "/activity?limit=2&offset=0", token=A).j
ok("activity paging has_more", len(pg["payments"]) == 2 and pg["has_more"] is True and call("GET", "/activity?limit=2&offset=2", token=A).j["has_more"] is False)
ok("private payment between other two users hidden from third party dee", prv["payment_id"] not in ids_(D))
# seeded payments: private/public from fixture follow the same rule
fxp = fx(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                   {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 700, "note": "secret", "visibility": "private"}])
ts = setup(fxp)
ok("seeded payments: public visible to cy, private not; ids preserved; balances not replayed",
   [x["payment_id"] for x in feed(ts["cy"])] == ["p_1"] and sorted(x["payment_id"] for x in feed(ts["bob"])) == ["p_1", "p_2"] and (bal(ts["ada"]), bal(ts["bob"])) == (10000, 2500))
# 0-amount request (via split) payable? record only
sp = call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, token=ts["ada"], key=k()).j
zr = sp["requests"][0]
zp = call("POST", "/requests/%s/pay" % zr["request_id"], {}, token=ts["bob"], key=k())
print("OBS pay 0-amount request ->", zp.s, zp.b[:200])

done("c05_requests_feed")
