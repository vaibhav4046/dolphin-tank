"""F03-F05 I02(API half): GET /authorizations filters/paging/order/scoping; Accept negotiation on /requests and /authorizations."""
import time, http.client, json
from lib import *

f = fx([user("ada", 100000), user("bob", 100000), user("cy", 100000), user("dee", 100000)])
t = setup(f)
A, B, C, D = t["ada"], t["bob"], t["cy"], t["dee"]
ids = []
plan = [(A, "bob"), (B, "ada"), (C, "ada"), (A, "cy"), (B, "cy"), (A, "bob"), (C, "bob")]
for i, (tok, to) in enumerate(plan):
    r = authorize(tok, to, 100 + i)
    assert r.s == 201, r
    ids.append(r.j["authorization_id"])
    time.sleep(1.05)  # distinct created_at seconds so order is deterministic
by_label = dict(zip(range(7), ids))
# states: 0 captured by bob, 1 voided by bob, 3 stays open, 5 captured by bob, rest open
capture(B, ids[0]); void(B, ids[1]); capture(B, ids[5], amount=50, final=False)
r = call("GET", "/authorizations", token=A)
ok("F03 200 + keys authorizations/has_more", r.s == 200 and isinstance(r.j.get("authorizations"), list) and r.j.get("has_more") is False, r)
la = [a["authorization_id"] for a in r.j["authorizations"]]
ok("F03 ada sees exactly those involving her (0,1,2,3,5), newest first", la == [ids[5], ids[3], ids[2], ids[1], ids[0]], la)
ok("F03 stranger dee sees none", call("GET", "/authorizations", token=D).j == {"authorizations": [], "has_more": False}, call("GET", "/authorizations", token=D))
lc = [a["authorization_id"] for a in call("GET", "/authorizations", token=C).j["authorizations"]]
ok("F03 cy sees 2,3,4,6 only", lc == [ids[6], ids[4], ids[3], ids[2]], lc)
lo = [a["authorization_id"] for a in call("GET", "/authorizations?direction=outgoing", token=A).j["authorizations"]]
li = [a["authorization_id"] for a in call("GET", "/authorizations?direction=incoming", token=A).j["authorizations"]]
ok("F03 direction=outgoing (caller is payer)", lo == [ids[5], ids[3], ids[0]], lo)
ok("F03 direction=incoming (caller is receiver)", li == [ids[2], ids[1]], li)
for st, exp in (("open", [ids[5], ids[3], ids[2]]), ("captured", [ids[0]]), ("voided", [ids[1]]), ("expired", [])):
    got = [a["authorization_id"] for a in call("GET", "/authorizations?status=" + st, token=A).j["authorizations"]]
    ok("F03 status=%s" % st, got == exp, got)
got = [a["authorization_id"] for a in call("GET", "/authorizations?direction=outgoing&status=open", token=A).j["authorizations"]]
ok("F03 direction+status combined", got == [ids[5], ids[3]], got)
# paging
p1 = call("GET", "/authorizations?limit=2&offset=0", token=A).j
p2 = call("GET", "/authorizations?limit=2&offset=2", token=A).j
p3 = call("GET", "/authorizations?limit=2&offset=4", token=A).j
ok("F04 limit=2 page1 has_more", [a["authorization_id"] for a in p1["authorizations"]] == [ids[5], ids[3]] and p1["has_more"] is True, p1)
ok("F04 page2 has_more", [a["authorization_id"] for a in p2["authorizations"]] == [ids[2], ids[1]] and p2["has_more"] is True, p2)
ok("F04 page3 last, has_more false", [a["authorization_id"] for a in p3["authorizations"]] == [ids[0]] and p3["has_more"] is False, p3)
pe = call("GET", "/authorizations?limit=5", token=A).j
ok("F04 limit exactly equals count: has_more false", len(pe["authorizations"]) == 5 and pe["has_more"] is False, pe)
pe = call("GET", "/authorizations?limit=4", token=A).j
ok("F04 limit < count: has_more true", len(pe["authorizations"]) == 4 and pe["has_more"] is True)
pe = call("GET", "/authorizations?offset=5", token=A).j
ok("F04 offset past end: empty, has_more false", pe == {"authorizations": [], "has_more": False}, pe)
ok("F04 limit 200 accepted, limit 1 accepted", call("GET", "/authorizations?limit=200", token=A).s == 200 and call("GET", "/authorizations?limit=1", token=A).j["has_more"] is True)
for q in ("limit=0", "limit=201", "limit=-1", "limit=abc", "limit=1e2", "limit=%2B4", "limit=4.0", "limit=", "offset=-1", "offset=1e1", "offset=x", "offset=%2B1", "offset=1.0",
          "direction=sideways", "direction=", "status=bogus", "status=OPEN", "status="):
    r = call("GET", "/authorizations?" + q, token=A)
    ok("F04 invalid %s -> 422 validation_failed" % q, r.s == 422 and r.code == "validation_failed", r)
