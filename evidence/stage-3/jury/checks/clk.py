"""Host wall-clock step monitor. The WSL2 VM this jury runs on steps its wall clock BACK by ~1 s every ~32 s (measured: three steps of
-820/-1037/-983 ms in 120 s, logs/wsl_clock_steps.log). A strictly monotonic stamp source then leads the wall clock until it catches up, so
'created_at within its request window' needs a tolerance equal to the steps seen. Imported only by the r3_* scripts."""
import datetime as dt
import threading
import time

UTC = dt.timezone.utc
STEPS = []   # (detected wall instant, delta seconds); negative = wall clock jumped back


def _watch():
    prev = time.time() - time.monotonic()
    while True:
        time.sleep(0.0005)
        off = time.time() - time.monotonic()
        d = off - prev
        if abs(d) > 0.002:
            STEPS.append((dt.datetime.now(UTC), d))
        prev = off


threading.Thread(target=_watch, daemon=True).start()


def inwin(created, t0, t1, slack=dt.timedelta(milliseconds=30)):
    """created lies in [t0, t1] +- slack, widened by any wall-clock step seen in the 3 s before t0"""
    time.sleep(0.004)
    recent = [d for (w, d) in list(STEPS) if w >= t0 - dt.timedelta(seconds=3)]
    back = dt.timedelta(seconds=sum(-d for d in recent if d < 0))
    fwd = dt.timedelta(seconds=sum(d for d in recent if d > 0))
    return t0 - slack - fwd <= created <= t1 + slack + back


def report():
    return "host wall-clock steps seen during this run: %s" % [(w.strftime("%H:%M:%S.%f"), round(d * 1000, 1)) for (w, d) in STEPS]
