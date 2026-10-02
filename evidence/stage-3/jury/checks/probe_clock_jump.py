"""probe: does reset with a seeded future-dated open authorization push server timestamps into the future?"""
import datetime as dt, json
from lib3 import *
def iso_s(d): return d.strftime("%Y-%m-%dT%H:%M:%S+00:00")
for label, ent in [("expired-status +2h (future expires_at)", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "expired", "expires_at": 7200}),
                   ("expired-status -2h (past expires_at)", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "expired", "expires_at": -7200}),
                   ("captured +48h", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "captured", "captured_amount": 2000, "expires_at": 172800}),
                   ("voided +48h", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "voided", "expires_at": 172800}),
                   ("open +2h with created_at in future +1h", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "open", "expires_at": 7200, "created_at": 3600}),
                   ("seeded-date from spec example (2026-09-24, past) expired", {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "expired", "expires_at": -86400 * 8})]:
    f = fx([user("ada", 10000), user("bob", 2500)])
    if ent:
        ent = dict(ent); ent["expires_at"] = iso_s(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ent["expires_at"]))
        if "created_at" in ent: ent["created_at"] = iso_s(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ent["created_at"]))
        f["authorizations"] = [ent]
    t = setup(f)
    r = pay(t["ada"], "bob", 10)
    now_ = dt.datetime.now(dt.timezone.utc)
    skew = (P(r.j["created_at"]) - now_).total_seconds()
    m = me(t["ada"])
    print("%-28s payment.created_at - local now = %+.1f s ; /me held=%s available=%s" % (label, skew, m["held"], m["available"]))
    if ent:
        print("   authorization:", json.dumps(call("GET", "/authorizations", token=t["ada"]).j["authorizations"][0]))
