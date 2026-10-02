"""probe: shape of a real 3c7c411 export (PF1 = legacy image) """
import os, json
from lib3 import *
def hp(n):
    h, p = os.environ[n].rsplit(":", 1); return (h, int(p))
L = hp("PF1")
c = lambda m, p, b=None, tok=None, key=None: call(m, p, b, token=tok, key=key, base=L)
f = fx([user("ada", 10000), user("bob", 0), user("cy", 0)])
assert c("POST", "/_test/reset", f).s == 204
ta = c("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).j["token"]
tb = c("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"}).j["token"]
p = c("POST", "/payments", {"to_handle": "bob", "amount": 5000}, ta, k()).j
a = c("POST", "/authorizations", {"to_handle": "cy", "amount": 4000}, tb, k()).j
print("payment", p)
print("authorization", a)
ex = c("GET", "/_test/export").j
st = ex["state"]
print("state keys", list(st.keys()))
print("authorizations", json.dumps(st.get("authorizations"), indent=1)[:900])
print("payments[0]", json.dumps(st.get("payments", [None])[0], indent=1)[:600])
for h, tk in (("bob", tb),):
    r = c("GET", "/me?as_of=" + q(a["created_at"]), None, tk)
    print("legacy view at auth.created_at:", r.j)
