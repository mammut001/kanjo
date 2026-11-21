#!/usr/bin/env bash
# End-to-end contract smoke: CLI fixture export → Mac / Windows / iOS decode.
# Windows-and-Mac agnostic (bash; Git Bash on Windows works for CLI + Windows app).
#
# Never reads real agent logs: every KANJO_*_DIR points at cli/tests/fixtures,
# and KANJO_DATA_DIR / CACHE / CONFIG are throwaway temp dirs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$ROOT/cli"
FIXTURES="$CLI/tests/fixtures"
OS="$(uname -s 2>/dev/null || echo unknown)"

export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"
export PATH="$DOTNET_ROOT:$DOTNET_ROOT/tools:${PATH:-}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kanjo-e2e.XXXXXX")"
DATA="$WORK/data"
CACHE="$WORK/cache"
CONFIG="$WORK/config"
TRASH="$WORK/trash"
SCRATCH="$WORK/scratch"
REPORT="$WORK/report.json"
MOBILE="$WORK/mobile.json"
DISK="$WORK/disk.json"
PNG_DIR="$WORK/png"
DEFAULTS_SUITE="kanjo-e2e-$$"
mkdir -p "$DATA" "$CACHE" "$CONFIG" "$TRASH" "$SCRATCH" "$PNG_DIR"

cleanup() {
  if [[ "$OS" == Darwin ]]; then
    defaults delete "$DEFAULTS_SUITE" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# Point every agent log root at fixtures; isolate Kanjo's own dirs in $WORK.
export KANJO_NO_NETWORK=1
export KANJO_DATA_DIR="$DATA"
export KANJO_CACHE_DIR="$CACHE"
export KANJO_CONFIG_DIR="$CONFIG"
export KANJO_TRASH_DIR="$TRASH"
export KANJO_SCRATCH_DIR="$SCRATCH"
export KANJO_TOKEI_DIR="$FIXTURES/no-tokei"
export KANJO_CLAUDE_APP_CACHE="$WORK/claude-app"
export KANJO_CLAUDE_CONFIG="$WORK/no-claude.json"
export KANJO_CODEX_AUTH="$WORK/no-codex-auth.json"
export KANJO_GROK_AUTH="$WORK/no-grok-auth.json"
mkdir -p "$KANJO_CLAUDE_APP_CACHE"

# pathsep: ; on Windows, : elsewhere (Git Bash reports MINGW*/MSYS*)
case "$OS" in
  MINGW*|MSYS*|CYGWIN*|Windows_NT) PATHSEP=';' ;;
  *) PATHSEP=':' ;;
esac

export KANJO_CLAUDE_DIR="$FIXTURES/claude"
export KANJO_ANTIGRAVITY_DIR="$FIXTURES/antigravity"
export KANJO_CODEX_DIR="$FIXTURES/codex"
export KANJO_GROK_DIR="$FIXTURES/grok"
export KANJO_QWEN_DIR="$FIXTURES/qwen"
export KANJO_COMMANDCODE_DIR="$FIXTURES/commandcode"
export KANJO_MINIMAX_DIR="$FIXTURES/minimax"
export KANJO_OPENCODE_DIR="$FIXTURES/opencode"
export KANJO_COPILOT_DIR="${FIXTURES}/copilot${PATHSEP}${FIXTURES}/copilot_db"
export KANJO_PI_DIR="$FIXTURES/pi"
export KANJO_WORKBUDDY_DIR="$FIXTURES/workbuddy"
export KANJO_WORKBUDDY_AI_DIR="$FIXTURES/workbuddy_ai"
export KANJO_CODEBUDDY_DIR="$FIXTURES/codebuddy"
export KANJO_QWENWORK_DIR="$FIXTURES/qwenwork"
export KANJO_GROK_BOT_DIR="$FIXTURES/grok_bot"
export KANJO_QODERWORK_DIR="$FIXTURES/qoderwork"
export KANJO_QODERCLI_DIR="$FIXTURES/qodercli"
export KANJO_QODERCLI_CN_DIR="$FIXTURES/qodercli_cn"
export KANJO_ZCODE_DIR="$FIXTURES/zcode"
export KANJO_KIMICODE_DIR="$FIXTURES/kimicode"
export KANJO_MUSECODE_DIR="$FIXTURES/musecode"
export KANJO_QODER_IDE_DIR="$FIXTURES/qoder_ide"
export KANJO_HERMES_DIR="$FIXTURES/hermes"
export KANJO_OPENCLAW_DIR="$FIXTURES/openclaw"
export KANJO_DEVIN_DIR="$FIXTURES/devin"
export KANJO_MIMOCODE_DIR="$FIXTURES/mimocode"
export KANJO_PRIME_AGENT_DIR="$FIXTURES/prime_agent"
export KANJO_OMP_DIR="$FIXTURES/omp"
export KANJO_DEEPSEEK_HARNESS_DIR="$FIXTURES/deepseek_harness"

fail=0
pass() { printf 'PASS  %s\n' "$1"; }
fail_msg() { printf 'FAIL  %s\n' "$1"; fail=1; }

