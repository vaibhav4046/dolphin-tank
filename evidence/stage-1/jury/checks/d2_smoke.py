"""Run inside a sibling container on a docker --internal network: no outbound, server reachable by name."""
import socket
from lib import *

blocked = 0
for ip in ("1.1.1.1", "8.8.8.8"):
    try:
        socket.create_connection((ip, 53), timeout=3).close()
        print("outbound reachable to", ip)
    except OSError as e:
        blocked += 1
        print("outbound blocked to", ip, "->", type(e).__name__)
ok("sibling has no outbound network", blocked == 2)

r = call("GET", "/health")
ok("health 200 on internal net", r.s == 200 and r.j == {"status": "ok"}, r)
t = setup()
r = call("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "x"}, token=t["ada"], key=k())
ok("payment 201 on internal net", r.s == 201 and r.j["amount"] == 1500, r)
ok("balances after payment", bal(t["ada"]) == 8500 and bal(t["bob"]) == 4000)
done("d2_smoke")
