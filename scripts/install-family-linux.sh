#!/usr/bin/env bash
# Kanjo family usage reporter for Linux (interactive installer).
#
# Installs the Kanjo CLI for the current user, stores the family report token,
# reports every 30 minutes (cron, or a systemd user timer when cron is missing)
# and sends a first report right away. No root needed.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mammut001/kanjo/main/scripts/install-family-linux.sh)
#
# Options:
#   --server URL     family server URL (asked when omitted)
#   --label NAME     member display name (default: hostname)
#   --cli-zip PATH   install from a local kanjo-cli.zip instead of downloading
#   --no-schedule    do not set up the 30-minute schedule
#   --skip-report    do not send the first report
#   --uninstall      remove the schedule, the token and the installed files
#
# The token is read from KANJO_FAMILY_TOKEN when set, otherwise asked for
# (hidden input). It is stored in ~/.config/kanjo-family/report.env (mode 600).

set -euo pipefail

CLI_URL="https://github.com/mammut001/kanjo/releases/latest/download/kanjo-cli.zip"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/kanjo-family"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/kanjo-family"
ENV_FILE="$CONF_DIR/report.env"
RUNNER="$DATA_DIR/report.sh"
LOG_FILE="$DATA_DIR/report.log"
CRON_TAG="# kanjo-family-report"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="kanjo-family-report"

SERVER=""
LABEL=""
CLI_ZIP=""
NO_SCHEDULE=0
SKIP_REPORT=0
UNINSTALL=0

die() { printf '\n  [x] %s\n' "$*" >&2; exit 1; }
ok() { printf '  [✓] %s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
step() { printf '\n[%s] %s\n' "$1" "$2"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="${2:-}"; shift 2 ;;
    --server=*) SERVER="${1#*=}"; shift ;;
    --label) LABEL="${2:-}"; shift 2 ;;
    --label=*) LABEL="${1#*=}"; shift ;;
    --cli-zip) CLI_ZIP="${2:-}"; shift 2 ;;
    --cli-zip=*) CLI_ZIP="${1#*=}"; shift ;;
    --no-schedule) NO_SCHEDULE=1; shift ;;
    --skip-report) SKIP_REPORT=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "未知参数 / Unknown option: $1" ;;
  esac
done

# Prompts read from the terminal even when the script itself comes from a pipe.
TTY=""
if [ -t 0 ]; then
  TTY=/dev/stdin
elif { : </dev/tty; } 2>/dev/null; then
  TTY=/dev/tty
fi

ask() { # ask "prompt" default -> echoes answer
  local answer=""
  if [ -n "$TTY" ]; then
    printf '%s' "$1" >&2
    IFS= read -r answer <"$TTY" || true
  fi
  printf '%s' "${answer:-$2}"
}

ask_secret() {
  local answer=""
  [ -n "$TTY" ] || return 0
  printf '%s' "$1" >&2
  IFS= read -rs answer <"$TTY" || true
  printf '\n' >&2
  printf '%s' "$answer"
}

have() { command -v "$1" >/dev/null 2>&1; }

remove_schedule() {
  if have crontab; then
    local current
    current="$(crontab -l 2>/dev/null || true)"
    if printf '%s\n' "$current" | grep -qF "$CRON_TAG"; then
      # grep -v exits 1 when nothing is left; that must not abort under pipefail.
      printf '%s\n' "$current" | { grep -vF "$CRON_TAG" || true; } | crontab -
      ok "已删除 cron 定时任务 / Cron entry removed"
    fi
  fi
  if [ -f "$UNIT_DIR/$UNIT_NAME.timer" ]; then
    systemctl --user disable --now "$UNIT_NAME.timer" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT_NAME.timer" "$UNIT_DIR/$UNIT_NAME.service"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    ok "已删除 systemd 定时器 / systemd timer removed"
  fi
}

echo "============================================================"
echo "Kanjo 家庭用量上报 (Linux) / Kanjo Family Usage Reporter"
echo "只上报 token 数和额度百分比，不上报项目名、路径或对话内容。"
echo "Reports token counts and quota percentages only."
echo "============================================================"

if [ "$UNINSTALL" = 1 ]; then
  step "-" "卸载 / Uninstalling"
  remove_schedule
  rm -rf "$DATA_DIR" "$CONF_DIR"
  ok "已删除令牌和安装文件 / Token and files removed"
  echo
  echo "卸载完成 / Uninstall complete."
  exit 0
fi

