#!/usr/bin/env bash
# Job control gives each server (and its workers) a separate process group.
set -em
servers=()
cleanup() {
  for pid in "${servers[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/python -m uvicorn api.main:app --port 8000 --reload --reload-dir api --reload-dir judge &
servers+=("$!")
npm --prefix web run dev -- --port 3000 &
servers+=("$!")
wait -n
