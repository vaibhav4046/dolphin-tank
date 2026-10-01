#!/bin/bash
# stage-1 regression: my accepted stage-1 jury checks (unmodified copies) against the stage-2 image. Fresh containers per script.
set -u
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/../logs; mkdir -p "$LOGS"
IMG=${IMG:-pocketful-s2-jury}; RUN=${1:-1}
service docker start >/dev/null 2>&1; . /root/dfv/bin/activate; cd "$HERE"
for S in c01_conservation c02_idempotency c03_validation c04_auth c05_requests_feed c06_reset_fixture c07_splits c08_export_import c09_no5xx_envelope c11_settlements c12_retries_edges c13_reset_vs_me d2_smoke; do
  N1=pf1r-$$-$RANDOM; N2=pf1d-$$-$RANDOM; P1=$((20000 + RANDOM % 10000)); P2=$((30000 + RANDOM % 10000))
  docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" "$IMG" >/dev/null
  docker run -d --name "$N2" -e PORT=8080 -p "127.0.0.1:$P2:8080" "$IMG" >/dev/null
  for p in $P1 $P2; do for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 0.1; done; done
  PF=127.0.0.1:$P1 PFD=127.0.0.1:$P2 python -u $S.py > "$LOGS/s1reg.$S.run$RUN.log" 2>&1; RC=$?
  echo "$S run$RUN rc=$RC :: $(grep '^==' "$LOGS/s1reg.$S.run$RUN.log" | tail -1)"
  grep -h "^FAIL" "$LOGS/s1reg.$S.run$RUN.log" | head -8
  docker rm -f "$N1" "$N2" >/dev/null
done
