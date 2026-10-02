#!/bin/bash
HERE=$(cd "$(dirname "$0")" && pwd); cd "$HERE"
for S in b1_quality b2_wallet b3_flows b5_visual b6_states; do
  bash run_browser.sh $S.py 1 pocketful-s3-jury > /dev/null 2>&1; echo "$S rc=$? :: $(grep -E '^== ' logs/$S.run1.log | tail -1 | cut -c1-200)"; grep -h '^FAIL' logs/$S.run1.log | head -5 | cut -c1-300
done
bash run_browser2.sh b4_upgrade.py 1 > /dev/null 2>&1; echo "b4_upgrade rc=$? :: $(grep -E '^== ' logs/b4_upgrade.run1.log | tail -1 | cut -c1-200)"; grep -h '^FAIL' logs/b4_upgrade.run1.log | head -5 | cut -c1-300
