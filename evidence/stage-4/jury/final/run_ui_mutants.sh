#!/bin/bash
# usage (WSL): run_ui_mutants.sh  -- builds one image per mutant (made by ui_mutants.py) and runs b7_stage4.py against it; a mutant is CAUGHT when b7 reports a FAIL.
HERE=$(cd "$(dirname "$0")" && pwd); OUT=/mnt/c/Users/lalwa/AppData/Local/Temp/s4jury/uimut
service docker start >/dev/null 2>&1
: > "$HERE/ui-mutation-check.txt"
for d in "$OUT"/m*; do
  n=$(basename "$d")
  (cd "$d" && docker build -q -t pf4-$n . >/dev/null 2>&1) || { echo "$n BUILD-FAILED" | tee -a "$HERE/ui-mutation-check.txt"; continue; }
  bash "$HERE/run_browser_s4.sh" b7_stage4.py "mut-$n" pf4-$n > /dev/null 2>&1
  L="$HERE/logs/b7_stage4.runmut-$n.log"
  F=$(grep -c "^FAIL" "$L"); P=$(grep -c "^PASS" "$L")
  if [ "$F" -gt 0 ]; then V=CAUGHT; else V=SURVIVED; fi
  echo "$V $n: pass=$P fail=$F :: $(grep -m2 '^FAIL' "$L" | cut -c1-210 | tr '\n' '|')" | tee -a "$HERE/ui-mutation-check.txt"
  docker rmi -f pf4-$n >/dev/null 2>&1
done
echo done | tee -a "$HERE/ui-mutation-check.txt"
