#!/bin/bash
# 把 Kanjo 菜单栏应用打包成 build/Kanjo.app 和 build/Kanjo-<version>-macos.zip。
# 只用 SwiftPM + 系统自带工具（iconutil / sips / codesign / ditto），不需要 Xcode 工程。
#
# 用法：./package.sh [version] [--icon]
#   version  默认读仓库顶层的 VERSION 文件
#   --icon   重新生成 Resources/Kanjo.png 和 Kanjo.icns（缺失时也会自动生成）
set -euo pipefail
cd "$(dirname "$0")"

VERSION=""
REGEN_ICON=0
for arg in "$@"; do
    case "$arg" in
        --icon) REGEN_ICON=1 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        -*) echo "unknown option: $arg" >&2; exit 1 ;;
        *) VERSION="$arg" ;;
    esac
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
    ICONSET_DIR="$(mktemp -d)"
    trap 'rm -rf "$ICONSET_DIR"' EXIT
    ICONSET="$ICONSET_DIR/$APP_NAME.iconset"
    mkdir "$ICONSET"
    for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns -o "$ICNS" "$ICONSET"
fi

echo "==> swift build -c release"
swift build -c release --product "$APP_NAME"
BIN="$(swift build -c release --show-bin-path)/$APP_NAME"
[[ -x "$BIN" ]] || { echo "release binary not found: $BIN" >&2; exit 1; }

echo "==> assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/$APP_NAME"
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
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null

echo "==> ad-hoc codesign"
# 先清掉扩展属性（Finder 信息、来源标记等），否则签名会拒绝或 zip 里多出 ._ 文件。
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"

echo "==> zipping"
rm -f "$ZIP"
ditto -c -k --keepParent --norsrc --noextattr "$APP" "$ZIP"

echo "App: $(pwd)/$APP"
echo "Zip: $(pwd)/$ZIP"
