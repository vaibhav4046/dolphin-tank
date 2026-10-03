"""jury regression: my accepted stage-1/2/3 check scripts (evidence/stage-{1,2,3}/jury, unmodified) against a stage-4 binary.
Two fresh instances per script (PF = under test, PFD = donor/destination for import checks), run natively, stdlib only.

usage: python run_reg.py <stage-4 exe> <logs dir>
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jlib import Svc  # noqa

EXE, LOGS = sys.argv[1], sys.argv[2]
EV = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.makedirs(LOGS, exist_ok=True)
S3 = os.path.join(EV, "stage-3", "jury")
SETS = [
    ("s1reg", os.path.join(S3, "s1reg"), ["c01_conservation", "c02_idempotency", "c03_validation", "c04_auth", "c05_requests_feed", "c06_reset_fixture",
                                         "c07_splits", "c08_export_import", "c09_no5xx_envelope", "c11_settlements", "c12_retries_edges", "c13_reset_vs_me", "d2_smoke"]),
    ("s2reg", os.path.join(S3, "s2reg"), ["s2_lifecycle", "s2_funds", "s2_errors", "s2_idem", "s2_list", "s2_fixture", "s2_expiry", "s2_race", "s2_export", "s2_export_expiry"]),
    ("s3chk", os.path.join(S3, "checks"), ["r3_corr_order", "r3_seedmatrix", "r3_sweep", "probe_shapes"]),
]
only = sys.argv[3:]


def wait_for_ports(limit=6000):
    """Windows runs out of ephemeral ports after ~16k connections (TIME_WAIT); let them drain before the next script."""
    import time
    for _ in range(40):
        n = subprocess.run(["netstat", "-an"], capture_output=True, text=True).stdout.count("TIME_WAIT")
        if n < limit:
            return n
        time.sleep(15)
    return -1

rows = []
for label, d, names in SETS:
    for n in names:
        if only and n not in only:
            continue
        if not os.path.exists(os.path.join(d, n + ".py")):
            rows.append((label, n, "missing", ""))
            continue
        wait_for_ports()
        a, b = Svc(EXE), Svc(EXE)
        env = dict(os.environ, PF="127.0.0.1:%d" % a.port, PFD="127.0.0.1:%d" % b.port, PYTHONIOENCODING="utf-8")
        try:
            r = subprocess.run([sys.executable, "-u", n + ".py"], cwd=d, env=env, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
            out = r.stdout + r.stderr
            rc = r.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = "TIMEOUT", -1
        finally:
            a.stop()
            b.stop()
        open(os.path.join(LOGS, "%s.%s.log" % (label, n)), "w", encoding="utf-8").write(out)
        last = [l for l in out.splitlines() if l.startswith("==")]
        fails = [l[:200] for l in out.splitlines() if l.startswith("FAIL")]
        rows.append((label, n, "rc=%s" % rc, (last[-1] if last else "") + ((" | " + " || ".join(fails[:3])) if fails else "")))
        print("%s %-22s rc=%s %s" % (label, n, rc, rows[-1][3][:260]))
        sys.stdout.flush()
bad = [r for r in rows if r[2] not in ("rc=0",)]
print("regression: %d scripts, %d non-zero" % (len(rows), len(bad)))
