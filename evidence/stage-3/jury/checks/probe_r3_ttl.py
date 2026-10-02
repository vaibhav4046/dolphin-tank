"""boundary probe: authorization_ttl_seconds extremes. PF1 = accepted stage-2 image, PF2 = 5e6f83f. Same calls; report and compare (informational)."""
import os
from lib3 import *


def hp(n):
    h, p = os.environ[n].rsplit(":", 1); return (h, int(p))


out = {}
for label, base in (("stage2", hp("PF1")), ("stage3", hp("PF2"))):
    c = lambda m, p, b=None, tok=None, key=None: call(m, p, b, token=tok, key=key, base=base)
    rows = []
    for ttl in (1, 3600, 10 ** 10, 3 * 10 ** 11, 2 ** 53, 2 ** 63 - 1, 2 ** 63, 10 ** 30):
        f = fx([user("ada", 10000), user("bob", 0)]); f["authorization_ttl_seconds"] = ttl
        r = c("POST", "/_test/reset", f)
        if r.s != 204:
            rows.append((ttl, "reset", r.s, r.code)); continue
        ta = c("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).j["token"]
        a = c("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, ta, k())
        m = c("GET", "/me", None, ta)
        rows.append((ttl, "authorize", a.s, a.code or (a.j or {}).get("expires_at"), "me.held", (m.j or {}).get("held"), "me.status", m.s))
    out[label] = rows
    for r in rows: print(label, r)
same = [a[:4] == b[:4] or (a[0] == b[0] and a[2] == b[2]) for a, b in zip(out["stage2"], out["stage3"])]
ok("authorization_ttl_seconds extremes: stage-3 answers with the same status codes as accepted stage 2 for every value, never 5xx", all(same) and not any(r[2] >= 500 for rr in out.values() for r in rr if isinstance(r[2], int)), list(zip(out["stage2"], out["stage3"])))
done("probe_r3_ttl")
