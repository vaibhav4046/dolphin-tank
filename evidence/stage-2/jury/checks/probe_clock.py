import datetime as dt, time
from lib import *
t = setup(fx([user("ada", 100000), user("bob", 0)]))
for i in range(12):
    time.sleep(0.13)
    b = dt.datetime.now(dt.timezone.utc); r = authorize(t["ada"], "bob", 10); a = dt.datetime.now(dt.timezone.utc)
    c = ts(r.j["created_at"]); e = ts(r.j["expires_at"])
    print("py_before %s created_at %s py_after %s | created-floor(before)=%s expires-created=%s" % (b.strftime("%H:%M:%S.%f")[:-3], r.j["created_at"][11:19], a.strftime("%H:%M:%S.%f")[:-3], (c - b.replace(microsecond=0)).total_seconds(), (e - c).total_seconds()))
