#!/bin/bash
# 构建内置 CLI 的通用 Kanjo.app、zip 和 DMG，产物留在 build/。
# 只用 SwiftPM + 系统自带工具（iconutil / sips / codesign / ditto），不需要 Xcode 工程。
#
# 用法：./package.sh [version] [--icon] [--no-dmg] [--arch arm64|x86_64]
#   version  默认读仓库顶层的 VERSION 文件
#   --icon   重新生成 Resources/Kanjo.png 和 Kanjo.icns（缺失时也会自动生成）
set -euo pipefail
cd "$(dirname "$0")"

VERSION=""
REGEN_ICON=0
ARCHS=(arm64 x86_64)
MAKE_DMG=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --icon) REGEN_ICON=1 ;;
        --no-dmg) MAKE_DMG=0 ;;
        --arch)
            shift
            case "${1:-}" in arm64|x86_64) ARCHS=("$1") ;; *) echo "expected arm64 or x86_64" >&2; exit 1 ;; esac ;;
        -h|--help) echo "Usage: ./package.sh [version] [--icon] [--no-dmg] [--arch arm64|x86_64]"; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 1 ;;
        *) VERSION="$1" ;;
    esac
    shift
done
if [[ -z "$VERSION" ]]; then
    [[ -f ../VERSION ]] || { echo "no version given and ../VERSION not found" >&2; exit 1; }
    VERSION="$(tr -d '[:space:]' < ../VERSION)"
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "invalid version (expected X.Y.Z): $VERSION" >&2
    exit 1
fi

APP_NAME="Kanjo"
BUNDLE_ID="com.lanshuagent.kanjo"
BUILD_DIR="build"
APP="$BUILD_DIR/$APP_NAME.app"
ZIP="$BUILD_DIR/$APP_NAME-$VERSION-macos.zip"
ICON_PNG="Resources/$APP_NAME.png"
ICNS="Resources/$APP_NAME.icns"

# 图标：PNG 和 icns 都提交在 Resources/ 里，平时直接用；缺失或 --icon 时重新生成。
if [[ "$REGEN_ICON" == 1 || ! -f "$ICON_PNG" ]]; then
    echo "==> rendering $ICON_PNG"
    swift Resources/make_icon.swift "$ICON_PNG"
fi
if [[ "$REGEN_ICON" == 1 || ! -f "$ICNS" || "$ICON_PNG" -nt "$ICNS" ]]; then
    echo "==> building $ICNS"
    mkdir -p "$BUILD_DIR"
    ICONSET_DIR="$(mktemp -d "$BUILD_DIR/icon.XXXXXX")"
    trap 'rm -rf "$ICONSET_DIR"' EXIT
    ICONSET="$ICONSET_DIR/$APP_NAME.iconset"
    mkdir "$ICONSET"
    for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns -o "$ICNS" "$ICONSET"
fi

mkdir -p "$BUILD_DIR"
SWIFT_FLAGS=(--cache-path "$BUILD_DIR/cache" --config-path "$BUILD_DIR/config" --security-path "$BUILD_DIR/security")
SLICES=()
for arch in "${ARCHS[@]}"; do
    swift build --scratch-path "$BUILD_DIR/swiftpm-$arch" "${SWIFT_FLAGS[@]}" -c release --arch "$arch" --product "$APP_NAME"
    SLICES+=("$(swift build --scratch-path "$BUILD_DIR/swiftpm-$arch" "${SWIFT_FLAGS[@]}" -c release --arch "$arch" --show-bin-path)/$APP_NAME")
done

echo "==> assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
lipo -create "${SLICES[@]}" -output "$APP/Contents/MacOS/$APP_NAME"
for arch in "${ARCHS[@]}"; do
    lipo "$APP/Contents/MacOS/$APP_NAME" -verify_arch "$arch"
done
CLI="$APP/Contents/Resources/cli"
mkdir -p "$CLI"
cp -R ../cli/kanjo "$CLI/kanjo"
find "$CLI" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$CLI" -name '*.pyc' -delete
cp ../cli/pricing.json ../cli/pricing_overrides.json ../VERSION "$CLI/"
chmod 755 "$APP/Contents/MacOS/$APP_NAME"
cp "$ICNS" "$APP/Contents/Resources/"
# 示例数据：没装 CLI 时退回到它（DefaultPaths.sampleFixture 会在 .app 里找 sample.json）。
cp fixtures/sample.json "$APP/Contents/Resources/sample.json"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
    <key>CFBundleExecutable</key><string>${APP_NAME}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>CFBundleIconFile</key><string>${APP_NAME}</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null

IDENTITY="${KANJO_CODESIGN_IDENTITY:-}"
if [[ -z "$IDENTITY" ]]; then
    IDENTITIES="$(security find-identity -v -p codesigning 2>/dev/null || true)"
    IDENTITY="$(echo "$IDENTITIES" | sed -nE 's/^[[:space:]]*[0-9]+\) [0-9A-F]+ "(Developer ID Application[^"]+)".*/\1/p' | head -n 1)"
    IDENTITY="${IDENTITY:--}"
fi
SIGN_FLAGS=(--force --sign "$IDENTITY")
if [[ "$IDENTITY" != - ]]; then
    SIGN_FLAGS+=(--options runtime --timestamp)
fi
xattr -cr "$APP"
codesign "${SIGN_FLAGS[@]}" "$APP/Contents/MacOS/$APP_NAME"
codesign "${SIGN_FLAGS[@]}" "$APP"
codesign --verify --deep --strict "$APP"

rm -f "$ZIP"
ditto -c -k --keepParent --norsrc --noextattr "$APP" "$ZIP"
if [[ "$MAKE_DMG" == 1 ]]; then
    DMG="$BUILD_DIR/$APP_NAME-$VERSION-macos.dmg"
    STAGE="$(mktemp -d "$BUILD_DIR/dmg.XXXXXX")"
    trap 'rm -rf "$STAGE"' EXIT
    ditto "$APP" "$STAGE/$APP_NAME.app"
    ln -s /Applications "$STAGE/Applications"
    hdiutil create -volname "Kanjo $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
    codesign "${SIGN_FLAGS[@]}" "$DMG"
    codesign --verify --strict "$DMG"
    rm -rf "$STAGE"
    trap - EXIT
fi
echo "Architectures: ${ARCHS[*]}"
echo "Signing identity: $IDENTITY"
echo "App: $(pwd)/$APP"
echo "Zip: $(pwd)/$ZIP"
ls -lh "$ZIP"
if [[ "$MAKE_DMG" == 1 ]]; then
    echo "DMG: $(pwd)/$DMG"
    ls -lh "$DMG"
fi
