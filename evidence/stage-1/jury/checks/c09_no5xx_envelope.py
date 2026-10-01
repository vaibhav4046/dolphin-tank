"""J08, J10, J12, J13, J15, J30, J33, J38: no 5xx under 50 concurrent mixed requests + malformed-input sweep; envelope + content type on every 4xx; latency."""
import http.client, json, random, threading, time
from lib import *

CODES = {"malformed_request", "missing_idempotency_key", "unauthenticated", "forbidden", "not_found", "idempotency_key_reuse", "validation_failed",
         "insufficient_funds", "self_payment", "self_request", "request_not_pending", "email_taken", "handle_taken"}
BAD = []
LAT = []
SEEN = {}


def check(tag, r):
    SEEN[r.s] = SEEN.get(r.s, 0) + 1
    if r.s >= 500:
        BAD.append((tag, "5xx", r.s, r.b[:120]))
    if r.s >= 400:
        e = (r.j or {}).get("error") if isinstance(r.j, dict) else None
        if not (isinstance(e, dict) and isinstance(e.get("code"), str) and isinstance(e.get("message"), str)):
            BAD.append((tag, "no envelope", r.s, r.b[:120], r.h.get("content-type")))
        elif e["code"] not in CODES:
            BAD.append((tag, "unknown code", r.s, e["code"]))
        if not r.h.get("content-type", "").lower().replace(" ", "").startswith("application/json;charset=utf-8"):
            BAD.append((tag, "content-type", r.s, r.h.get("content-type")))
    elif r.s in (200, 201) and not r.h.get("content-type", "").lower().replace(" ", "").startswith("application/json;charset=utf-8"):
        BAD.append((tag, "content-type 2xx", r.s, r.h.get("content-type")))


U = [user("ada", 100000), user("bob", 50000), user("cy", 0), user("dee", 5000), user("op", 0)]
TOTAL = sum(u["balance"] for u in U)
t = setup(fx(U, ops=["u_op"]))
A = t["ada"]
ok("health exact body + content type", (lambda r: r.s == 200 and r.j == {"status": "ok"} and r.h["content-type"].lower().replace(" ", "") == "application/json;charset=utf-8")(call("GET", "/health")))
print("OBS HEAD /health ->", call("HEAD", "/health").s)

# ---- part 1: routing / method / path oddities
odd = [("GET", "/nope"), ("POST", "/nope"), ("GET", "/"), ("GET", "/payments"), ("PUT", "/payments"), ("DELETE", "/me"), ("PATCH", "/requests"), ("POST", "/me"),
       ("POST", "/activity"), ("OPTIONS", "/payments"), ("GET", "/me/"), ("GET", "//me"), ("POST", "/requests//pay"), ("POST", "/requests/%00/pay"),
       ("POST", "/requests/%ZZ/pay"), ("POST", "/requests/" + "x" * 10000 + "/pay"), ("POST", "/requests/x/pay/extra"), ("GET", "/_test/reset"), ("POST", "/_test/export"),
       ("GET", "/health?x=%ZZ"), ("GET", "/requests/x"), ("DELETE", "/requests/x/cancel"), ("GET", "/requests/x/pay"), ("GET", "/auth/login"), ("GET", "/settlements"),
       ("GET", "/splits"), ("POST", "/requests/x/PAY"), ("GET", "/ME"), ("GET", "/../me"), ("GET", "/me/../health")]
for m, p in odd:
    r = call(m, p, token=A, key=k(), raw=b"{}" if m in ("POST", "PUT", "PATCH") else None)
    check("odd %s %s" % (m[:4], p[:30]), r)
    print("OBS %-7s %-40s -> %s %s %s" % (m, p[:40], r.s, r.code, r.h.get("content-type")))
# statuses for unknown routes must be 4xx
ok("unknown route GET /nope -> 404", call("GET", "/nope", token=A).s == 404)

# ---- part 2: malformed body sweep on every POST endpoint
BODIES = ["", "{", "}", "[]", "null", '"s"', "123", "true", "{\"amount\":1e999}", '{"amount":' + "9" * 400 + "}", "[" * 100000, "{\"a\":" * 50000, b"\xff\xfe\x00", b"\x00", b"\xef\xbb\xbf{}",
          '{"amount":1,"to_handle":"bob","note":"' + "x" * 2_000_000 + '"}', '{"a":1}{"b":2}', "{'a':1}", '{"a":1,}', "\x00" * 1000, "0" * 100000, '{"amount":-0}', '{"to_handle":"\\ud800","amount":1}']
