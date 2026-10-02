#!/bin/bash
# usage: run_check.sh <script.py> <run-number> [image]  -- fresh production container per run, run inside WSL
# env: IMG (default pocketful-s3-jury)
set -u
SCRIPT=$1; RUN=${2:-1}; IMG=${3:-${IMG:-pocketful-s3-jury}}
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS=$HERE/../logs; mkdir -p "$LOGS"
NAME=pf3c-$$-$RANDOM
PORT=$((20000 + RANDOM % 20000))
service docker start >/dev/null 2>&1
docker run -d --name "$NAME" -e PORT=8080 -p "127.0.0.1:$PORT:8080" "$IMG" >/dev/null
for i in $(seq 1 100); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.1; done
. /root/dfv/bin/activate
cd "$HERE"
PF=127.0.0.1:$PORT python -u "$SCRIPT" ${ARGS:-} 2>&1 | tee "$LOGS/${SCRIPT%.py}.run$RUN.log"
RC=${PIPESTATUS[0]}
docker logs "$NAME" > "$LOGS/${SCRIPT%.py}.run$RUN.server.log" 2>&1
docker rm -f "$NAME" >/dev/null
echo "rc=$RC" | tee -a "$LOGS/${SCRIPT%.py}.run$RUN.log"
exit $RC
