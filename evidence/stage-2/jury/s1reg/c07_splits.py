"""J24, J62-J68: splits, rounding table, caller position, zero share, errors, conservation after paying everything."""
from lib import *

U = [user(h, 0 if h != "ada" else 10000) for h in ("ada", "bob", "cy", "dee", "eve", "fay", "gus", "hal", "ida", "jon")]
t = setup(fx(U))


def split(tok, amount, hs, note=None, key=None):
    b = {"amount": amount, "participant_handles": hs}
    if note is not None:
        b["note"] = note
    return call("POST", "/splits", b, token=tok, key=key or k())


# table: (amount, handles, caller, expected shares)
T = [(1000, ["ada", "bob", "cy"], "ada", [334, 333, 333]), (1, ["ada", "bob", "cy"], "ada", [1, 0, 0]), (10, ["ada", "bob", "cy"], "ada", [4, 3, 3]),
     (999, ["ada", "bob", "cy"], "ada", [333, 333, 333]), (5, ["ada", "bob", "cy", "dee", "eve"], "ada", [1, 1, 1, 1, 1]),
     (1000, ["cy", "ada", "bob"], "ada", [334, 333, 333]), (1000, ["bob", "cy", "ada"], "ada", [334, 333, 333]), (1000, ["bob", "cy", "dee"], "ada", [334, 333, 333]),
     (1000, ["cy", "bob", "ada"], "ada", [334, 333, 333]), (1000, ["ada"], "ada", [1000]), (1, ["bob", "ada", "cy"], "ada", [1, 0, 0]),
     (2, ["bob", "cy", "ada"], "ada", [1, 1, 0]), (1003, list(u["handle"] for u in U), "ada", [101, 101, 101] + [100] * 7),
     (7, list(u["handle"] for u in U), "ada", [1] * 7 + [0] * 3), (1000000000, ["ada", "bob", "cy"], "ada", [333333334, 333333333, 333333333]),
     (1000000000, list(u["handle"] for u in U), "ada", [100000000] * 10)]
