#!/usr/bin/env bash
# 校验 appcast.xml 是一条能用的 Sparkle 2 更新条目（版本、长度、签名、URL 都在）。
#
# 用法：scripts/validate-appcast.sh <appcast.xml> <version> <build> <expected-enclosure-url>
#   version  例如 0.6.0（对应 sparkle:shortVersionString）
#   build    CFBundleVersion，例如 600
#   URL      enclosure 必须指向的地址（GitHub Releases 上的 zip）
set -euo pipefail

APPCAST="${1:-}"
EXPECTED_VERSION="${2:-}"
EXPECTED_BUILD="${3:-}"
EXPECTED_URL="${4:-}"

if [[ -z "$APPCAST" || -z "$EXPECTED_VERSION" || -z "$EXPECTED_BUILD" || -z "$EXPECTED_URL" ]]; then
    echo "Usage: $0 <path/to/appcast.xml> <version> <build> <expected-enclosure-url>" >&2
    exit 1
fi

if [[ ! -f "$APPCAST" || ! -s "$APPCAST" ]]; then
    echo "error: appcast file missing or empty: $APPCAST" >&2
    exit 1
fi

python3 - "$APPCAST" "$EXPECTED_VERSION" "$EXPECTED_BUILD" "$EXPECTED_URL" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

appcast_path, expected_ver, expected_bld, expected_url = sys.argv[1:5]
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"

try:
    root = ET.parse(appcast_path).getroot()
except Exception as exc:
    sys.exit(f"error: failed to parse XML in {appcast_path}: {exc}")

channel = root.find("channel")
if channel is None:
    sys.exit(f"error: <channel> element not found in {appcast_path}")

items = channel.findall("item")
if not items:
    sys.exit(f"error: no <item> entries found in {appcast_path}")

matching = None
for item in items:
    ver_el = item.find(f"{{{SPARKLE_NS}}}shortVersionString")
    bld_el = item.find(f"{{{SPARKLE_NS}}}version")
    item_ver = (ver_el.text or "").strip() if ver_el is not None else ""
    item_bld = (bld_el.text or "").strip() if bld_el is not None else ""
    if item_ver == expected_ver and item_bld == expected_bld:
        matching = item
        break

if matching is None:
    sys.exit(f"error: no <item> matching version {expected_ver} (build {expected_bld}) in {appcast_path}")

enclosure = matching.find("enclosure")
if enclosure is None:
    sys.exit(f"error: <enclosure> missing in the item for version {expected_ver}")

url = (enclosure.attrib.get("url") or "").strip()
if url != expected_url:
    sys.exit(f"error: enclosure url mismatch.\n  Expected: {expected_url}\n  Actual:   {url}")

signature = (enclosure.attrib.get(f"{{{SPARKLE_NS}}}edSignature") or "").strip()
if len(signature) < 40:
    sys.exit(f"error: enclosure sparkle:edSignature missing or invalid: '{signature}'")

length_str = (enclosure.attrib.get("length") or "0").strip()
try:
    length = int(length_str)
except ValueError:
    sys.exit(f"error: invalid enclosure length: '{length_str}'")
if length <= 0:
    sys.exit(f"error: enclosure length must be > 0, got {length}")

print(f"Appcast OK: {expected_ver} (build {expected_bld})")
print(f"  URL:       {url}")
print(f"  Length:    {length} bytes")
print(f"  Signature: {signature[:16]}… (EdDSA present)")
PYEOF

echo "==> Appcast $APPCAST is valid"
