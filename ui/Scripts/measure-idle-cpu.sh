#!/usr/bin/env bash
# Sample Kanjo idle CPU with fixtures (no real user data). Usage: measure-idle-cpu.sh [seconds]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.build/debug/Kanjo"
DATA="$ROOT/fixtures/sample.json"
SUITE="kanjo-goal-energy"
SECS="${1:-30}"

if [[ ! -x "$BIN" ]]; then
  echo "Building Kanjo…" >&2
  (cd "$ROOT" && swift build)
fi

# Launch detached; leave panel closed for idle sampling.
"$BIN" --window --data "$DATA" --defaults-suite "$SUITE" >/dev/null 2>&1 &
PID=$!
cleanup() { kill -TERM "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }
trap cleanup EXIT

sleep 5
echo "Sampling PID $PID for ${SECS}s (panel should stay closed)…"
samples="$(top -l "$SECS" -pid "$PID" -stats pid,command,cpu 2>/dev/null | grep -E '^[0-9]+' || true)"
if [[ -z "$samples" ]]; then
  echo "No CPU samples (is Kanjo still running?)"
else
  mean="$(echo "$samples" | awk '{gsub(/%/,"",$NF); sum+=$NF; n++} END {if (n) printf "%.2f", sum/n; else print "n/a"}')"
  count="$(echo "$samples" | wc -l | tr -d ' ')"
  echo "Kanjo mean CPU% over $count samples: $mean"
fi