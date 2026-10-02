#!/bin/bash
# startup time: `docker run -d` -> first /health 200, 5 runs each for stage-2 and the accepted stage-1 baseline image
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
measure() {
  img=$1
  docker rm -f pfs >/dev/null 2>&1
  start=$(date +%s%N)
  docker run -d --name pfs -e PORT=8080 -p 8080:8080 "$img" >/dev/null
  until curl -sf http://127.0.0.1:8080/health >/dev/null; do sleep 0.02; done
  end=$(date +%s%N)
  started=$(docker inspect -f '{{.State.StartedAt}}' pfs)
  echo "$img run->health_ms=$(( (end-start)/1000000 ))"
  docker rm -f pfs >/dev/null 2>&1
}
for i in 1 2 3 4 5; do measure pocketful-s3; done
for i in 1 2 3; do measure pocketful-s1; done
