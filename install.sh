#!/bin/bash
# 安装 kanjo CLI：把 cli/ 复制到 ~/.local/share/kanjo/cli，在 ~/.local/bin/kanjo 写一个启动脚本。
# 菜单栏应用（Kanjo.app）在设置里的 CLI 工作目录留空时会自动找到这里。
#
# 用法：./install.sh            安装或更新
#       ./install.sh --uninstall 删除上面两处
# 只需要 python3（3.9+），没有第三方依赖。
set -euo pipefail

SHARE_DIR="$HOME/.local/share/kanjo"
CLI_DEST="$SHARE_DIR/cli"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/kanjo"

case "${1:-}" in
    "") ;;
    --uninstall)
        rm -f "$LAUNCHER"
        rm -rf "$CLI_DEST"
        rmdir "$SHARE_DIR" 2>/dev/null || true
        echo "Removed $LAUNCHER and $CLI_DEST"
        echo "Config (~/.config/kanjo) and cache (~/.cache/kanjo) were left in place."
        exit 0
        ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
esac

SRC="$(cd "$(dirname "$0")" && pwd)/cli"
[[ -d "$SRC/kanjo" ]] || { echo "cli/kanjo not found next to install.sh ($SRC)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || { echo "kanjo needs Python 3.9+, found $(python3 --version 2>&1)" >&2; exit 1; }

# 先装到临时目录再替换，失败时不留下半套文件。只带运行需要的东西，不带测试和缓存。
mkdir -p "$SHARE_DIR" "$BIN_DIR"
STAGE="$(mktemp -d "$SHARE_DIR/.cli.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$SRC/kanjo" "$STAGE/kanjo"
for f in pricing.json pricing_overrides.json README.md; do
    [[ -f "$SRC/$f" ]] && cp "$SRC/$f" "$STAGE/"
done
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$CLI_DEST"
mv "$STAGE" "$CLI_DEST"
trap - EXIT

cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
# kanjo launcher, written by install.sh
PYTHONPATH="$CLI_DEST\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m kanjo "\$@"
LAUNCH
chmod +x "$LAUNCHER"

echo "Installed kanjo CLI to $CLI_DEST"
echo "Launcher: $LAUNCHER"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo
        echo "$BIN_DIR is not on your PATH. Add it, for example:"
        echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
        ;;
esac
echo
echo "Try: kanjo doctor"
