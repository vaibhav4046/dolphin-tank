"""jury checks, part 4: U41 real exports of the accepted stage-1/2/3 services imported into stage 4, then batches on them,
then stage-4's own export -> import -> export byte identity (same process, new process), replay survival, id reservation.

usage: python jury_batch_4.py s4.exe s1.exe s2.exe s3.exe
"""
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta

from jlib import *

EXE4, EXES = sys.argv[1], {1: sys.argv[2], 2: sys.argv[3], 3: sys.argv[4]}
USERS = {h: 10000 for h in ["op", "ada", "bob", "cy", "dee", "eve"]}


def dt(s):
    return datetime.fromisoformat(s)


class Src:
    pass


def build(stage):
    svc = Svc(EXES[stage])
    w = World(svc, fixture(USERS))
    src = Src()
    src.svc, src.w, src.receipts = svc, w, []

    def post(who, path, body, name):
        k = key("src%d-%s" % (stage, name))
        s, b = svc.call("POST", path, w.tok[who], k, body)
        assert s == 201, (stage, name, s, b)
        src.receipts.append({"name": name, "who": who, "path": path, "key": k, "body": body, "resp": b})
        return json.loads(b)

    src.ids = {}
    src.ids["r1"] = post("ada", "/payments", {"to_handle": "bob", "amount": 1000, "note": "n1", "visibility": "public"}, "pay1")["payment_id"]
    rq = post("bob", "/requests", {"payer_handle": "ada", "amount": 400, "note": "taxi"}, "req1")
    src.ids["rq_paid"] = post("ada", "/requests/%s/pay" % rq["request_id"], {"visibility": "private"}, "reqpay1")["payment_id"]
    src.ids["rq_pending"] = post("bob", "/requests", {"payer_handle": "cy", "amount": 300, "note": "pending"}, "req2")["request_id"]
    post("ada", "/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, "split1")
    s1 = post("op", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "s1a"},
                                                   {"from_handle": "bob", "to_handle": "cy", "amount": 100},
                                                   {"from_handle": "cy", "to_handle": "dee", "amount": 100, "visibility": "private"}]}, "set1")
    src.ids["S1"] = [p["payment_id"] for p in s1["payments"]]
    s2 = post("op", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "eve", "amount": 50}, {"from_handle": "eve", "to_handle": "ada", "amount": 20}]}, "set2")
    src.ids["S2"] = [p["payment_id"] for p in s2["payments"]]
    post("ada", "/payments", {"to_handle": "dee", "amount": 77, "note": "priv", "visibility": "private"}, "pay2")
    if stage >= 2:
        post("ada", "/authorizations", {"to_handle": "dee", "amount": 500, "note": "open"}, "auth_open")
        a = post("ada", "/authorizations", {"to_handle": "bob", "amount": 600, "note": "partial"}, "auth_part")
        c1 = post("bob", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 200, "final": False}, "cap_part")
        src.ids["CAP"] = c1["payment_id"]
        a2 = post("ada", "/authorizations", {"to_handle": "cy", "amount": 100, "note": "done"}, "auth_done")
        post("cy", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 100}, "cap_done")
        a3 = post("ada", "/authorizations", {"to_handle": "bob", "amount": 50, "note": "void"}, "auth_void")
        s, o = svc.j("POST", "/authorizations/%s/void" % a3["authorization_id"], w.tok["ada"])
        assert s == 200, (s, o)
    if stage >= 3:
        E = iso(now())
        post("ada", "/payments/%s/corrections" % src.ids["r1"], {"expected_revision": 1, "amount": 900, "effective_at": E, "reason": "c1"}, "corr1")
        post("ada", "/payments/%s/corrections" % src.ids["r1"], {"expected_revision": 2, "amount": 950, "effective_at": E, "reason": "c2"}, "corr2")
        s, st = svc.j("GET", "/statement?limit=2", w.tok["ada"])
        src.snapshot = st["snapshot"]
        src.snapshot_page = svc.call("GET", "/statement?snapshot=%s&limit=2&offset=0" % src.snapshot, w.tok["ada"])
    src.bal = {h: w.me(h) for h in w.tok}
    src.activity = {h: svc.j("GET", "/activity?limit=200", w.tok[h])[1] for h in w.tok}
    src.revs = {}
    if stage >= 3:
        src.revs = w.revs("ada", src.ids["r1"])
    src.export = svc.export()
    src.tokens = dict(w.tok)
    return src


