#!/bin/bash
# 构建内置 CLI 的通用 Kanjo.app、zip 和 DMG，产物留在 build/。
# 只用 SwiftPM + 系统自带工具（iconutil / sips / codesign / ditto / notarytool / stapler），不需要 Xcode 工程。
#
# 用法：./package.sh [version] [--icon] [--no-dmg] [--arch arm64|x86_64] [--notarize [profile]] [--profile <path>]
#   version  默认读仓库顶层的 VERSION 文件
#   --icon   重新生成 Resources/Kanjo.png 和 Kanjo.icns（缺失时也会自动生成）
#   --notarize [profile]  公证产物（默认 keychain profile 为 'kanjo-notary'，亦可设环境变量 KANJO_NOTARY_PROFILE）
#   --profile <path>  嵌入 Developer ID 描述文件并加 iCloud entitlements（亦可设环境变量 KANJO_PROVISION_PROFILE）
#
# 应用内更新用 Sparkle：Resources/sparkle-public-ed-key.txt 里是 EdDSA 公钥
# （generate_keys --account kanjo 生成）。还是占位符时本地构建不写 SU 键（更新关闭），
# 而 --notarize 会直接拒绝。发布走 scripts/make-appcast.sh 生成 appcast.xml。
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Kanjo"
BUNDLE_ID="com.lanshuagent.kanjo"
ICLOUD_CONTAINER="iCloud.com.lanshuagent.kanjo"
BUILD_DIR="build"

profile_info() {
    python3 - "$1" "$BUNDLE_ID" "$ICLOUD_CONTAINER" <<'PY'
import plistlib, sys

path, bundle_id, container = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, "rb") as fh:
        profile = plistlib.load(fh)
except Exception as exc:
    sys.exit(f"could not read provisioning profile: {exc}")

def values(raw):
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [str(raw)]

entitlements = profile.get("Entitlements") or {}
app_ids = values(entitlements.get("com.apple.application-identifier")) + values(entitlements.get("application-identifier"))
app_ids = list(dict.fromkeys(app_ids))
if not app_ids:
    sys.exit("provisioning profile has no application-identifier")
suffix = "." + bundle_id
matches = [app_id for app_id in app_ids if app_id.endswith(suffix)]
if not matches:
    sys.exit(f"provisioning profile application-identifier {', '.join(app_ids)} does not end with {suffix}")

containers = []
for key in (
    "com.apple.developer.icloud-container-identifiers",
    "com.apple.developer.ubiquity-container-identifiers",
    "com.apple.developer.icloud-container-development-container-identifiers",
):
    containers += values(entitlements.get(key))
if container not in containers:
    sys.exit(f"provisioning profile does not contain iCloud container {container}")

team_ids = values(entitlements.get("com.apple.developer.team-identifier")) + values(profile.get("TeamIdentifier"))
team_id = team_ids[0] if team_ids else matches[0].split(".", 1)[0]
if not team_id:
    sys.exit("provisioning profile has no team identifier")
print(f"{matches[0]}\t{team_id}")
PY
}

VERSION=""
REGEN_ICON=0
ARCHS=(arm64 x86_64)
MAKE_DMG=1
NOTARY_PROFILE="${KANJO_NOTARY_PROFILE:-}"
PROFILE="${KANJO_PROVISION_PROFILE:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --icon) REGEN_ICON=1 ;;
        --no-dmg) MAKE_DMG=0 ;;
        --arch)
            shift
            case "${1:-}" in arm64|x86_64) ARCHS=("$1") ;; *) echo "expected arm64 or x86_64" >&2; exit 1 ;; esac ;;
        --notarize)
            if [[ $# -gt 1 && ! "$2" =~ ^- && ! "$2" =~ ^v?[0-9] ]]; then
                shift
                NOTARY_PROFILE="$1"
            else
                NOTARY_PROFILE="${NOTARY_PROFILE:-kanjo-notary}"
            fi
            ;;
        --notarize=*)
            NOTARY_PROFILE="${1#*=}"
            ;;
        --profile)
            if [[ $# -lt 2 || "$2" =~ ^- ]]; then echo "--profile needs a path" >&2; exit 1; fi
            shift
            PROFILE="$1"
            ;;
        --profile=*)
            PROFILE="${1#*=}"
            ;;
        -h|--help) echo "Usage: ./package.sh [version] [--icon] [--no-dmg] [--arch arm64|x86_64] [--notarize [profile]] [--profile <path>]"; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 1 ;;
        *) VERSION="$1" ;;
    esac
    shift