# Existing settings are kept when re-running (e.g. to update the CLI).
OLD_TOKEN=""; OLD_URL=""; OLD_LABEL=""
if [ -f "$ENV_FILE" ]; then
  OLD_TOKEN="$(sed -n 's/^KANJO_FAMILY_TOKEN=//p' "$ENV_FILE" | head -n1)"
  OLD_URL="$(sed -n 's/^KANJO_FAMILY_URL=//p' "$ENV_FILE" | head -n1)"
  OLD_LABEL="$(sed -n 's/^KANJO_FAMILY_LABEL=//p' "$ENV_FILE" | head -n1)"
fi

# 1. Python
step "1/5" "检查 Python / Checking Python"
PYTHON=""
for candidate in python3 python; do
  if have "$candidate" && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON" ] || die "需要 Python 3.9 以上。Ubuntu/Debian: sudo apt install python3 / Python 3.9+ is required."
ok "$("$PYTHON" --version 2>&1) ($PYTHON)"

# 2. Kanjo CLI
step "2/5" "安装 Kanjo CLI / Installing Kanjo CLI"
mkdir -p "$DATA_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -n "$CLI_ZIP" ]; then
  [ -f "$CLI_ZIP" ] || die "找不到 / Not found: $CLI_ZIP"
  cp "$CLI_ZIP" "$TMP/kanjo-cli.zip"
  info "使用本地压缩包 / Using local zip: $CLI_ZIP"
else
  info "下载 / Downloading: $CLI_URL"
  if have curl; then
    curl -fsSL -o "$TMP/kanjo-cli.zip" "$CLI_URL" || die "下载失败 / Download failed"
  elif have wget; then
    wget -q -O "$TMP/kanjo-cli.zip" "$CLI_URL" || die "下载失败 / Download failed"
  else
    die "需要 curl 或 wget / curl or wget is required"
  fi
fi
"$PYTHON" -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
  "$TMP/kanjo-cli.zip" "$TMP/cli" || die "解压失败 / Could not unpack the CLI"
[ -d "$TMP/cli/kanjo" ] || die "压缩包里没有 kanjo / The zip has no kanjo package"
rm -rf "$DATA_DIR/cli"
mv "$TMP/cli" "$DATA_DIR/cli"
VERSION="$(cd "$DATA_DIR/cli" && PYTHONPATH=. "$PYTHON" -m kanjo --version 2>&1 || true)"
ok "$VERSION -> $DATA_DIR/cli"

# 3. Server, token, label
step "3/5" "配置服务器和令牌 / Server and token"
if [ -z "$SERVER" ]; then
  if [ -n "$OLD_URL" ]; then
    SERVER="$(ask "  家庭服务器地址 / Family server URL [$OLD_URL]: " "$OLD_URL")"
  else
    SERVER="$(ask "  家庭服务器地址 / Family server URL (https://...): " "")"
  fi
fi
SERVER="${SERVER%/}"
case "$SERVER" in
  https://*|http://127.0.0.1*|http://localhost*) ;;
  "") die "缺少服务器地址，请用 --server 指定 / Missing server URL (--server)" ;;
  *) die "服务器地址必须以 https:// 开头 / The URL must start with https://" ;;
esac
ok "服务器 / Server: $SERVER"

TOKEN="${KANJO_FAMILY_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -n "$OLD_TOKEN" ]; then
  answer="$(ask "  已保存过令牌，是否更换？/ A token is already saved. Replace it? [y/N]: " "n")"
  case "$answer" in
    y|Y|yes|YES) TOKEN="" ;;
    *) TOKEN="$OLD_TOKEN" ;;
  esac
fi
while [ -z "$TOKEN" ]; do
  [ -n "$TTY" ] || die "没有终端可输入令牌，请设置 KANJO_FAMILY_TOKEN / No terminal: set KANJO_FAMILY_TOKEN"
  TOKEN="$(ask_secret "  粘贴家庭上报令牌（输入不显示）/ Paste the family report token (hidden): ")"
  TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
done
case "$TOKEN" in *[!A-Za-z0-9._~+/=-]*) die "令牌含有无效字符 / The token contains invalid characters" ;; esac
ok "令牌已读取 / Token received"

if [ -z "$LABEL" ]; then
  default_label="${OLD_LABEL:-$(hostname 2>/dev/null || echo linux)}"
  LABEL="$(ask "  成员显示名 / Member label [$default_label]: " "$default_label")"
fi
case "$LABEL" in *[$'\n\r=']*) die "显示名不能含换行或等号 / Label cannot contain newlines or '='" ;; esac
ok "显示名 / Label: $LABEL"

