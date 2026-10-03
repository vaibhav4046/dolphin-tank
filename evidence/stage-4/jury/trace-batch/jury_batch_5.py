"""jury checks, part 5: snapshot-vs-import behaviour (route decision D-B8), HTTP surface, imported revision recorded ahead of the clock.

usage: python jury_batch_5.py s4.exe s3.exe
"""
import json
import sys
from datetime import datetime, timedelta

from jlib import *

EXE4, EXE3 = sys.argv[1], sys.argv[2]


def dt(s):
    return datetime.fromisoformat(s)


# ---- D-B8: what does the accepted stage-3 service itself do with a snapshot token across export/import?
for label, exe in (("stage-3 (accepted)", EXE3), ("stage-4", EXE4)):
    svc = Svc(exe)
    w = World(svc, fixture({h: 5000 for h in ["op", "ada", "bob"]}))
    for a in (10, 20, 30):
        w.pay("ada", "bob", a)
    s, st = svc.j("GET", "/statement?limit=1", w.tok["bob"])
    tokn = st["snapshot"]
    before = svc.call("GET", "/statement?snapshot=%s&limit=1&offset=1" % tokn, w.tok["bob"])
    e = svc.export()
    print("%s: snapshot token present in its own export: %s" % (label, tokn.encode() in e))
    s, _ = svc.import_(e)
    after = svc.call("GET", "/statement?snapshot=%s&limit=1&offset=1" % tokn, w.tok["bob"])
    print("%s: token before import %s, after export->import of the same state %s" % (label, before[0], after[0]))
    svc.stop()

# ---- HTTP surface of the new route
svc = Svc(EXE4)
w = World(svc, fixture({h: 5000 for h in ["op", "ada", "bob"]}))
P = w.pay("ada", "bob", 100)["payment_id"]
E = iso(now())
body = {"corrections": [item(P, 1, 90, E)]}
for m in ("GET", "PUT", "PATCH", "DELETE"):
    s, o = svc.j(m, "/correction-batches", w.tok["op"], key(), body)
    check("surface %s /correction-batches is refused with an error envelope (%s)" % (m, s), s in (404, 405) and isinstance(o, dict) and "error" in o, (s, o))
for path in ("/correction-batches/", "/Correction-Batches", "/correction-batches/x", "/correction-batch"):
    s, o = svc.j("POST", path, w.tok["op"], key(), body)
    check("surface POST %s -> 404 envelope (%s)" % (path, s), s in (404, 405) and isinstance(o, dict) and "error" in o, (s, o))
s, o = svc.j("POST", "/correction-batches?x=1&limit=banana", w.tok["op"], key(), body)
check("surface unknown query parameters are ignored (201)", s == 201, (s, o))
s, raw = svc.call("POST", "/correction-batches", w.tok["op"], key(), raw=b'{"corrections":[' + json.dumps(item(P, 2, 80, E)).encode() + b']}',
                  hdr={"Content-Type": "text/plain"})
check("surface body without a JSON content-type is still parsed (stage-1 convention) -> 201 or 4xx envelope", s == 201 or json.loads(raw).get("error"), (s, raw[:200]))
svc.stop()

# ---- a member revision imported with a recorded_at ahead of the clock
svc = Svc(EXE4)
w = World(svc, fixture({h: 5000 for h in ["op", "ada", "bob"]}))
P = w.pay("ada", "bob", 100)["payment_id"]
Q = w.pay("ada", "bob", 50)["payment_id"]
e = json.loads(svc.export())
fut = now() + timedelta(hours=2)
past = now() - timedelta(minutes=1)
e["state"]["revisions"].append({"payment_id": P, "revision": 2, "amount": 100, "effective_at": iso(past), "recorded_at": iso(fut), "reason": "future-recorded", "correction_batch_id": None})
s, b = svc.import_(json.dumps(e).encode())
print("import of a state with a revision recorded 2h ahead of the clock ->", s)
if s == 204:
    s, o = w.batch("op", [item(P, 2, 70, iso(now())), item(Q, 1, 40, iso(now()))])
    check("future-recorded member: batch accepted (201)", s == 201, (s, o))
    if s == 201:
        check("U34 batch recorded_at is strictly later than the member's imported recorded_at (+2h)", dt(o["recorded_at"]) > fut, (o["recorded_at"], fut.isoformat()))
        check("U34 both revisions share it", len({r["recorded_at"] for r in o["revisions"]}) == 1)
        s, st = svc.j("GET", "/statement?limit=50", w.tok["bob"])
        ent = {x["payment"]["payment_id"]: x for x in st["entries"]}
        check("a default read after the batch sees both new revisions (known_at defaults to the read's start)", ent[P]["revision"] == 3 and ent[Q]["revision"] == 2, {k: v["revision"] for k, v in ent.items()})
        s, o2 = w.batch("op", [item(P, 3, 60, iso(now()))])
        check("a following batch records strictly later again", s == 201 and dt(o2["recorded_at"]) > dt(o["recorded_at"]), (s, o2))
svc.stop()

print("\nPART5 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
if FAILS:
    print("FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
