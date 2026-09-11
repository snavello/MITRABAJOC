#!/bin/bash
# Corre CADA test_*.py en su propio proceso pytest (los módulos comparten
# estado de import y se contaminan si corren batcheados -- ver CLAUDE.md).
#
# El chequeo mira "failed"/"error" y NO "passed": un archivo con "13 failed,
# 1 passed" contiene la palabra "passed" y un patrón ingenuo lo daba por OK.
LOG="${1:-suite.log}"
: > "$LOG"
for f in test_*.py; do
  out=$(python -m pytest "$f" -q 2>&1 | tail -1)
  if echo "$out" | grep -qiE "failed|error"; then
    echo "FALLA $f  ($out)" >> "$LOG"
  else
    echo "ok    $f  ($out)" >> "$LOG"
  fi
done
echo "FIN $(grep -c . "$LOG") archivos, fallas: $(grep -c '^FALLA' "$LOG")" >> "$LOG"
grep '^FALLA' "$LOG" || echo "sin fallas"
