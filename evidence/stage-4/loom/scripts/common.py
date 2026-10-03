"""Shared helpers for the stage-4 browser scripts (loom). Run with a local Python Playwright and a stage-4 binary."""
import json, os, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE", "http://127.0.0.1:8084")
SHOTS = os.environ.get("SHOTS", os.path.join(os.path.dirname(__file__), "..", "shots"))
os.makedirs(SHOTS, exist_ok=True)
FAILS = []


def iso(delta):
    return (datetime.now(timezone.utc) + delta).replace(microsecond=0).isoformat()


def http(method, path, body=None, token=None, key=None, base=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request((base or BASE) + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def user(uid, handle, name, balance):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse", "display_name": name, "handle": handle, "balance": balance}


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)
    return bool(cond)


def token_of(handle, base=None):
    st, body = http("POST", "/auth/login", {"email": f"{handle}@example.com", "password": "correct horse"}, base=base)
    assert st == 200, (st, body)
    return body["token"]


class Session:
    """One browser context signed in with a token, recording POSTs and any non-local request."""

    def __init__(self, browser, width=1280, height=900, token=None, base=None, **ctx):
        self.base = base or BASE
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, **ctx)
        if token:
            self.ctx.add_init_script(f"if(!localStorage.getItem('pocketful.token')) localStorage.setItem('pocketful.token','{token}')")
        self.page = self.ctx.new_page()
        self.errors, self.posts, self.external = [], [], []
        self.page.on("request", lambda r: self.external.append(r.url) if not r.url.startswith((self.base, "data:")) else None)
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.posts.append((r.url.replace(self.base, ""), r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST" else None)

    def t(self, testid):
        return self.page.locator(f'[data-testid="{testid}"]')

    def goto(self, path):
        self.page.goto(self.base + path, wait_until="domcontentloaded")
        self.page.wait_for_selector("main[aria-busy='false'], .auth-wrap")

    def shot(self, name):
        self.page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)

    def hscroll_ok(self, name):
        sw, cw = self.page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        return check(f"no horizontal scroll: {name}", sw <= cw, f"{sw}>{cw}")

    def amount(self, testid):
        return int(self.t(testid).get_attribute("data-amount"))

    def refund_posts(self, pid):
        return [p for p in self.posts if p[0] == f"/payments/{pid}/refunds"]


WEIGHT_JS = """() => { const bad = []; for (const el of document.querySelectorAll('body, body *')) {
  const w = parseInt(getComputedStyle(el).fontWeight, 10); if (w > 500) bad.push(el.tagName + ':' + w); } return bad.slice(0, 5); }"""

CONTRAST_JS = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r:p[0], g:p[1], b:p[2], a:p.length > 3 ? p[3] : 1}; };
  const lum = ({r, g, b}) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c.a > 0) return c; } return {r:3, g:0, b:20, a:1}; };
  const opOf = el => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  let worst = {ratio: 99}; let n;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while ((n = walker.nextNode())) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement; const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || el.closest('[hidden]') || el.closest('.vh')) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const fg = parse(cs.color), bg = bgOf(el), op = opOf(el);
    const eff = {r: fg.r * op + bg.r * (1 - op), g: fg.g * op + bg.g * (1 - op), b: fg.b * op + bg.b * (1 - op)};
    const rt = ratio(eff, bg);
    if (rt < worst.ratio) worst = {ratio: Math.round(rt * 100) / 100, text: n.textContent.trim().slice(0, 40), color: cs.color, op};
  }
  return worst; }"""

UNLABELLED_JS = """() => [...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(el => {
  if (el.closest('[hidden]')) return false;
  const l = el.id && document.querySelector('label[for="' + el.id + '"]');
  return !(l && l.textContent.trim()) && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby'); }).map(el => el.id || el.name || el.tagName)"""

SMALL_TARGET_JS = """() => [...document.querySelectorAll('button, a[href], input:not([type=checkbox]), select')].filter(el => {
  if (el.closest('[hidden]')) return false;
  const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 43.5; }).map(el => (el.dataset.testid || el.tagName) + ':' + Math.round(el.getBoundingClientRect().height))"""
