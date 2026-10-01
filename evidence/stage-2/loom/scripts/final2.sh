#!/bin/bash
# full evidence run against a clean clone: image build, image size, startup, offline serving, browser smoke, real stage-1 -> stage-2 upgrade
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
D=/mnt/d/project/dolphin-tank/band-work/scratch/s2-loom
CLONE=$D/clone
echo "== commit $(git -C $CLONE rev-parse HEAD)"
echo "== docker build (clean clone)"
docker build -t pocketful-s2 $CLONE/stage-2 2>&1 | tail -4
docker images pocketful-s2 --format 'image {{.Repository}}:{{.Tag}} {{.Size}}'
echo "== startup"
bash $D/startup.sh
bash $D/startup2.sh
echo "== offline"
bash $D/offline.sh
echo "== browser smoke"
bash $D/run2.sh pocketful-s2 ui_smoke.py 2>&1 | tee $D/smoke.log | grep -E "FAIL|checks passed"
echo "== real stage-1 export -> stage-2 import"
bash $D/run2.sh pocketful-s2 upgrade_real.py 2>&1 | tee $D/upgrade.log
