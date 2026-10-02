"""trace: cross-attack on forge's F2 (11e76f9, in HEAD ac96360). stdlib only, persistent connections, servers started and killed by PID here.
env F2BIN = directory holding s3-ac96360.exe, s3-legacy-3c7c411.exe, s1.exe, s2.exe.  usage: python f2_attack.py <attack> [...]
attacks: ttl poll race storm storm1 imp1 imp2 legacy"""
import collections, datetime as dt, http.client, json, os, queue, random, re, subprocess, sys, threading, time, urllib.parse, uuid

UTC = dt.timezone.utc
EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
BIN = os.environ["F2BIN"]
LOG = os.environ.get("F2LOG", BIN)
S3EXE = os.environ.get("F2S3", "s3-ac96360.exe")  # HEAD binary under attack (R-L1 runs: s3-5e6f83f.exe)
NPASS, FAILS, NREQ = [0], [], [0]
_lk = threading.Lock()


def us(s):
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00")) - EPOCH
    return d.days * 86400_000000 + d.seconds * 1_000000 + d.microseconds


def iso(u):
    return (EPOCH + dt.timedelta(microseconds=u)).isoformat(timespec="microseconds")


def now_us():
    return time.time_ns() // 1000


def wait_until(u):
    while now_us() < u:
        time.sleep(0.004)


def k():
    return uuid.uuid4().hex


def ok(name, cond, detail=""):
    with _lk:
        if cond:
            NPASS[0] += 1
            print("PASS", name, flush=True)
        else:
            FAILS.append(name)
            print("FAIL", name, "::", str(detail)[:700], flush=True)


def silent_ok(name, cond, detail=""):
    with _lk:
        if cond:
            NPASS[0] += 1
        else:
            FAILS.append(name)
            print("FAIL", name, "::", str(detail)[:700], flush=True)


class Resp:
    def __init__(self, s, b, t0, t1):
        self.s, self.b, self.t0, self.t1 = s, b, t0, t1
        try:
            self.j = json.loads(b) if b else None
        except Exception:
            self.j = None

    @property
    def code(self):
        return self.j["error"]["code"] if isinstance(self.j, dict) and isinstance(self.j.get("error"), dict) else None


