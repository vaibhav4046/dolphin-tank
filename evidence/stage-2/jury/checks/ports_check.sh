#!/bin/bash
# PORT variants, default port, arbitrary uid / read-only fs / resource limits for the stage-2 image
IMG=${1:-pocketful-s2-jury}
service docker start >/dev/null 2>&1
wait_health() { for i in $(seq 1 100); do curl -sf "$1" >/dev/null && return 0; sleep 0.1; done; return 1; }
for P in 9999 80 8080; do
  docker rm -f pp$P >/dev/null 2>&1
  docker run -d --rm --name pp$P -e PORT=$P -p 127.0.0.1:1$P:$P $IMG >/dev/null
  wait_health http://127.0.0.1:1$P/health; echo "PORT=$P -> $(curl -s http://127.0.0.1:1$P/health)"
  docker rm -f pp$P >/dev/null
done
docker rm -f dp >/dev/null 2>&1
docker run -d --rm --name dp -p 127.0.0.1:18088:8080 $IMG >/dev/null
wait_health http://127.0.0.1:18088/health; echo "default (no PORT) -> $(curl -s http://127.0.0.1:18088/health)"
docker rm -f dp >/dev/null
docker rm -f hard >/dev/null 2>&1
docker run -d --rm --name hard --read-only --cpus 2 -m 2g --user 12345 -p 127.0.0.1:18089:8080 $IMG >/dev/null
wait_health http://127.0.0.1:18089/health; echo "read-only fs, 2 cpu, 2g, uid 12345 -> $(curl -s http://127.0.0.1:18089/health)"
curl -s -X POST http://127.0.0.1:18089/_test/reset -H 'Content-Type: application/json' -d '{"currency":"EUR","minor_units":2,"users":[]}' -o /dev/null -w "reset on read-only fs -> %{http_code}\n"
docker rm -f hard >/dev/null
