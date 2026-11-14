"""Translations for the `kanjo usage` terminal UI.

Every user-visible string of the TUI lives here, with English and Simplified
Chinese (``zh``) variants. Chinese wording follows
``ui/Sources/KanjoCore/Resources/zh-Hans.lproj/Localizable.strings`` where the
macOS app already has a translation.

``auto`` resolution order (``resolve_lang``):

1. ``--lang en`` / ``--lang zh`` wins.
2. The Kanjo app language setting (macOS ``UserDefaults`` domain
   ``com.lanshuagent.kanjo``, key ``appLanguage``, values ``system`` / ``en`` /
   ``zh-Hans`` / ``fr``): Chinese -> zh, anything else except ``system`` -> en.
3. ``LC_ALL`` / ``LC_MESSAGES`` / ``LANG`` starting with ``zh`` -> zh.
4. Otherwise English.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, Optional

DEFAULT_LANG = "en"
LANGS = ("auto", "en", "zh")
LANG_CHOICES = LANGS

APP_DEFAULTS_DOMAIN = "com.lanshuagent.kanjo"
APP_DEFAULTS_SUITE_ENV = "KANJO_DEFAULTS_SUITE"
APP_LANGUAGE_KEY = "appLanguage"


def normalize_lang(lang: Optional[str]) -> str:
    """Map anything that is not a supported explicit language to English."""
    value = (lang or "").strip().lower()
    if value.startswith("zh"):
        return "zh"
    if value.startswith("en"):
        return "en"
    return DEFAULT_LANG


_STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        # chrome
        "loading": "Loading…",
        "refreshing": "refreshing…",
        "terminal_too_small": "Terminal too small (need >= 60x15, current: {width}x{height})",
        "more": "+{count} more",
        "filter_prompt": "Filter: {query}_ (Enter to apply, Esc to cancel)",
        "time.today": "Today {time}",

        # time ranges
        "range.all": "All",
        "range.today": "Today",
        "range.7d": "7d",
        "range.30d": "30d",
        "range.reset": "Since reset",
        "range.cycle": "Cycle",

        # views
        "view.projects": "Projects",
        "view.models": "Models",
        "view.agents": "Agents",
        "view.days": "Days",
        "view.accounts": "Accounts",

        # table columns
        "col.project": "PROJECT",
        "col.cost": "COST",
        "col.tokens": "TOKENS",
        "col.sessions": "SESSIONS",
        "col.agents": "AGENTS",
        "col.last_active": "LAST ACTIVE",
        "col.week8": "8W",
        "col.model": "MODEL",
        "col.provider": "PROVIDER",
        "col.agent": "AGENT",
        "col.share": "SHARE",
        "col.date": "DATE",
        "col.cost_bar": "COST BAR",
        "col.account": "ACCOUNT",
        "col.messages": "MESSAGES",
        "col.last_seen": "LAST SEEN",
        "col.login": "LOGIN",

        # footer rows and totals
        "row.unattributed": "Unattributed",
        "row.excluded": "Excluded",
        "row.parse_failed": "Parse failed",
        "row.total": "Total",
        "total.tokens": "{value} tokens",
        "total.sessions": "{count} sessions",
        "total.projects": "{count} projects",
        "bool.yes": "yes",
        "bool.no": "no",

        # F-key bar
        "fkey.help": "Help",
        "fkey.range": "Range",
        "fkey.view": "View",
        "fkey.filter": "Filter",
        "fkey.refresh": "Refresh",
        "fkey.sort": "Sort",
        "fkey.meters": "Meters",
        "fkey.quit": "Quit",

        # help overlay
        "help.title": "Help & Shortcuts",
        "help.close": "Press any key to close help",
        "help.navigation.title": "Navigation",
        "help.navigation.desc": "↑ / ↓ / PgUp / PgDn / Home / End to scroll rows",
        "help.range.title": "Time Range",
        "help.range.desc": "1-6 or ← / → to change range (All, Today, 7d, 30d, Reset, Cycle)",
        "help.views.title": "Views",
        "help.views.desc": "Tab / F3 or p / m / a / d / g to switch view (Projects, Models, Agents, Days, Accounts)",
        "help.detail.title": "Detail",
        "help.detail.desc": "Enter on a project to open details, Esc / Backspace to close",
        "help.filter.title": "Filter",
        "help.filter.desc": "/ or F4 to filter by name, Enter to confirm, Esc to cancel",
        "help.sort.title": "Sort",
        "help.sort.desc": "s or F6 to cycle sort column",
        "help.meters.title": "Meters",
        "help.meters.desc": "M or F7 toggles expanded meters (full quota detail, smaller table)",
        "help.refresh.title": "Refresh",
        "help.refresh.desc": "r or F5 to refresh now (in-process re-scan)",
        "help.mouse.title": "Mouse",
        "help.mouse.desc": "Click tabs, F-keys, rows or headers; wheel scrolls; --no-mouse disables",
        "help.quit.title": "Quit",
        "help.quit.desc": "q or F10 to exit cleanly",

        # meters
        "meter.weekly": "Weekly",
        "meter.hours": "{hours}-hour",
        "meter.five_hour": "5-hour",
        "meter.weekly_short": "W",
        "meter.five_short": "5h",
        "meter.usage": "usage {amount}",
        "meter.per_month": "{price}/mo",
        "meter.window_ended": "window ended",
        "meter.reset.in_m": "resets in {minutes}m",
        "meter.reset.at": "resets {time}",
        "meter.reset.in_hm": "resets in {hours}h {minutes}m",
        "meter.reset.in_dh": "resets in {days}d {hours}h",
        "meter.quota": "quota",
        "meter.extra": "Extra",
        "meter.claude_gpt_weekly": "Claude/GPT weekly",
        "meter.claude_gpt_five_hour": "Claude/GPT 5-hour",
        "meter.no_live_data": "(no live data)",

        # accounts section / view
        "accounts.title.quota_week": "Antigravity accounts · this quota week (since {when})",
        "accounts.title.billing_cycle": "Antigravity accounts · this billing cycle (since {when})",
        "accounts.title.last_7d": "Antigravity accounts · last 7 days (since {when})",
        "accounts.current": "● current",
        "accounts.ascii_current": "* current",
        "accounts.unattributed": "unattributed",
        "accounts.confirm": "Switch the Antigravity CLI login to {email}? Running agy sessions write their own login back at their next token refresh — quit them (or restart them) after switching. [y/N]",
        "accounts.confirm_title": "Switch login",
        "accounts.switched": "Switched to {email} — running agy sessions write their login back at their next token refresh",
        "accounts.switched_running": "{count} agy sessions running — quit and reopen them or they will switch back within about an hour",
        "accounts.no_saved_login": "Sign in once with `agy` using this account, then refresh",
        "accounts.macos_only": "Switching is macOS-only",
        "accounts.error.no_saved_login": "No saved login found",
        "accounts.error.unsaved_login": "Current login is not saved yet; run agy once and refresh Kanjo",
        "accounts.error.generic": "Switch failed",

        # project detail pane
        "detail.title": "Project: {name}",
        "detail.remote": "Remote: {remote}",
        "detail.paths": "Paths:  {paths}",
        "detail.stats": "Cost: {cost}  ·  Tokens: {tokens}  ·  Sessions: {sessions}",
        "detail.sparkline": "30-day sparkline: {spark}  ({peak})",
        "detail.peak": "{money}/day max",
        "detail.by_agent": "By Agent:",
        "detail.by_model": "By Model:",
        "detail.close": "[Esc / Backspace] Close",
    },
    "zh": {
        # chrome
        "loading": "正在加载…",
        "refreshing": "正在刷新…",
        "terminal_too_small": "终端窗口太小（至少需要 60x15，当前 {width}x{height}）",
        "more": "另有 {count} 项",
        "filter_prompt": "筛选：{query}_（Enter 应用，Esc 取消）",
        "time.today": "今天 {time}",

        # time ranges
        "range.all": "全部",
        "range.today": "今天",
        "range.7d": "7 天",
        "range.30d": "30 天",
        "range.reset": "自上次重置",
        "range.cycle": "本账期",

        # views
        "view.projects": "项目",
        "view.models": "模型",
        "view.agents": "Agent",
        "view.days": "按天",
        "view.accounts": "账号",

        # table columns
        "col.project": "项目",
        "col.cost": "花费",
        "col.tokens": "Token",
        "col.sessions": "会话",
        "col.agents": "AGENT",
        "col.last_active": "最后活跃",
        "col.week8": "8周",
        "col.model": "模型",
        "col.provider": "提供商",
        "col.agent": "AGENT",
        "col.share": "占比",
        "col.date": "日期",
        "col.cost_bar": "花费条",
        "col.account": "账号",
        "col.messages": "消息",
        "col.last_seen": "最后活跃",
        "col.login": "登录",

        # footer rows and totals
        "row.unattributed": "未归属",
        "row.excluded": "已排除",
        "row.parse_failed": "解析失败",
        "row.total": "总计",
        "total.tokens": "{value} Token",
        "total.sessions": "{count} 次会话",
        "total.projects": "{count} 个项目",
        "bool.yes": "是",
        "bool.no": "否",

        # F-key bar
        "fkey.help": "帮助",
        "fkey.range": "范围",
        "fkey.view": "视图",
        "fkey.filter": "筛选",
        "fkey.refresh": "刷新",
        "fkey.sort": "排序",
        "fkey.meters": "额度",
        "fkey.quit": "退出",

        # help overlay
        "help.title": "帮助与快捷键",
        "help.close": "按任意键关闭帮助",
        "help.navigation.title": "导航",
        "help.navigation.desc": "↑ / ↓ / PgUp / PgDn / Home / End 滚动列表",
        "help.range.title": "时间范围",
        "help.range.desc": "1-6 或 ← / → 切换范围（全部、今天、7 天、30 天、自上次重置、本账期）",
        "help.views.title": "视图",
        "help.views.desc": "Tab / F3 或 p / m / a / d / g 切换视图（项目、模型、Agent、按天、账号）",
        "help.detail.title": "详情",
        "help.detail.desc": "在项目上按 Enter 打开详情，Esc / Backspace 关闭",
        "help.filter.title": "筛选",
        "help.filter.desc": "/ 或 F4 按名称筛选，Enter 确认，Esc 取消",
        "help.sort.title": "排序",
        "help.sort.desc": "s 或 F6 切换排序列",
        "help.meters.title": "额度",
        "help.meters.desc": "M 或 F7 展开额度仪表（完整额度详情，表格更小）",
        "help.refresh.title": "刷新",
        "help.refresh.desc": "r 或 F5 立即刷新（进程内重新扫描）",
        "help.mouse.title": "鼠标",
        "help.mouse.desc": "点击范围标签、F 键、行或表头；滚轮滚动；--no-mouse 可关闭",
        "help.quit.title": "退出",
        "help.quit.desc": "q 或 F10 退出",

        # meters
        "meter.weekly": "每周",
        "meter.hours": "{hours} 小时",
        "meter.five_hour": "5 小时",
        "meter.weekly_short": "周",
        "meter.five_short": "5小时",
        "meter.usage": "用量 {amount}",
        "meter.per_month": "{price}/月",
        "meter.window_ended": "窗口已结束",
        "meter.reset.in_m": "{minutes} 分钟后重置",
        "meter.reset.at": "今天 {time} 重置",
        "meter.reset.in_hm": "{hours} 小时 {minutes} 分后重置",
        "meter.reset.in_dh": "{days} 天 {hours} 小时后重置",
        "meter.quota": "额度",
        "meter.extra": "额外",
        "meter.claude_gpt_weekly": "Claude/GPT 每周",
        "meter.claude_gpt_five_hour": "Claude/GPT 5 小时",
        "meter.no_live_data": "（暂无实时数据）",

        # accounts section / view
        "accounts.title.quota_week": "Antigravity 账号 · 本额度周（{when} 起）",
        "accounts.title.billing_cycle": "Antigravity 账号 · 本账期（{when} 起）",
        "accounts.title.last_7d": "Antigravity 账号 · 最近 7 天（{when} 起）",
        "accounts.current": "● 当前",
        "accounts.ascii_current": "* 当前",
        "accounts.unattributed": "未归属",
        "accounts.confirm": "将 Antigravity CLI 登录切换为 {email}？正在运行的 agy 会在下次令牌刷新时写回自己的登录——切换后请退出（或重开）它们。[y/N]",
        "accounts.confirm_title": "切换登录",
        "accounts.switched": "已切换到 {email}——正在运行的 agy 会在下次令牌刷新时写回自己的登录",
        "accounts.switched_running": "{count} 个 agy 正在运行，需退出后重开，否则约一小时内会被切回",
        "accounts.no_saved_login": "先用 agy 以该账号登录一次，然后刷新",
        "accounts.macos_only": "仅 macOS 支持切换",
        "accounts.error.no_saved_login": "未找到已保存的登录信息",
        "accounts.error.unsaved_login": "当前登录尚未保存；请运行一次 agy 并刷新 Kanjo",
        "accounts.error.generic": "切换失败",

        # project detail pane
        "detail.title": "项目：{name}",
        "detail.remote": "远程：{remote}",
        "detail.paths": "路径：{paths}",
        "detail.stats": "花费：{cost}  ·  Token：{tokens}  ·  会话：{sessions}",
        "detail.sparkline": "30 天走势：{spark}  ({peak})",
        "detail.peak": "单日峰值 {money}",
        "detail.by_agent": "按 Agent：",
        "detail.by_model": "按模型：",
        "detail.close": "[Esc / Backspace] 关闭",
    },
}


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Translate ``key``; unknown keys fall back to English, then to the key."""
    table = _STRINGS.get(normalize_lang(lang) if lang else DEFAULT_LANG, _STRINGS[DEFAULT_LANG])
    text = table.get(key)
    if text is None:
        text = _STRINGS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def app_language() -> Optional[str]:
    """Read the macOS app language setting, or ``None`` when unavailable.

    Read-only. Uses ``defaults read`` first (UserDefaults may not have flushed
    the plist yet), then falls back to reading the preference plist directly
    with the standard library.
    """
    if sys.platform != "darwin":
        return None
    domain = os.environ.get(APP_DEFAULTS_SUITE_ENV, "").strip() or APP_DEFAULTS_DOMAIN
    try:
        res = subprocess.run(
            ["defaults", "read", domain, APP_LANGUAGE_KEY],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if res.returncode == 0:
            value = (res.stdout or "").strip()
            if value:
                return value
    except Exception:
        pass
    try:
        import plistlib
        path = os.path.expanduser("~/Library/Preferences/%s.plist" % domain)
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
        value = data.get(APP_LANGUAGE_KEY)
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return None


def _env_language(environ: Dict[str, str]) -> Optional[str]:
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = (environ.get(name) or "").strip().lower()
        if value.startswith("zh"):
            return "zh"
    return None


def resolve_lang(option: Optional[str] = "auto", environ: Optional[Dict[str, str]] = None,
                 app_language_value: Optional[str] = None) -> str:
    """Resolve ``auto`` / ``en`` / ``zh`` to a concrete language.

    ``app_language_value`` overrides the macOS setting for tests: pass ``""``
    to simulate "no setting available".
    """
    value = (option or "auto").strip().lower()
    if value in ("en", "zh"):
        return value
    if value.startswith("zh"):
        return "zh"
    if value.startswith("en"):
        return "en"

    app_value = app_language() if app_language_value is None else app_language_value
    app_value = (app_value or "").strip().lower()
    if app_value:
        if app_value.startswith("zh"):
            return "zh"
        if app_value != "system":
            return "en"

    return _env_language(environ if environ is not None else os.environ) or "en"
