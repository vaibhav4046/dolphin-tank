#!/bin/bash
# usage: run_browser2.sh <script.py> <run> -- stage-1 container (PF1, ACCEPTED stage-1 image) + stage-2 container (PFB) + playwright in df-harness-runner
SCRIPT=$1; RUN=${2:-1}; I1=${I1:-pocketful-s1-accepted-jury}; I2=${I2:-pocketful-s2-jury}
HERE=$(cd "$(dirname "$0")" && pwd); B=$HERE/browser; LOGS=$HERE/logs; mkdir -p "$LOGS" "$B/shots"
N1=pf2u1-$$-$RANDOM; N2=pf2u2-$$-$RANDOM; P1=$((41000 + RANDOM % 3000)); P2=$((44000 + RANDOM % 3000)); PP=$((47000 + RANDOM % 2000))
service docker start >/dev/null 2>&1
docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" "$I1" >/dev/null
docker run -d --name "$N2" -e PORT=8080 -p "127.0.0.1:$P2:8080" "$I2" >/dev/null
for p in $P1 $P2; do for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 0.1; done; done
docker run --rm --network host -e PFB=http://127.0.0.1:$P2 -e PF1=http://127.0.0.1:$P1 -e PROXY_PORT=$PP -e SHOTS=/b/shots/run$RUN --entrypoint python3 -v "$B":/b -w /b df-harness-runner -u "$SCRIPT" 2>&1 | tee "$LOGS/${SCRIPT%.py}.run$RUN.log"
RC=${PIPESTATUS[0]}
docker logs "$N1" > "$LOGS/${SCRIPT%.py}.run$RUN.s1.server.log" 2>&1; docker logs "$N2" > "$LOGS/${SCRIPT%.py}.run$RUN.s2.server.log" 2>&1; docker rm -f "$N1" "$N2" >/dev/null
echo "rc=$RC" | tee -a "$LOGS/${SCRIPT%.py}.run$RUN.log"; exit $RC
