#!/bin/bash
# usage (WSL): run_upgrade34.sh [run] [stage4-image] [stage3-image] -- accepted stage-3 (5e6f83f) image -> export -> stage-4 image import, browser against a tiny proxy
RUN=${1:-1}; IMG4=${2:-pocketful-s4-jury}; IMG3=${3:-pocketful-s3-b04}
HERE=$(cd "$(dirname "$0")" && pwd); B=$HERE/browser; LOGS=$HERE/logs; mkdir -p "$LOGS" "$B/shots"
N3=pf34-s3-$$; N4=pf34-s4-$$; P3=$((43000 + RANDOM % 1500)); P4=$((44600 + RANDOM % 1500)); PP=$((46200 + RANDOM % 1500))
service docker start >/dev/null 2>&1
docker run -d --name $N3 -e PORT=8080 -p 127.0.0.1:$P3:8080 $IMG3 >/dev/null
docker run -d --name $N4 -e PORT=8080 -p 127.0.0.1:$P4:8080 $IMG4 >/dev/null
for i in $(seq 1 150); do curl -sf http://127.0.0.1:$P3/health >/dev/null && curl -sf http://127.0.0.1:$P4/health >/dev/null && break; sleep 0.1; done
docker run --rm --network host -e PFB=http://127.0.0.1:$P4 -e PF3=http://127.0.0.1:$P3 -e PROXY_PORT=$PP -e SHOTS=/b/shots/run$RUN --entrypoint python3 -v "$B":/b -w /b df-harness-runner -u b8_upgrade34.py 2>&1 | tee "$LOGS/b8_upgrade34.run$RUN.log"
RC=${PIPESTATUS[0]}
docker rm -f $N3 $N4 >/dev/null; echo "rc=$RC" | tee -a "$LOGS/b8_upgrade34.run$RUN.log"; exit $RC
