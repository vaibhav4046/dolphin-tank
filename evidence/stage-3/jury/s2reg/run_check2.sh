#!/bin/bash
# usage: run_check2.sh <script.py> <run> [src-image] [dst-image]  -- two fresh containers; PF=source PFD=destination
set -u
SCRIPT=$1; RUN=${2:-1}; SIMG=${3:-${SIMG:-pocketful-s3-jury}}; DIMG=${4:-${DIMG:-pocketful-s3-jury}}
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/../logs; mkdir -p "$LOGS"
N1=pf2s-$$-$RANDOM; N2=pf2d-$$-$RANDOM; P1=$((20000 + RANDOM % 10000)); P2=$((30000 + RANDOM % 10000))
service docker start >/dev/null 2>&1
docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" "$SIMG" >/dev/null
docker run -d --name "$N2" -e PORT=8080 -p "127.0.0.1:$P2:8080" "$DIMG" >/dev/null
for p in $P1 $P2; do for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 0.1; done; done
. /root/dfv/bin/activate; cd "$HERE"
PF=127.0.0.1:$P1 PFD=127.0.0.1:$P2 python -u "$SCRIPT" 2>&1 | tee "$LOGS/${SCRIPT%.py}.run$RUN.log"
RC=${PIPESTATUS[0]}
docker logs "$N1" > "$LOGS/${SCRIPT%.py}.run$RUN.src.server.log" 2>&1; docker logs "$N2" > "$LOGS/${SCRIPT%.py}.run$RUN.dst.server.log" 2>&1
docker rm -f "$N1" "$N2" >/dev/null
echo "rc=$RC" | tee -a "$LOGS/${SCRIPT%.py}.run$RUN.log"; exit $RC
