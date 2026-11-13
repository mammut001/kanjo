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

shoot() { # <route> <file> <appearance> [update-state]
  "$dotnet" run --project "$repo/windows/src/Kanjo.App" --no-build -- \
    --snapshot "$out/$2" --route "$1" --snapshot-appearance "$3" \
    ${4:+--snapshot-update "$4"} \
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
             "disk|disk-dark.png" "settings|settings-dark.png" \
             "settings:subscriptions:codex|settings-subscriptions-codex-dark.png"; do
  shoot "${entry%%|*}" "${entry##*|}" dark
done

# 更新横幅 / 设置页 Updates 卡片：注入假的更新状态（只有 --snapshot 才有这条路），明暗各一张。
shoot "overview" "update-banner-ready-light.png" light ready
shoot "overview" "update-banner-ready-dark.png" dark ready
shoot "overview" "update-banner-downloading-light.png" light downloading
shoot "settings" "settings-update-ready-light.png" light ready
shoot "settings" "settings-update-ready-dark.png" dark ready
shoot "settings" "settings-update-downloading-light.png" light downloading
shoot "settings" "settings-update-not-installed-light.png" light not-installed

echo "snapshots written to $out"
