#!/bin/bash
# usage: [S3IMG=.. S2IMG=.. S1IMG=..] run3.sh <script in scripts/>  -- stage-3 on :8080, stage-2 on :8081, stage-1 on :8082
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
E=/mnt/d/project/dolphin-tank/band-work/result/evidence/stage-3/loom
docker rm -f pf pf2 pf1 >/dev/null 2>&1
docker run -d --name pf -e PORT=8080 -p 8080:8080 ${S3IMG:-pocketful-s3} >/dev/null
docker run -d --name pf2 -e PORT=8080 -p 8081:8080 ${S2IMG:-pocketful-s2} >/dev/null
docker run -d --name pf1 -e PORT=8080 -p 8082:8080 ${S1IMG:-pocketful-s1} >/dev/null
for i in $(seq 1 20); do curl -sf http://127.0.0.1:8080/health >/dev/null && curl -sf http://127.0.0.1:8081/health >/dev/null && curl -sf http://127.0.0.1:8082/health >/dev/null && break; sleep 0.5; done
docker run --rm --network host -v "$E":/work --entrypoint python3 df-harness-runner:latest "/work/scripts/$1"
rc=$?
docker rm -f pf pf2 pf1 >/dev/null 2>&1
exit $rc
