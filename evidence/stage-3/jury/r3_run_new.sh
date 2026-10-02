#!/bin/bash
# R3 jury run, new checks written for 5e6f83f. usage (inside WSL): bash r3_run_new.sh  -> logs/r3-run-new.summary.log
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
export IMG=${IMG:-pocketful-s3-r3}
LEG=${LEG:-pocketful-s3-legacy-r3}
LOGS=$HERE/logs; mkdir -p "$LOGS"
SUM=$LOGS/r3-run-new.summary.log; : > "$SUM"
cd "$HERE/checks"
line() { local L="$LOGS/${1%.py}.run$2.log"
  echo "$1 $2 :: $(grep -E '^==' "$L" | tail -1) :: $(tail -1 "$L") :: FAILS=$(grep -c '^FAIL' "$L")" | tee -a "$SUM"
  grep -h '^FAIL' "$L" | head -10 | cut -c1-500 | tee -a "$SUM"; }
for s in 1 2 3 4 5 6; do ARGS=$s bash run_check.sh r3_sweep.py r3s$s >/dev/null 2>&1; line r3_sweep.py r3s$s; done
bash run_check.sh r3_seedmatrix.py r3a >/dev/null 2>&1; line r3_seedmatrix.py r3a
for s in 5 6 7; do ARGS=$s bash run_multi.sh r3_legacy_import.py r3s$s "$LEG" "$IMG" >/dev/null 2>&1; line r3_legacy_import.py r3s$s; done
echo "== NEW DONE" | tee -a "$SUM"
