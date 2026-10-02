"""J42 J43 J51: REAL stage-1 and stage-2 exports imported into stage 3; ledger accounting of payments/authorizations/captures; round trip.
PF1 = ACCEPTED stage-1 image, PF2 = stage-2 image, PF3/PF4/PF5 = stage-3 images."""
import os, time, json
from lib3 import *


def hp(name):
    h, p = os.environ[name].rsplit(":", 1)
    return (h, int(p))


S1, S2, S3A, S3B, S3C = hp("PF1"), hp("PF2"), hp("PF3"), hp("PF4"), hp("PF5")


def C(base):
    def c(method, path, body=None, token=None, key=None, raw=None):
        return call(method, path, body, token=token, key=key, raw=raw, base=base)
    return c


def setup_on(c, f):
    assert c("POST", "/_test/reset", f).s == 204
    return {u["handle"]: c("POST", "/auth/login", {"email": u["email"], "password": u["password"]}).j["token"] for u in f["users"]}


def paypay(c, tok, to, amt, key=None, **kw):
    b = {"to_handle": to, "amount": amt}; b.update(kw)
    key = key or k()
    return c("POST", "/payments", b, token=tok, key=key), key, b


def subset(small, big):
    return all(k_ in big and big[k_] == v for k_, v in small.items())


# ======================================================================= PART A: stage-1 export
c1, c3 = C(S1), C(S3A)
OPEN1 = {"ada": 10000, "bob": 2500, "cy": 4000, "op": 3000}
f1 = fx([user(h, b) for h, b in OPEN1.items()], ops=["u_op"])
t1 = setup_on(c1, f1)
zoe = c1("POST", "/auth/signup", {"email": "zoe@example.com", "password": "correct horse", "display_name": "Zoe"}).j
orig = {}  # key-> (method,path,body,response json, status)
def rec(name, c, method, path, body, tok, key):
    r = c(method, path, body, token=tok, key=key)
    orig[name] = (method, path, body, r.j, r.s, tok, key)
    return r
rec("pay1", c1, "POST", "/payments", {"to_handle": "bob", "amount": 500, "note": "coffee", "visibility": "public"}, t1["ada"], "k-pay1")
time.sleep(0.02)
rec("pay2", c1, "POST", "/payments", {"to_handle": "cy", "amount": 300, "note": "priv", "visibility": "private"}, t1["bob"], "k-pay2")
time.sleep(0.02)
rec("pay3", c1, "POST", "/payments", {"to_handle": "zoe", "amount": 100}, t1["ada"], "k-pay3")
rq1 = rec("rq1", c1, "POST", "/requests", {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, t1["bob"], "k-rq1").j  # stays pending
rq2 = rec("rq2", c1, "POST", "/requests", {"payer_handle": "ada", "amount": 400}, t1["cy"], "k-rq2").j
rec("rq2pay", c1, "POST", "/requests/%s/pay" % rq2["request_id"], {"visibility": "private"}, t1["ada"], "k-rq2pay")
rq3 = rec("rq3", c1, "POST", "/requests", {"payer_handle": "cy", "amount": 50}, t1["bob"], "k-rq3").j
c1("POST", "/requests/%s/cancel" % rq3["request_id"], {}, token=t1["bob"])
rec("split", c1, "POST", "/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, t1["ada"], "k-split")
time.sleep(0.02)
rec("settle", c1, "POST", "/settlements", {"transfers": [{"from_handle": "op", "to_handle": "ada", "amount": 700, "note": "s-a"}, {"from_handle": "ada", "to_handle": "cy", "amount": 200, "visibility": "private"}]}, t1["op"], "k-settle")
fail = rec("fail", c1, "POST", "/payments", {"to_handle": "bob", "amount": 99999999}, t1["ada"], "k-fail")  # 409 insufficient funds, key must stay reusable
# lost response: payment committed, response "lost" - we keep key/body only
lost_body = {"to_handle": "cy", "amount": 77, "note": "lost-response"}
lost = c1("POST", "/payments", lost_body, token=t1["ada"], key="k-lost")
orig["lost"] = ("POST", "/payments", lost_body, lost.j, lost.s, t1["ada"], "k-lost")
ok("setup stage-1 state: 201s", all(orig[n][4] == 201 for n in ("pay1", "pay2", "pay3", "rq2pay", "split", "settle", "lost")) and orig["fail"][4] == 409, {n: orig[n][4] for n in orig})
snap1 = {h: {"me": c1("GET", "/me", token=t1[h]).j, "act": c1("GET", "/activity?limit=200", token=t1[h]).j, "req": c1("GET", "/requests?limit=200", token=t1[h]).j} for h in t1}
zoe_tok = zoe["token"]
snap1["zoe"] = {"me": c1("GET", "/me", token=zoe_tok).j, "act": c1("GET", "/activity?limit=200", token=zoe_tok).j, "req": c1("GET", "/requests?limit=200", token=zoe_tok).j}
TOT1 = sum(OPEN1.values())
ex = c1("GET", "/_test/export")
ok("J42 stage-1 export is 200 with track/format_version", ex.s == 200 and ex.j["track"] == "pocketful" and ex.j["format_version"] == 1)
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "real-stage1-export.json"), "wb").write(ex.b)
r = c3("POST", "/_test/import", raw=ex.b)
ok("J42 stage-3 imports the REAL stage-1 export: 204", r.s == 204, r)
toks = dict(t1); toks["zoe"] = zoe_tok
bad = []
for h in toks:
    me3 = c3("GET", "/me", token=toks[h]).j if True else None
    m1 = snap1[h]["me"]
    if not (me3 and me3["balance"] == m1["balance"] and me3["total"] == m1["balance"] and me3["available"] == m1["balance"] and me3["held"] == 0 and me3["user_id"] == m1["user_id"] and me3["handle"] == m1["handle"]):
        bad.append((h, me3, m1))
