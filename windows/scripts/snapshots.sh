#!/usr/bin/env bash
# 生成 windows/snapshots/ 下的全部离屏截图（light；overview / project:0 / disk / settings 另出 dark）。
# 用法：windows/scripts/snapshots.sh [dotnet]（默认 $HOME/.dotnet/dotnet，不存在则用 PATH 上的 dotnet）
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
dotnet="${1:-$HOME/.dotnet/dotnet}"
[ -x "$dotnet" ] || dotnet="dotnet"

data="$repo/ui/fixtures/sample.json"
disk="$repo/ui/fixtures/disk-sample.json"
out="$repo/windows/snapshots"
mkdir -p "$out"

shoot() { # <route> <file> <appearance>
  "$dotnet" run --project "$repo/windows/src/Kanjo.App" --no-build -- \
    --snapshot "$out/$2" --route "$1" --snapshot-appearance "$3" \
    --data "$data" --disk-data "$disk"
}

routes=(
  "overview|overview-light.png"
  "overview-bottom|overview-bottom-light.png"
  "project:0|project-0-light.png"
  "project:0:bottom|project-0-bottom-light.png"
  "project:0:locations|project-0-locations-light.png"
  "project:0:hover:tokens|project-0-hover-tokens-light.png"
  "project:0:hover:model:1|project-0-hover-model-light.png"
  "project:0:hover:branch:0|project-0-hover-branch-light.png"
  "project:0:hover:day|project-0-hover-day-light.png"
  "project:0:hover:session:0|project-0-hover-session-light.png"
  "bucket:unattributed|bucket-unattributed-light.png"
  "bucket:excluded|bucket-excluded-light.png"
  "disk|disk-light.png"
  "disk:expanded|disk-expanded-light.png"
  "settings|settings-light.png"
  "settings-bottom|settings-bottom-light.png"
  "settings:subscriptions:codex|settings-subscriptions-codex-light.png"
  "settings:subscriptions:codex:edit|settings-subscriptions-codex-edit-light.png"
  "loading|loading-light.png"
  "overview:quota:claude|overview-quota-claude-light.png"
  "overview:tile:0|overview-tile-0-light.png"
  "overview:hover:legend|overview-hover-legend-light.png"
  "overview:hover:heat:0:5|overview-hover-heat-light.png"
  "overview:hover:dots:0|overview-hover-dots-light.png"
  "overview:hover:model:0|overview-hover-model-light.png"
)

for entry in "${routes[@]}"; do
  shoot "${entry%%|*}" "${entry##*|}" light
done

for entry in "overview|overview-dark.png" "project:0|project-0-dark.png" \
             "disk|disk-dark.png" "settings|settings-dark.png"; do
  shoot "${entry%%|*}" "${entry##*|}" dark
done

echo "snapshots written to $out"
