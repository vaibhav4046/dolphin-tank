#!/bin/bash
# usage: run_multi.sh <script.py> <run> img1 img2 ...  -- one fresh container per image; env PF1..PFn=host:port (PF = PF1)
set -u
SCRIPT=$1; RUN=${2:-1}; shift 2
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/../logs; mkdir -p "$LOGS"
service docker start >/dev/null 2>&1
NAMES=(); i=0; ENVS=()
for IMG in "$@"; do
  i=$((i+1)); N=pf3m$i-$$-$RANDOM; P=$((20000 + RANDOM % 20000))
  docker run -d --name "$N" -e PORT=8080 -p "127.0.0.1:$P:8080" "$IMG" >/dev/null
  NAMES+=("$N"); ENVS+=("PF$i=127.0.0.1:$P")
  for t in $(seq 1 150); do curl -sf "http://127.0.0.1:$P/health" >/dev/null && break; sleep 0.1; done
done
. /root/dfv/bin/activate; cd "$HERE"
env "${ENVS[@]}" PF="$(echo "${ENVS[0]}" | cut -d= -f2)" python -u "$SCRIPT" 2>&1 | tee "$LOGS/${SCRIPT%.py}.run$RUN.log"
RC=${PIPESTATUS[0]}
j=0; for N in "${NAMES[@]}"; do j=$((j+1)); docker logs "$N" > "$LOGS/${SCRIPT%.py}.run$RUN.c$j.server.log" 2>&1; done
docker rm -f "${NAMES[@]}" >/dev/null
echo "rc=$RC" | tee -a "$LOGS/${SCRIPT%.py}.run$RUN.log"; exit $RC
