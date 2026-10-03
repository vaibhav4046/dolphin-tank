#!/bin/bash
# B11 + image hygiene on the stage-4 image built from the clean worktree at 1dd5560 (RUN.md commands).
# usage (inside WSL): bash run_b11.sh      env: SRC (build context), IMG
set -u
SRC=${SRC:-/mnt/c/Users/lalwa/AppData/Local/Temp/s4jury/wt-batch/stage-4}
IMG=${IMG:-pocketful-s4-jury}
EV=/mnt/d/project/dolphin-tank/band-work/result/evidence/stage-4/jury/final
service docker start >/dev/null 2>&1
echo "== docker build -t $IMG . (RUN.md), context $SRC"
(cd "$SRC" && docker build -t "$IMG" . 2>&1 | tail -4)
echo "== docker build --no-cache --network none (base image cached locally; go.mod has no external requires)"
grep -c "^require" "$SRC/go.mod" | sed 's/^/go.mod require lines: /'
(cd "$SRC" && docker build --no-cache --network none -t "$IMG-nonet" . 2>&1 | tail -3)
echo "== image config"
docker inspect --format 'user={{.Config.User}} entrypoint={{.Config.Entrypoint}} port={{.Config.ExposedPorts}} env={{.Config.Env}}' "$IMG"
docker image ls "$IMG" --format 'size={{.Size}}'
echo "== image file list (scratch: expect only the binary)"
docker rm -f pf4-ls >/dev/null 2>&1; docker create --name pf4-ls "$IMG" >/dev/null
docker export pf4-ls | tar -t | tee "$EV/image-files.txt" | head -20
docker rm pf4-ls >/dev/null
echo "files matching .git*/.claude*/*.log in image: $(grep -c -E '(^|/)\.git|(^|/)\.claude|\.log$' "$EV/image-files.txt")"
echo "== docker run --network none"
docker rm -f pf4-none >/dev/null 2>&1
docker run -d --network none --name pf4-none "$IMG" >/dev/null
docker inspect --format 'networkmode={{.HostConfig.NetworkMode}} running={{.State.Running}}' pf4-none
docker run --rm --network container:pf4-none -v "$EV":/p --entrypoint python3 df-harness-runner -u /p/b11_probe.py
RC=$?
echo "probe rc=$RC"
docker logs pf4-none 2>&1 | tail -3
docker rm -f pf4-none >/dev/null
echo "== RUN.md run command exactly: docker run --rm -e PORT=8080 -p 8080:8080 $IMG"
docker rm -f pf4-runmd >/dev/null 2>&1
docker run --rm -d -e PORT=8080 -p 8080:8080 --name pf4-runmd "$IMG" >/dev/null
for i in $(seq 1 100); do curl -sf http://127.0.0.1:8080/health && break; sleep 0.2; done; echo
curl -s -o /dev/null -w "GET / (Accept text/html) -> %{http_code} %{content_type}\n" -H 'Accept: text/html' http://127.0.0.1:8080/
curl -s -w "\nGET /requests (no Accept, no token) -> %{http_code}\n" http://127.0.0.1:8080/requests
docker rm -f pf4-runmd >/dev/null
exit $RC