echo "Kanjo e2e smoke"
echo "  worktree : $ROOT"
echo "  work dir : $WORK"
echo "  os       : $OS"
echo

# --- 1. CLI exports -----------------------------------------------------------
echo "== CLI export =="
if (cd "$CLI" && python3 -m kanjo export -o "$REPORT"); then
  pass "kanjo export → report.json"
else
  fail_msg "kanjo export"
fi

if (cd "$CLI" && python3 -m kanjo export --mobile -o "$MOBILE"); then
  pass "kanjo export --mobile → mobile.json"
else
  fail_msg "kanjo export --mobile"
fi

if (cd "$CLI" && python3 -m kanjo disk --json >"$DISK"); then
  pass "kanjo disk --json → disk.json"
else
  fail_msg "kanjo disk --json"
fi

for f in "$REPORT" "$MOBILE" "$DISK"; do
  if [[ -s "$f" ]] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f"; then
    pass "JSON parse $(basename "$f")"
  else
    fail_msg "JSON parse $(basename "$f")"
  fi
done

ROUTES=(overview agents disk project:0 settings)

# --- 2. Mac snapshots ---------------------------------------------------------
if [[ "$OS" == Darwin ]]; then
  echo
  echo "== Mac snapshots =="
  if (cd "$ROOT/ui" && swift build --product Kanjo -c debug); then
    MAC_BIN="$ROOT/ui/.build/debug/Kanjo"
    if [[ ! -x "$MAC_BIN" ]]; then
      MAC_BIN="$(cd "$ROOT/ui" && swift build --product Kanjo -c debug --show-bin-path)/Kanjo"
    fi
    for route in "${ROUTES[@]}"; do
      safe="${route//[:\/]/_}"
      out="$PNG_DIR/mac-${safe}.png"
      if "$MAC_BIN" \
          --snapshot "$out" \
          --route "$route" \
          --data "$REPORT" \
          --disk-data "$DISK" \
          --defaults-suite "$DEFAULTS_SUITE"; then
        pass "Mac --route $route"
      else
        fail_msg "Mac --route $route"
      fi
    done
  else
    fail_msg "swift build Kanjo"
  fi
else
  echo
  echo "== Mac snapshots =="
  pass "skipped (not Darwin)"
fi

# --- 3. Windows snapshots (dotnet; headless Avalonia works on macOS too) ------
echo
echo "== Windows snapshots =="
if command -v dotnet >/dev/null 2>&1; then
  if (cd "$ROOT" && dotnet build windows/src/Kanjo.App/Kanjo.App.csproj -c Debug -v q); then
    for route in "${ROUTES[@]}"; do
      safe="${route//[:\/]/_}"
      out="$PNG_DIR/win-${safe}.png"
      if (cd "$ROOT" && dotnet run --project windows/src/Kanjo.App --no-build -c Debug -- \
          --snapshot "$out" \
          --route "$route" \
          --data "$REPORT" \
          --disk-data "$DISK"); then
        pass "Windows --route $route"
      else
        fail_msg "Windows --route $route"
      fi
    done
  else
    fail_msg "dotnet build Kanjo.App"
  fi
else
  fail_msg "dotnet not on PATH"
fi

# --- 4. iOS / KanjoCore mobile decode ----------------------------------------
echo
echo "== Mobile decode =="
export KANJO_E2E_MOBILE_JSON="$MOBILE"

if [[ "$OS" == Darwin ]]; then
  # KanjoCore (shared decoder) via SwiftPM
  if (cd "$ROOT/ui" && swift test --filter MobileExportE2E); then
    pass "KanjoCore MobileExportE2E (swift test)"
  else
    fail_msg "KanjoCore MobileExportE2E (swift test)"
  fi

  # iOS XCTest on the dedicated simulator (SIMCTL_CHILD_* reaches the test host)
  SIM="FB349C43-7936-4A34-872B-BF9EDEEB9096"
  if command -v xcodegen >/dev/null 2>&1; then
    (cd "$ROOT/ios" && xcodegen generate >/dev/null)
  fi
  export SIMCTL_CHILD_KANJO_E2E_MOBILE_JSON="$MOBILE"
  if (cd "$ROOT/ios" && \
      env KANJO_E2E_MOBILE_JSON="$MOBILE" \
          SIMCTL_CHILD_KANJO_E2E_MOBILE_JSON="$MOBILE" \
      xcodebuild test \
        -project Kanjo.xcodeproj \
        -scheme Kanjo \
        -destination "platform=iOS Simulator,id=$SIM" \
        -only-testing:KanjoTests/MobileExportDecodeTests \
        -quiet); then
    pass "iOS MobileExportDecodeTests (simulator $SIM)"
  else
    fail_msg "iOS MobileExportDecodeTests (simulator $SIM)"
  fi
else
  pass "iOS/KanjoCore mobile decode skipped (not Darwin)"
fi

echo
if [[ "$fail" -ne 0 ]]; then
  echo "E2E smoke FAILED"
  exit 1
fi
echo "E2E smoke OK"
exit 0
