#!/bin/bash
# offline serving + RUN.md as written: internal network, sibling container drives the service
set -u
IMG=${IMG:-pocketful-s3-jury}
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/logs; mkdir -p "$LOGS"; OUT=$LOGS/offline-and-runmd.log
service docker start >/dev/null 2>&1
{
echo "== RUN.md verbatim (tag pocketful-s3-runmd): docker build -t pocketful-s3-runmd . ; docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s3-runmd ; curl /health"
(cd /root/jury/s3/stage-3 && docker build -q -t pocketful-s3-runmd . | tail -1)
docker rm -f pf3runmd >/dev/null 2>&1
docker run -d --rm --name pf3runmd -e PORT=8080 -p 18999:8080 pocketful-s3-runmd >/dev/null
for i in $(seq 1 100); do curl -sf http://127.0.0.1:18999/health && break; sleep 0.1; done; echo
docker rm -f pf3runmd >/dev/null 2>&1
echo "== internal network, sibling container"
docker network rm pf3-int >/dev/null 2>&1; docker network create --internal pf3-int >/dev/null
docker rm -f pf3off >/dev/null 2>&1
docker run -d --name pf3off --network pf3-int -e PORT=8080 "$IMG" >/dev/null
sleep 1
docker run -i --rm --network pf3-int python:3.12-alpine python - <<'PY'
import urllib.request, socket, re, json
base = "http://pf3off:8080"
def get(p, hdr=None):
    r = urllib.request.Request(base + p, headers=hdr or {})
    with urllib.request.urlopen(r, timeout=5) as x:
        return x.status, x.headers.get("content-type"), x.read()
for h in ("1.1.1.1", "8.8.8.8"):
    try:
        socket.create_connection((h, 53), timeout=2); print("OUTBOUND REACHABLE", h)
    except OSError as e:
        print("outbound blocked to", h, "->", type(e).__name__)
print("health", get("/health")[:2])
bad = []
refs = set()
for route in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
    st, ct, body = get(route, {"Accept": "text/html"})
    txt = body.decode()
    print(route, st, ct, len(body))
    for m in re.finditer(r'(?:src|href)\s*=\s*"([^"]+)"', txt):
        u = m.group(1); refs.add(u)
        if re.match(r"^(https?:)?//", u): bad.append((route, u))
for u in sorted(refs):
    if u.startswith("/assets/"):
        st, ct, body = get(u)
        print("asset", u, st, ct, len(body))
        if u.endswith(".css"):
            for m in re.finditer(r"url\(([^)]+)\)", body.decode()):
                v = m.group(1).strip("'\"")
                if re.match(r"^(https?:)?//", v): bad.append((u, v))
                elif not v.startswith("data:"):
                    p = v if v.startswith("/") else "/assets/css/" + v
                    print("  css url", v, get(p)[0:2])
        if u.endswith(".js"):
            if re.search(r"https?://(?!www\.w3\.org)", body.decode()): bad.append((u, "http(s) URL in js"))
print("EXTERNAL REFERENCES:", bad if bad else "none")
# stage-3 endpoints alive offline
j = lambda m, p, b=None, t=None, k=None: __import__("json")
import urllib.error
def req(m, p, b=None, t=None, k=None):
    h = {"Content-Type": "application/json"}
    if t: h["Authorization"] = "Bearer " + t
    if k: h["Idempotency-Key"] = k
    r = urllib.request.Request(base + p, data=json.dumps(b).encode() if b is not None else None, headers=h, method=m)
    try:
        with urllib.request.urlopen(r, timeout=5) as x: return x.status, json.loads(x.read() or b"null")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
f = {"currency": "EUR", "minor_units": 2, "users": [{"id": "u_a", "email": "a@example.com", "password": "correct horse", "display_name": "A", "handle": "a", "balance": 1000}, {"id": "u_b", "email": "b@example.com", "password": "correct horse", "display_name": "B", "handle": "b", "balance": 0}]}
print("reset", req("POST", "/_test/reset", f)[0])
tok = req("POST", "/auth/login", {"email": "a@example.com", "password": "correct horse"})[1]["token"]
print("pay", req("POST", "/payments", {"to_handle": "b", "amount": 100}, tok, "k1")[0])
print("statement", req("GET", "/statement", None, tok)[0], "me", req("GET", "/me?as_of=2030-01-01T00:00:00%2B00:00", None, tok)[0])
PY
docker rm -f pf3off >/dev/null; docker network rm pf3-int >/dev/null
} 2>&1 | tee "$OUT"
