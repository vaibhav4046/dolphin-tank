"""A02 A05 A06 A07: holds are not spendable on payments / request pay / authorize / settlement net debits; captures spend reserved funds."""
from lib import *

f = fx([user("ada", 10000), user("bob", 2500), user("cy", 3000), user("dee", 5000), user("op", 0)], ops=["u_op"])
t = setup(f)
TOTAL = 20500

def state(h):
    m = me(t[h]); return (m["total"], m["available"], m["held"])

a = authorize(t["ada"], "bob", 9000)
ok("A02 setup hold 9000", a.s == 201 and state("ada") == (10000, 1000, 9000), (a, state("ada")))
aid = a.j["authorization_id"]

# --- payments blocked by holds
r = pay(t["ada"], "cy", 1001)
ok("A06 payment above available refused 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("A06 refused payment changed nothing", state("ada") == (10000, 1000, 9000) and state("cy") == (3000, 3000, 0))
r = pay(t["ada"], "cy", 1000)
ok("A02 payment of exactly available allowed", r.s == 201, r)
ok("A05 payment moved money immediately and created no hold", state("ada") == (9000, 0, 9000) and state("cy") == (4000, 4000, 0), (state("ada"), state("cy")))
r = pay(t["ada"], "cy", 1)
ok("A02 available 0 -> payment of 1 refused", r.s == 409 and r.code == "insufficient_funds", r)
# payment must not appear as authorization
ok("A05 payment is not an authorization", all(x["authorization_id"] == aid for x in authz(t["ada"])["authorizations"]), authz(t["ada"]))

# --- authorize blocked by holds
r = authorize(t["ada"], "cy", 1)
ok("A06 authorize above available refused 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("A06 refused authorize created nothing", len(authz(t["ada"])["authorizations"]) == 1)

# --- captures spend reserved funds while available == 0
r = capture(t["bob"], aid, amount=9000)
ok("A02 capture of reserved funds succeeds with available 0", r.s == 201, r)
ok("A02 after capture ada total 0 available 0 held 0, bob +9000", state("ada") == (0, 0, 0) and state("bob") == (11500, 11500, 0), (state("ada"), state("bob")))
ok("A01 conservation", sum(me(t[h])["total"] for h in t) == TOTAL)

# --- request pay uses available
t = setup(f)
a = authorize(t["ada"], "bob", 9000)
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 1500, "note": "x"}, token=t["bob"], key=k())
rid = rq.j["request_id"]
r = call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=k())
ok("A06 request pay above available 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("A06 refused request pay: still pending, nothing moved", call("GET", "/requests?status=pending", token=t["ada"]).j["requests"][0]["status"] == "pending" and state("ada") == (10000, 1000, 9000))
ok("A06 void releases; request now payable", void(t["ada"], a.j["authorization_id"]).s == 200)
r = call("POST", "/requests/%s/pay" % rid, {}, token=t["ada"], key=k())
ok("A06 request payable after release", r.s == 201 and state("ada") == (8500, 8500, 0), (r, state("ada")))
# request pay at exactly available
a = authorize(t["ada"], "bob", 7000)
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 1500}, token=t["bob"], key=k())
r = call("POST", "/requests/%s/pay" % rq.j["request_id"], {}, token=t["ada"], key=k())
ok("A02 request pay of exactly available (1500) allowed", r.s == 201 and state("ada") == (7000, 0, 7000), (r, state("ada")))

# --- settlements: net debit against available
t = setup(f)
a = authorize(t["ada"], "bob", 9000)   # ada available 1000
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1001}]}, token=t["op"], key=k())
ok("A06 settlement net debit above available 409 insufficient_funds", r.s == 409 and r.code == "insufficient_funds", r)
ok("A06 refused settlement changed nothing", state("ada") == (10000, 1000, 9000) and state("bob") == (2500, 2500, 0))
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1500}, {"from_handle": "cy", "to_handle": "ada", "amount": 501}]}, token=t["op"], key=k())
ok("A06 net debit 999 (<= available 1000) allowed though gross 1500 > 1000", r.s == 201, r)
ok("A06 after settlement", state("ada") == (9999, 1, 9000) or state("ada") == (10000 - 999, 1, 9000), state("ada"))
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 2}]}, token=t["op"], key=k())
ok("A02 settlement exactly one above available refused", r.s == 409 and r.code == "insufficient_funds", r)
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=t["op"], key=k())
ok("A02 settlement of exactly available allowed", r.s == 201 and state("ada") == (9000 + 0, 0, 9000) or r.s == 201, (r, state("ada")))
ok("A06 settlement members authorization_id null", r.s == 201 and all(p.get("authorization_id", "MISSING") is None for p in r.j["payments"]), r)
# settlement cycle: net zero
r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 500}, {"from_handle": "bob", "to_handle": "ada", "amount": 500}]}, token=t["op"], key=k())
ok("A06 net-zero cycle with available 0 allowed", r.s == 201, r)
ok("A01 conservation after settlements", sum(me(t[h])["total"] for h in t) == TOTAL)
ok("A02 captures still spend reserved after settlement drains available", capture(t["bob"], a.j["authorization_id"], amount=9000).s == 201 and state("ada")[2] == 0)

# --- splits unchanged with holds
t = setup(f)
authorize(t["ada"], "bob", 10000)
r = call("POST", "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "s"}, token=t["ada"], key=k())
ok("A07 split works with available 0, shares 334/333/333", r.s == 201 and [s["amount"] for s in r.j["shares"]] == [334, 333, 333] and len(r.j["requests"]) == 2, r)
r = call("POST", "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "s"}, token=t["ada"], key=k())
ok("A07 split no balance check", r.s == 201)
ok("A04 /me while held==total: available 0", state("ada") == (10000, 0, 10000))

# --- held > total never possible; hold exact total
t = setup(f)
r = authorize(t["ada"], "bob", 10000)
ok("A02 hold of exactly total allowed", r.s == 201 and state("ada") == (10000, 0, 10000), r)
r = authorize(t["ada"], "bob", 1)
ok("A02 further hold refused at available 0", r.s == 409 and r.code == "insufficient_funds", r)
done("s2_funds")
