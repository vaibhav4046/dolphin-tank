"""exploration only (not a verdict): print raw shapes of the stage-3 endpoints"""
import json
from lib import *

f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0)])
t = setup(f)
A, B, C = t["ada"], t["bob"], t["cy"]
p = pay(A, "bob", 500, note="coffee").j
print("PAY", json.dumps(p))
print("ME", json.dumps(me(A)))
print("ME as_of", json.dumps(call("GET", "/me?as_of=2030-01-01T00:00:00%2B00:00", token=A).j))
print("ME plus-unencoded", call("GET", "/me?as_of=2030-01-01T00:00:00+00:00", token=A))
s = call("GET", "/statement", token=A)
print("STMT", s.s, json.dumps(s.j))
c = call("POST", "/payments/%s/corrections" % p["payment_id"], {"expected_revision": 1, "amount": 400, "effective_at": p["created_at"], "reason": "x"}, token=A, key=k())
print("CORR", c.s, json.dumps(c.j))
print("REVS", json.dumps(call("GET", "/payments/%s/revisions" % p["payment_id"], token=A).j))
print("STMT2", json.dumps(call("GET", "/statement", token=A).j))
a = authorize(A, "bob", 1000).j
print("AUTH", json.dumps(a))
print("AUTHS", json.dumps(call("GET", "/authorizations", token=A).j))
print("ME2", json.dumps(me(A)))
