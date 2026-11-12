#!/usr/bin/env bash
# Build the Windows release folder for one architecture (runs on macOS or Windows CI bash).
#
#   windows/scripts/build-release.sh <version> <rid>
#
# <version>  X.Y.Z (normally the repo VERSION file)
# <rid>      win-x64 | win-arm64
#
# Output: windows/dist/<rid>/   the folder Velopack packs (Kanjo.exe + .NET runtime + python\ + cli\)
#         windows/dist/Kanjo-<rid>-<version>.zip  the same folder zipped
#         windows/dist/releases/<rid>/            Setup.exe / nupkg / RELEASES (needs vpk)
#
# vpk is optional for macOS local builds: without it you still get the folder and the zip.
# When vpk is installed, a cross-pack failure is an error (vpk does support `[win] pack` on macOS);
# export KANJO_ALLOW_NO_INSTALLER=1 to accept the folder + zip instead.
#
# The Python + CLI bundle mirrors scripts/install-family-windows.ps1 (same official embeddable
# Python 3.12.8 archives, same SHA-256 pins) and the kanjo-cli.zip step in CI:
#   python\   official embeddable Python, `._pth` extended with `../cli` so `python.exe -m kanjo`
#             finds the CLI (the CLI is stdlib-only, so `import site` is not needed)
#   cli\      cli/kanjo (no __pycache__ / *.pyc) + cli/pricing.json + cli/pricing_overrides.json
set -euo pipefail

VERSION_ARG="${1:-}"
RID_ARG="${2:-}"

if [[ -z "$VERSION_ARG" || -z "$RID_ARG" ]]; then
  echo "usage: $0 <version> <rid>   (rid = win-x64 | win-arm64)" >&2
  exit 2
fi

VERSION="${VERSION_ARG#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "invalid version (expected X.Y.Z): $VERSION_ARG" >&2
  exit 2
fi
case "$RID_ARG" in
  win-x64) PY_ARCH="amd64" ;;
  win-arm64) PY_ARCH="arm64" ;;
  *) echo "invalid rid (expected win-x64 or win-arm64): $RID_ARG" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DIST="$REPO/windows/dist"
OUT="$DIST/$RID_ARG"
ICON="$REPO/windows/src/Kanjo.App/Assets/Kanjo.ico"

# Keep the app version and the CLI version in step: both read the repo VERSION file.
REPO_VERSION="$(tr -d '[:space:]' < "$REPO/VERSION")"
if [[ "$VERSION" != "$REPO_VERSION" ]]; then
  echo "warning: version $VERSION differs from VERSION ($REPO_VERSION)" >&2
fi

PY_URL="https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-$PY_ARCH.zip"
case "$PY_ARCH" in
  # Same pins as scripts/install-family-windows.ps1 (keep the two files in sync).
  arm64) PY_SHA256="D34DB37675973785A2A539CD1C8DDE1B6D45665F48C615EF55274B3798BF9FD3" ;;
  amd64) PY_SHA256="8D3F33BE9EB810F23C102F08475AF2854E50484B8E4E06275E937BE61CE3D2FB" ;;
esac

