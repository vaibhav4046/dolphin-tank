"""REPRO (reject evidence): reset with a seeded authorization whose status is 'expired' and whose expires_at is 2h in the future
(stage-2 spec: seeded status may be expired; seeded expiry is 'at least an hour from reset, in the past or future').
PF1 = accepted stage-2 image, PF2 = stage-3 image under test. Same fixture, same calls."""
import os, datetime as dt
from lib3 import *
def hp(n):
    h, p = os.environ[n].rsplit(":", 1); return (h, int(p))
def run(label, base):
    c = lambda m, p, b=None, tok=None, key=None: call(m, p, b, token=tok, key=key, base=base)
    now = dt.datetime.now(dt.timezone.utc)
    exp = (now + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    f = fx([user("ada", 10000), user("bob", 2500), user("cy", 0)])
    f["authorizations"] = [
        {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "seed", "visibility": "public", "status": "open", "expires_at": exp},
        {"id": "a4", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 4000, "note": "", "visibility": "public", "status": "expired", "expires_at": exp}]
    assert c("POST", "/_test/reset", f).s == 204
    ta = c("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).j["token"]
    tb = c("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"}).j["token"]
    m0 = c("GET", "/me", tok=ta).j
    r_cap = c("POST", "/authorizations/a1/capture", {"amount": 800, "final": False}, tb, k())
    r_pay = c("POST", "/payments", {"to_handle": "cy", "amount": 8001}, ta, k())
    skew = (P(r_pay.j["created_at"]) - dt.datetime.now(dt.timezone.utc)).total_seconds() if r_pay.s == 201 else None
    print("%-22s /me held=%s available=%s | capture seeded open hold -> %s %s | pay 8001 (> available 8000) -> %s | payment.created_at - now = %s s" % (
        label, m0["held"], m0["available"], r_cap.s, r_cap.code, r_pay.s, None if skew is None else round(skew)))
    return r_cap.s, r_pay.s, skew
a = run("stage-2 (accepted)", hp("PF1"))
b = run("stage-3 (under test)", hp("PF2"))
ok("REGRESSION: accepted stage 2 captures the seeded open hold and refuses a payment above available", a[0] == 201 and a[1] == 409)
ok("stage 3: seeded expired-status hold with future expires_at must not move the server clock: capture 201, over-available payment 409, created_at ~ now", b[0] == 201 and b[1] == 409, b)
done("repro_expired_future")