EP = [("POST", "/auth/signup", False), ("POST", "/auth/login", False), ("POST", "/payments", True), ("POST", "/requests", True), ("POST", "/requests/rq_1/pay", True),
      ("POST", "/requests/rq_1/decline", False), ("POST", "/requests/rq_1/cancel", False), ("POST", "/splits", True), ("POST", "/settlements", True),
      ("POST", "/_test/reset", False), ("POST", "/_test/import", False)]
t0 = time.time()
for m, p, needkey in EP:
    tok = t["op"] if p == "/settlements" else A
    for b in BODIES:
        if p == "/_test/reset":
            try:
                if isinstance(json.loads(b), dict):
                    continue  # a JSON object is a (lenient) valid fixture and would legitimately wipe state
            except Exception:
                pass
        r = call(m, p, raw=b, token=tok, key=k() if needkey else None, timeout=30)
        check("malformed %s %r" % (p, (b[:12] if isinstance(b, (bytes, str)) else b)), r)
        if p in ("/_test/reset", "/_test/import", "/auth/signup", "/auth/login", "/payments", "/requests", "/splits", "/settlements") and r.s in (200, 201, 204):
            if not (b in ('{"to_handle":"\\ud800","amount":1}',) or p in ("/requests/rq_1/decline",)):
                BAD.append(("accepted garbage", p, (b[:20] if isinstance(b, (str, bytes)) else b), r.s))
print("malformed sweep %d requests in %.1fs" % (len(EP) * len(BODIES), time.time() - t0))
ok("state untouched by garbage (reset/import/pay garbage rejected): balances", sum(bal(t[h]) for h in t) == TOTAL and bal(A) == 100000)
for hdr_name, val in (("Idempotency-Key", "k" * 100000), ("Authorization", "Bearer " + "a" * 100000), ("X-Junk", "j" * 50000), ("Content-Type", "garbage/\x01")):
    try:
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=A, key=k(), hdrs={hdr_name: val})
        check("big header " + hdr_name, r)
        print("OBS big header %s -> %s %s" % (hdr_name, r.s, r.code))
    except Exception as e:
        print("OBS big header %s -> client error %r" % (hdr_name, e))
r = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1}', token=A, key=k(), hdrs={"Content-Type": "text/plain"})
print("OBS payments with Content-Type text/plain ->", r.s, r.code)
check("ctype text/plain", r)
c = http.client.HTTPConnection(HOST, PORT, timeout=10)
c.request("POST", "/payments", body=iter([b'{"to_handle":"bob",', b'"amount":1}']), headers={"Authorization": "Bearer " + A, "Idempotency-Key": k(), "Content-Type": "application/json"}, encode_chunked=True)
rr = c.getresponse(); rb = rr.read(); c.close()
ok("chunked-encoded JSON body accepted (201)", rr.status == 201, (rr.status, rb[:120]))
c = http.client.HTTPConnection(HOST, PORT, timeout=10)
c.request("GET", "/me", body=b'{"x":1}', headers={"Authorization": "Bearer " + A})
rr = c.getresponse(); rr.read(); c.close()
ok("GET with body is served normally", rr.status == 200, rr.status)

# ---- part 3: query fuzz
rnd = random.Random(7)
qs = ["limit=%zz", "limit=1&limit=2", "limit=1&limit=x", "offset=" + "9" * 50, "limit=" + "9" * 50, "direction=incoming&direction=outgoing", "status=%00", "limit=é", "%", "&&&&", "=", "a" * 20000, "limit=1;offset=2", "offset=-0", "limit=+", "limit=1 2"]
for path in ("/activity", "/requests"):
    for q in qs:
        try:
            r = call("GET", path + "?" + q, token=A)
        except Exception as e:
            print("OBS query %r client err %r" % (q[:20], e)); continue
        check("query %s?%s" % (path, q[:20]), r)

# ---- part 4: 50 concurrent mixed requests, random valid/invalid, with conservation afterwards
hs = ["ada", "bob", "cy", "dee", "op"]
extra = {}
elock = threading.Lock()


