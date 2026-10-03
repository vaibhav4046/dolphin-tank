"""Runs INSIDE the network namespace of a container started with `--network none` (so only loopback exists).
Proves: outbound is impossible, the service still starts and serves the whole browser product from the binary, and nothing it
serves points at another host. Stdlib only."""
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8080"
FAILS = []


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " :: %s" % (str(detail)[:300],)))
    if not cond:
        FAILS.append(name)


def get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# the namespace has no route out
blocked = 0
for ip in ("1.1.1.1", "8.8.8.8", "93.184.216.34"):
    try:
        socket.create_connection((ip, 80), timeout=3).close()
        print("outbound reachable to", ip)
    except OSError as e:
        blocked += 1
        print("outbound blocked to %s -> %s" % (ip, type(e).__name__))
try:
    socket.getaddrinfo("example.com", 80)
    dns = True
except OSError:
    dns = False
ok("no outbound network: 3 of 3 connects fail", blocked == 3)
ok("no DNS", not dns)
ifaces = open("/proc/net/dev").read().split("\n")[2:]
names = [l.split(":")[0].strip() for l in ifaces if ":" in l]
ok("only loopback interface exists %s" % names, names == ["lo"], names)

t0 = time.time()
up = False
while time.time() - t0 < 60:
    try:
        s, b, h = get("/health")
        up = s == 200 and json.loads(b) == {"status": "ok"}
        if up:
            break
    except Exception:
        pass
    time.sleep(0.2)
ok("service healthy with --network none (%.1fs)" % (time.time() - t0), up)

# the whole UI from the binary
seen = {}
queue = ["/", "/login", "/signup", "/requests", "/split", "/authorizations"]
html_hdr = {"Accept": "text/html"}
done = set()
while queue:
    p = queue.pop(0)
    if p in done:
        continue
    done.add(p)
    s, b, h = get(p, html_hdr if p in ("/", "/login", "/signup", "/requests", "/split", "/authorizations") else None)
    seen[p] = (s, h.get("Content-Type", ""), len(b))
    ok("GET %s -> 200 (%s, %d bytes)" % (p, h.get("Content-Type", ""), len(b)), s == 200 and len(b) > 0, (s, b[:100]))
    txt = b.decode("utf-8", "replace") if "font" not in h.get("Content-Type", "") and not p.endswith((".woff2", ".woff", ".ttf")) else ""
    for m in re.findall(r"""(?:src|href)=["']([^"'#]+)["']""", txt) + re.findall(r"""url\(\s*["']?([^)"']+)["']?\s*\)""", txt) + re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", txt):
        m = m.strip()
        if m.startswith("data:") or m.startswith("mailto:") or m.startswith("#"):
            continue
        if re.match(r"^[a-z]+://", m) or m.startswith("//"):
            ok("served %s references an absolute URL %s" % (p, m), False, m)
            continue
        target = urllib.parse.urlparse(urllib.parse.urljoin(BASE + p, m)).path
        if target not in done and target not in queue:
            queue.append(target)
    ext = re.findall(r"https?://[^\s\"'<>)]+", txt)
    ext = [e for e in ext if not e.startswith("http://www.w3.org/")]
    ok("served %s contains no http(s) URL to another host (found %s)" % (p, ext[:3]), not ext, ext)

kinds = {}
for p, (s, ct, n) in seen.items():
    kinds.setdefault(ct.split(";")[0], []).append(p)
print("assets served by the binary:", {k: len(v) for k, v in kinds.items()})
ok("fonts are served by the binary (woff2)", any("font" in k or k.endswith("woff2") for k in kinds), kinds.keys())
ok("scripts are served by the binary", any("javascript" in k for k in kinds), kinds.keys())
ok("stylesheets are served by the binary", any("css" in k for k in kinds), kinds.keys())

# the API works with no network
fx = {"currency": "EUR", "minor_units": 2, "users": [
    {"id": "u_a", "email": "a@example.com", "password": "correct horse", "display_name": "A", "handle": "a", "balance": 1000},
    {"id": "u_b", "email": "b@example.com", "password": "correct horse", "display_name": "B", "handle": "b", "balance": 0}]}
req = urllib.request.Request(BASE + "/_test/reset", data=json.dumps(fx).encode(), method="POST", headers={"Content-Type": "application/json"})
ok("reset 204", urllib.request.urlopen(req, timeout=10).status == 204)
def post(path, body, tok=None, key=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key: h["Idempotency-Key"] = key
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST", headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
tok = post("/auth/login", {"email": "a@example.com", "password": "correct horse"})[1]["token"]
tokb = post("/auth/login", {"email": "b@example.com", "password": "correct horse"})[1]["token"]
s, pay = post("/payments", {"to_handle": "b", "amount": 400, "note": "offline"}, tok, "k1")
ok("payment 201 with no network", s == 201, (s, pay))
s, rf = post("/payments/%s/refunds" % pay["payment_id"], {"amount": 100}, tokb, "k2")
ok("refund 201 with no network", s == 201 and rf["refund_of"] == pay["payment_id"], (s, rf))
print("\nB11 probe: %s" % ("ALL PASSED" if not FAILS else "FAILED %s" % FAILS))
sys.exit(1 if FAILS else 0)
