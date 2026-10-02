#!/bin/bash
# R3: browser regression of 5e6f83f (Playwright chromium in df-harness-runner, 375/768/1280) - sequential
HERE=$(cd "$(dirname "$0")" && pwd); cd "$HERE"
IMG=${IMG:-pocketful-s3-r3}; export I2=$IMG
for S in b1_quality b2_wallet b3_flows b5_visual b6_states; do
  bash run_browser.sh $S.py r3 $IMG > /dev/null 2>&1; echo "$S rc=$? :: $(grep -E '^== ' logs/$S.runr3.log | tail -1 | cut -c1-200)"; grep -h '^FAIL' logs/$S.runr3.log | head -5 | cut -c1-300
done
bash run_browser2.sh b4_upgrade.py r3 > /dev/null 2>&1; echo "b4_upgrade rc=$? :: $(grep -E '^== ' logs/b4_upgrade.runr3.log | tail -1 | cut -c1-200)"; grep -h '^FAIL' logs/b4_upgrade.runr3.log | head -5 | cut -c1-300