class Cli:
    def __init__(self, hp):
        self.hp, self.tl = hp, threading.local()

    def req(self, method, path, body=None, token=None, key=None, raw=None):
        h = {}
        if token:
            h["Authorization"] = "Bearer " + token
        if key:
            h["Idempotency-Key"] = key
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h["Content-Type"] = "application/json"
        for attempt in (1, 2, 3):
            c = getattr(self.tl, "c", None)
            if c is None:
                host, port = self.hp.rsplit(":", 1)
                c = self.tl.c = http.client.HTTPConnection(host, int(port), timeout=60)
            try:
                t0 = time.time_ns()
                c.request(method, path, body=data, headers=h)
                r = c.getresponse()
                b = r.read()
                t1 = time.time_ns()
                break
            except (OSError, http.client.HTTPException):
                c.close()
                self.tl.c = None
                if attempt == 3:
                    raise
        with _lk:
            NREQ[0] += 1
        return Resp(r.status, b, t0 // 1000, t1 // 1000)


class Srv:
    def __init__(self, exe, port):
        self.port = port
        self.p = subprocess.Popen([os.path.join(BIN, exe)], env=dict(os.environ, PORT=str(port)),
                                  stdout=open(os.path.join(LOG, "srv-%d.log" % port), "wb"), stderr=subprocess.STDOUT)
        self.c = Cli("127.0.0.1:%d" % port)
        for _ in range(200):
            try:
                if self.c.req("GET", "/health").s == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def stop(self):
        self.p.kill()
        self.p.wait()


def mkusers(bal):
    return [{"id": "u_" + h, "email": h + "@example.com", "password": "correct horse", "display_name": h.capitalize(),
             "handle": h, "balance": b} for h, b in bal.items()]


def login(c, h):
    r = c.req("POST", "/auth/login", {"email": h + "@example.com", "password": "correct horse"})
    assert r.s == 200, r.b
    return r.j["token"]


def setup(c, bal, ttl=None, extra=None):
    f = {"currency": "EUR", "minor_units": 2, "users": mkusers(bal)}
    if ttl:
        f["authorization_ttl_seconds"] = ttl
    if extra:
        f.update(extra)
    r = c.req("POST", "/_test/reset", f)
    assert r.s == 204, (r.s, r.b)
    return {h: login(c, h) for h in bal}


def authorize(c, tok, to, amount):
    return c.req("POST", "/authorizations", {"to_handle": to, "amount": amount}, tok, key=k())


def capture(c, tok, aid, amount=None, final=None):
    b = {}
    if amount is not None:
        b["amount"] = amount
    if final is not None:
        b["final"] = final
    return c.req("POST", "/authorizations/%s/capture" % aid, b, tok, key=k())


def void(c, tok, aid):
    return c.req("POST", "/authorizations/%s/void" % aid, {}, tok)


def pay(c, tok, to, amount):
    return c.req("POST", "/payments", {"to_handle": to, "amount": amount}, tok, key=k())


def view(c, tok, T=None, K=None):
    q = []
    if T is not None:
        q.append("as_of=" + urllib.parse.quote(iso(T), safe=""))
    if K is not None:
        q.append("known_at=" + urllib.parse.quote(iso(K), safe=""))
    r = c.req("GET", "/me" + ("?" + "&".join(q) if q else ""), token=tok)
    assert r.s == 200, (r.s, r.b)
    j = r.j
    return (j["total"], j["held"], j["available"], j["balance"])


def inv_ok(v):
    total, held, avail, bal = v
    return bal == total and avail == total - held and held >= 0 and avail >= 0 and total >= 0 and held <= total


def alist(c, tok, **q):
    r = c.req("GET", "/authorizations" + ("?" + urllib.parse.urlencode(q) if q else ""), token=tok)
    assert r.s == 200, (r.s, r.b)
    return {a["authorization_id"]: a for a in r.j["authorizations"]}


MICRO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$")


# ------------------------------------------------------------------ oracle (spec rules, from an export)
class Oracle:
    def __init__(self, ex):
        st = ex["state"]
        self.open = {u["id"]: u["opening_balance"] for u in st["users"]}
        self.pays = collections.defaultdict(list)  # uid -> [(created_us, signed amount)]
        self.pay = {}
        for p in st["payments"]:
            c = us(p["created_at"])
            self.pay[p["payment_id"]] = (c, p["amount"])
            self.pays[p["from_user_id"]].append((c, -p["amount"]))
            self.pays[p["to_user_id"]].append((c, p["amount"]))
        self.auths = collections.defaultdict(list)
        self.instants = set()
        for a in st["authorizations"]:
            o = dict(amt=a["amount"], status=a["status"], created=us(a["created_at"]), expires=us(a["expires_at"]),
                     closed=us(a["closed_at"]) if a.get("closed_at") else None, cap=a["captured_amount"], pids=a["payment_ids"])
            self.auths[a["from_user_id"]].append(o)
            self.instants |= {o["created"], o["expires"]} | ({o["closed"]} if o["closed"] else set())
        for c, _a in self.pay.values():
            self.instants.add(c)

    def view(self, uid, T):
        total = self.open[uid] + sum(a for c, a in self.pays[uid] if c <= T)
        held = 0
        for o in self.auths[uid]:
            if T < o["created"] or T >= o["expires"] or o["status"] == "expired":
                continue
            if o["status"] != "open" and o["closed"] is not None and T >= o["closed"]:
                continue
            cap = o["cap"] - sum(self.pay[p][1] for p in o["pids"] if p in self.pay and self.pay[p][0] > T)
            held += max(o["amt"] - max(cap, 0), 0)
        return (total, held, total - held, total)


def compare_views(c, tok, uids, orc, label, nthreads=3, instants=None):
    """every (user, T-1/T/T+1) view from the server equals the oracle; returns (n views, mismatches list)"""
    ts = sorted(instants if instants is not None else orc.instants)
    work = [(u, T + d) for T in ts for d in (-1, 0, 1) for u in uids]
    bad, n = [], [0]
    it = iter(work)
    lk = threading.Lock()

    def run():
        while True:
            with lk:
                x = next(it, None)
            if x is None:
                return
            u, T = x
            v = view(c, tok[u], T)
            n[0] += 1
            exp = orc.view("u_" + u, T)
            if v != exp or not inv_ok(v):
                bad.append((u, iso(T), v, exp))

    th = [threading.Thread(target=run) for _ in range(nthreads)]
    [t.start() for t in th]
    [t.join() for t in th]
    return n[0], bad


# ------------------------------------------------------------------ attack: real-clock ttl 1 and 2
def atk_ttl(S, ttl):
    c = S.c
    for variant in ("me-first", "list-first", "capture-first", "void-first"):
        tag = "TTL%d/%s" % (ttl, variant)
        t = setup(c, {"ada": 10000, "bob": 2500, "cy": 0}, ttl)
        a = authorize(c, t["ada"], "bob", 3000).j
        aid, C, E = a["authorization_id"], us(a["created_at"]), us(a["expires_at"])
        ok(tag + " created_at/expires_at are microsecond instants (6 fraction digits)", bool(MICRO.match(a["created_at"]) and MICRO.match(a["expires_at"])), a)
        ok(tag + " expires_at - created_at == %d s exactly (microsecond arithmetic)" % ttl, E - C == ttl * 1_000_000, (a["created_at"], a["expires_at"], E - C))
        pre = {d: view(c, t["ada"], E + d) for d in (-1, 0, 1)}
        ok(tag + " as_of expires_at-1us still held (10000,3000,7000)", pre[-1] == (10000, 3000, 7000, 10000), pre[-1])
        ok(tag + " as_of expires_at released (10000,0,10000)", pre[0] == (10000, 0, 10000, 10000), pre[0])
        ok(tag + " as_of expires_at+1us released", pre[1] == (10000, 0, 10000, 10000), pre[1])
        cre = {d: view(c, t["ada"], C + d) for d in (-1, 0, 1)}
        ok(tag + " as_of created_at-1us no hold; at created_at and +1us held", cre[-1] == (10000, 0, 10000, 10000) and cre[0] == (10000, 3000, 7000, 10000) and cre[1] == cre[0], cre)
        ok(tag + " known_at before creation: hold unknown (as_of mid-life)", view(c, t["ada"], E - 1, C - 1)[1] == 0)
        ok(tag + " deadline is known with creation: as_of E+1 known_at E-1 -> released", view(c, t["ada"], E + 1, E - 1) == (10000, 0, 10000, 10000))
        wait_until(E + 30_000)  # no request anywhere near the deadline
        if variant == "me-first":
            m = view(c, t["ada"])
            ok(tag + " first read after the deadline is /me: held 0 available == total == 10000", m == (10000, 0, 10000, 10000), m)
            x = alist(c, t["ada"])[aid]
            ok(tag + " then GET /authorizations: expired, remaining 0, closed_at == expires_at", (x["status"], x["remaining_amount"], x["closed_at"]) == ("expired", 0, a["expires_at"]), x)
        elif variant == "list-first":
            x = alist(c, t["bob"])[aid]
            ok(tag + " first read after the deadline is GET /authorizations (payee): expired, closed_at == expires_at", (x["status"], x["remaining_amount"], x["closed_at"]) == ("expired", 0, a["expires_at"]), x)
            m = view(c, t["ada"])
            ok(tag + " then /me: released", m == (10000, 0, 10000, 10000), m)
        elif variant == "capture-first":
            r = capture(c, t["bob"], aid, 1000, False)
            ok(tag + " first request after the deadline is a capture: 409 authorization_expired", (r.s, r.code) == (409, "authorization_expired"), (r.s, r.b))
            ok(tag + " no money moved by the refused capture", (view(c, t["ada"]), view(c, t["bob"])) == ((10000, 0, 10000, 10000), (2500, 0, 2500, 2500)))
        else:
            r = void(c, t["ada"], aid)
            ok(tag + " first request after the deadline is a void: 409", r.s == 409, (r.s, r.b))
            x = alist(c, t["ada"])[aid]
            ok(tag + " the refused void leaves it expired with closed_at == expires_at", (x["status"], x["closed_at"]) == ("expired", a["expires_at"]), x)
        post = {d: view(c, t["ada"], E + d) for d in (-1, 0, 1)}
        ok(tag + " history is stable: the three as_of views are unchanged after the clock passed the deadline", post == pre, (pre, post))
        x = alist(c, t["ada"])[aid]
        ok(tag + " agreement: closed_at as_of -> released, closed_at-1us -> held", (view(c, t["ada"], us(x["closed_at"])), view(c, t["ada"], us(x["closed_at"]) - 1)) == ((10000, 0, 10000, 10000), (10000, 3000, 7000, 10000)), x)


# ------------------------------------------------------------------ attack: read the deadline while it passes
def atk_poll(S, ttl):
    c = S.c
    t = setup(c, {"ada": 10000, "bob": 2500}, ttl)
    a = authorize(c, t["ada"], "bob", 3000).j
    aid, E = a["authorization_id"], us(a["expires_at"])
    wait_until(E - 120_000)
    seq, i = [], 0
    while now_us() < E + 120_000:
        if i % 3 == 0:
            r = c.req("GET", "/me", token=t["ada"])
            j = r.j
            silent_ok("POLL%d /me invariants" % ttl, j["available"] == j["total"] - j["held"] and j["available"] >= 0, j)
            st = "held" if j["held"] == 3000 else ("released" if j["held"] == 0 else "BAD:%s" % j["held"])
        elif i % 3 == 1:
            r = c.req("GET", "/authorizations", token=t["ada"])
            x = [y for y in r.j["authorizations"] if y["authorization_id"] == aid][0]
            st = "held" if (x["status"], x["remaining_amount"], x["closed_at"]) == ("open", 3000, None) else (
                "released" if (x["status"], x["remaining_amount"], x["closed_at"]) == ("expired", 0, a["expires_at"]) else "BAD:%s" % x)
        else:
            r = c.req("GET", "/authorizations?status=open", token=t["bob"])
            st = "held" if aid in [y["authorization_id"] for y in r.j["authorizations"]] else "released"
        seq.append((r.t0, r.t1, i % 3, st))
        i += 1
    bad = [x for x in seq if x[3].startswith("BAD")]
    ok("POLL%d no torn state across %d reads straddling the deadline" % (ttl, len(seq)), not bad, bad[:3])
    first_rel = next((n for n, x in enumerate(seq) if x[3] == "released"), None)
    ok("POLL%d the deadline was observed" % ttl, first_rel is not None and first_rel > 0)
    ok("POLL%d no regression: after the first released read no read shows held (me, list, status filter)" % ttl,
       first_rel is not None and all(x[3] == "released" for x in seq[first_rel:]), [x for x in seq[first_rel:] if x[3] != "released"][:3])
    ok("POLL%d every read that finished 20 ms before expires_at shows held" % ttl, all(x[3] == "held" for x in seq if x[1] < E - 20_000))
    ok("POLL%d every read that began 20 ms after expires_at shows released" % ttl, all(x[3] == "released" for x in seq if x[0] > E + 20_000))
    print("   POLL%d first released read began %+d us / finished %+d us relative to expires_at; %d reads" % (ttl, seq[first_rel][0] - E, seq[first_rel][1] - E, len(seq)))


# ------------------------------------------------------------------ attack: captures racing the deadline
def atk_race(S, ttl):
    c = S.c
    t = setup(c, {"ada": 10000, "bob": 2500}, ttl)
    a = authorize(c, t["ada"], "bob", 3000).j
    aid, E = a["authorization_id"], us(a["expires_at"])
    res = []

    def worker():
        while now_us() < E + 120_000:
            r = capture(c, t["bob"], aid, 1, False)
            res.append((r.t0, r.t1, r.s, r.code, us(r.j["created_at"]) if r.s == 201 else None))

    wait_until(E - 150_000)
    th = [threading.Thread(target=worker) for _ in range(4)]
    [x.start() for x in th]
    [x.join() for x in th]
    wins = [x for x in res if x[2] == 201]
    n = len(wins)
    ok("RACE%d captures attempted around the deadline: %d (201: %d)" % (ttl, len(res), n), n > 20 and len(res) > n, (len(res), n))
    ok("RACE%d every 201 capture has created_at strictly before expires_at" % ttl, all(x[4] < E for x in wins), [iso(x[4]) for x in wins if x[4] >= E][:3])
    ok("RACE%d every response is 201 or 409 authorization_expired" % ttl, all((x[2], x[3]) in ((201, None), (409, "authorization_expired")) for x in res), collections.Counter((x[2], x[3]) for x in res))
    ok("RACE%d no 201 began after expires_at+20ms and no 409 finished before expires_at-20ms" % ttl,
       not [x for x in res if (x[2] == 201 and x[0] > E + 20_000) or (x[2] == 409 and x[1] < E - 20_000)])
    ok("RACE%d created_at of the 201s are strictly increasing in completion order" % ttl, len({x[4] for x in wins}) == n)
    wait_until(E + 40_000)
    x = alist(c, t["ada"])[aid]
    ok("RACE%d after the deadline: expired, captured_amount == %d, remaining 0, closed_at == expires_at" % (ttl, n),
       (x["status"], x["captured_amount"], x["remaining_amount"], x["closed_at"]) == ("expired", n, 0, a["expires_at"]), x)
    ok("RACE%d money: ada total 10000-%d, held 0; bob total 2500+%d" % (ttl, n, n), (view(c, t["ada"]), view(c, t["bob"])) == ((10000 - n, 0, 10000 - n, 10000 - n), (2500 + n, 0, 2500 + n, 2500 + n)))
    caps = sorted(x[4] for x in wins)
    bad = []
    for T in sorted({y + d for y in caps[:: max(1, n // 60)] for d in (-1, 0, 1)} | {E - 1, E, E + 1}):
        m = sum(1 for y in caps if y <= T)
        exp = (10000 - m, 0, 10000 - m, 10000 - m) if T >= E else (10000 - m, 3000 - m, 7000, 10000 - m)
        if T < caps[0]:
            exp = (10000, 3000, 7000, 10000) if T >= us(a["created_at"]) else (10000, 0, 10000, 10000)
        v = view(c, t["ada"], T)
        if v != exp:
            bad.append((iso(T), v, exp))
    ok("RACE%d ada's as_of views at sampled capture instants +-1us, E-1, E, E+1 follow the capture count (available constant 7000 before E)" % ttl, not bad, bad[:3])


# ------------------------------------------------------------------ attack: 6 concurrent writers, observer at every event instant
def atk_storm(S, ttl, rounds=100, writers=6, label=None):
    c = S.c
    label = label or "STORM(ttl=%s)" % ttl
    bal = {"ada": 10000, "bob": 8000, "cy": 6000, "dee": 4000}
    names, SEED = list(bal), sum(bal.values())
    t = setup(c, bal, ttl)
    inst, viol, stats = queue.Queue(), [], collections.Counter()
    done = threading.Event()

    def chk(where, v):
        stats["views"] += 1
        if not inv_ok(v):
            viol.append((where, v))

    def writer(wi):
        rng = random.Random(7000 + wi)
        for _ in range(rounds):
            a, b = rng.sample(names, 2)
            r = pay(c, t[a], b, rng.randint(1, 1500))
            stats["pay", r.s] += 1
            if r.s == 201:
                inst.put((us(r.j["created_at"]), a, b))
            amt = rng.randint(1, 2500)
            r = authorize(c, t[a], b, amt)
            stats["auth", r.s] += 1
            if r.s == 201:
                aid = r.j["authorization_id"]
                inst.put((us(r.j["created_at"]), a, b))
                x = rng.random()
                if x < 0.35:
                    r = capture(c, t[b], aid, rng.randint(1, amt), False)
                    stats["cap", r.s] += 1
                    if r.s == 201:
                        inst.put((us(r.j["created_at"]), a, b))
                    if rng.random() < 0.5:
                        r = capture(c, t[b], aid, None, True)
                        stats["capfinal", r.s] += 1
                        if r.s == 201:
                            inst.put((us(r.j["created_at"]), a, b))
                elif x < 0.6:
                    r = void(c, t[a], aid)
                    stats["void", r.s] += 1
                    if r.s == 200 and r.j["closed_at"]:
                        inst.put((us(r.j["closed_at"]), a, b))
                elif x < 0.8:
                    r = capture(c, t[b], aid, None, True)
                    stats["capfinal", r.s] += 1
                    if r.s == 201:
                        inst.put((us(r.j["created_at"]), a, b))
            for u in (a, b):
                j = c.req("GET", "/me", token=t[u]).j
                chk("current /me " + u, (j["total"], j["held"], j["available"], j["balance"]))

    def observer():
        while True:
            try:
                T, a, b = inst.get(timeout=0.2)
            except queue.Empty:
                if done.is_set():
                    return
                continue
            for d in (-1, 0, 1):
                for u in (a, b):
                    chk("as_of %s %+d %s" % (iso(T), d, u), view(c, t[u], T + d))
            for d in (-1, 0):  # past instants: no write can still change them, so the books must balance
                tot = sum(view(c, t[u], T + d)[0] for u in names)
                stats["conservation"] += 1
                if tot != SEED:
                    viol.append(("conservation as_of %s %+d" % (iso(T), d), tot))

    wt = [threading.Thread(target=writer, args=(i,)) for i in range(writers)]
    ot = [threading.Thread(target=observer) for _ in range(2)]
    t0 = time.time()
    [x.start() for x in wt + ot]
    [x.join() for x in wt]
    done.set()
    [x.join() for x in ot]
    print("   %s writers+observers finished in %.1fs: %s" % (label, time.time() - t0, dict(stats)))
    ok("%s: %d writers x %d rounds, %d concurrent as_of views and %d conservation sums: no view with available<0, held>total, total<0, balance!=total or available!=total-held; books always balance" % (label, writers, rounds, stats["views"], stats["conservation"]), not viol and stats["views"] > 1000, viol[:4])
    ok("%s: no request failed with 5xx" % label, not [k_ for k_ in stats if isinstance(k_, tuple) and k_[1] >= 500], dict(stats))
    if ttl and ttl <= 2:
        time.sleep(ttl + 0.3)
    ex = c.req("GET", "/_test/export").j
    orc = Oracle(ex)
    ok("%s: Σ balances == seeded total after the storm" % label, sum(u["balance"] for u in ex["state"]["users"]) == SEED)
    n, bad = compare_views(c, t, names, orc, label)
    ok("%s: post-run oracle: %d views (every payment/authorization/closed/expires instant -1us,0,+1us x 4 users) equal the spec rules computed from the export" % (label, n), not bad and n > 3000, bad[:4])
    # round trip
    ex1 = json.dumps(ex, sort_keys=True)
    r = c.req("POST", "/_test/import", raw=json.dumps(ex).encode())
    ok("%s: export -> import 204" % label, r.s == 204, (r.s, r.b))
    ex2 = json.dumps(c.req("GET", "/_test/export").j, sort_keys=True)
    ok("%s: export -> import -> export byte-identical" % label, ex1 == ex2, "len %d vs %d" % (len(ex1), len(ex2)))
    t = {h: login(c, h) for h in names}
    pick = sorted(orc.instants)[:: max(1, len(orc.instants) // 400)]
    n, bad = compare_views(c, t, names, orc, label, instants=pick)
    ok("%s: after the round trip %d sampled views still equal the oracle" % (label, n), not bad, bad[:3])
    a = authorize(c, t["ada"], "bob", 1)
    if a.s == 201:
        ok("%s: authorize after the round trip: created_at later than every recorded instant, exact ttl" % label, us(a.j["created_at"]) > max(orc.instants - {x for x in orc.instants if x > now_us() + 60_000_000}) and us(a.j["expires_at"]) - us(a.j["created_at"]) == (ttl or 600) * 1_000_000, a.j)


# ------------------------------------------------------------------ attack: upgrades
def check_after_import(c3, t, label, names, SEED, ttl_expected):
    """authorize/capture/void on the imported state, exactness of the new instants, views, clock"""
    ex = c3.req("GET", "/_test/export").j
    orc = Oracle(ex)
    ok("%s: imported state: Σ balances == %d" % (label, SEED), sum(u["balance"] for u in ex["state"]["users"]) == SEED)
    n, bad = compare_views(c3, t, names, orc, label)
    ok("%s: imported state: %d views at every instant of the import -1us/0/+1us satisfy the invariants and equal the oracle" % (label, n), not bad, bad[:4])
    t_before = now_us()
    a = authorize(c3, t["ada"], "bob", 700)
    ok("%s: authorize after import 201" % label, a.s == 201, (a.s, a.b))
    a = a.j
    C, E = us(a["created_at"]), us(a["expires_at"])
    ok("%s: new authorization created_at tracks the real clock (|created_at - now| < 2 s), microsecond format" % label, abs(C - t_before) < 2_000_000 and bool(MICRO.match(a["created_at"])), (a["created_at"], iso(t_before)))
    ok("%s: expires_at - created_at == %d s exactly" % (label, ttl_expected), E - C == ttl_expected * 1_000_000, (a["created_at"], a["expires_at"]))
    v = {d: view(c3, t["ada"], C + d) for d in (-1, 0, 1)}
    ok("%s: held appears exactly at created_at (-1us none, 0 and +1us 700)" % label, v[0][1] - v[-1][1] == 700 and v[1] == v[0] and all(inv_ok(x) for x in v.values()), v)
    cp = capture(c3, t["bob"], a["authorization_id"], 200, False)
    ok("%s: nonfinal capture 201" % label, cp.s == 201, (cp.s, cp.b))
    c1 = us(cp.j["created_at"])
    ok("%s: capture payment later than the hold, microsecond instant" % label, c1 > C and bool(MICRO.match(cp.j["created_at"])), cp.j)
    w = {d: view(c3, t["ada"], c1 + d) for d in (-1, 0, 1)}
    ok("%s: at the capture instant total drops 200 and held drops 200 together (available unchanged, never negative)" % label,
       w[0][0] == w[-1][0] - 200 and w[0][1] == w[-1][1] - 200 and w[0][2] == w[-1][2] and all(inv_ok(x) for x in w.values()), w)
    fc = capture(c3, t["bob"], a["authorization_id"], None, True)
    ok("%s: final capture 201 closes it" % label, fc.s == 201, (fc.s, fc.b))
    x = alist(c3, t["ada"])[a["authorization_id"]]
    ok("%s: closed_at == final capture created_at" % label, x["status"] == "captured" and x["closed_at"] == fc.j["created_at"], x)
    b = authorize(c3, t["ada"], "cy", 300).j
    vv = void(c3, t["ada"], b["authorization_id"])
    ok("%s: void closes at its own instant" % label, vv.s == 200 and us(vv.j["closed_at"]) > us(b["created_at"]), (vv.s, vv.b))
    ex2 = c3.req("GET", "/_test/export").j
    orc2 = Oracle(ex2)
    tk = t
    n, bad = compare_views(c3, tk, names, orc2, label, instants={us(a["created_at"]), c1, us(fc.j["created_at"]), us(b["created_at"]), us(vv.j["closed_at"])})
    ok("%s: views around every new event equal the oracle (%d views)" % (label, n), not bad, bad[:3])
    return ex


def atk_imp1(S3, S1):
    """stage-1 export (real stage-1 binary, accepted) -> stage 3"""
    c1, c3 = S1.c, S3.c
    bal = {"ada": 10000, "bob": 2500, "cy": 3000, "dee": 0}
    f = {"currency": "EUR", "minor_units": 2, "users": mkusers(bal),
         "payments": [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}]}
    assert c1.req("POST", "/_test/reset", f).s == 204
    t = {h: login(c1, h) for h in bal}
    for i in range(6):
        assert pay(c1, t["ada"], "bob", 100 + i).s == 201
        assert pay(c1, t["cy"], "ada", 50 + i).s == 201
    ex = c1.req("GET", "/_test/export")
    r = c3.req("POST", "/_test/import", raw=ex.b)
    ok("IMP1 stage-1 export imports into stage 3: 204", r.s == 204, (r.s, r.b))
    SEED = 15500
    check_after_import(c3, t, "IMP1(stage-1)", list(bal), SEED, 600)


def atk_imp2(S3, S2):
    """stage-2 export (real stage-2 binary, accepted) with open, expired, captured and voided holds -> stage 3"""
    c2, c3 = S2.c, S3.c
    bal = {"ada": 10000, "bob": 2500, "cy": 3000, "dee": 0}
    t = setup(c2, bal, ttl=3)
    ae = authorize(c2, t["ada"], "bob", 1000).j  # expires before the export
    time.sleep(3.3)
    ao = authorize(c2, t["ada"], "bob", 2500).j  # stays open past the import
    ac = authorize(c2, t["ada"], "cy", 800).j
    assert capture(c2, t["cy"], ac["authorization_id"], 300, False).s == 201
    af = authorize(c2, t["ada"], "cy", 600).j
    assert capture(c2, t["cy"], af["authorization_id"], None, True).s == 201
    av = authorize(c2, t["ada"], "bob", 400).j
    assert void(c2, t["ada"], av["authorization_id"]).s == 200
    assert pay(c2, t["bob"], "ada", 77).s == 201
    ex = c2.req("GET", "/_test/export")
    exj = ex.j
    print("   IMP2 stage-2 export authorizations (created_at / expires_at / status):", [(a["created_at"], a["expires_at"], a["status"]) for a in exj["state"]["authorizations"]])
    r = c3.req("POST", "/_test/import", raw=ex.b)
    ok("IMP2 stage-2 export imports into stage 3: 204", r.s == 204, (r.s, r.b))
    lst = alist(c3, t["ada"])
    ok("IMP2 imported holds: statuses open (never touched), open (partly captured), expired (deadline passed before export), captured, voided", sorted(x["status"] for x in lst.values()) == sorted(["open", "open", "expired", "captured", "voided"]), [(x["status"], x["closed_at"]) for x in lst.values()])
    ok("IMP2 closed_at: null for both open holds, set for every closed one, expires_at for the expired one",
       lst[ao["authorization_id"]]["closed_at"] is None and lst[ac["authorization_id"]]["closed_at"] is None and all(x["closed_at"] for k_, x in lst.items() if k_ not in (ao["authorization_id"], ac["authorization_id"])) and lst[ae["authorization_id"]]["closed_at"] == ae["expires_at"], [(x["status"], x["closed_at"]) for x in lst.values()])
    SEED = 15500
    ex3 = check_after_import(c3, t, "IMP2(stage-2)", list(bal), SEED, 3)
    # the open imported hold must expire on the real clock, with no request near its deadline
    E = us(ao["expires_at"])
    wait_until(E + 40_000)
    x = alist(c3, t["ada"])[ao["authorization_id"]]
    ok("IMP2 imported open hold expires at its (whole-second) deadline on the real clock: expired, closed_at == expires_at", (x["status"], x["closed_at"]) == ("expired", ao["expires_at"]), x)
    m = view(c3, t["ada"])
    ok("IMP2 after the imported hold expired /me releases it (available == total)", m[2] == m[0] and m[1] == 0 and inv_ok(m), m)
    orc = Oracle(c3.req("GET", "/_test/export").j)
    n, bad = compare_views(c3, t, list(bal), orc, "IMP2", instants=set(orc.instants))
    ok("IMP2 final: %d views at every instant (incl. imported whole-second ones) equal the oracle" % n, not bad, bad[:4])


def atk_legacy(S3, SL):
    """export from the rejected 3c7c411 build (created_at whole second + created_exact microsecond) -> HEAD"""
    cl, c3 = SL.c, S3.c
    bal = {"ada": 10000, "bob": 6000, "cy": 0}
    t = setup(cl, bal, ttl=600)
    for _ in range(40):  # start a flow early in a wall-clock second so payment and hold share it
        frac = (now_us() % 1_000_000)
        if 30_000 < frac < 400_000:
            break
        time.sleep(0.02)
    p = pay(cl, t["bob"], "ada", 5000)  # funds the hold below
    a = authorize(cl, t["ada"], "cy", 12000)  # ada: balance 15000, available before the payment was 10000 < 12000
    print("   LEGACY source payment %s  authorization created_at %s" % (p.j["created_at"], a.j["created_at"] if a.s == 201 else a.b))
    ok("LEGACY source flow made (pay 5000 then hold 12000)", p.s == 201 and a.s == 201, (p.s, a.s, a.b))
    ex = cl.req("GET", "/_test/export")
    aj = ex.j["state"]["authorizations"][0]
    print("   LEGACY export authorization:", json.dumps({k_: aj.get(k_) for k_ in ("created_at", "created_exact", "expires_at", "status")}))
    P, F, X = us(p.j["created_at"]), us(aj["created_at"]), us(aj["created_exact"])
    ok("LEGACY precondition: payment lies between created_at (whole second) and created_exact", F < P < X, (iso(F), iso(P), iso(X)))
    r = c3.req("POST", "/_test/import", raw=ex.b)
    ok("LEGACY export imports into HEAD: 204", r.s == 204, (r.s, r.b))
    t3 = {h: login(c3, h) for h in bal}
    views = {name: view(c3, t3["ada"], T) for name, T in (("created_at(whole second)", F), ("payment-1us", P - 1), ("payment", P), ("created_exact-1us", X - 1), ("created_exact", X))}
    for n_, v in views.items():
        print("   LEGACY ada as_of %-26s total/held/available/balance = %s" % (n_, v))
    ok("LEGACY imported hold: every historical view of ada has available >= 0 (the funding payment is not later than the hold)", all(inv_ok(v) for v in views.values()), views)
    x = alist(c3, t3["ada"])
    print("   LEGACY HEAD authorizations:", [(y["created_at"], y["status"]) for y in x.values()])


ATK = {}


def main():
    which = sys.argv[1:] or ["ttl", "poll", "race", "storm", "storm1", "imp1", "imp2", "legacy"]
    srv = {}
    try:
        port = 18230
        S3 = Srv(S3EXE, port)
        srv["s3"] = S3
        for w in which:
            t0 = time.time()
            print("#### %s" % w, flush=True)
            if w == "ttl":
                atk_ttl(S3, 1), atk_ttl(S3, 2)
            elif w == "poll":
                atk_poll(S3, 1), atk_poll(S3, 2)
            elif w == "race":
                atk_race(S3, 1), atk_race(S3, 2)
            elif w == "storm":
                atk_storm(S3, None, label="STORM(ttl=600)")
            elif w == "storm1":
                atk_storm(S3, 1, label="STORM(ttl=1)")
            elif w == "imp1":
                s = srv["s1"] = Srv("s1.exe", port + 1)
                atk_imp1(S3, s)
                s.stop()
            elif w == "imp2":
                s = srv["s2"] = Srv("s2.exe", port + 2)
                atk_imp2(S3, s)
                s.stop()
            elif w == "legacy":
                s = srv["sl"] = Srv("s3-legacy-3c7c411.exe", port + 3)
                atk_legacy(S3, s)
                s.stop()
            print("#### %s done in %.1fs" % (w, time.time() - t0), flush=True)
    finally:
        for s in srv.values():
            s.stop()
    print("== f2_attack %s: %d pass, %d fail, %d requests" % (",".join(which), NPASS[0], len(FAILS), NREQ[0]))
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)


if __name__ == "__main__":
    main()
