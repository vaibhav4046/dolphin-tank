"""trace: does a hold that expired on the live clock keep its history through export -> import -> export -> import?
usage: F2BIN=<dir with s3-5e6f83f.exe> F2S3=s3-5e6f83f.exe uv run python -u evidence/stage-3/trace/rl1_probe_expired.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import f2_attack as F
from f2_attack import Srv, authorize, login, setup, us, view

S = Srv(F.S3EXE, 18262)
try:
    c = S.c
    t = setup(c, {"ada": 5000, "bob": 100}, 1)
    a = authorize(c, t["ada"], "bob", 1000).j
    C, E = us(a["created_at"]), us(a["expires_at"])
    time.sleep(1.4)

    def views(tag):
        tk = {h: login(c, h) for h in ("ada", "bob")}
        print("%-22s as_of created+1us %s | expires-1us %s | expires %s" % (tag, view(c, tk["ada"], C + 1), view(c, tk["ada"], E - 1), view(c, tk["ada"], E)), flush=True)

    def stat(tag, ex):
        A = ex["state"]["authorizations"][0]
        print("%-22s status=%s closed_at=%s" % (tag, A["status"], A["closed_at"]), flush=True)

    views("live (expired)")
    ex1 = c.req("GET", "/_test/export").j
    stat("export #1", ex1)
    for n in (1, 2, 3):
        r = c.req("POST", "/_test/import", raw=json.dumps(ex1 if n == 1 else exn).encode())
        exn = c.req("GET", "/_test/export").j
        print("import #%d -> %d" % (n, r.s), flush=True)
        views("after import #%d" % n)
        stat("export #%d" % (n + 1), exn)
        print("export #%d == export #%d: %s" % (n + 1, n, json.dumps(exn, sort_keys=True) == json.dumps(ex1 if n == 1 else prev, sort_keys=True)), flush=True)
        prev = exn
finally:
    S.stop()
