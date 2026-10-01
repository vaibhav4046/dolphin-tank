"""Spec-silent probe: GET /me and writes racing many POST /_test/reset. Records any non-{200 object, 401} outcome and every 5xx."""
import threading, time
from lib import *

t = setup(fx())
stop = threading.Event()
seen = {}
bad = []
lock = threading.Lock()


def note(tag):
    with lock:
        seen[tag] = seen.get(tag, 0) + 1


def hammer(i):
    tok = t["ada"]
    while not stop.is_set():
        r = call("GET", "/me", token=tok)
        if r.s == 200 and isinstance(r.j, dict) and r.j.get("handle") == "ada":
            note("me 200 object")
        elif r.s == 200:
            note("me 200 NON-OBJECT %r" % r.b[:40]); bad.append(r.b[:80])
        elif r.s == 401:
            note("me 401")
        else:
            note("me %s" % r.s); bad.append((r.s, r.b[:80]))
        for path, body in (("/payments", {"to_handle": "bob", "amount": 1}), ("/requests", {"payer_handle": "bob", "amount": 1})):
            r = call("POST", path, body, token=tok, key=k())
            note("%s %s" % (path, r.s))
            if r.s >= 500 or (r.s == 200 and r.j is None):
                bad.append((path, r.s, r.b[:80]))
        r = call("GET", "/activity", token=tok)
        if r.s not in (200, 401):
            bad.append(("activity", r.s));
        if r.s == 200 and not isinstance(r.j, dict):
            bad.append(("activity non-object", r.b[:60]))


ths = [threading.Thread(target=hammer, args=(i,)) for i in range(16)]
[x.start() for x in ths]
t0 = time.time(); n = 0
while time.time() - t0 < 12:
    reset(fx()); n += 1
stop.set(); [x.join() for x in ths]
print("OBS %d resets under 16 hammer threads; outcomes: %s" % (n, dict(sorted(seen.items()))))
ok("no 5xx, no 200-with-non-object from /me or /activity during %d racing resets" % n, not bad, bad[:5])
t = setup(fx())
ok("final state exactly the fixture", [bal(t[h]) for h in ("ada", "bob", "cy", "dee")] == [10000, 2500, 0, 5000])
done("c13_reset_vs_me")
