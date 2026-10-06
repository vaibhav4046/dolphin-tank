#!/usr/bin/env bash
set -euo pipefail
# Run from the official dark-factory-wearedevs checkout, in its prepared venv.
# Argument is the owner-approved frozen Git revision, not a branch name.
rev=${1:?Provide full frozen commit SHA}
root=$(mktemp -d)
GIT_TERMINAL_PROMPT=0 git clone https://github.com/vaibhav4046/dolphin-tank.git "$root/result"
git -C "$root/result" checkout --detach "$rev"
test "$(git -C "$root/result" rev-parse HEAD)" = "$rev"
git -C "$root/result" status --porcelain
sha256sum "$root/result/room.json" | tee "$root/room-sha256.txt"
python -m harness check "$root/result" --track pocketful | tee "$root/check.log"
python -m harness run --track pocketful --repo "$root/result" --all --mode isolated --out "$root/isolated" | tee "$root/run.log"
printf 'Inspect report.json, each stage claim, overshoot, errors/skips and logs before marking verified. Evidence directory: %s\n' "$root"