SUMMARY = {}


def verify(stage, src):
    tag = "U41/stage%d" % stage
    s4 = Svc(EXE4)
    exp_hash = hashlib.sha256(src.export).hexdigest()[:16]
    s, b = s4.import_(src.export)
    check("%s: stage-%d export (sha256 %s..., %d bytes) imports into stage 4 -> 204" % (tag, stage, exp_hash, len(src.export)), s == 204, (s, b[:300]))
    if s != 204:
        s4.stop()
        return
    tok = src.tokens
    for h, t in tok.items():
        s, o = s4.j("GET", "/me", t)
        want = src.bal[h]
        same = s == 200 and all(o.get(k) == want[k] for k in want)
        check("%s: pre-export bearer token of %s still works, same /me" % (tag, h), same, (o, want))
    # receipts replay
    for r in src.receipts:
        s, b = s4.call("POST", r["path"], tok[r["who"]], r["key"], r["body"])
        okj = s == 200 and json.loads(b) == json.loads(r["resp"])
        check("%s: replay of %s -> 200 original body" % (tag, r["name"]), okj, (s, b[:200]))
        if okj and b != r["resp"]:
            print("  note: %s body equal as JSON but not byte-identical" % r["name"])
    # tokens/keys scoped to the user: wrong user, same key -> not a replay
    r0 = src.receipts[0]
    s, b = s4.call("POST", r0["path"], tok["cy"], r0["key"], r0["body"])
    check("%s: another user's use of the same key is a first use (201)" % tag, s == 201, (s, b[:200]))
    # activity equality (source fields preserved; stage 4 may add refund_of)
    for h in tok:
        s, o = s4.j("GET", "/activity?limit=200", tok[h])
        src_ps = src.activity[h]["payments"]
        got = {p["payment_id"]: p for p in o["payments"]}
        miss = [p["payment_id"] for p in src_ps if p["payment_id"] not in got]
        diff = [p["payment_id"] for p in src_ps if p["payment_id"] in got and any(got[p["payment_id"]].get(k) != v for k, v in p.items())]
        check("%s: /activity of %s keeps every source payment and field (extra keys: %s)" % (tag, h, sorted({k for p in o["payments"] for k in p} - {k for p in src_ps for k in p})),
              not miss and not diff, (miss, diff))
    # settlement membership retained
    for sname in ("S1", "S2"):
        mem = {}
        for h in tok:
            for p in s4.j("GET", "/activity?limit=200", tok[h])[1]["payments"]:
                if p.get("settlement_id"):
                    mem.setdefault(p["settlement_id"], set()).add(p["payment_id"])
        check("%s: %s membership retained as %s" % (tag, sname, sorted(src.ids[sname])), set(src.ids[sname]) in mem.values(), mem)
    # revisions retained for stage 3
    op = tok["op"]
    if stage >= 3:
        s, o = s4.j("GET", "/payments/%s/revisions" % src.ids["r1"], tok["ada"])
        got = o["revisions"]
        strip = lambda r: {k: v for k, v in r.items() if k != "correction_batch_id"}
        check("%s: imported corrections retained (3 revisions, same amounts/times/reasons), correction_batch_id null" % tag,
              [strip(r) for r in got] == [strip(r) for r in src.revs] and all(r["correction_batch_id"] is None for r in got), (got, src.revs))
        st = s4.call("GET", "/statement?snapshot=%s&limit=2&offset=0" % src.snapshot, tok["ada"])
        print("  observation: stage-3 statement snapshot token after import into stage 4 -> HTTP %s; token present in source export text: %s" %
              (st[0], src.snapshot.encode() in src.export))
        SUMMARY["snapshot_after_import_s%d" % stage] = st[0]
    # batches on imported data
    E = iso(now())
    cur = lambda pid: max(r["revision"] for r in s4.j("GET", "/payments/%s/revisions" % pid, tok["ada"] if True else None)[1]["revisions"]) if True else 1
    def revof(pid):
        for h in ("ada", "bob", "cy", "dee", "eve"):
            s, o = s4.j("GET", "/payments/%s/revisions" % pid, tok[h])
            if s == 200:
                return max(r["revision"] for r in o["revisions"])
        raise AssertionError(pid)
    def batch(items, k=None):
        return s4.j("POST", "/correction-batches", op, k or key("imp"), {"corrections": items})
    S1, S2 = src.ids["S1"], src.ids["S2"]
    before = s4.export()
    s, o = batch([item(m, 1, 50, E) for m in S1[:2]])
    check("%s: incomplete imported settlement -> 422 incomplete_settlement" % tag, s == 422 and code(o) == "incomplete_settlement", (s, o))
    s, o = batch([item(S2[0], 1, 10, E)])
    check("%s: one of two members of the second imported settlement -> 422 incomplete_settlement" % tag, s == 422 and code(o) == "incomplete_settlement", (s, o))
    s, o = batch([item(m, 1, 50, E) for m in S1] + [item(S2[0], 1, 10, E), item(S2[1], 1, 10, iso(now() - timedelta(seconds=1)))])
    check("%s: second settlement with different instants -> 422 validation_failed" % tag, s == 422 and code(o) == "validation_failed", (s, o))
    check("%s: all of the above left the imported state byte-identical" % tag, s4.export() == before)
    r1rev = revof(src.ids["r1"])
    if stage >= 3:
        for bad in (1, 2):
            s, o = batch([item(src.ids["r1"], bad, 960, E)])
            check("%s: stale revision %d of a payment already corrected twice -> 409 stale_revision" % (tag, bad), s == 409 and code(o) == "stale_revision", (s, o))
    check("%s: current revision of r1 is %d" % (tag, 3 if stage >= 3 else 1), r1rev == (3 if stage >= 3 else 1), r1rev)
    if stage >= 2:
        s, o = batch([item(src.ids["CAP"], 1, 1, E)])
        check("%s: imported capture -> 422 linked_payment_immutable" % tag, s == 422 and code(o) == "linked_payment_immutable", (s, o))
    prev_rec = {}
    for pid in S1 + S2 + [src.ids["r1"], src.ids["rq_paid"]]:
        for h in ("ada", "bob", "cy", "dee", "eve"):
            s, o = s4.j("GET", "/payments/%s/revisions" % pid, tok[h])
            if s == 200:
                prev_rec[pid] = max(dt(r["recorded_at"]) for r in o["revisions"])
                break
    items = ([item(m, 1, 50 + i, [iso(now() - timedelta(seconds=3), 0), iso(now() - timedelta(seconds=3), 2)][0]) for i, m in enumerate(S1)])
    t = now() - timedelta(seconds=2)
    items = [item(m, 1, 60, iso(t, tz)) for m, tz in zip(S1, (0, 2, -5))] + [item(S2[0], 1, 10, iso(t, 0)), item(S2[1], 1, 10, iso(t, 9)),
             item(src.ids["r1"], r1rev, 800, E), item(src.ids["rq_paid"], 1, 300, E)]
    b0 = {h: s4.j("GET", "/me", tok[h])[1]["balance"] for h in tok}
    KB = key("imp-ok")
    s, ok = batch(items, KB)
    check("%s: batch over both imported settlements (offset spellings) + imported ordinary + request payment -> 201" % tag, s == 201, (s, ok))
    if s != 201:
        s4.stop()
        return
    b1 = {h: s4.j("GET", "/me", tok[h])[1]["balance"] for h in tok}
    check("%s: balances sum unchanged by the batch" % tag, sum(b0.values()) == sum(b1.values()))
    check("%s: new recorded_at strictly later than every member's imported recorded_at" % tag, all(dt(ok["recorded_at"]) > prev_rec[p] for p in prev_rec if p in {i["payment_id"] for i in items}),
          (ok["recorded_at"], {k: v.isoformat() for k, v in prev_rec.items()}))
    check("%s: revision numbers continue the imported history" % tag, [r["revision"] for r in ok["revisions"]][-2] == r1rev + 1, [r["revision"] for r in ok["revisions"]])
    if stage >= 3:
        s, o = s4.j("GET", "/payments/%s/revisions" % src.ids["r1"], tok["ada"])
        check("%s: r1 history is now imported 3 + batch 1, batch id only on the last" % tag, [r["correction_batch_id"] for r in o["revisions"]] == [None, None, None, ok["correction_batch_id"]], o)
    # a refund of an imported settlement member, then more batches
    kr = key("imp-ref")
    s, rf = s4.j("POST", "/payments/%s/refunds" % S1[0], tok["bob"], kr, {"amount": 20})
    check("%s: refund of an imported settlement member -> 201 (settlement_id null, refund_of set)" % tag, s == 201 and rf["refund_of"] == S1[0] and rf["settlement_id"] is None, (s, rf))
    s, o = batch([item(m, 2, 40, E) for m in S1], key("imp-2"))
    check("%s: second batch on the same settlement at revision 2 -> 201 (refund payment not required)" % tag, s == 201, (s, o))
    s, o = batch([item(m, 3, 10, E) for m in S1], key("imp-3"))
    check("%s: third batch lowering the refunded member below 20 -> 422 refund_exceeds_payment" % tag, s == 422 and code(o) == "refund_exceeds_payment", (s, o))
    # pending request still payable (stage 1/2 retention)
    s, o = s4.j("POST", "/requests/%s/pay" % src.ids["rq_pending"], tok["cy"], key("imp-pay"), {})
    check("%s: imported pending request is still payable -> 201" % tag, s == 201, (s, o))

    # ---- stage-4 own export: same-process and cross-process round trips
    e1 = s4.export()
    s, _ = s4.import_(e1)
    check("%s: stage-4 export -> import (same process) -> 204" % tag, s == 204)
    e2 = s4.export()
    check("%s: export -> import -> export byte-identical (refunds + batches + imported history)" % tag, e1 == e2, (len(e1), len(e2)))
    s4b = Svc(EXE4)
    s, _ = s4b.import_(e1)
    check("%s: stage-4 export imports into a fresh process" % tag, s == 204)
    check("%s: ... and re-exports byte-identical from the fresh process" % tag, s4b.export() == e1)
    s, b = s4b.call("POST", "/correction-batches", op, KB, {"corrections": items})
    check("%s: batch replay after export/import in a new process -> 200, original bytes" % tag, s == 200 and json.loads(b) == ok, (s, b[:200]))
    s, b = s4b.call("POST", "/payments/%s/refunds" % S1[0], tok["bob"], kr, {"amount": 20})
    check("%s: refund replay after import -> 200" % tag, s == 200, (s, b[:200]))
    s, o = s4b.j("POST", "/correction-batches", op, KB, {"corrections": items[:1]})
    check("%s: batch key reuse after import -> 409" % tag, s == 409 and code(o) == "idempotency_key_reuse", (s, o))
    # new batch after import: new id, continues revisions
    cur_r = max(r["revision"] for r in s4b.j("GET", "/payments/%s/revisions" % src.ids["rq_paid"], tok["ada"])[1]["revisions"])
    s, o2 = s4b.j("POST", "/correction-batches", op, key("imp-new"), {"corrections": [item(src.ids["rq_paid"], cur_r, 250, iso(now()))]})
    check("%s: a new batch after import is 201 with an id different from every earlier one" % tag, s == 201 and o2["correction_batch_id"] != ok["correction_batch_id"], (s, o2))
    # id reservation: drop the batch counter from the export; the imported batch ids must still never be reissued
    e = json.loads(e1)
    used = {r["correction_batch_id"] for r in e["state"]["revisions"] if r.get("correction_batch_id")}
    e["state"]["seq"].pop("cb", None)
    s4c = Svc(EXE4)
    s, _ = s4c.import_(json.dumps(e).encode())
    check("%s: export with the batch counter stripped still imports" % tag, s == 204, s)
    s, o3 = s4c.j("POST", "/correction-batches", op, key("imp-new2"), {"corrections": [item(src.ids["rq_paid"], cur_r, 250, iso(now()))]})
    check("%s: batch id issued after a counter-less import (%s) collides with none of %s" % (tag, o3.get("correction_batch_id") if isinstance(o3, dict) else o3, sorted(used)),
          s == 201 and o3["correction_batch_id"] not in used, (s, o3))
    for x in (s4, s4b, s4c):
        x.stop()
    src.svc.stop()


for stage in (1, 2, 3):
    print("== building stage-%d source and import" % stage)
    verify(stage, build(stage))

print("\nPART4 pass=%d fail=%d" % (COUNT["pass"], COUNT["fail"]))
print("summary:", json.dumps(SUMMARY))
if FAILS:
    print("FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
