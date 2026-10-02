#!/bin/bash
# usage: rerun_some.sh <run#> ; reruns c01 c08 (s1reg) and s2_lifecycle (s2reg) alone (quiet host)
set -u
HERE=$(cd "$(dirname "$0")" && pwd); LOGS=$HERE/logs; IMG=${IMG:-pocketful-s3-jury}; RUN=${1:-2}
service docker start >/dev/null 2>&1; . /root/dfv/bin/activate
cd "$HERE/s1reg"
for S in ${SCRIPTS:-c01_conservation c08_export_import}; do
  N1=pf1r-$$-$RANDOM; N2=pf1d-$$-$RANDOM; P1=$((20000 + RANDOM % 10000)); P2=$((50000 + RANDOM % 5000))
  docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" "$IMG" >/dev/null
  docker run -d --name "$N2" -e PORT=8080 -p "127.0.0.1:$P2:8080" "$IMG" >/dev/null
  for p in $P1 $P2; do for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 0.1; done; done
  PF=127.0.0.1:$P1 PFD=127.0.0.1:$P2 python -u $S.py > "$LOGS/s1reg.$S.run$RUN.log" 2>&1; RC=$?
  echo "s1 $S run$RUN rc=$RC :: $(grep '^==' "$LOGS/s1reg.$S.run$RUN.log" | tail -1)"; grep -h "^FAIL" "$LOGS/s1reg.$S.run$RUN.log" | head -4 | cut -c1-300
  docker rm -f "$N1" "$N2" >/dev/null
done
cd "$HERE/s2reg"
IMG=$IMG bash run_check.sh s2_lifecycle.py r$RUN >/dev/null 2>&1; RC=$?
echo "s2 s2_lifecycle run$RUN rc=$RC :: $(grep '^==' "$LOGS/s2_lifecycle.runr$RUN.log" | tail -1)"; grep -h "^FAIL" "$LOGS/s2_lifecycle.runr$RUN.log" | head -4 | cut -c1-300