for amt, hs, caller, want in T:
    r = split(t[caller], amt, hs, note="sp")
    ok("split %d among %s -> %s" % (amt, ",".join(hs), want), r.s == 201 and [s["amount"] for s in r.j["shares"]] == want and [s["handle"] for s in r.j["shares"]] == hs and sum(s["amount"] for s in r.j["shares"]) == amt, r)
    if r.s != 201:
        continue
    j = r.j
    exp_req = [(h, a) for h, a in zip(hs, want) if h != caller]
    ok("  requests = every participant except caller, same order, each for own share (0 included), caller is requester, pending",
       [(x["payer_handle"], x["amount"]) for x in j["requests"]] == exp_req and all(x["requester_handle"] == caller and x["status"] == "pending" and x["note"] == "sp" and x["currency"] == "EUR" and x["payment_id"] is None for x in j["requests"]), j["requests"])
    ok("  shape: split_id,amount,currency,note,shares,requests,created_at", set(j) == {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"} and RFC3339.match(j["created_at"]) and j["amount"] == amt and j["note"] == "sp", sorted(j))
    ok("  shares differ by at most 1 and extra units go first", max(want) - min(want) <= 1 and want == sorted(want, reverse=True), want)
ok("split creates no money movement (ada balance unchanged)", bal(t["ada"]) == 10000 and sum(bal(t[h]) for h in t) == 10000)

# caller omitted / caller only / caller not first: requests still exclude the caller
r = split(t["bob"], 100, ["ada", "cy"])
ok("caller absent from participants: requests for all participants", r.s == 201 and [x["payer_handle"] for x in r.j["requests"]] == ["ada", "cy"] and [s["amount"] for s in r.j["shares"]] == [50, 50], r)
r = split(t["ada"], 3000, ["ada"])
ok("only participant is caller: valid, one share, zero requests", r.s == 201 and r.j["requests"] == [] and [(s["handle"], s["amount"]) for s in r.j["shares"]] == [("ada", 3000)], r)
ok("default note is ''", r.j["note"] == "")
# caller with balance 0 may split (nothing checks balance)
r = split(t["dee"], 500, ["dee", "bob"])
ok("split by zero-balance caller succeeds (no balance check)", r.s == 201 and bal(t["dee"]) == 0, r)

# errors
for nm, b, st, code in (("amount 0", {"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"), ("amount 1e9+1", {"amount": 1000000001, "participant_handles": ["bob"]}, 422, "validation_failed"),
                        ("amount string", {"amount": "5", "participant_handles": ["bob"]}, 422, "validation_failed"), ("empty list", {"amount": 5, "participant_handles": []}, 422, "validation_failed"),
                        ("duplicate", {"amount": 5, "participant_handles": ["bob", "cy", "bob"]}, 422, "validation_failed"), ("caller duplicate", {"amount": 5, "participant_handles": ["ada", "ada"]}, 422, "validation_failed"),
                        ("note 201", {"amount": 5, "participant_handles": ["bob"], "note": "n" * 201}, 422, "validation_failed"), ("unknown handle", {"amount": 5, "participant_handles": ["bob", "nope"]}, 404, "not_found"),
                        ("unknown handle only", {"amount": 5, "participant_handles": ["nope"]}, 404, "not_found")):
    n0 = len(call("GET", "/requests?limit=200", token=t["ada"]).j["requests"])
    r = call("POST", "/splits", b, token=t["ada"], key=k())
    ok("split %s -> %d %s and creates no request" % (nm, st, code), r.s == st and r.code == code and len(call("GET", "/requests?limit=200", token=t["ada"]).j["requests"]) == n0, r)

# visibility of split requests: only the two parties; not in the feed
t2 = setup(fx(U))
r = split(t2["ada"], 900, ["ada", "bob", "cy"]).j
rb, rc = r["requests"]
ok("bob sees only his split request, cy only hers, dee none", [x["request_id"] for x in call("GET", "/requests", token=t2["bob"]).j["requests"]] == [rb["request_id"]]
   and [x["request_id"] for x in call("GET", "/requests", token=t2["cy"]).j["requests"]] == [rc["request_id"]] and call("GET", "/requests", token=t2["dee"]).j["requests"] == [])
ok("split is not a feed item; nothing in anyone's activity", all(feed == [] for feed in (call("GET", "/activity", token=t2[h]).j["payments"] for h in ("ada", "bob", "cy", "dee"))))
ok("bob cannot cancel/decline/pay-as-other: bob pays cy's request -> 403", call("POST", "/requests/%s/pay" % rc["request_id"], {}, token=t2["bob"], key=k()).s == 403)

# conservation after every split request of a batch of splits is paid in full
t3 = setup(fx(U))
total = sum(u["balance"] for u in U)
for u in ("bob", "cy", "dee", "eve"):
    call("POST", "/payments", {"to_handle": u, "amount": 1000}, token=t3["ada"], key=k())
reqs_ = []
for amt, hs in ((1000, ["ada", "bob", "cy"]), (7, ["cy", "bob", "ada", "dee"]), (1, ["bob", "cy", "dee"]), (999, ["dee", "eve", "bob"]), (5, ["ada", "bob", "cy", "dee", "eve"])):
    caller = "ada"
    r = split(t3[caller], amt, hs).j
    reqs_ += [(x["request_id"], x["payer_handle"], x["amount"]) for x in r["requests"]]
for rid, payer, amt in reqs_:
    x = call("POST", "/requests/%s/pay" % rid, {}, token=t3[payer], key=k())
    ok("pay split request %s (%s %d)" % (rid, payer, amt), x.s == 201 and x.j["amount"] == amt, x)
ok("after every split request paid in full, balances sum to seeded total", sum(bal(t3[h]) for h in t3) == total, [bal(t3[h]) for h in t3])
ok("ada received exactly the sum of the other shares", bal(t3["ada"]) == 10000 - 4000 + sum(a for _, _, a in reqs_), bal(t3["ada"]))

done("c07_splits")