def one(rnd, tid, n):
    c_ = rnd.random()
    a = rnd.choice(hs)
    tok = t[a]
    b = rnd.choice([x for x in hs if x != a])
    if c_ < 0.25:
        amt = rnd.choice([1, 5, 17, 100, 1000, 0, -3, 10 ** 9, 10 ** 9 + 1, "5", True, None, 1.5])
        return call("POST", "/payments", {"to_handle": rnd.choice([b, b, b, "nobody", a]), "amount": amt, "visibility": rnd.choice(["public", "private", "x"]), "note": rnd.choice(["", "n", "x" * 201, None])}, token=tok, key=k())
    if c_ < 0.35:
        return call("POST", "/requests", {"payer_handle": b, "amount": rnd.choice([1, 50, 600, 0])}, token=tok, key=rnd.choice([k(), "shared-" + str(tid % 3)]))
    if c_ < 0.45:
        rs = call("GET", "/requests?limit=50", token=tok).j
        if rs and rs.get("requests"):
            rq = rnd.choice(rs["requests"])
            act = rnd.choice(["pay", "pay", "decline", "cancel"])
            return call("POST", "/requests/%s/%s" % (rq["request_id"], act), rnd.choice([{}, {"visibility": "private"}, {"visibility": "zz"}]), token=tok, key=k())
        return call("GET", "/me", token=tok)
    if c_ < 0.52:
        return call("POST", "/splits", {"amount": rnd.choice([1, 10, 1001]), "participant_handles": rnd.sample(hs, rnd.randint(1, 5))}, token=tok, key=k())
    if c_ < 0.58:
        return call("POST", "/settlements", {"transfers": [{"from_handle": rnd.choice(hs), "to_handle": rnd.choice(hs), "amount": rnd.choice([1, 20, 10 ** 6])} for _ in range(rnd.randint(1, 4))]}, token=rnd.choice([t["op"], t["op"], tok]), key=k())
    if c_ < 0.66:
        em = "s%d_%d@x.com" % (tid, n)
        r = call("POST", "/auth/signup", {"email": em, "password": "password1", "display_name": "S"})
        if r.s == 201:
            with elock:
                extra[em] = r.j["token"]
        return r
    if c_ < 0.72:
        return call("POST", "/auth/login", {"email": rnd.choice(["ada@example.com", "ghost@x.com"]), "password": rnd.choice(["correct horse", "wrong"])})
    if c_ < 0.80:
        return call("GET", rnd.choice(["/activity", "/requests", "/me", "/requests?status=pending", "/activity?limit=3&offset=1", "/requests?limit=0"]), token=tok)
    if c_ < 0.85:
        return call("GET", "/_test/export")
    if c_ < 0.90:
        return call("POST", "/payments", raw=rnd.choice(["{", "[]", "", "null"]), token=tok, key=k())
    if c_ < 0.95:
        return call("GET", "/me", token=rnd.choice(["bad", "", tok + "x"]))
    return call("GET", "/health")


def worker(tid):
    rnd = random.Random(tid)
    for n in range(40):
        t0 = time.time()
        r = one(rnd, tid, n)
        LAT.append(time.time() - t0)
        check("mixed", r)


for rnd_i in range(3):
    ths = [threading.Thread(target=worker, args=(rnd_i * 100 + i,)) for i in range(50)]
    t0 = time.time()
    [x.start() for x in ths]; [x.join() for x in ths]
    print("mixed round %d: 50 threads x 40 ops in %.1fs" % (rnd_i, time.time() - t0))
    tot = sum(bal(t[h]) for h in t) + sum(bal(tk) for tk in extra.values())
    ok("mixed round %d: conservation (sum of all wallets incl. %d new users == seeded total) and no negative" % (rnd_i, len(extra)), tot == TOTAL and min(bal(t[h]) for h in t) >= 0 and min([bal(x) for x in extra.values()] or [0]) >= 0, tot)

TRANSPORT = {"odd POST /requests/%ZZ/pay", "big header Content-Type"}  # rejected by net/http before any handler: invalid URL escape / control byte in header
print("OBS transport-level plain-text 4xx (stdlib, pre-handler):", [b[:4] for b in BAD if b[0] in TRANSPORT])
BAD = [b for b in BAD if b[0] not in TRANSPORT]
ok("no 5xx / envelope / content-type / unknown-code violations across the sweep (%d problems)" % len(BAD), not BAD, BAD[:8])
ok("max latency under 50 concurrent: %.2fs (<5s)" % max(LAT), max(LAT) < 5, max(LAT))
print("OBS status histogram:", dict(sorted(SEEN.items())))
done("c09_no5xx_envelope")
