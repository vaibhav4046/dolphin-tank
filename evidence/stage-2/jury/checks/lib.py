"""jury check helpers - stdlib only. Target from env PF=host:port (default 127.0.0.1:18080)."""
import http.client, json, os, re, sys, threading, uuid

HOST, PORT = os.environ.get("PF", "127.0.0.1:18080").rsplit(":", 1)
PORT = int(PORT)
FAILS = []
NPASS = [0]
STATUSES = []  # every status observed, for the no-5xx sweep
LAT = []  # per-request latency seconds
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class R:
    def __init__(self, s, h, b):
        self.s, self.h, self.b = s, h, b
        try:
            self.j = json.loads(b.decode("utf-8")) if b else None
        except Exception:
            self.j = None

    @property
    def code(self):
        return (self.j or {}).get("error", {}).get("code") if isinstance(self.j, dict) else None

    def __repr__(self):
        return "R(%s %s)" % (self.s, self.b[:300])


DST = os.environ.get("PFD", "127.0.0.1:18081").rsplit(":", 1)
DST = (DST[0], int(DST[1]))


def call(method, path, body=None, token=None, key=None, hdrs=None, raw=None, timeout=20, base=None):
    h = {}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    if hdrs:
        h.update(hdrs)
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    c = http.client.HTTPConnection(*(base or (HOST, PORT)), timeout=timeout)
    t0 = __import__("time").time()
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        b = r.read()
        LAT.append(__import__("time").time() - t0)
        STATUSES.append(r.status)
        return R(r.status, {k.lower(): v for k, v in r.getheaders()}, b)
    finally:
        c.close()


def ok(name, cond, detail=""):
    if cond:
        NPASS[0] += 1
        print("PASS", name)
    else:
        FAILS.append(name)
        print("FAIL", name, "::", str(detail)[:600])


def done(label):
    n5 = [s for s in STATUSES if s >= 500]
    print("== %s: %d pass, %d fail, %d requests, %d 5xx, max latency %.3fs, p99 %.3fs" % (label, NPASS[0], len(FAILS), len(STATUSES), len(n5), max(LAT or [0]), sorted(LAT or [0])[int(len(LAT or [0]) * .99) - 1 if LAT else 0]))
    if n5:
        FAILS.append("5xx observed")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)


def user(h, bal=0, uid=None, pw="correct horse"):
    return {"id": uid or "u_" + h, "email": h + "@example.com", "password": pw,
            "display_name": h.capitalize(), "handle": h, "balance": bal}


def fx(users=None, currency="EUR", mu=2, payments=None, requests=None, ops=None):
    f = {"currency": currency, "minor_units": mu,
         "users": users or [user("ada", 10000), user("bob", 2500), user("cy", 0), user("dee", 5000)]}
    if payments is not None:
        f["payments"] = payments
    if requests is not None:
        f["requests"] = requests
    if ops is not None:
        f["settlement_operator_ids"] = ops
    return f


def reset(f=None):
    r = call("POST", "/_test/reset", f if f is not None else fx())
    assert r.s == 204, r
    return r


def login(email, pw="correct horse"):
    r = call("POST", "/auth/login", {"email": email, "password": pw})
    assert r.s == 200, r
    return r.j["token"]


def setup(f=None):
    f = f if f is not None else fx()
    reset(f)
    return {u["handle"]: login(u["email"], u["password"]) for u in f["users"]}


def me(tok):
    r = call("GET", "/me", token=tok)
    assert r.s == 200, r
    return r.j


def bal(tok):
    return me(tok)["balance"]


def k():
    return uuid.uuid4().hex


def parallel(fns):
    """run callables simultaneously behind a barrier; return results in order"""
    n = len(fns)
    bar = threading.Barrier(n)
    out = [None] * n

    def w(i):
        bar.wait()
        try:
            out[i] = fns[i]()
        except Exception as e:  # noqa
            out[i] = e

    ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


# ------------------------------------------------------------------ stage-2 helpers
import datetime as _dt
import time as _time


def ts(s):
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def authorize(tok, to, amount, note=None, vis=None, key=None, **extra):
    b = {"to_handle": to, "amount": amount}
    if note is not None:
        b["note"] = note
    if vis is not None:
        b["visibility"] = vis
    b.update(extra)
    return call("POST", "/authorizations", b, token=tok, key=key or k())


def capture(tok, aid, amount=None, final=None, key=None, body=None):
    b = {} if body is None else body
    if body is None:
        if amount is not None:
            b["amount"] = amount
        if final is not None:
            b["final"] = final
    return call("POST", "/authorizations/%s/capture" % aid, b, token=tok, key=key or k())


def void(tok, aid):
    return call("POST", "/authorizations/%s/void" % aid, {}, token=tok)


def authz(tok, aid=None, **q):
    qs = "&".join("%s=%s" % (a, b) for a, b in q.items())
    r = call("GET", "/authorizations" + ("?" + qs if qs else ""), token=tok)
    assert r.s == 200, r
    if aid is None:
        return r.j
    for a in r.j["authorizations"]:
        if a["authorization_id"] == aid:
            return a
    return None


def pay(tok, to, amount, key=None, **kw):
    b = {"to_handle": to, "amount": amount}
    b.update(kw)
    return call("POST", "/payments", b, token=tok, key=key or k())


def mefull(tok):
    return me(tok)


def inv(m):
    """per-/me invariants: balance==total, held+available==total, available>=0, held>=0"""
    return (m["balance"] == m["total"] and m["available"] >= 0 and m["held"] >= 0
            and m["available"] + m["held"] == m["total"] and m["held"] <= m["total"])


def sleep_until(iso, extra=0.4):
    """wait on the WALL clock (the one expires_at is judged against), not on a computed sleep"""
    end = ts(iso) + _dt.timedelta(seconds=extra)
    n = 0
    while _dt.datetime.now(_dt.timezone.utc) < end:
        _time.sleep(0.02); n += 1
    return n
