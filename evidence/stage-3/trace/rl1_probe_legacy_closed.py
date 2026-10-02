"""trace: what do closed/expired holds look like in a real 3c7c411 export, and how does HEAD import them?
usage: F2BIN=<dir> F2S3=s3-5e6f83f.exe uv run python -u evidence/stage-3/trace/rl1_probe_legacy_closed.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import f2_attack as F
from f2_attack import Srv, authorize, capture, login, pay, setup, us, view, void, iso

SL, S3 = Srv("s3-legacy-3c7c411.exe", 18263), Srv(F.S3EXE, 18264)
try:
    c = SL.c
    t = setup(c, {"ada": 9000, "bob": 100, "cy": 0}, 1)
    while not 100_000 < F.now_us() % 1_000_000 < 300_000:
        time.sleep(0.005)
    pay(c, t["bob"], "ada", 50)
    a_void = authorize(c, t["ada"], "bob", 1000).j
    a_fin = authorize(c, t["ada"], "cy", 700).j
    a_part = authorize(c, t["ada"], "cy", 500).j
    a_exp = authorize(c, t["ada"], "cy", 400).j
    void(c, t["ada"], a_void["authorization_id"])
    capture(c, t["cy"], a_fin["authorization_id"], None, True)
    capture(c, t["cy"], a_part["authorization_id"], 100, False)
    time.sleep(1.3)
    ex = c.req("GET", "/_test/export").j
    for a in ex["state"]["authorizations"]:
        print("LEGACY", {k: a.get(k) for k in ("authorization_id", "status", "created_at", "created_exact", "expires_at", "closed_at", "captured_amount")}, flush=True)
    r = S3.c.req("POST", "/_test/import", raw=json.dumps(ex).encode())
    print("HEAD import:", r.s, flush=True)
    e1 = S3.c.req("GET", "/_test/export").j
    for a in e1["state"]["authorizations"]:
        print("HEAD  ", {k: a.get(k) for k in ("authorization_id", "status", "created_at", "created_exact", "expires_at", "closed_at", "captured_amount")}, flush=True)
    tk = {h: login(S3.c, h) for h in ("ada", "bob", "cy")}
    for a in e1["state"]["authorizations"]:
        C = us(a["created_at"])
        print("HEAD views ada for", a["authorization_id"], a["status"], "created+1us", view(S3.c, tk["ada"], C + 1), "created+1ms", view(S3.c, tk["ada"], C + 1000), flush=True)
finally:
    SL.stop(); S3.stop()
