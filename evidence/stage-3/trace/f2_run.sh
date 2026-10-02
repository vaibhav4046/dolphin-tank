#!/bin/bash
# usage: f2_run.sh <port> <script-path> [exe]   -- fresh server on <port>, run python script against it, kill server by PID
PORT=$1; SCRIPT=$2; EXE=${3:-/tmp/f2bin/s3-ac96360.exe}
PORT=$PORT "$EXE" >/tmp/f2bin/server-$PORT.log 2>&1 &
SP=$!
for i in $(seq 1 100); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.1; done
cd "$(dirname "$SCRIPT")"
PF=127.0.0.1:$PORT PFD=127.0.0.1:$PORT uv run python -u "$(basename "$SCRIPT")" ${ARGS:-}
RC=$?
kill $SP 2>/dev/null
echo "rc=$RC"
exit $RC
