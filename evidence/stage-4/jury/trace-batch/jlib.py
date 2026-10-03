"""jury helpers: launch a pocketful binary, call it over HTTP only, build fixtures."""
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

PW = "correct horse"
FAILS = []
COUNT = {"pass": 0, "fail": 0}
_key = [0]
_lock = threading.Lock()


def key(prefix="k"):
    with _lock:
        _key[0] += 1
        return "%s-%d-%d" % (prefix, os.getpid(), _key[0])


def check(name, ok, detail=""):
    if ok:
        COUNT["pass"] += 1
        print("PASS " + name)
    else:
        COUNT["fail"] += 1
        FAILS.append(name)
        print("FAIL " + name + (" :: " + str(detail)[:900] if detail != "" else ""))
    sys.stdout.flush()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Svc:
    def __init__(self, exe):
        self.exe = exe
        for attempt in range(8):
            self.port = free_port()
            env = dict(os.environ, PORT=str(self.port))
            self.proc = subprocess.Popen([exe], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(200):
                try:
                    if self.call("GET", "/health")[0] == 200 and self.proc.poll() is None:
                        return
                except Exception:
                    pass
                if self.proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.proc.kill()
            self.proc.wait()
            time.sleep(1)
        raise RuntimeError("service did not start: " + exe)

    def stop(self):
        self.proc.kill()
        self.proc.wait()

    def call(self, method, path, tok=None, k=None, body=None, raw=None, hdr=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        h = {}
        if data is not None:
            h["Content-Type"] = "application/json"
        if tok:
            h["Authorization"] = "Bearer " + tok
        if k is not None:
            h["Idempotency-Key"] = k
        if hdr:
            h.update(hdr)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def j(self, *a, **kw):
        s, b = self.call(*a, **kw)
        try:
            return s, json.loads(b)
        except Exception:
            return s, b

    def export(self):
        s, b = self.call("GET", "/_test/export")
        assert s == 200, (s, b)
        return b

    def import_(self, raw):
        return self.call("POST", "/_test/import", raw=raw)


def code(obj):
    try:
        return obj["error"]["code"]
    except Exception:
        return None


def iso(dt, tz=None):
    if tz is not None:
        dt = dt.astimezone(timezone(timedelta(hours=tz)))
    return dt.isoformat()


def now():
    return datetime.now(timezone.utc)


def fixture(users, payments=(), ops=("op",), ttl=3600, extra=None):
    """users: dict handle -> balance."""
    fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": ttl,
          "settlement_operator_ids": ["u_" + o for o in ops],
          "users": [{"id": "u_" + h, "email": h + "@example.com", "password": PW,
                     "display_name": h.title(), "handle": h, "balance": b} for h, b in users.items()],
          "payments": list(payments)}
    if extra:
        fx.update(extra)
    return fx


class World:
    """A service plus a token per handle, after reset."""

    def __init__(self, svc, fx):
        self.svc = svc
        s, b = svc.call("POST", "/_test/reset", body=fx)
        assert s == 204, (s, b)
        self.fx = fx
        self.tok = {}
        for u in fx["users"]:
            s, o = svc.j("POST", "/auth/login", body={"email": u["email"], "password": PW})
            assert s == 200, (s, o)
            self.tok[u["handle"]] = o["token"]

    def me(self, h, q=""):
        s, o = self.svc.j("GET", "/me" + q, self.tok[h])
        assert s == 200, (s, o)
        return o

    def balances(self):
        return {h: self.me(h)["balance"] for h in self.tok}

    def total(self):
        return sum(self.balances().values())

    def pay(self, frm, to, amount, note="", vis="public", k=None):
        s, o = self.svc.j("POST", "/payments", self.tok[frm], k or key("pay"),
                          {"to_handle": to, "amount": amount, "note": note, "visibility": vis})
        assert s == 201, (s, o)
        return o

    def settle(self, op, transfers, k=None):
        return self.svc.j("POST", "/settlements", self.tok[op], k or key("set"), {"transfers": transfers})

    def batch(self, op, items, k=None, extra=None):
        body = {"corrections": items}
        if extra:
            body.update(extra)
        return self.svc.j("POST", "/correction-batches", self.tok[op], k or key("cb"), body)

    def batch_raw(self, op, items, k=None):
        return self.svc.call("POST", "/correction-batches", self.tok[op], k or key("cb"), {"corrections": items})

    def revs(self, who, pid):
        s, o = self.svc.j("GET", "/payments/%s/revisions" % pid, self.tok[who])
        assert s == 200, (s, o)
        return o["revisions"]

    def refund(self, who, pid, amount, k=None):
        return self.svc.j("POST", "/payments/%s/refunds" % pid, self.tok[who], k or key("rf"), {"amount": amount})

    def correct(self, who, pid, rev, amount, eff, reason="single", k=None):
        return self.svc.j("POST", "/payments/%s/corrections" % pid, self.tok[who], k or key("c"),
                          {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason})


def item(pid, rev, amount, eff, reason="jury"):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}


def parallel(fns):
    """Run callables at (nearly) the same instant; return their results in order."""
    out = [None] * len(fns)
    gate = threading.Event()

    def run(i, f):
        gate.wait()
        try:
            out[i] = f()
        except Exception as e:  # noqa
            out[i] = ("EXC", repr(e))

    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    gate.set()
    [t.join() for t in ts]
    return out
