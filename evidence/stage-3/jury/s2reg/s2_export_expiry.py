"""H05b/C01 imported hold expiry is absolute: export, wait past expires_at, import elsewhere -> expired immediately. Repeats with varied phase."""
import time, datetime as dt
from lib import *
DSTB = DST
def d(*a, **kw):
    kw["base"] = DSTB; return call(*a, **kw)
for i in range(6):
    f2 = fx([user("ada", 10000), user("bob", 0)]); f2["authorization_ttl_seconds"] = 2
    reset(f2); ta = login("ada@example.com"); tb = login("bob@example.com")
    time.sleep((i * 0.17) % 1.0)  # vary where in the second the hold is created
    ra = authorize(ta, "bob", 4000); ex = call("GET", "/_test/export").b
    exp = ts(ra.j["expires_at"])
    sleep_until(ra.j["expires_at"], 0.6)
    now_py = dt.datetime.now(dt.timezone.utc)
    ok("clock sanity: python now is past displayed expires_at (i=%d)" % i, now_py >= exp, (now_py, exp))
    s_src = authz(ta, ra.j["authorization_id"])
    ok("C01 source shows expired past displayed expires_at (i=%d)" % i, s_src["status"] == "expired", (s_src, now_py.isoformat()))
    d("POST", "/_test/import", raw=ex)
    x = d("GET", "/authorizations", token=tb).j["authorizations"][0]
    ok("H05 destination shows imported hold expired (i=%d)" % i, x["status"] == "expired" and x["expires_at"] == ra.j["expires_at"] and d("GET", "/me", token=ta).j["held"] == 0, (x, now_py.isoformat()))
done("s2_export_expiry")