done
if [[ -z "$VERSION" ]]; then
    [[ -f ../VERSION ]] || { echo "no version given and ../VERSION not found" >&2; exit 1; }
    VERSION="$(tr -d '[:space:]' < ../VERSION)"
fi
VERSION="${VERSION#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "invalid version (expected X.Y.Z): $VERSION" >&2
    exit 1
fi

IDENTITY="${KANJO_CODESIGN_IDENTITY:-}"
if [[ -z "$IDENTITY" ]]; then
    IDENTITIES="$(security find-identity -v -p codesigning 2>/dev/null || true)"
    IDENTITY="$(echo "$IDENTITIES" | sed -nE 's/^[[:space:]]*[0-9]+\) [0-9A-F]+ "(Developer ID Application[^"]+)".*/\1/p' | head -n 1)"
    IDENTITY="${IDENTITY:--}"
fi
if [[ -n "$NOTARY_PROFILE" && "$IDENTITY" == "-" ]]; then
    echo "notarization needs a Developer ID identity" >&2
    exit 1
fi

# Sparkle 的 EdDSA 公钥（由 generate_keys --account kanjo 生成后写进这个文件）。
# 占位符还在时：本地构建照常，但不写 SU 键，应用内更新保持关闭；公证构建直接拒绝。
SPARKLE_KEY_FILE="Resources/sparkle-public-ed-key.txt"
SPARKLE_PUBLIC_KEY_PLACEHOLDER="REPLACE_WITH_KANJO_SPARKLE_PUBLIC_KEY"
SPARKLE_FEED_URL="https://github.com/mammut001/kanjo/releases/latest/download/appcast.xml"
SPARKLE_PUBLIC_KEY=""
if [[ -f "$SPARKLE_KEY_FILE" ]]; then
    SPARKLE_PUBLIC_KEY="$(tr -d '[:space:]' < "$SPARKLE_KEY_FILE")"
fi
SPARKLE_ENABLED=0
if [[ -n "$SPARKLE_PUBLIC_KEY" && "$SPARKLE_PUBLIC_KEY" != "$SPARKLE_PUBLIC_KEY_PLACEHOLDER" ]]; then
    SPARKLE_ENABLED=1
fi
if [[ -n "$NOTARY_PROFILE" && "$SPARKLE_ENABLED" == 0 ]]; then
    echo "notarized builds need a real Sparkle public key: run 'generate_keys --account kanjo'" >&2
    echo "and put the printed key in $SPARKLE_KEY_FILE (it still holds the placeholder)." >&2
    exit 1
fi

# Sparkle 比较 CFBundleVersion，每次发布必须变大。这里用版本号派生一个单调递增的整数：
# 0.5.2 -> 502，0.6.0 -> 600，1.2.3 -> 10203（major*10000 + minor*100 + patch）。
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
BUILD_NUMBER=$((10#$VERSION_MAJOR * 10000 + 10#$VERSION_MINOR * 100 + 10#$VERSION_PATCH))

if [[ -z "$PROFILE" && -f "Resources/$APP_NAME.provisionprofile" ]]; then
    PROFILE="Resources/$APP_NAME.provisionprofile"
fi
if [[ -n "$PROFILE" ]]; then
    [[ -f "$PROFILE" ]] || { echo "provisioning profile not found: $PROFILE" >&2; exit 1; }
    if [[ "$IDENTITY" == "-" ]]; then
        echo "iCloud entitlements need a Developer ID identity" >&2
        exit 1
    fi
    mkdir -p "$BUILD_DIR"
    PROFILE_PLIST="$BUILD_DIR/profile.plist"
    if ! security cms -D -i "$PROFILE" > "$PROFILE_PLIST"; then
        echo "could not decode provisioning profile: $PROFILE" >&2
        exit 1
    fi
    PROFILE_INFO="$(profile_info "$PROFILE_PLIST")"
    APP_ID="${PROFILE_INFO%%$'\t'*}"
    TEAM_ID="${PROFILE_INFO##*$'\t'}"
    ENTITLEMENTS="$BUILD_DIR/$APP_NAME.entitlements"
    cat > "$ENTITLEMENTS" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.application-identifier</key><string>${TEAM_ID}.${BUNDLE_ID}</string>
    <key>com.apple.developer.team-identifier</key><string>${TEAM_ID}</string>
    <key>com.apple.developer.icloud-container-identifiers</key>
    <array>
        <string>${ICLOUD_CONTAINER}</string>
    </array>
    <key>com.apple.developer.icloud-services</key>
    <array>
        <string>CloudKit</string>
    </array>
    <key>com.apple.developer.icloud-container-environment</key><string>Production</string>
    <key>com.apple.developer.ubiquity-kvstore-identifier</key><string>${TEAM_ID}.${BUNDLE_ID}</string>
</dict>
</plist>
PLIST
    plutil -lint "$ENTITLEMENTS" >/dev/null
    echo "==> provisioning profile: $PROFILE ($APP_ID, team $TEAM_ID)"
fi

APP="$BUILD_DIR/$APP_NAME.app"
ZIP="$BUILD_DIR/$APP_NAME-$VERSION-macos.zip"
DMG="$BUILD_DIR/$APP_NAME-$VERSION-macos.dmg"
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
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"
lipo -create "${SLICES[@]}" -output "$APP/Contents/MacOS/$APP_NAME"
for arch in "${ARCHS[@]}"; do
    lipo "$APP/Contents/MacOS/$APP_NAME" -verify_arch "$arch"
done
# 让 dyld 在 Contents/Frameworks 里找 Sparkle（SwiftPM 的 rpath 指着构建目录，不能发布）。
if ! otool -l "$APP/Contents/MacOS/$APP_NAME" | grep -q "@executable_path/../Frameworks"; then
    install_name_tool -add_rpath "@executable_path/../Frameworks" "$APP/Contents/MacOS/$APP_NAME"
fi
# Sparkle.framework 直接取 SwiftPM 解出来的 xcframework 里的那一份（本身已是 arm64 + x86_64 通用）。
# ditto 会保留 framework 版本目录里的符号链接和可执行权限。
SPARKLE_FRAMEWORK_SRC="$BUILD_DIR/swiftpm-${ARCHS[0]}/artifacts/sparkle/Sparkle/Sparkle.xcframework/macos-arm64_x86_64/Sparkle.framework"
if [[ ! -d "$SPARKLE_FRAMEWORK_SRC" ]]; then
    SPARKLE_FRAMEWORK_SRC="$(find "$BUILD_DIR" -path '*/artifacts/sparkle/Sparkle/Sparkle.xcframework/macos-arm64_x86_64/Sparkle.framework' -type d 2>/dev/null | head -n 1)"
fi
[[ -d "$SPARKLE_FRAMEWORK_SRC" ]] || { echo "Sparkle.framework not found under $BUILD_DIR" >&2; exit 1; }
if [[ ${#ARCHS[@]} -gt 1 ]]; then
    for arch in "${ARCHS[@]}"; do
        lipo "$SPARKLE_FRAMEWORK_SRC/Versions/B/Sparkle" -verify_arch "$arch"
    done
fi
ditto "$SPARKLE_FRAMEWORK_SRC" "$APP/Contents/Frameworks/Sparkle.framework"
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
# 拷贝 SwiftPM 资源 bundle 到 Contents/Resources/，使 Bundle.module 在 .app 运行时正常加载
BIN_DIR="$(swift build --scratch-path "$BUILD_DIR/swiftpm-${ARCHS[0]}" "${SWIFT_FLAGS[@]}" -c release --arch "${ARCHS[0]}" --show-bin-path)"
for b in "$BIN_DIR"/*.bundle; do
    if [[ -d "$b" ]]; then
        cp -R "$b" "$APP/Contents/Resources/"
    fi
done

# Sparkle 的 Info.plist 键。公钥是占位符时整段省略，应用内更新保持关闭（本地构建照常可用）。
sparkle_info_plist_keys() {
    if [[ "$SPARKLE_ENABLED" == 0 ]]; then
        return 0
    fi
    cat <<KEYS
    <key>SUFeedURL</key><string>${SPARKLE_FEED_URL}</string>
    <key>SUPublicEDKey</key><string>${SPARKLE_PUBLIC_KEY}</string>
    <key>SUEnableAutomaticChecks</key><true/>
    <key>SUScheduledCheckInterval</key><integer>86400</integer>
    <key>SUAllowsAutomaticUpdates</key><false/>
KEYS
}

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
    <key>CFBundleVersion</key><string>${BUILD_NUMBER}</string>
    <key>CFBundleIconFile</key><string>${APP_NAME}</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleLocalizations</key>
    <array>
        <string>en</string>
        <string>zh-Hans</string>
        <string>fr</string>
    </array>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
$(sparkle_info_plist_keys)
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null

if [[ -n "$PROFILE" ]]; then
    cp "$PROFILE" "$APP/Contents/embedded.provisionprofile"
fi

SIGN_FLAGS=(--force --sign "$IDENTITY")
if [[ "$IDENTITY" != - ]]; then
    SIGN_FLAGS+=(--options runtime --timestamp)
fi
MAIN_SIGN_FLAGS=("${SIGN_FLAGS[@]}")
if [[ -n "$PROFILE" ]]; then
    MAIN_SIGN_FLAGS+=(--entitlements "$ENTITLEMENTS")
fi
xattr -cr "$APP"
for b in "$APP/Contents/Resources"/*.bundle; do
    if [[ -d "$b" ]]; then
        codesign "${SIGN_FLAGS[@]}" "$b"
    fi
done

# Sparkle 的嵌套组件必须由内向外先签，再用同一身份 / 同一选项签 framework 和 app
# （SwiftPM 解出来的那份带的是 Sparkle 自己的签名，换身份后必须重签）。
SPARKLE_FW="$APP/Contents/Frameworks/Sparkle.framework"
if [[ -d "$SPARKLE_FW" ]]; then
    echo "==> codesigning Sparkle.framework (inside-out)"
    for xpc in "$SPARKLE_FW/Versions/B/XPCServices/Installer.xpc" "$SPARKLE_FW/Versions/B/XPCServices/Downloader.xpc"; do
        [[ -d "$xpc" ]] && codesign "${SIGN_FLAGS[@]}" "$xpc"
    done
    codesign "${SIGN_FLAGS[@]}" "$SPARKLE_FW/Versions/B/Autoupdate"
    codesign "${SIGN_FLAGS[@]}" "$SPARKLE_FW/Versions/B/Updater.app"
    codesign "${SIGN_FLAGS[@]}" "$SPARKLE_FW"
fi

codesign "${MAIN_SIGN_FLAGS[@]}" "$APP/Contents/MacOS/$APP_NAME"
codesign "${MAIN_SIGN_FLAGS[@]}" "$APP"
codesign --verify --deep --strict "$APP"

if [[ -n "$PROFILE" ]]; then
    echo "==> codesign -d --entitlements :- $APP"
    ENT_OUTPUT="$(codesign -d --entitlements :- "$APP" 2>/dev/null || true)"
    ENT_SUMMARY="$(printf '%s' "$ENT_OUTPUT" | python3 -c '
import plistlib, sys
try:
    data = plistlib.loads(sys.stdin.buffer.read())
except Exception:
    sys.exit(0)
containers = data.get("com.apple.developer.icloud-container-identifiers") or []
container = containers[0] if containers else "?"
environment = data.get("com.apple.developer.icloud-container-environment", "?")
print(f"iCloud container {container} · environment {environment}")
' 2>/dev/null || true)"
    echo "    ${ENT_SUMMARY:-iCloud container $ICLOUD_CONTAINER · environment Production}"
fi

create_dmg() {
    rm -f "$DMG"
    local stage
    stage="$(mktemp -d "$BUILD_DIR/dmg.XXXXXX")"
    trap 'rm -rf "$stage"' EXIT
    ditto "$APP" "$stage/$APP_NAME.app"
    ln -s /Applications "$stage/Applications"
    hdiutil create -volname "Kanjo $VERSION" -srcfolder "$stage" -ov -format UDZO "$DMG"
    if [[ "$IDENTITY" != - ]]; then
        codesign --force --timestamp --sign "$IDENTITY" "$DMG"
        codesign --verify --strict "$DMG"
    fi
    rm -rf "$stage"
    trap - EXIT
}

notarize_artifact() {
    local target="$1"
    echo "==> notarizing $target with profile '$NOTARY_PROFILE'"
    local tmp_log
    tmp_log="$(mktemp "$BUILD_DIR/notary.XXXXXX")"
    trap 'rm -f "$tmp_log"' EXIT
    local status=0
    set +e
    xcrun notarytool submit "$target" --keychain-profile "$NOTARY_PROFILE" --wait --output-format json 2>&1 | tee "$tmp_log"
    status="${PIPESTATUS[0]}"
    set -e

    local notary_status="" sub_id=""
    if [[ -s "$tmp_log" ]]; then
        local parsed
        parsed="$(python3 -c '
import json, re, sys
content = sys.stdin.read()
status, sub_id = "", ""
try:
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1:
        data = json.loads(content[start:end+1])
        status = str(data.get("status", ""))
        sub_id = str(data.get("id", ""))
except Exception:
    pass
if not status:
    m = re.search(r"status\s*[:=]\s*[\"'\''\"]?([A-Za-z]+)", content, re.IGNORECASE)
    if m:
        status = m.group(1)
if not sub_id:
    m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", content)
    if m:
        sub_id = m.group(0)
print(f"{status.lower()}\t{sub_id}")
' < "$tmp_log" 2>/dev/null || true)"
        IFS=$'\t' read -r notary_status sub_id <<< "$parsed"
    fi

    if [[ $status -ne 0 || "$notary_status" != "accepted" ]]; then
        rm -f "$tmp_log"
        trap - EXIT
        echo "==> notarization failed for $target (status: ${notary_status:-unknown})" >&2
        if [[ -n "$sub_id" ]]; then
            echo "notarytool log command: xcrun notarytool log $sub_id --keychain-profile $NOTARY_PROFILE" >&2
        else
            echo "notarytool log command: xcrun notarytool log <submission-id> --keychain-profile $NOTARY_PROFILE" >&2
        fi
        exit 1
    fi
    rm -f "$tmp_log"
    trap - EXIT
}

rm -f "$ZIP"
ditto -c -k --keepParent --norsrc --noextattr "$APP" "$ZIP"
if [[ "$MAKE_DMG" == 1 ]]; then
    create_dmg
fi

if [[ -n "$NOTARY_PROFILE" ]]; then
    notarize_artifact "$ZIP"
    echo "==> stapling $APP"
    xcrun stapler staple "$APP"
    echo "==> rebuilding $ZIP"
    rm -f "$ZIP"
    ditto -c -k --keepParent --norsrc --noextattr "$APP" "$ZIP"
    if [[ "$MAKE_DMG" == 1 ]]; then
        echo "==> rebuilding $DMG"
        create_dmg
        echo "==> notarizing $DMG"
        notarize_artifact "$DMG"
        echo "==> stapling $DMG"
        xcrun stapler staple "$DMG"
    fi
else
    echo "notarization skipped (set KANJO_NOTARY_PROFILE)"
fi

echo "Architectures: ${ARCHS[*]}"
echo "Signing identity: $IDENTITY"
echo "Version: $VERSION (CFBundleVersion $BUILD_NUMBER)"
if [[ "$SPARKLE_ENABLED" == 1 ]]; then
    echo "Updater: Sparkle enabled (feed $SPARKLE_FEED_URL)"
else
    echo "Updater: disabled (placeholder Sparkle key in $SPARKLE_KEY_FILE; not for notarized builds)"
fi
if [[ -n "$PROFILE" ]]; then
    echo "Provisioning profile: $PROFILE"
    echo "iCloud container: $ICLOUD_CONTAINER (Production)"
fi
if [[ -n "$NOTARY_PROFILE" ]]; then
    echo "Notary profile: $NOTARY_PROFILE"
fi
echo "App: $(pwd)/$APP"
echo "Zip: $(pwd)/$ZIP"
ls -lh "$ZIP"
if [[ "$MAKE_DMG" == 1 ]]; then
    echo "DMG: $(pwd)/$DMG"
    ls -lh "$DMG"
fi
