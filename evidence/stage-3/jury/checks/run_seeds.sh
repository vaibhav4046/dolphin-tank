#!/bin/bash
cd "$(dirname "$0")"
for S in 21 45; do
  for SC in t3_statement.py t3_known.py; do
    ARGS=$S bash run_check.sh $SC seed$S 2>&1 | grep -E "^(seed|FAIL|==|rc=)"
  done
done
