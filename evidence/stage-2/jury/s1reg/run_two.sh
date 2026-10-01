#!/bin/bash
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/../logs; RUN=${1:-2}
service docker start >/dev/null 2>&1; . /root/dfv/bin/activate; cd "$HERE"
for S in c04_auth c09_no5xx_envelope; do
  N1=pf1r-$$-$RANDOM; P1=$((20000 + RANDOM % 10000)); docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" pocketful-s2-jury >/dev/null
  for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$P1/health" >/dev/null && break; sleep 0.1; done
  PF=127.0.0.1:$P1 python -u $S.py > "$LOGS/s1reg.$S.run$RUN.log" 2>&1; echo "$S run$RUN rc=$? :: $(grep '^==' "$LOGS/s1reg.$S.run$RUN.log" | tail -1)"; grep -h "^FAIL" "$LOGS/s1reg.$S.run$RUN.log" | head -5
  docker rm -f "$N1" >/dev/null
done
