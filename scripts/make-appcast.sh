#!/usr/bin/env bash
# 为一次 macOS 发布生成 Sparkle 的 appcast.xml。
#
# 用法：scripts/make-appcast.sh <version>
#   例：scripts/make-appcast.sh 0.6.0
#
# 输入是 ui/package.sh --notarize 产出的 ui/build/Kanjo-<version>-macos.zip；
# 输出 ui/build/appcast.xml，只有一条 item，enclosure 指向该 zip 在 GitHub Releases 上的地址。
# 签名用 Sparkle 的 sign_update（EdDSA 私钥在钥匙串账号 "kanjo" 里）。
#
# 第一次发布前需要一次性生成密钥，并把公钥写进 ui/Resources/sparkle-public-ed-key.txt：
#   ui/.build/artifacts/sparkle/Sparkle/bin/generate_keys --account kanjo
#
# 发布步骤：把这个 zip 和 appcast.xml 一起作为 release 资源上传。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UI="$ROOT/ui"
REPO_SLUG="mammut001/kanjo"
MINIMUM_SYSTEM_VERSION="13.0"
KEYCHAIN_ACCOUNT="kanjo"
BUILD_DIR="$UI/build"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>   (e.g. $0 0.6.0)" >&2
    exit 1
fi
VERSION="${VERSION#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "invalid version (expected X.Y.Z): $VERSION" >&2
    exit 1
fi

ZIP="$BUILD_DIR/Kanjo-$VERSION-macos.zip"
if [[ ! -f "$ZIP" ]]; then
    echo "missing update archive: $ZIP" >&2
    echo "build it first: cd ui && ./package.sh --notarize" >&2
    exit 1
fi

# 从打包好的 .app 里读版本号，保证 appcast 和用户看到的包完全一致。
PLIST="$(mktemp)"
trap 'rm -f "$PLIST"' EXIT
unzip -p "$ZIP" "Kanjo.app/Contents/Info.plist" > "$PLIST" 2>/dev/null || {
    echo "could not read Kanjo.app/Contents/Info.plist from $ZIP" >&2
    exit 1
}
plutil -convert xml1 "$PLIST" >/dev/null
read_plist() { /usr/libexec/PlistBuddy -c "Print :$1" "$PLIST" 2>/dev/null || true; }
SHORT_VERSION="$(read_plist CFBundleShortVersionString)"
BUILD_NUMBER="$(read_plist CFBundleVersion)"
PUBLIC_KEY="$(read_plist SUPublicEDKey)"
if [[ "$SHORT_VERSION" != "$VERSION" ]]; then
    echo "archive version mismatch: zip has '$SHORT_VERSION', expected '$VERSION'" >&2
    exit 1
fi
if [[ ! "$BUILD_NUMBER" =~ ^[0-9]+$ ]]; then
    echo "CFBundleVersion in the archive is not an integer: '$BUILD_NUMBER'" >&2
    exit 1
fi
# 没有公钥的包不会启动更新，签出来的 appcast 也就没有意义。
if [[ -z "$PUBLIC_KEY" || "$PUBLIC_KEY" == "REPLACE_WITH_KANJO_SPARKLE_PUBLIC_KEY" ]]; then
    echo "the archive has no real SUPublicEDKey; put the generate_keys public key in" >&2
    echo "ui/Resources/sparkle-public-ed-key.txt and rebuild with ./package.sh --notarize" >&2
    exit 1
fi

# Sparkle 的工具在 SwiftPM 解出来的 artifacts 里（ui/.build 或 package.sh 的 build/swiftpm-*）。
SIGN_UPDATE=""
for candidate in \
    "$UI/.build/artifacts/sparkle/Sparkle/bin/sign_update" \
    "$BUILD_DIR"/swiftpm-*/artifacts/sparkle/Sparkle/bin/sign_update; do
    if [[ -x "$candidate" ]]; then
        SIGN_UPDATE="$candidate"
        break
    fi
done
if [[ -z "$SIGN_UPDATE" ]]; then
    echo "sign_update not found; run 'cd ui && swift package resolve' first" >&2
    exit 1
fi

LENGTH="$(stat -f %z "$ZIP")"
if [[ ! "$LENGTH" =~ ^[0-9]+$ || "$LENGTH" -le 0 ]]; then
    echo "could not determine size of $ZIP" >&2
    exit 1
fi

echo "==> signing $ZIP with keychain account '$KEYCHAIN_ACCOUNT'"
set +e
SIGNATURE="$("$SIGN_UPDATE" --account "$KEYCHAIN_ACCOUNT" -p "$ZIP" 2>&1)"
SIGN_STATUS=$?
set -e
if [[ $SIGN_STATUS -ne 0 ]]; then
    echo "$SIGNATURE" >&2
    cat >&2 <<'HINT'
Could not sign the update archive. Generate the Kanjo signing key once with:
  ui/.build/artifacts/sparkle/Sparkle/bin/generate_keys --account kanjo
then put the printed public key in ui/Resources/sparkle-public-ed-key.txt.
HINT
    exit 1
fi
# sign_update -p 在有些版本会带一行说明，只取最后一行签名本身。
SIGNATURE="$(printf '%s\n' "$SIGNATURE" | tail -n 1 | tr -d '[:space:]')"
if [[ ${#SIGNATURE} -lt 40 ]]; then
    echo "unexpected sign_update output (expected a base64 EdDSA signature)" >&2
    exit 1
fi

DOWNLOAD_URL="https://github.com/$REPO_SLUG/releases/download/v$VERSION/Kanjo-$VERSION-macos.zip"
RELEASE_NOTES_URL="https://github.com/$REPO_SLUG/releases/tag/v$VERSION"
PUB_DATE="$(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S +0000')"
APPCAST="$BUILD_DIR/appcast.xml"

cat > "$APPCAST" <<XML
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Kanjo</title>
    <link>https://github.com/$REPO_SLUG/releases/latest/download/appcast.xml</link>
    <description>Kanjo for macOS — in-app updates.</description>
    <language>en</language>
    <item>
      <title>Version $SHORT_VERSION</title>
      <pubDate>$PUB_DATE</pubDate>
      <sparkle:version>$BUILD_NUMBER</sparkle:version>
      <sparkle:shortVersionString>$SHORT_VERSION</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>$MINIMUM_SYSTEM_VERSION</sparkle:minimumSystemVersion>
      <sparkle:releaseNotesLink>$RELEASE_NOTES_URL</sparkle:releaseNotesLink>
      <link>$RELEASE_NOTES_URL</link>
      <enclosure
        url="$DOWNLOAD_URL"
        length="$LENGTH"
        sparkle:edSignature="$SIGNATURE"
        type="application/octet-stream" />
    </item>
  </channel>
</rss>
XML

echo "==> validating $APPCAST"
"$ROOT/scripts/validate-appcast.sh" "$APPCAST" "$SHORT_VERSION" "$BUILD_NUMBER" "$DOWNLOAD_URL"

echo
echo "Appcast: $(cd "$(dirname "$APPCAST")" && pwd)/appcast.xml"
echo "Upload both files to the v$VERSION release:"
echo "  $(basename "$ZIP")"
echo "  appcast.xml"
