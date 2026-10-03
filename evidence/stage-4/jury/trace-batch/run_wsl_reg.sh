#!/bin/bash
# jury regression on the stage-4 IMAGE (docker in WSL): my accepted stage-1/2/3 check scripts, unmodified, against fresh containers.
# usage: bash run_wsl_reg.sh [script ...]   (no args = all)   env: IMG (default pocketful-s4-jury)
set -u
IMG=${IMG:-pocketful-s4-jury}
EV=/mnt/d/project/dolphin-tank/band-work/result/evidence
LOGS=$EV/stage-4/jury/trace-batch/reg-wsl-logs; mkdir -p "$LOGS"
service docker start >/dev/null 2>&1
. /root/dfv/bin/activate
ONLY=" $* "
run() {
  d=$1; s=$2
  if [ -n "$*" ] && [ "$ONLY" != "  " ] && [[ "$ONLY" != *" $s "* ]]; then return; fi
  N1=pf4r-$$-$RANDOM; N2=pf4d-$$-$RANDOM; P1=$((20000 + RANDOM % 10000)); P2=$((30000 + RANDOM % 10000))
  docker run -d --name "$N1" -e PORT=8080 -p "127.0.0.1:$P1:8080" "$IMG" >/dev/null
  docker run -d --name "$N2" -e PORT=8080 -p "127.0.0.1:$P2:8080" "$IMG" >/dev/null
  for p in $P1 $P2; do for i in $(seq 1 150); do curl -sf "http://127.0.0.1:$p/health" >/dev/null && break; sleep 0.1; done; done
  (cd "$d" && PF=127.0.0.1:$P1 PFD=127.0.0.1:$P2 python -u "$s.py" > "$LOGS/$s.log" 2>&1); RC=$?
  echo "$s rc=$RC :: $(grep '^==' "$LOGS/$s.log" | tail -1 | cut -c1-200)"
  grep -h "^FAIL" "$LOGS/$s.log" | head -5 | cut -c1-300
  docker rm -f "$N1" "$N2" >/dev/null
}
S1=$EV/stage-3/jury/s1reg; S2=$EV/stage-3/jury/s2reg; S3=$EV/stage-3/jury/checks
for s in c01_conservation c02_idempotency c03_validation c04_auth c05_requests_feed c06_reset_fixture c07_splits c08_export_import c09_no5xx_envelope c11_settlements c12_retries_edges c13_reset_vs_me d2_smoke; do run $S1 $s; done
for s in s2_lifecycle s2_funds s2_errors s2_idem s2_list s2_fixture s2_expiry s2_race s2_export s2_export_expiry; do run $S2 $s; done
for s in r3_corr_order r3_seedmatrix r3_sweep probe_shapes; do run $S3 $s; done
echo "done"
