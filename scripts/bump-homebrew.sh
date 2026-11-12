#!/usr/bin/env bash
# Point the Homebrew cask (mammut001/homebrew-kanjo) at a published release.
# Usage: scripts/bump-homebrew.sh 0.5.1   (run after the DMG is uploaded to Release v0.5.1)
set -euo pipefail
version="${1:?usage: $0 <version>}"
dmg="https://github.com/mammut001/kanjo/releases/download/v${version}/Kanjo-${version}-macos.dmg"
sha=$(curl -fsSL "$dmg" | shasum -a 256 | cut -d' ' -f1)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
gh repo clone mammut001/homebrew-kanjo "$tmp/tap" -- -q
cask="$tmp/tap/Casks/kanjo.rb"
sed -i '' -E "s/^  version \".*\"/  version \"${version}\"/; s/^  sha256 \".*\"/  sha256 \"${sha}\"/" "$cask"
git -C "$tmp/tap" commit -qam "kanjo ${version}"
git -C "$tmp/tap" push -q
echo "cask updated: kanjo ${version} (${sha})"
