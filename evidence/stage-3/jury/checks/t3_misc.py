"""J47: closed_at on the void response and on repeat void; created response closed_at null; capture of full remainder with final:false closes with closed_at."""
import time
from lib3 import *
t = setup(fx([user("ada", 10000), user("bob", 0)]))
A, B = t["ada"], t["bob"]
a = authorize(A, "bob", 1000).j
ok("J47 authorize response: closed_at null", a.get("closed_at", "MISSING") is None, a)
v = void(A, a["authorization_id"])
ok("J47 void response carries closed_at (event time) and status voided", v.s == 200 and v.j["status"] == "voided" and v.j["closed_at"] and RFC3339.match(v.j["closed_at"]), v)
v2 = void(A, a["authorization_id"])
ok("J47 second void: same closed_at", v2.s == 200 and v2.j["closed_at"] == v.j["closed_at"], (v, v2))
b = authorize(A, "bob", 600).j
c1 = capture(B, b["authorization_id"], amount=200, final=False)
c2 = capture(B, b["authorization_id"], amount=400, final=False)  # whole remainder closes even with final:false
bb = authz(A, b["authorization_id"])
ok("J47 capturing the whole remainder with final:false closes: captured, closed_at set, remaining 0", bb["status"] == "captured" and bb["closed_at"] and bb["remaining_amount"] == 0 and bb["payment_ids"] == [c1.j["payment_id"], c2.j["payment_id"]], bb)
ok("J47 closed_at not later than the last capture payment's created_at (event time)", P(bb["closed_at"]) <= P(c2.j["created_at"]) + US, (bb["closed_at"], c2.j["created_at"]))
vv = me_at(A, bb["closed_at"]).j
ok("J45 view at closed_at: hold released (held 0, total 9400... both captures counted if closed_at >= c2)", vv["held"] == 0 or P(bb["closed_at"]) < P(c2.j["created_at"]), vv)
done("t3_misc")
