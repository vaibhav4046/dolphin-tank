"""Black-box check of POST /correction-batches against a running stage-4 binary.

usage: python batch_blackbox.py http://127.0.0.1:PORT export1.json [export2.json ...]

Each export is a real export of an earlier build (stage 1, 2 or 3). For each one: import it, then
exercise the batch route over HTTP only (auth order, settlement rules, replay, reuse, a rejected batch
leaving /_test/export byte-identical, 8 concurrent batches sharing a payment, export->import->export).
Prints one line per check; exit status 1 if any check failed.
"""
import json
import sys
import threading
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
failures = []


def call(method, path, token=None, key=None, body=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def code(b):
    try:
        return json.loads(b)["error"]["code"]
    except Exception:
        return None


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if (detail and not ok) else ""))
    if not ok:
        failures.append(name)


def item(pid, rev, amount, eff):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "blackbox"}


def run(path):
    print("== " + path)
    raw = open(path, "rb").read()
    state = json.loads(raw)["state"]
    ops = [u for u, v in state["sys"]["operators"].items() if v]
    tok = {u: t for t, u in state["tokens"].items()}
    op = tok[ops[0]]
    other = next(t for u, t in tok.items() if u != ops[0])
    s, _ = call("POST", "/_test/import", raw=raw)
    check("import 204", s == 204, str(s))
    latest = {}
    for r in state.get("revisions", []):
        latest[r["payment_id"]] = max(latest.get(r["payment_id"], 1), r["revision"])
    rev = lambda p: latest.get(p, 1)
    groups = {}
    for p in state["payments"]:
        if p.get("settlement_id"):
            groups.setdefault(p["settlement_id"], []).append(p["payment_id"])
    ordinary = [p["payment_id"] for p in state["payments"] if not p.get("settlement_id") and not p.get("authorization_id") and p["amount"] > 0]
    sid, members = next(iter(groups.items()))
    eff = "2026-09-27T10:00:00+00:00"
    body = lambda items: {"corrections": items}

    s, b = call("POST", "/correction-batches", None, "k", body([item(ordinary[0], rev(ordinary[0]), 1, eff)]))
    check("no token -> 401", s == 401, str(s))
    s, b = call("POST", "/correction-batches", other, "k", body([item(ordinary[0], rev(ordinary[0]), 1, eff)]))
    check("non-operator -> 403", s == 403, str(s))
    s, b = call("POST", "/correction-batches", op, None, body([item(ordinary[0], rev(ordinary[0]), 1, eff)]))
    check("operator without key -> 400", s == 400 and code(b) == "missing_idempotency_key", "%s %s" % (s, b))

    before = call("GET", "/_test/export")[1]
    s, b = call("POST", "/correction-batches", op, "inc", body([item(m, rev(m), 1, eff) for m in members[:-1]]))
    check("incomplete settlement -> 422", s == 422 and code(b) == "incomplete_settlement", "%s %s" % (s, b))
    s, b = call("POST", "/correction-batches", op, "ins", body([item(m, rev(m), 1, eff if i else "2026-09-27T10:00:01+00:00") for i, m in enumerate(members)]))
    check("different instants -> 422 validation_failed", s == 422 and code(b) == "validation_failed", "%s %s" % (s, b))
    s, b = call("POST", "/correction-batches", op, "unk", body([item("p_nope", 1, 1, eff)]))
    check("unknown payment -> 404", s == 404, str(s))
    s, b = call("POST", "/correction-batches", op, "old", body([item(ordinary[0], rev(ordinary[0]) + 5, 1, eff)]))
    check("stale revision -> 409", s == 409 and code(b) == "stale_revision", "%s %s" % (s, b))
    s, b = call("POST", "/correction-batches", op, "big", body([item(ordinary[0], rev(ordinary[0]), 1000000000, eff)]))
    check("unaffordable -> 409 insufficient_funds", s == 409 and code(b) == "insufficient_funds", "%s %s" % (s, b))
    check("rejected batches leave /_test/export byte-identical", call("GET", "/_test/export")[1] == before)

    spell = [eff, "2026-09-27T12:00:00+02:00", "2026-09-27T10:00:00Z", "2026-09-27T05:00:00-05:00"]
    items = [item(m, rev(m), 1, spell[i % 4]) for i, m in enumerate(members)] + [item(ordinary[0], rev(ordinary[0]), 1, eff)]
    s, b = call("POST", "/correction-batches", op, "ok", body(items))
    check("complete settlement + ordinary payment -> 201", s == 201, "%s %s" % (s, b))
    out = json.loads(b)
    check("one recorded_at, batch id on every revision, input order",
          all(r["recorded_at"] == out["recorded_at"] and r["correction_batch_id"] == out["correction_batch_id"] for r in out["revisions"])
          and [r["payment_id"] for r in out["revisions"]] == [i["payment_id"] for i in items])
    s2, b2 = call("POST", "/correction-batches", op, "ok", body(items))
    check("replay -> 200 identical bytes", s2 == 200 and b2 == b)
    s3, b3 = call("POST", "/correction-batches", op, "ok", body(items[:1]))
    check("same key other body -> 409 idempotency_key_reuse", s3 == 409 and code(b3) == "idempotency_key_reuse")

    e1 = call("GET", "/_test/export")[1]
    s, _ = call("POST", "/_test/import", raw=e1)
    check("re-import of own export 204", s == 204)
    check("export -> import -> export byte-identical", call("GET", "/_test/export")[1] == e1)
    s4, b4 = call("POST", "/correction-batches", op, "ok", body(items))
    check("batch replay survives the import", s4 == 200 and b4 == b)

    # 8 concurrent batches that all name the same ordinary payment at its current revision.
    state2 = json.loads(call("GET", "/_test/export")[1])["state"]
    cur = {}
    for r in state2["revisions"]:
        cur[r["payment_id"]] = max(cur.get(r["payment_id"], 1), r["revision"])
    shared = ordinary[0]
    results = []

    def worker(i):
        s, b = call("POST", "/correction-batches", op, "race-%d" % i, body([item(shared, cur[shared], 1 + i % 2, eff)]))
        results.append(s)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("8 concurrent batches on one revision: exactly one 201, rest 409", sorted(results) == [201] + [409] * 7, str(sorted(results)))


for p in sys.argv[2:]:
    run(p)
print("FAILED: %s" % failures if failures else "ALL PASSED")
sys.exit(1 if failures else 0)
