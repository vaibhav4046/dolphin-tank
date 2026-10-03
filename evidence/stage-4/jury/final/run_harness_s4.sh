#!/bin/bash
# Shipped harness over every stage folder of the tree at 1dd5560 (isolated mode: build with network, run with none).
# usage (inside WSL): bash run_harness_s4.sh <tarball of the commit>
set -u
TAR=${1:-/mnt/c/Users/lalwa/AppData/Local/Temp/s4jury/s4-1dd5560.tar}
EV=/mnt/d/project/dolphin-tank/band-work/result/evidence/stage-4/jury/final
service docker start >/dev/null 2>&1
rm -rf /root/jury/s4r1 && mkdir -p /root/jury/s4r1 && tar -xf "$TAR" -C /root/jury/s4r1
ls /root/jury/s4r1
rm -rf "$EV/harness-s4"
cd /mnt/d/project/dolphin-tank/dark-factory-wearedevs && . /root/dfv/bin/activate
python -m harness run --track pocketful --repo /root/jury/s4r1 --all --mode isolated --out "$EV/harness-s4" > "$EV/harness-s4.console.txt" 2>&1
echo "exit $?" >> "$EV/harness-s4.console.txt"
tail -25 "$EV/harness-s4.console.txt"
