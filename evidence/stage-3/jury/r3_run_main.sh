#!/bin/bash
# R3 jury run of 5e6f83f: own checks against image $IMG (default pocketful-s3-r3), sequential (no host-load flakes).
# usage (inside WSL): bash r3_run_main.sh   -> summary lines to logs/r3-run-main.summary.log
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
export IMG=${IMG:-pocketful-s3-r3}
S1IMG=${S1IMG:-pocketful-s1-accepted-jury}
S2IMG=${S2IMG:-pocketful-s2-jury}
LOGS=$HERE/logs; mkdir -p "$LOGS"
SUM=$LOGS/r3-run-main.summary.log; : > "$SUM"
cd "$HERE/checks"
line() { # script runid
  local L="$LOGS/${1%.py}.run$2.log"
  echo "$1 $2 :: $(grep -E '^==' "$L" | tail -1) :: $(tail -1 "$L") :: FAILS=$(grep -c '^FAIL' "$L")" | tee -a "$SUM"
  grep -h '^FAIL' "$L" | head -8 | cut -c1-400 | tee -a "$SUM"
}
one() { bash run_check.sh "$1" "$2" >/dev/null 2>&1; line "$1" "$2"; }
echo "== F1 repro: PF1 accepted stage-2 image ($S2IMG) vs PF2 under test ($IMG)" | tee -a "$SUM"
bash run_multi.sh repro_expired_future.py r3a "$S2IMG" "$IMG" >/dev/null 2>&1; line repro_expired_future.py r3a
grep -h -E "^stage-" "$LOGS/repro_expired_future.runr3a.log" | tee -a "$SUM"
for n in r3a r3b r3c; do one t3_holds.py $n; done
one t3_seedholds.py r3a
for n in r3a r3b; do one t3_time.py $n; done
for n in r3a r3b; do one t3_corr.py $n; done
one t3_fixture.py r3a
one t3_misc.py r3a
one t3_settle.py r3a
for s in 7 21 45; do ARGS=$s bash run_check.sh t3_statement.py r3seed$s >/dev/null 2>&1; line t3_statement.py r3seed$s; done
for s in 11 21 45; do ARGS=$s bash run_check.sh t3_known.py r3seed$s >/dev/null 2>&1; line t3_known.py r3seed$s; done
one t3_snap.py r3a
bash run_multi.sh t3_import.py r3a "$S1IMG" "$S2IMG" "$IMG" "$IMG" "$IMG" >/dev/null 2>&1; line t3_import.py r3a
one t3_scale.py r3a
for n in r3a r3b r3c; do one t3_race.py $n; done
cd "$HERE/s2reg"
for S in s2_fixture s2_export s2_export_expiry; do
  if [ "$S" = s2_fixture ]; then bash run_check.sh $S.py r3a >/dev/null 2>&1; else SIMG=$IMG DIMG=$IMG bash run_check2.sh $S.py r3a >/dev/null 2>&1; fi
  L="$LOGS/$S.runr3a.log"; echo "$S r3a :: $(grep -E '^==' "$L" | tail -1) :: $(tail -1 "$L") :: FAILS=$(grep -c '^FAIL' "$L")" | tee -a "$SUM"; grep -h '^FAIL' "$L" | head -8 | cut -c1-400 | tee -a "$SUM"; done
echo "== ALL DONE" | tee -a "$SUM"