DOTNET="${DOTNET:-$HOME/.dotnet/dotnet}"
[[ -x "$DOTNET" ]] || DOTNET="dotnet"
command -v "$DOTNET" >/dev/null 2>&1 || { echo "dotnet not found" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl not found" >&2; exit 1; }
command -v unzip >/dev/null 2>&1 || { echo "unzip not found" >&2; exit 1; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else echo "no shasum / sha256sum" >&2; exit 1
  fi
}

echo "==> publish $RID_ARG (self-contained, ReadyToRun, single folder)"
rm -rf "$OUT"
mkdir -p "$OUT"
# Single folder, not single-file: Avalonia's native libraries (libSkiaSharp / Avalonia.Native /
# Avalonia.Win32) have to sit next to the exe. Not trimmed: Avalonia uses reflection and trimming
# is not supported there.
"$DOTNET" publish "$REPO/windows/src/Kanjo.App" \
  -c Release \
  -r "$RID_ARG" \
  --self-contained true \
  -p:Version="$VERSION" \
  -p:PublishSingleFile=false \
  -p:PublishReadyToRun=true \
  -p:PublishTrimmed=false \
  -o "$OUT"

# Debug symbols are not needed in the shipped folder (vpk would exclude them from the package anyway).
find "$OUT" -maxdepth 1 -name '*.pdb' -delete

echo "==> bundle python ($PY_ARCH, official embeddable 3.12.8)"
PY_DIR="$OUT/python"
TMP_ZIP="$(mktemp -t kanjo-python-embed)"
trap 'rm -f "$TMP_ZIP"' EXIT
curl -fsSL "$PY_URL" -o "$TMP_ZIP"
# macOS bash 3.2 has no ${var^^}: uppercase with tr.
ACTUAL="$(sha256_of "$TMP_ZIP" | tr '[:lower:]' '[:upper:]')"
EXPECTED="$(printf '%s' "$PY_SHA256" | tr '[:lower:]' '[:upper:]')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "python embeddable SHA-256 mismatch: expected $PY_SHA256, got $ACTUAL" >&2
  exit 1
fi
mkdir -p "$PY_DIR"
unzip -q -o "$TMP_ZIP" -d "$PY_DIR"
rm -f "$TMP_ZIP"
trap - EXIT

# `._pth` is read relative to python.exe: `../cli` puts <appdir>\cli on sys.path so
# `python.exe -m kanjo --version` works. `import site` stays commented out (not needed).
PTH="$(find "$PY_DIR" -maxdepth 1 -name 'python*._pth' | head -n 1)"
[[ -n "$PTH" ]] || { echo "no python*._pth in $PY_DIR" >&2; exit 1; }
if ! grep -qx '\.\./cli' "$PTH"; then
  printf '../cli\n' >> "$PTH"
fi

echo "==> bundle CLI"
CLI_DIR="$OUT/cli"
rm -rf "$CLI_DIR"
mkdir -p "$CLI_DIR/kanjo"
cp -R "$REPO/cli/kanjo/." "$CLI_DIR/kanjo/"
find "$CLI_DIR/kanjo" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$CLI_DIR/kanjo" -name '*.pyc' -delete 2>/dev/null || true
cp "$REPO/cli/pricing.json" "$REPO/cli/pricing_overrides.json" "$CLI_DIR/"
# Settings shows "Bundled CLI <version>" by reading cli/VERSION (same as the Mac bundle).
cp "$REPO/VERSION" "$CLI_DIR/VERSION"

echo "==> verify bundle layout"
for required in \
  "$OUT/Kanjo.exe" \
  "$PY_DIR/python.exe" \
  "$CLI_DIR/kanjo/__init__.py" \
  "$CLI_DIR/pricing.json" \
  "$CLI_DIR/pricing_overrides.json" \
  "$CLI_DIR/VERSION" \
  "$OUT/sample.json"; do
  [[ -f "$required" ]] || { echo "missing in bundle: $required" >&2; exit 1; }
done
grep -qx '\.\./cli' "$PTH" || { echo "$PTH does not list ../cli" >&2; exit 1; }
grep -qx 'import site' "$PTH" && echo "warning: $PTH enables 'import site' (not required)" >&2 || true

echo "==> zip folder"
ZIP="$DIST/Kanjo-$RID_ARG-$VERSION.zip"
rm -f "$ZIP"
(cd "$OUT" && zip -q -r "$ZIP" .)

# Velopack packing: vpk can cross-compile a Windows installer from macOS when the `[win]`
# directive is used (`vpk [win] pack ...`). Skip quietly when vpk is not installed.
VPK="$(command -v vpk || true)"
if [[ -n "$VPK" ]]; then
  echo "==> vpk pack ($RID_ARG)"
  REL="$DIST/releases/$RID_ARG"
  # Fresh output dir: vpk refuses to pack a version that already exists in the channel.
  rm -rf "$REL"
  # vpk needs the .NET runtime it was built against; ROLL_FORWARD lets it run on a newer one.
  VPK_ENV=(env DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}" DOTNET_ROLL_FORWARD=Major)
  # packId (KanjoApp) decides the install root %LOCALAPPDATA%\KanjoApp; it must differ from
  # the CLI's %LOCALAPPDATA%\kanjo (see windows/src/Kanjo.Core/AppPaths.cs). --packTitle sets
  # the Start Menu shortcut and Apps-list name back to "Kanjo".
  if "${VPK_ENV[@]}" vpk '[win]' pack \
      --packId KanjoApp \
      --packTitle Kanjo \
      --packVersion "$VERSION" \
      --packDir "$OUT" \
      --mainExe Kanjo.exe \
      --icon "$ICON" \
      --runtime "$RID_ARG" \
      --channel "$RID_ARG" \
      --outputDir "$REL" \
      --noPortable \
      --shortcuts "StartMenuRoot"; then
    echo "installer written to $REL"
  else
    # Cross-packing is known to work on macOS (`vpk [win] pack`); a failure here is a real error.
    # Set KANJO_ALLOW_NO_INSTALLER=1 to accept the folder + zip only.
    if [[ "${KANJO_ALLOW_NO_INSTALLER:-0}" == "1" ]]; then
      echo "warning: vpk cross-pack failed; keeping the folder and zip only" >&2
    else
      echo "error: vpk cross-pack failed (set KANJO_ALLOW_NO_INSTALLER=1 to skip the installer)" >&2
      exit 1
    fi
  fi
else
  echo "==> vpk not installed, skipping installer (dotnet tool install -g vpk --version 1.2.158)"
fi

echo
echo "release folder: $OUT ($(du -sh "$OUT" | cut -f1))"
echo "zip:            $ZIP ($(du -h "$ZIP" | cut -f1))"
