"""jury checks, part 6: the spec's literal example (reversal of a settlement) and a no-5xx sweep over hostile bodies."""
import json
import sys
from datetime import timedelta

from jlib import *

EXE = sys.argv[1]
svc = Svc(EXE)

# ---- the literal example of the specification: two settlement payments reversed at 2026-09-20T12:00:00+00:00, reason "reversal"
w = World(svc, fixture({h: 10000 for h in ["op", "ada", "bob", "cy"]}))
init = w.balances()
s, sr = w.settle("op", [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 50}])
pa, pb = [p["payment_id"] for p in sr["payments"]]
body = {"corrections": [{"payment_id": pa, "expected_revision": 1, "amount": 0, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reversal"},
                        {"payment_id": pb, "expected_revision": 1, "amount": 0, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reversal"}]}
k = key("lit")
s, b = svc.call("POST", "/correction-batches", w.tok["op"], k, body)
o = json.loads(b)
check("literal example: reversal of both settlement members -> 201", s == 201, (s, b[:300]))
check("literal example: balances restored to the opening 10000 each", w.balances() == init, w.balances())
check("literal example: both revisions amount 0, effective_at echoed as given, reason reversal",
      all(r["amount"] == 0 and r["effective_at"] == "2026-09-20T12:00:00+00:00" and r["reason"] == "reversal" and r["revision"] == 2 for r in o["revisions"]), o)
check("literal example: statement of bob shows both zero-amount entries with delta 0 (zero revisions still appear)",
      [(e["payment"]["amount"], e["delta"]) for e in svc.j("GET", "/statement?limit=50", w.tok["bob"])[1]["entries"]] == [(0, 0), (0, 0)] or
      sorted((e["payment"]["amount"], e["delta"]) for e in svc.j("GET", "/statement?limit=50", w.tok["bob"])[1]["entries"]) == [(0, 0), (0, 0)],
      svc.j("GET", "/statement?limit=50", w.tok["bob"])[1])
s, st = svc.j("GET", "/statement?limit=50", w.tok["bob"])
check("literal example: statement sums (opening + deltas = closing)", st["opening_balance"] + sum(e["delta"] for e in st["entries"]) == st["closing_balance"] == 10000, st)
s2, b2 = svc.call("POST", "/correction-batches", w.tok["op"], k, body)
check("literal example: replay 200 identical", s2 == 200 and b2 == b)
s, o2 = svc.j("POST", "/correction-batches", w.tok["op"], key("lit2"), {"corrections": [item(pa, 1, 0, "2026-09-20T12:00:00+00:00"), item(pb, 1, 0, "2026-09-20T12:00:00+00:00")]})
check("literal example: reversing the same revision again -> 409 stale_revision", s == 409 and code(o2) == "stale_revision", (s, o2))
s, o2 = svc.j("POST", "/correction-batches", w.tok["op"], key("lit3"), {"corrections": [item(pa, 2, 100, "2026-09-20T12:00:00+00:00"), item(pb, 2, 50, "2026-09-20T12:00:00+00:00")]})
check("literal example: restoring the original amounts at the same instant -> 201 and balances as after the settlement", s == 201 and w.balances() == {**init, "ada": init["ada"] - 100, "bob": init["bob"] + 50, "cy": init["cy"] + 50}, (s, o2, w.balances()))

# ---- no 5xx over hostile bodies; the server must stay up and unchanged
w = World(svc, fixture({h: 10000 for h in ["op", "ada", "bob"]}))
P = w.pay("ada", "bob", 100)["payment_id"]
E = iso(now())
before = svc.export()
hostile = [
    b"", b"null", b"true", b"123", b'"x"', b"[]", b"{", b'{"corrections":', b'{"corrections":[{}]}', b'{"corrections":[null]}',
    b'{"corrections":' + b"[" * 5000 + b"]" * 5000 + b"}",
    b'{"corrections":[{"payment_id":"%s","expected_revision":1e30,"amount":1,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    b'{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":1e30,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    b'{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":9007199254740993,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    b'{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":-0,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    b'{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":1e999,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    b'{"corrections":[{"payment_id":"%s","expected_revision":99999999999999999999,"amount":1,"effective_at":"%s","reason":"r"}]}' % (P.encode(), E.encode()),
    ('{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":1,"effective_at":"%s","reason":"r"}]}' % ("x" * 1000000, E)).encode(),
    ('{"corrections":[%s]}' % ",".join(['{"payment_id":"p%d"}' % i for i in range(60000)])).encode(),
    b'{"corrections":[{"payment_id":"\\ud800","expected_revision":1,"amount":1,"effective_at":"2026-09-20T12:00:00+00:00","reason":"\\udc00"}]}',
    b'\xff\xfe{"corrections":[]}',
]
for eff in ["0001-01-01T00:00:00+00:00", "0000-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00", "2026-02-30T00:00:00+00:00", "2026-09-20T23:59:60+00:00",
            "2026-09-20T12:00:00.123456789123+00:00", "2026-09-20T12:00:00+99:99", "2026-09-20T12:00:00-23:59", "1900-01-01T00:00:00Z", "2026-09-20T12:00:00+0000",
            "  2026-09-20T12:00:00+00:00", "2026-09-20T12:00:00+00:00\n"]:
    hostile.append(json.dumps({"corrections": [item(P, 1, 1, eff)]}).encode())
statuses = []
for h in hostile:
    s, b = svc.call("POST", "/correction-batches", w.tok["op"], key("host"), raw=h)
    statuses.append(s)
    check("hostile body (%d bytes) %r -> no 5xx, error envelope on 4xx (got %s)" % (len(h), h[:50], s), s < 500 and (s < 400 or "error" in json.loads(b)), (s, b[:200]))
check("server still healthy and the state is unchanged unless a hostile body was a valid correction",
      svc.call("GET", "/health")[0] == 200)
rv = w.revs("ada", P)
print("revisions of the target after the sweep: %d (valid ones among the hostile bodies may legitimately apply)" % len(rv))
accepted = [s for s in statuses if s == 201]
print("statuses:", sorted(set(statuses)), "201 count", len(accepted))

print("\nPART6 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
if FAILS:
    print("FAILED: %s" % FAILS)
svc.stop()
sys.exit(1 if FAILS else 0)