ok("J42 sessions survive: every stage-1 token (incl. a signed-up user's) works on stage 3; /me balances/total/available/held right", not bad, bad[:2])
bad = []
for h in toks:
    a3 = c3("GET", "/activity?limit=200", token=toks[h]).j["payments"]
    a1 = snap1[h]["act"]["payments"]
    if [p["payment_id"] for p in a3] != [p["payment_id"] for p in a1] or not all(subset(x, y) for x, y in zip(a1, a3)):
        bad.append((h, len(a3), len(a1)))
ok("J42 activity feeds identical (ids, order, every stage-1 field incl. created_at preserved, not regenerated)", not bad, bad[:2])
bad = []
for h in toks:
    q3 = c3("GET", "/requests?limit=200", token=toks[h]).j
    if q3["requests"] != snap1[h]["req"]["requests"]:
        bad.append(h)
ok("J42 requests identical (statuses, payment links, timestamps)", not bad, bad)
bad = []
for name, (method, path, body, resp, st, tok, key) in orig.items():
    r = c3(method, path, body, token=tok, key=key)
    if st == 201:
        if not (r.s == 200 and r.j == resp):
            bad.append((name, r.s, r.j, resp))
    else:
        pass
ok("J42 every completed idempotent write replays on stage 3 as 200 with the ORIGINAL response (JSON-equal), no money moved", not bad, bad[:2])
ok("J42 balances unchanged after the replays (no replay against an already-net balance)", all(c3("GET", "/me", token=toks[h]).j["balance"] == snap1[h]["me"]["balance"] for h in toks))
r = c3("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=t1["ada"], key="k-fail")
ok("J42 key that failed 409 before export is reusable after import (first use -> 201)", r.s == 201, r)
c3("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=t1["bob"], key=k())  # even out
# stage-3 views over the imported ledger
payments1 = {}
for h in toks:
    for p in snap1[h]["act"]["payments"]:
        payments1[p["payment_id"]] = p
ok("setup: %d distinct stage-1 payments" % len(payments1), len(payments1) >= 7)
tokof = {"u_" + h: toks[h] for h in toks}
tokof[zoe["user_id"]] = zoe_tok
o = Oracle({"u_" + h: OPEN1[h] for h in OPEN1} | {zoe["user_id"]: 0})
for pid, p in payments1.items():
    rv = c3("GET", "/payments/%s/revisions" % pid, token=tokof[p["from_user_id"]])
    assert rv.s == 200, rv
    o.add(pid, p["from_user_id"], p["to_user_id"], rv.j["revisions"])
    r1 = rv.j["revisions"]
    if len(r1) != 1 or r1[0]["revision"] != 1 or r1[0]["amount"] != p["amount"] or P(r1[0]["effective_at"]) != P(r1[0]["recorded_at"]) != P(p["created_at"]):
        ok("J18/J42 imported payment %s revision 1 == original (amount, effective_at == recorded_at == created_at)" % pid, False, (r1, p))
        break
else:
    ok("J18/J42 every imported payment has revision 1: original amount, effective_at == recorded_at == original created_at (incl. settlement members at committed_at)", True)
stl = orig["settle"][3]
for m in stl["payments"]:
    r1 = c3("GET", "/payments/%s/revisions" % m["payment_id"], token=tokof[m["from_user_id"]]).j["revisions"][0]
    ok("J40/J42 imported settlement member %s: effective_at == recorded_at == committed_at" % m["payment_id"], P(r1["effective_at"]) == P(r1["recorded_at"]) == P(stl["committed_at"]), r1)
ST = {}
for h in toks:
    s_ = c3("GET", "/statement?limit=200", token=toks[h]).j
    ST[h] = s_
    exp_o = OPEN1.get(h, 0)
    ok("J19/J42 %s opening == %d and invariants" % (h, exp_o), s_["opening_balance"] == exp_o and s_["opening_balance"] + sum(e["delta"] for e in s_["entries"]) == s_["closing_balance"], (s_["opening_balance"], exp_o))
    mine = [p for p in payments1.values() if ("u_" + h if h != "zoe" else zoe["user_id"]) in (p["from_user_id"], p["to_user_id"])]
    ok("J42 %s statement has exactly its %d imported payments (+2 new ones for ada/bob)" % (h, len(mine)), len(s_["entries"]) == len(mine) + {"ada": 2, "bob": 2}.get(h, 0), (len(s_["entries"]), len(mine)))
# as_of vs oracle on the imported ledger
bad = []
stamps = sorted({P(p["created_at"]) for p in payments1.values()})
for x in stamps + [s_ - US for s_ in stamps] + [stamps[0] - dt.timedelta(days=1), stamps[-1] + dt.timedelta(days=1)]:
    for h in toks:
        uid = "u_" + h if h != "zoe" else zoe["user_id"]
        r = c3("GET", "/me?as_of=" + q(iso(x)), token=toks[h])
        if r.s != 200 or r.j["balance"] != o.total(uid, x):
            bad.append((h, iso(x), o.total(uid, x), r.j.get("balance")))
ok("J08/J42 /me?as_of over the imported ledger == oracle at every payment instant and just before", not bad, bad[:3])
# pending request still payable after import; corrections on imported payments; replays
pend = c3("GET", "/requests?direction=incoming&status=pending", token=t1["ada"]).j["requests"]
ok("J42 the pending request survived (rq1 pending for ada)", [x["request_id"] for x in pend] == [rq1["request_id"]], pend)
a_before = c3("GET", "/me", token=t1["ada"]).j["balance"]
r = c3("POST", "/requests/%s/pay" % rq1["request_id"], {}, token=t1["ada"], key="k-new-rq1pay")
ok("J42 pending request payable after import: 201, ada -1200", r.s == 201 and c3("GET", "/me", token=t1["ada"]).j["balance"] == a_before - 1200, r)
pid1 = orig["pay1"][3]["payment_id"]
cr = c3("POST", "/payments/%s/corrections" % pid1, {"expected_revision": 1, "amount": 650, "effective_at": orig["pay1"][3]["created_at"], "reason": "post-import"}, token=t1["ada"], key="k-c1")
ok("J42/J22 correcting an IMPORTED payment works (201 revision 2); ada -150, bob +150", cr.s == 201 and cr.j["revision"] == 2 and c3("GET", "/me", token=t1["ada"]).j["balance"] == a_before - 1200 - 150, cr)
r = c3("POST", "/payments", orig["pay1"][2], token=t1["ada"], key="k-pay1")
ok("J42 old payment key replay still returns the stage-1 ORIGINAL body after the correction", r.s == 200 and r.j == orig["pay1"][3], r)
tot3 = sum(c3("GET", "/me", token=toks[h]).j["balance"] for h in toks)
ok("J29/J42 sum of all balances == seeded total after import + new activity", tot3 == TOT1 + 0, (tot3, TOT1))
for m in stl["payments"]:
    cr = c3("POST", "/payments/%s/corrections" % m["payment_id"], {"expected_revision": 1, "amount": m["amount"] + 1, "effective_at": m["created_at"], "reason": "x"}, token=tokof[m["from_user_id"]], key=k())
    ok("J41/J42 correcting imported settlement member %s -> 422 linked_payment_immutable" % m["payment_id"], cr.s == 422 and cr.code == "linked_payment_immutable", cr)
# re-import is replacement, not merge
r = c3("POST", "/_test/import", raw=ex.b)
ok("J42 re-importing the same stage-1 export replaces state (204) and restores it exactly (no duplicate payments)", r.s == 204 and [c3("GET", "/me", token=toks[h]).j["balance"] for h in toks] == [snap1[h]["me"]["balance"] for h in toks] and len(c3("GET", "/activity?limit=200", token=t1["ada"]).j["payments"]) == len(snap1["ada"]["act"]["payments"]))

# ======================================================================= PART B: stage-2 export
c2, c3b = C(S2), C(S3B)
OPEN2 = {"ada": 20000, "bob": 3000, "cy": 5000, "op": 1000}
f2 = fx([user(h, b) for h, b in OPEN2.items()], ops=["u_op"])
f2["authorization_ttl_seconds"] = 3
exp_soon = iso(dt.datetime.now(UTC) + dt.timedelta(hours=3))
exp_old = iso(dt.datetime.now(UTC) - dt.timedelta(hours=3))
f2["authorizations"] = [
    {"id": "a_seed_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1500, "note": "seeded", "visibility": "private", "status": "open", "expires_at": exp_soon},
    {"id": "a_seed_cap", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 400, "note": "", "visibility": "public", "status": "captured", "captured_amount": 400, "expires_at": exp_soon},
    {"id": "a_seed_void", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 100, "note": "", "visibility": "public", "status": "voided", "expires_at": exp_old},
]
t2 = setup_on(c2, f2)
au = lambda tok, to, amt, key, **kw: c2("POST", "/authorizations", dict({"to_handle": to, "amount": amt}, **kw), token=tok, key=key)
orig2 = {}
def rec2(name, r, method, path, body, tok, key):
    orig2[name] = (method, path, body, r.j, r.s, tok, key)
    return r
a1 = rec2("a1", au(t2["ada"], "bob", 3000, "k-a1", note="open", visibility="private"), "POST", "/authorizations", {"to_handle": "bob", "amount": 3000, "note": "open", "visibility": "private"}, t2["ada"], "k-a1").j
a2r = au(t2["ada"], "cy", 2000, "k-a2")
a2 = rec2("a2", a2r, "POST", "/authorizations", {"to_handle": "cy", "amount": 2000}, t2["ada"], "k-a2").j
cp2 = rec2("cap2", c2("POST", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 700, "final": False}, token=t2["cy"], key="k-cap2"), "POST", "/authorizations/%s/capture" % a2["authorization_id"], {"amount": 700, "final": False}, t2["cy"], "k-cap2")
a3 = rec2("a3", au(t2["ada"], "bob", 1000, "k-a3"), "POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, t2["ada"], "k-a3").j
cp3 = rec2("cap3", c2("POST", "/authorizations/%s/capture" % a3["authorization_id"], {"amount": 600}, token=t2["bob"], key="k-cap3"), "POST", "/authorizations/%s/capture" % a3["authorization_id"], {"amount": 600}, t2["bob"], "k-cap3")
a4 = au(t2["ada"], "bob", 800, "k-a4").j
c2("POST", "/authorizations/%s/void" % a4["authorization_id"], {}, token=t2["ada"])
a5 = au(t2["ada"], "bob", 500, "k-a5").j
sleep_until(a5["expires_at"], 0.8)  # expired by clock (also expires a2's remainder and a1 after ttl 3 -> a1 too)
pp = rec2("pay", c2("POST", "/payments", {"to_handle": "cy", "amount": 250, "note": "s2 pay"}, token=t2["bob"], key="k-s2pay"), "POST", "/payments", {"to_handle": "cy", "amount": 250, "note": "s2 pay"}, t2["bob"], "k-s2pay")
# a fresh long hold created right before export so an OPEN hold crosses the import (ttl 3 s is global; use seeded open + a new one)
a6 = au(t2["ada"], "bob", 900, "k-a6").j
snap2 = {h: {"me": c2("GET", "/me", token=t2[h]).j, "az": c2("GET", "/authorizations?limit=200", token=t2[h]).j["authorizations"], "act": c2("GET", "/activity?limit=200", token=t2[h]).j["payments"]} for h in t2}
ex2 = c2("GET", "/_test/export")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "real-stage2-export.json"), "wb").write(ex2.b)
r = c3b("POST", "/_test/import", raw=ex2.b)
ok("J42 stage-3 imports the REAL stage-2 export (holds, captures, expired, voided, seeded): 204", ex2.s == 200 and r.s == 204, r)
bad = []
for h in t2:
    m3 = c3b("GET", "/me", token=t2[h]).j
    m2 = snap2[h]["me"]
    if not (m3["balance"] == m2["balance"] and m3["total"] == m2["total"] and m3["available"] == m2["available"] and m3["held"] == m2["held"]):
        bad.append((h, m3, m2))
ok("J42 /me total/available/held identical to the stage-2 service for every user (holds accounted)", not bad, bad[:2])
bad = []
for h in t2:
    z3 = c3b("GET", "/authorizations?limit=200", token=t2[h]).j["authorizations"]
    z2 = snap2[h]["az"]
    if [a["authorization_id"] for a in z3] != [a["authorization_id"] for a in z2] or not all(subset(x, y) for x, y in zip(z2, z3)):
        bad.append((h, len(z3), len(z2)))
ok("J42 authorizations list: same ids/order, every stage-2 field equal (status, captured_amount, payment_ids, remaining_amount, expires_at, created_at)", not bad, bad[:2])
z3 = {a["authorization_id"]: a for a in c3b("GET", "/authorizations?limit=200", token=t2["ada"]).j["authorizations"]}
z3.update({a["authorization_id"]: a for a in c3b("GET", "/authorizations?limit=200", token=t2["cy"]).j["authorizations"]})
closed_ids = [a["authorization_id"] for a in (a2, a3, a4, a5)]
for aid in closed_ids:
    a = z3[aid]
    ok("J47/J42 imported API-closed authorization %s (%s): closed_at filled in (RFC3339), remaining 0" % (aid, a["status"]), a["status"] != "open" and a["closed_at"] and RFC3339.match(a["closed_at"]) and a["remaining_amount"] == 0, a)
for aid in (a6["authorization_id"], "a_seed_open"):
    a = z3[aid]
    ok("J47/J42 imported open authorization %s: closed_at null (or already expired w/ closed_at)" % aid, (a["status"] == "open" and a["closed_at"] is None) or (a["status"] == "expired" and a["closed_at"]), a)
replay_bad = []
for name, (method, path, body, resp, st, tok, key) in orig2.items():
    r = c3b(method, path, body, token=tok, key=key)
    if st == 201 and not (r.s == 200 and r.j == resp):
        replay_bad.append((name, r.s, r.j, resp))
ok("J42 every stage-2 write (authorize, partial capture, final capture, payment) replays as 200 with the original response", not replay_bad, replay_bad[:2])
cp2p = orig2["cap2"][3]
cr = c3b("POST", "/payments/%s/corrections" % cp2p["payment_id"], {"expected_revision": 1, "amount": 600, "effective_at": cp2p["created_at"], "reason": "x"}, token=t2["ada"], key=k())
ok("J43/J42 correcting an IMPORTED capture payment -> 422 linked_payment_immutable", cr.s == 422 and cr.code == "linked_payment_immutable", cr)
rv = c3b("GET", "/payments/%s/revisions" % cp2p["payment_id"], token=t2["cy"])
ok("J18/J42 imported capture revision 1: original amount, effective_at == recorded_at == created_at", rv.s == 200 and len(rv.j["revisions"]) == 1 and P(rv.j["revisions"][0]["effective_at"]) == P(rv.j["revisions"][0]["recorded_at"]) == P(cp2p["created_at"]), rv)
sa = c3b("GET", "/statement?limit=200", token=t2["ada"]).j
exp_open = OPEN2["ada"]
ok("J19/J42 ada statement: opening == %d (pre-history), captures appear once each with authorization_id, no authorization entries, opening+deltas==closing==total" % exp_open,
   sa["opening_balance"] == exp_open and [e["payment"]["authorization_id"] for e in sa["entries"] if e["payment"]["authorization_id"]] == [a2["authorization_id"], a3["authorization_id"]] and sa["opening_balance"] + sum(e["delta"] for e in sa["entries"]) == sa["closing_balance"] == c3b("GET", "/me", token=t2["ada"]).j["total"], (sa["opening_balance"], [(e["payment"]["payment_id"], e["payment"]["authorization_id"], e["delta"]) for e in sa["entries"]]))
# imported holds as history
ca1 = P(a1["created_at"])
m = c3b("GET", "/me?as_of=" + q(iso(ca1)), token=t2["ada"]).j
ok("J45/J42 imported ledger replays holds: ada at a1.created_at has a1 held (>= 3000) and available = total - held, total/available consistent", m["held"] >= 3000 and m["available"] == m["total"] - m["held"] and m["balance"] == m["total"], m)
m0 = c3b("GET", "/me?as_of=" + q(iso(ca1 - dt.timedelta(days=1))), token=t2["ada"]).j
ok("J42 ada one day before everything: opening total, no holds (except seeded-at-reset)", m0["total"] == OPEN2["ada"] and m0["held"] == 0, m0)
tot3 = sum(c3b("GET", "/me", token=t2[h]).j["total"] for h in t2)
ok("J29/J42 sum of totals == seeded total (%d) after importing stage-2 state" % sum(OPEN2.values()), tot3 == sum(OPEN2.values()), tot3)
# continuing lifecycle after import
last = z3[a6["authorization_id"]]
if last["status"] == "open":
    r = c3b("POST", "/authorizations/%s/capture" % last["authorization_id"], {"amount": 400}, token=t2["bob"], key=k())
    ok("J42 an imported OPEN hold can still be captured after import (final capture of 400 releases the rest)", r.s == 201 and r.j["authorization_id"] == last["authorization_id"], r)
# ======================================================================= PART C: stage-3 round trip
tot_before = {h: c3b("GET", "/me", token=t2[h]).j for h in t2}
cr = c3b("POST", "/payments/%s/corrections" % pp.j["payment_id"], {"expected_revision": 1, "amount": 200, "effective_at": pp.j["created_at"], "reason": "rt"}, token=t2["bob"], key="k-rt")
ok("setup: correction on stage-3 B", cr.s == 201, cr)
snapB = {h: {"me": c3b("GET", "/me", token=t2[h]).j, "st": c3b("GET", "/statement?limit=200", token=t2[h]).j, "az": c3b("GET", "/authorizations?limit=200", token=t2[h]).j} for h in t2}
revB = c3b("GET", "/payments/%s/revisions" % pp.j["payment_id"], token=t2["bob"]).j
exB = c3b("GET", "/_test/export")
r = C(S3C)("POST", "/_test/import", raw=exB.b)
c3c = C(S3C)
ok("J51 stage-3 export imports into a fresh stage-3 service: 204", exB.s == 200 and r.s == 204, r)
bad = []
for h in t2:
    mm = c3c("GET", "/me", token=t2[h]).j
    ss = c3c("GET", "/statement?limit=200", token=t2[h]).j
    aa = c3c("GET", "/authorizations?limit=200", token=t2[h]).j
    if mm != snapB[h]["me"] or aa != snapB[h]["az"] or ss["entries"] != snapB[h]["st"]["entries"] or (ss["opening_balance"], ss["closing_balance"]) != (snapB[h]["st"]["opening_balance"], snapB[h]["st"]["closing_balance"]):
        bad.append(h)
ok("J51 round trip: /me, authorizations (incl. closed_at), statements (revisions, opening/closing) identical on the new instance", not bad, bad)
ok("J51 revisions history preserved (rev1 + correction with recorded_at)", c3c("GET", "/payments/%s/revisions" % pp.j["payment_id"], token=t2["bob"]).j == revB)
r = c3c("POST", "/payments/%s/corrections" % pp.j["payment_id"], {"expected_revision": 1, "amount": 200, "effective_at": pp.j["created_at"], "reason": "rt"}, token=t2["bob"], key="k-rt")
ok("J51 correction idempotency survives export/import: replay -> 200 original revision", r.s == 200 and r.j == cr.j, r)
r = c3c("POST", "/payments/%s/corrections" % pp.j["payment_id"], {"expected_revision": 1, "amount": 201, "effective_at": pp.j["created_at"], "reason": "rt"}, token=t2["bob"], key="k-rt")
ok("J51 same key different body after import -> 409 idempotency_key_reuse", r.s == 409 and r.code == "idempotency_key_reuse", r)
r = c3c("POST", "/payments/%s/corrections" % pp.j["payment_id"], {"expected_revision": 1, "amount": 210, "effective_at": pp.j["created_at"], "reason": "stale"}, token=t2["bob"], key=k())
ok("J51 stale revision still detected after import (expected 1 vs 2) -> 409 stale_revision", r.s == 409 and r.code == "stale_revision", r)
ok("J51 snapshot tokens: a pre-import-export snapshot is not required to survive (no assertion), but new ones work", c3c("GET", "/statement?limit=2", token=t2["ada"]).j.get("snapshot"))
done("t3_import")