r = call("GET", "/authorizations?foo=bar&limit=1&zzz=1", token=A)
ok("F05 unknown query params ignored", r.s == 200 and len(r.j["authorizations"]) == 1, r)
# every element carries the new fields and remaining amounts are consistent with status
for a in call("GET", "/authorizations", token=A).j["authorizations"]:
    ok("E07 list element %s: remaining consistent" % a["authorization_id"],
       a["remaining_amount"] == (a["amount"] - a["captured_amount"] if a["status"] == "open" else 0) and "payment_ids" in a, a)
ok("E07 partially captured open (5): remaining 100+5-50=55, captured 50", (lambda a: (a["captured_amount"], a["remaining_amount"], a["status"]) == (50, 55, "open"))(authz(A, ids[5])), authz(A, ids[5]))

# ---------------- Accept negotiation
def raw(method, path, hdrs=None, body=None):
    c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    c.request(method, path, body=body, headers=hdrs or {})
    r = c.getresponse(); b = r.read(); STATUSES.append(r.status)
    return r.status, r.getheader("Content-Type") or "", b
for path in ("/requests", "/authorizations"):
    for acc in ("text/html", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"):
        s, ct, b = raw("GET", path, {"Accept": acc})
        ok("I02 GET %s Accept %s... -> 200 HTML without a token" % (path, acc[:20]), s == 200 and ct.startswith("text/html") and b.lstrip().lower().startswith(b"<!doctype html"), (s, ct, b[:60]))
    for acc in (None, "application/json", "*/*", "application/json, text/plain, */*"):
        h = {"Accept": acc} if acc else {}
        s, ct, b = raw("GET", path, h)
        j = json.loads(b)
        ok("I02 GET %s Accept %r no token -> 401 JSON envelope" % (path, acc), s == 401 and ct.startswith("application/json") and j["error"]["code"] == "unauthenticated", (s, ct, b[:100]))
        s, ct, b = raw("GET", path, dict(h, Authorization="Bearer " + A))
        ok("I02 GET %s Accept %r with token -> 200 JSON" % (path, acc), s == 200 and ct.startswith("application/json") and isinstance(json.loads(b), dict), (s, ct, b[:80]))
# POST on those paths stays API even with a browser Accept
c = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=A, key=k(), hdrs={"Accept": "text/html"})
ok("I02 POST /authorizations with Accept text/html is still the API (201 JSON)", c.s == 201 and c.j and "authorization_id" in c.j, c)
c = call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, token=A, key=k(), hdrs={"Accept": "text/html"})
ok("I02 POST /requests with Accept text/html is still the API (201 JSON)", c.s == 201 and c.j and "request_id" in c.j, c)
# always-UI routes + unknown
for path in ("/", "/split", "/login", "/signup"):
    s, ct, b = raw("GET", path, {"Accept": "application/json"})
    ok("I01 GET %s serves the UI" % path, s == 200 and ct.startswith("text/html"), (s, ct))
s, ct, b = raw("GET", "/nope", {"Accept": "text/html"})
ok("I01 unknown path 404 not 5xx", s == 404, (s, ct, b[:60]))
done("s2_list")
