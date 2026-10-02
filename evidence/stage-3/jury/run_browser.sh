#!/bin/bash
# usage: run_browser.sh <script.py> <run> [image]  -- fresh stage-2 container + playwright chromium in df-harness-runner (host network)
SCRIPT=$1; RUN=${2:-1}; IMG=${3:-pocketful-s3-jury}
HERE=$(cd "$(dirname "$0")" && pwd); B=$HERE/browser; LOGS=$HERE/logs; mkdir -p "$LOGS" "$B/shots"
N=pf3b-$$-$RANDOM; P=$((41000 + RANDOM % 8000))
service docker start >/dev/null 2>&1
docker run -d --name "$N" -e PORT=8080 -p "127.0.0.1:$P:8080" "$IMG" >/dev/null
for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$P/health" >/dev/null && break; sleep 0.1; done
docker run --rm --network host -e PFB=http://127.0.0.1:$P -e SHOTS=/b/shots/run$RUN --entrypoint python3 -v "$B":/b -w /b df-harness-runner -u "$SCRIPT" 2>&1 | tee "$LOGS/${SCRIPT%.py}.run$RUN.log"
RC=${PIPESTATUS[0]}
docker logs "$N" > "$LOGS/${SCRIPT%.py}.run$RUN.server.log" 2>&1; docker rm -f "$N" >/dev/null
echo "rc=$RC" | tee -a "$LOGS/${SCRIPT%.py}.run$RUN.log"; exit $RC
