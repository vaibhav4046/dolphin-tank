#!/bin/bash
# usage: bash evidence/stage-3/trace/rl1_jury_run.sh > evidence/stage-3/trace/rl1-jury-checks.txt
# jury scripts that touch import/holds, against /tmp/rl1bin/s3-5e6f83f.exe (git archive 5e6f83f stage-3 -> go build); one fresh server per script, run sequentially.
EXE=/tmp/rl1bin/s3-5e6f83f.exe
R=evidence/stage-3
run() { # label port script
  echo "=== $1 (HEAD 5e6f83f) :: bash evidence/stage-3/trace/f2_run.sh $2 $3 $EXE"
  bash evidence/stage-3/trace/f2_run.sh "$2" "$3" "$EXE" 2>&1
}
for i in 1 2 3; do run "t3_holds.py run $i" 18310 $R/jury/checks/t3_holds.py; done
run t3_seedholds.py 18311 $R/jury/checks/t3_seedholds.py
run t3_time.py 18311 $R/jury/checks/t3_time.py
run t3_corr.py 18311 $R/jury/checks/t3_corr.py
run s2_fixture.py 18312 $R/jury/s2reg/s2_fixture.py
run s2_export.py 18312 $R/jury/s2reg/s2_export.py
run s2_export_expiry.py 18313 $R/jury/s2reg/s2_export_expiry.py
