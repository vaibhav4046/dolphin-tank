#!/bin/bash
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
docker rm -f pf pf1 >/dev/null 2>&1
docker run -d --name pf -e PORT=8080 -p 8080:8080 "$1" >/dev/null
docker run -d --name pf1 -e PORT=8080 -p 8081:8080 pocketful-s1 >/dev/null
for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8080/health >/dev/null && curl -sf http://127.0.0.1:8081/health >/dev/null && break; sleep 0.5; done
docker run --rm --network host -v /mnt/d/project/dolphin-tank/band-work/scratch/s2-loom:/work --entrypoint python3 df-harness-runner:latest "/work/$2"
rc=$?
docker rm -f pf pf1 >/dev/null 2>&1
exit $rc
