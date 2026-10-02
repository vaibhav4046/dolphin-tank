#!/bin/bash
# split docker-run overhead from process startup: StartedAt (container process start) -> first /health 200
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
for i in 1 2 3 4 5; do
  docker rm -f pfs >/dev/null 2>&1
  docker run -d --name pfs -e PORT=8080 -p 8080:8080 pocketful-s3 >/dev/null
  until curl -sf http://127.0.0.1:8080/health >/dev/null; do sleep 0.005; done
  now=$(date +%s%N)
  st=$(docker inspect -f '{{.State.StartedAt}}' pfs)
  stn=$(date -d "$st" +%s%N)
  echo "process_start->health_ms=$(( (now-stn)/1000000 ))"
  docker rm -f pfs >/dev/null 2>&1
done