mkdir -p "$CONF_DIR"
chmod 700 "$CONF_DIR"
( umask 077
  {
    printf 'KANJO_FAMILY_TOKEN=%s\n' "$TOKEN"
    printf 'KANJO_FAMILY_URL=%s\n' "$SERVER"
    printf 'KANJO_FAMILY_LABEL=%s\n' "$LABEL"
  } >"$ENV_FILE.tmp"
)
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "已保存到 / Saved to $ENV_FILE (600)"

cat >"$RUNNER" <<EOF
#!/usr/bin/env bash
# Sends one Kanjo family report. Written by install-family-linux.sh.
set -u
ENV_FILE="$ENV_FILE"
TOKEN="\$(sed -n 's/^KANJO_FAMILY_TOKEN=//p' "\$ENV_FILE" | head -n1)"
URL="\$(sed -n 's/^KANJO_FAMILY_URL=//p' "\$ENV_FILE" | head -n1)"
LABEL="\$(sed -n 's/^KANJO_FAMILY_LABEL=//p' "\$ENV_FILE" | head -n1)"
cd "$DATA_DIR/cli" || exit 1
set -- report-family --url "\$URL"
[ -n "\$LABEL" ] && set -- "\$@" --member-label "\$LABEL"
KANJO_FAMILY_TOKEN="\$TOKEN" PYTHONPATH=. exec "$PYTHON" -m kanjo "\$@"
EOF
chmod 700 "$RUNNER"

# 4. Schedule
step "4/5" "设置每 30 分钟自动上报 / Scheduling a report every 30 minutes"
if [ "$NO_SCHEDULE" = 1 ]; then
  info "已跳过 (--no-schedule) / Skipped"
else
  remove_schedule >/dev/null
  scheduled=0
  if have crontab; then
    line="*/30 * * * * \"$RUNNER\" >>\"$LOG_FILE\" 2>&1 $CRON_TAG"
    if { crontab -l 2>/dev/null || true; printf '%s\n' "$line"; } | crontab - 2>/dev/null; then
      ok "已添加 cron 任务 / Cron entry added (crontab -l)"
      scheduled=1
    fi
  fi
  if [ "$scheduled" = 0 ] && have systemctl && systemctl --user show-environment >/dev/null 2>&1; then
    mkdir -p "$UNIT_DIR"
    cat >"$UNIT_DIR/$UNIT_NAME.service" <<EOF
[Unit]
Description=Kanjo family usage report

[Service]
Type=oneshot
ExecStart=$RUNNER
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE
EOF
    cat >"$UNIT_DIR/$UNIT_NAME.timer" <<EOF
[Unit]
Description=Kanjo family usage report every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT_NAME.timer" >/dev/null
    ok "已启用 systemd 用户定时器 / systemd user timer enabled"
    info "退出登录后也要运行，请执行 / To keep it running after logout: sudo loginctl enable-linger $USER"
    scheduled=1
  fi
  if [ "$scheduled" = 0 ]; then
    info "[!] 没有 cron 也没有 systemd 用户服务，无法自动上报。/ Neither cron nor a systemd user session is available."
    info "    可以手动运行 / Run manually: $RUNNER"
  fi
fi

# 5. First report
step "5/5" "首次上报 / First report"
if [ "$SKIP_REPORT" = 1 ]; then
  info "已跳过 (--skip-report) / Skipped"
else
  if [ ! -d "$HOME/.gemini" ]; then
    info "[!] 没找到 ~/.gemini，这个用户可能没用过 Antigravity，上报会是 0。"
    info "    ~/.gemini not found: this user may not have used Antigravity yet."
  fi
  out="$("$RUNNER" 2>&1 || true)"
  printf '%s\n' "$out" >>"$LOG_FILE"
  if printf '%s' "$out" | grep -q '"status": *"sent"'; then
    ok "上报成功 / Report sent"
  elif printf '%s' "$out" | grep -q '"http_status": *401'; then
    die "令牌无效，请重新运行并更换令牌 / The server rejected the token (401). Re-run and replace it."
  else
    printf '%s\n' "$out" | tail -n 5 | sed 's/^/    /'
    die "上报失败，详情见上面 / Report failed (see above)"
  fi
fi

echo
echo "完成 / Done."
echo "  手动上报 / Report now:  $RUNNER"
echo "  查看日志 / Log:         $LOG_FILE"
echo "  卸载 / Uninstall:       bash install-family-linux.sh --uninstall"
