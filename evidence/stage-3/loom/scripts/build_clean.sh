#!/bin/bash
# usage: build_clean.sh <commit>  -- export the commit tree, build stage-3/2/1 images with no cache and no network
set -u
COMMIT=${1:?commit}
SHORT=${COMMIT:0:7}
REPO=/mnt/d/project/dolphin-tank/band-work/result
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
W=/tmp/clean-$SHORT
rm -rf "$W" && mkdir -p "$W"
git -c safe.directory='*' -C "$REPO" archive --format=tar "$COMMIT" stage-1 stage-2 stage-3 | tar -x -C "$W"
echo "exported $COMMIT -> $W ($(ls "$W"/stage-3 | wc -l) stage-3 entries)"
for s in 3 2 1; do
  echo "=== docker build --no-cache --network none stage-$s ==="
  docker build --no-cache --network none -t pocketful-s$s-$SHORT "$W/stage-$s" 2>&1 | tail -12
  echo "build stage-$s rc=${PIPESTATUS[0]}"
done
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep "$SHORT"
