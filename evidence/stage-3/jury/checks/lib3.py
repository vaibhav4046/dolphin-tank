"""stage-3 helpers on top of lib.py (stdlib only). Independent oracle written from stage-3.md."""
import datetime as dt
import urllib.parse
from lib import *

UTC = dt.timezone.utc
EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
US = dt.timedelta(microseconds=1)


def P(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))


def iso(d):
    return d.astimezone(UTC).isoformat(timespec="microseconds")


def q(s):
    return urllib.parse.quote(s, safe="")


def me_at(tok, as_of=None, known_at=None):
    qs = []
    if as_of is not None:
        qs.append("as_of=" + q(as_of))
    if known_at is not None:
        qs.append("known_at=" + q(known_at))
    return call("GET", "/me" + ("?" + "&".join(qs) if qs else ""), token=tok)


def stmt(tok, **kw):
    qs = "&".join("%s=%s" % (a, q(str(b))) for a, b in kw.items())
    return call("GET", "/statement" + ("?" + qs if qs else ""), token=tok)


def revs(tok, pid):
    r = call("GET", "/payments/%s/revisions" % pid, token=tok)
    assert r.s == 200, r
    return r.j["revisions"]


def correct(tok, pid, rev, amount, eff, reason="r", key=None):
    return call("POST", "/payments/%s/corrections" % pid,
                {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason},
                token=tok, key=key or k())


def all_stmt(tok, **kw):
    """read the whole statement window in pages of 7 via snapshot; return (first_response_json, entries)"""
    first = stmt(tok, limit=7, **kw)
    assert first.s == 200, first
    entries = list(first.j["entries"])
    more = first.j["has_more"]
    off = 7
    while more:
        r = call("GET", "/statement?snapshot=%s&limit=7&offset=%d" % (first.j["snapshot"], off), token=tok)
        assert r.s == 200, r
        entries += r.j["entries"]
        more = r.j["has_more"]
        off += 7
    return first.j, entries


class Oracle:
    """expected balances from the spec: opening + selected revisions applied at their effective times."""

    def __init__(self, opening):
        self.opening = dict(opening)  # user_id -> opening balance
        self.pay = {}  # pid -> (from_uid, to_uid)
        self.revs = {}  # pid -> [{revision, amount, effective_at(dt), recorded_at(dt)}]

    def add(self, pid, frm, to, revlist):
        self.pay[pid] = (frm, to)
        self.revs[pid] = [dict(revision=r["revision"], amount=r["amount"], eff=P(r["effective_at"]), rec=P(r["recorded_at"])) for r in revlist]

    def selected(self, pid, known_at):
        best = None
        for r in self.revs[pid]:
            if known_at is None or r["rec"] <= known_at:
                if best is None or r["revision"] > best["revision"]:
                    best = r
        return best

    def moves(self, uid, known_at):
        out = []
        for pid, (f, t) in self.pay.items():
            if uid not in (f, t):
                continue
            s = self.selected(pid, known_at)
            if s is None:
                continue
            out.append((s["eff"], pid, -s["amount"] if uid == f else s["amount"], s))
        out.sort(key=lambda x: (x[0], x[1].encode()))
        return out

    def total(self, uid, as_of=None, known_at=None):
        t = self.opening[uid]
        for eff, pid, d, s in self.moves(uid, known_at):
            if as_of is None or eff <= as_of:
                t += d
        return t

    def window(self, uid, frm=None, to=None, known_at=None):
        mv = self.moves(uid, known_at)
        opening = self.opening[uid] + sum(d for eff, pid, d, s in mv if frm is not None and eff < frm)
        entries, bal = [], opening
        for eff, pid, d, s in mv:
            if (frm is None or eff >= frm) and (to is None or eff < to):
                bal += d
                entries.append((pid, d, bal, s["revision"], s["amount"], eff))
        closing = opening + sum(d for e in entries for d in [e[1]])
        return opening, entries, closing
