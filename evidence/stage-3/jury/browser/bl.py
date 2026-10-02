"""jury browser helpers. Runs inside df-harness-runner (python playwright, chromium). PFB=http://host:port of the stage-2 server."""
import json, os, re, sys, time, http.client, urllib.parse, uuid, threading
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("PFB", "http://127.0.0.1:18090")
U = urllib.parse.urlparse(BASE); HOST, PORT = U.hostname, U.port
SHOTS = os.environ.get("SHOTS", "/b/shots")
os.makedirs(SHOTS, exist_ok=True)
FAILS, NPASS = [], [0]
INFO = []

def ok(name, cond, detail=""):
    if cond:
        NPASS[0] += 1; print("PASS", name)
    else:
        FAILS.append(name); print("FAIL", name, "::", str(detail)[:700])

def info(*a):
    s = " ".join(str(x) for x in a); INFO.append(s); print("INFO", s)

def done(label):
    print("== %s: %d pass, %d fail" % (label, NPASS[0], len(FAILS)))
    if FAILS:
        print("FAILED:", FAILS); sys.exit(1)

def api(method, path, body=None, token=None, key=None, base=None, raw=None, hdrs=None):
    h, p = (base or (HOST, PORT))
    c = http.client.HTTPConnection(h, p, timeout=20)
    hd = dict(hdrs or {})
    if token: hd["Authorization"] = "Bearer " + token
    if key is not None: hd["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None: hd["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=hd)
    r = c.getresponse(); b = r.read(); c.close()
    try: j = json.loads(b) if b else None
    except Exception: j = None
    return r.status, j

def k(): return uuid.uuid4().hex

def user(h, bal=0):
    return {"id": "u_" + h, "email": h + "@example.com", "password": "correct horse", "display_name": h.capitalize(), "handle": h, "balance": bal}

def reset(fx):
    s, _ = api("POST", "/_test/reset", fx); assert s == 204, s

def fixture(users=None, **kw):
    f = {"currency": "EUR", "minor_units": 2, "users": users or [user("ada", 10000), user("bob", 2500), user("cy", 0), user("dee", 5000)]}
    f.update(kw); return f

def tok(email):
    s, j = api("POST", "/auth/login", {"email": email, "password": "correct horse"}); assert s == 200, (s, j); return j["token"]

def tid(page, t): return page.locator('[data-testid="%s"]' % t)

def ui_login(page, email, pw="correct horse"):
    page.goto(BASE + "/login")
    tid(page, "login-email").fill(email); tid(page, "login-password").fill(pw); tid(page, "login-submit").click()
    page.wait_for_selector('[data-testid="current-user"]', timeout=8000)

def seeded_page(ctx, token):
    ctx.add_init_script("try{localStorage.setItem('pocketful.token', %s)}catch(e){}" % json.dumps(token))

def shot(page, name):
    try: page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)
    except Exception as e: info("screenshot failed", name, e)

def launch(pw):
    return pw.chromium.launch(args=["--no-sandbox"])
