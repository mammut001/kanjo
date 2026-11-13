"""Command line interface: ``kanjo export | projects | doctor | ledger | disk | config | paths``."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import uuid
from typing import List, Optional

from . import __version__, disk_cache, winsupport
from .config import Config, ConfigError, load as load_config, subscription_value
from .config_cmd import cmd_config
from .disk import clean as disk_clean, parse_older_than, report as disk_report
from .export import (
    COST_NOTE, SOURCES, build_export, build_public_summary, build_family_report,
    check_invariants, check_public_summary_invariants, check_family_report_invariants,
    dedupe, mobile_document, scan, load_fast_export, save_fast_export,
    load_fast_public_summary, save_fast_public_summary,
    load_fast_family_report, save_fast_family_report, source_fingerprint
)
from .ledger import Ledger
from .publish import cmd_publish_usage
from .report_family import cmd_report_family
from .sources.base import AGENT_LABELS
from .subscriptions import subscriptions as load_subscriptions


def _config(args) -> Config:
    cfg = load_config(args.config)
    if getattr(args, "threshold", None) is not None:
        if not 0.0 < args.threshold <= 1.0:
            raise ConfigError("--threshold must be in (0, 1]")
        cfg.dominant_threshold = args.threshold
    return cfg


def _cache(args):
    if getattr(args, "no_cache", False):
        return None
    from .cache import SessionCache
    return SessionCache()


def cmd_export(args) -> int:
    if args.hide_project_names and not args.mobile:
        print("kanjo: --hide-project-names requires --mobile", file=sys.stderr)
        return 2
    if getattr(args, "public_summary", False) and args.mobile:
        print("kanjo: --public-summary cannot be combined with --mobile", file=sys.stderr)
        return 2
    if getattr(args, "family_report", False) and (args.mobile or getattr(args, "public_summary", False)):
        print("kanjo: --family-report cannot be combined with --mobile or --public-summary", file=sys.stderr)
        return 2
    cfg = _config(args)
    if sys.platform == "darwin":
        if not (os.environ.get("KANJO_DATA_DIR") and not os.environ.get("KANJO_AGY_LOGIN_SYNC")):
            try:
                from .agy_login import sync
                sync()
            except Exception:
                pass
    raw_accounts = getattr(args, "accounts", None)
    if raw_accounts:
        from .config import _validate_family_accounts
        cfg.family_accounts = _validate_family_accounts(raw_accounts)
        cfg.family_origins["accounts"] = "cli"

    doc = None
    fp = None
    use_cache = not getattr(args, "no_cache", False)

    if getattr(args, "family_report", False):
        expected_scope = {
            "agents": (
                ["all"] if cfg.family_agents == "all" or cfg.family_agents == ["all"]
                else (list(cfg.family_agents) if cfg.family_agents is not None else ["antigravity"])
            ),
            "since": cfg.family_since or None,
            "accounts_filter": len(cfg.family_accounts) if cfg.family_accounts is not None else None,
        }
        if use_cache:
            fp = source_fingerprint(config=cfg)
            doc = load_fast_family_report(fp, member_label=args.member_label, scope=expected_scope)
        if doc is None:
            doc = build_family_report(config=cfg, cache=_cache(args), member_label=args.member_label)
            if use_cache:
                if fp is None:
                    fp = source_fingerprint(config=cfg)
                save_fast_family_report(fp, doc, member_label=args.member_label, scope=expected_scope)
    elif getattr(args, "public_summary", False):
        if use_cache:
            fp = source_fingerprint(config=cfg)
            doc = load_fast_public_summary(fp)
        if doc is None:
            doc = build_public_summary(config=cfg, cache=_cache(args))
            if use_cache:
                if fp is None:
                    fp = source_fingerprint(config=cfg)
                save_fast_public_summary(fp, doc)
    else:
        if use_cache:
            fp = source_fingerprint(config=cfg)
            doc = load_fast_export(fp)
        if doc is None:
            doc = build_export(config=cfg, cache=_cache(args))
            if use_cache:
                if fp is None:
                    fp = source_fingerprint(config=cfg)
                save_fast_export(fp, doc)
        if args.mobile:
            doc = mobile_document(doc, hide_project_names=args.hide_project_names)

    if args.gzip:
        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        data = gzip.compress(payload, mtime=0)
    else:
        text = json.dumps(doc, ensure_ascii=False, indent=None if args.compact else 2)
        data = (text + "\n").encode("utf-8")
    if args.output and args.output != "-":
        tmp = "%s.%d.%s.tmp" % (args.output, os.getpid(), uuid.uuid4().hex[:8])
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, args.output)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        if getattr(args, "family_report", False):
            s = doc["summary"]
            print("wrote %s (%d months, %d weeks, %d days, total $%.2f)" % (
                args.output, len(s["months"]), len(s["weeks"]), len(s["days"]), s["all_time"]["cost_usd"]),
                file=sys.stderr)
        elif getattr(args, "public_summary", False):
            print("wrote %s (%d months, %d weeks, total $%.2f)" % (
                args.output, len(doc["months"]), len(doc["weeks"]), doc["all_time"]["cost_usd"]),
                file=sys.stderr)
        else:
            print("wrote %s (%d projects, total $%.2f)" % (args.output, len(doc["projects"]), doc["totals"]["cost"]),
                  file=sys.stderr)
    elif args.gzip:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(data.decode("utf-8"))
    if getattr(args, "family_report", False):
        problems = check_family_report_invariants(doc)
    elif getattr(args, "public_summary", False):
        problems = check_public_summary_invariants(doc)
    else:
        problems = check_invariants(doc)
    for p in problems:
        print("warning: invariant: %s" % p, file=sys.stderr)
    return 0


def _money(v: float) -> str:
    return "${:,.2f}".format(v) if v >= 0.005 or v == 0 else "<$0.01"


def _human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%d B" % int(n)


def _table(rows: List[List[str]], align: str) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        cells = [cell.rjust(widths[i]) if align[i] == "r" else cell.ljust(widths[i]) for i, cell in enumerate(row)]
        out.append("  ".join(cells).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def cmd_projects(args) -> int:
    cfg = _config(args)
    doc = None
    fp = None
    use_cache = not getattr(args, "no_cache", False)
    if use_cache:
        fp = source_fingerprint(config=cfg)
        doc = load_fast_export(fp)
    if doc is None:
        doc = build_export(config=cfg, cache=_cache(args))
        if use_cache:
            if fp is None:
                fp = source_fingerprint(config=cfg)
            save_fast_export(fp, doc)
    agents = list(AGENT_LABELS)
    rows = [["#", "Project", "Cost", "Sessions", "Last active"] + [AGENT_LABELS[a] for a in agents]]
    projects = doc["projects"] if args.all else doc["projects"][:args.limit]
    for i, p in enumerate(projects, 1):
        by_agent = {a["agent"]: a["cost"] for a in p["by_agent"]}
        name = p["name"] + (" (missing)" if p["path_missing"] else "")
        rows.append([str(i), name, _money(p["cost"]), str(p["sessions"]), p["last_active"] or "-"]
                    + [_money(by_agent[a]) if a in by_agent else "-" for a in agents])
    hidden = doc["projects"][len(projects):]
    if hidden:
        rows.append(["", "(%d more)" % len(hidden), _money(sum(p["cost"] for p in hidden)),
                     str(sum(p["sessions"] for p in hidden)), "", *[""] * len(agents)])
    b = doc["buckets"]
    rows.append(["", "Unattributed", _money(b["unattributed"]["cost"]), str(b["unattributed"]["sessions"]),
                 b["unattributed"]["last_active"] or "-", *[""] * len(agents)])
    rows.append(["", "Excluded", _money(b["excluded"]["cost"]), str(b["excluded"]["sessions"]),
                 b["excluded"]["last_active"] or "-", *[""] * len(agents)])
    rows.append(["", "Parse failed", "-", str(b["parse_failed"]["sessions"]), "-", *[""] * len(agents)])
    rows.append(["", "Total", _money(doc["totals"]["cost"]), str(doc["totals"]["sessions"]),
                 doc["totals"]["last_active"] or "-", *[""] * len(agents)])
    print(_table(rows, "rlrrl" + "r" * len(agents)))
    print()
    print("* " + COST_NOTE)
    print("* Sessions split across projects count once in each project.")
    problems = check_invariants(doc)
    for p in problems:
        print("warning: invariant: %s" % p, file=sys.stderr)
    return 0


def _print_subscriptions(cfg) -> None:
    cfg = cfg or Config()
    found = load_subscriptions(cfg.subscriptions)
    print("subscriptions:")
    if not found:
        print("  none")
        return
    for agent, sub in found.items():
        if sub["monthly_price_usd"] is None:
            price = "unknown price"
        else:
            price = "$%.2f" % sub["monthly_price_usd"]
        _, origin = subscription_value(cfg, agent, "anchor_day", found)
        if origin == "overrides":
            origin = "overrides.json"
        if sub["anchor_day"] is None:
            anchor = "anchor day: unknown (rolling 30 days)"
        else:
            anchor = "anchor day %d (%s)" % (sub["anchor_day"], origin)
        print("  %s: %s, %s, %s, source %s"
              % (agent, sub["plan_label"], price, anchor, sub["source"]))


def _default_config_hint() -> str:
    """``none (defaults; looked in <dir>/attribution.toml|json)`` for the current platform."""
    if not winsupport.is_windows():
        return "none (defaults; looked in ~/.config/kanjo/attribution.toml|json)"
    base = winsupport.kanjo_config_dir()
    return "none (defaults; looked in %sattribution.toml|json)" % winsupport.join(base, "")


def cmd_doctor(args) -> int:
    print("kanjo %s, Python %s" % (__version__, sys.version.split()[0]))
    cfg = None
    try:
        cfg = load_config(args.config)
        print("config: %s" % (cfg.source or _default_config_hint()))
        print("  dominant_threshold=%s aliases=%d overrides=%d exclude=%d"
              % (cfg.dominant_threshold, len(cfg.aliases), len(cfg.overrides), len(cfg.exclude)))
    except ConfigError as exc:
        print("config: ERROR %s" % exc)
    _print_subscriptions(cfg)
    age = disk_cache.cache_age()
    print("disk cache: %s" % disk_cache.cache_path())
    print("  age: %s" % ("%.1f seconds" % age if age is not None else "not available"))
    result = scan(cache=_cache(args))
    led = result.ledger or {}
    print()
    print("ledger: %s" % led.get("path", ""))
    print("  sessions=%d orphaned=%d" % (int(led.get("sessions") or 0), int(led.get("orphaned") or 0)))
    print()
    rows = [["Agent", "Files", "Sessions", "Subagents", "Failed", "Messages", "Log directories"]]
    for agent, st in result.stats.items():
        dirs = ", ".join("%s%s" % (d, "" if os.path.isdir(d) else " (not found)") for d in st.dirs)
        rows.append([AGENT_LABELS.get(agent, agent), str(st.files), str(st.sessions), str(st.subagents),
                     str(st.failed), str(st.messages), dirs])
    print(_table(rows, "lrrrrrl"))
    if result.failed_files:
        print("\nfiles that could not be parsed:")
        for f in result.failed_files[:20]:
            print("  " + f)
        if len(result.failed_files) > 20:
            print("  ... and %d more" % (len(result.failed_files) - 20))
    unsupported = winsupport.unsupported_agents()
    if unsupported:
        print("\nnot supported on Windows:")
        for agent, reason in unsupported.items():
            print("  %s: %s" % (AGENT_LABELS.get(agent, agent), reason))
    return 0


def cmd_ledger(args) -> int:
    ledger = Ledger()
    if args.forget_orphans:
        pending = ledger.summary()["orphaned"]
        if not args.yes:
            print("%d orphaned session(s) in %s" % (pending, ledger.path))
            print("re-run with --forget-orphans --yes to remove them")
            return 0
        print("forgot %d orphaned session(s)" % ledger.forget_orphans())
    info = ledger.summary()
    print(info["path"])
    print("sessions: %d" % info["sessions"])
    print("orphaned: %d" % info["orphaned"])
    print("empty: %d" % info["empty"])
    print("errors: %d" % info["errors"])
    print("size: %d" % ledger.size_bytes())
    return 0


def cmd_accounts(args) -> int:
    from .antigravity_accounts import list_accounts
    from .sources import antigravity
    roots = antigravity.roots()
    result = scan({"antigravity": roots}, cache=_cache(args))
    sessions = dedupe(result.sessions)
    rows = list_accounts(sessions)
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    table_rows = [["Account", "Messages", "Total Tokens", "First Seen", "Last Seen"]]
    for r in rows:
        acc_label = r["account"]
        tok_str = f"{r['tokens']:,}" if r["tokens"] else "0"
        first_str = r["first_seen"] or "-"
        last_str = r["last_seen"] or "-"
        table_rows.append([acc_label, str(r["messages"]), tok_str, first_str, last_str])
    print(_table(table_rows, "lrrrr"))
    return 0


def cmd_agy_account(args) -> int:
    from . import agy_login
    backend = agy_login.get_backend()
    if backend is None and sys.platform != "darwin":
        output = {"status": "error", "message": "only supported on macOS"}
        print(json.dumps(output))
        return 1

    action = getattr(args, "agy_action", None) or "list"
    use_json = getattr(args, "json", False)

    if action == "sync":
        res = agy_login.sync(backend)
        status = 0 if res.get("status") == "ok" else 1
        if use_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if status == 0:
                acc = res.get("account")
                if res.get("synced"):
                    print(f"Synced active login for {acc}")
                else:
                    print(f"Active login up to date ({res.get('reason', '')})")
            else:
                print(f"Sync error: {res.get('message', 'unknown')}", file=sys.stderr)
        return status

    elif action == "switch":
        email = getattr(args, "email", "")
        code, res = agy_login.switch(email, backend)
        if use_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if code == 0:
                print(f"Switched to {res['account']}. Note: {res['note']}")
            else:
                print(f"Error: {res.get('message', 'switch failed')}", file=sys.stderr)
        return code

    elif action == "forget":
        email = getattr(args, "email", "")
        code, res = agy_login.forget(email, backend)
        if use_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if code == 0:
                print(f"Forgot saved login for {res['account']}")
            else:
                print(f"Error: {res.get('message', 'forget failed')}", file=sys.stderr)
        return code

    elif action == "list":
        code, res = agy_login.list_accounts_login(backend)
        if use_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if code == 0:
                table_rows = [["Account", "Saved Login", "Current"]]
                for a in res.get("accounts", []):
                    saved_str = "yes" if a["saved_login"] else "no"
                    curr_str = "● yes" if a["current"] else "no"
                    table_rows.append([a["email"], saved_str, curr_str])
                print(_table(table_rows, "lll"))
            else:
                print(f"Error: {res.get('message', 'list failed')}", file=sys.stderr)
        return code

    else:
        output = {"status": "error", "message": f"unknown action: {action}"}
        if use_json:
            print(json.dumps(output))
        else:
            print(f"Error: unknown action {action}", file=sys.stderr)
        return 1


def _format_disk(doc: dict) -> str:
    rows = [["Agent", "Entry", "Size", "Files", "Newest", "Deletable"]]
    errors = 0
    for agent in doc["agents"]:
        for entry in agent["entries"]:
            state = entry["deletable"]
            if entry["blocked"]:
                state = "%s (%s)" % (state, ",".join(entry["blocked"]))
            files = str(entry["files"])
            if entry["kind"] == "sessions" and "log_files" in entry:
                files = "%d/%d" % (entry["imported_files"], entry["log_files"])
            rows.append([
                agent["label"], entry["id"], _human_bytes(entry["bytes"]),
                files, entry["newest"] or "-", state,
            ])
            errors += entry.get("skipped_errors") or 0
    if len(rows) == 1:
        return "no AI tool directories found"
    lines = [
        _table(rows, "llrrll"),
        "",
        "total %s, reclaimable %s" % (_human_bytes(doc["total_bytes"]), _human_bytes(doc["reclaimable_bytes"])),
    ]
    if errors:
        lines.append("unreadable paths skipped: %d" % errors)
    return "\n".join(lines)


def cmd_paths(args) -> int:
    result = {}
    for agent, module in SOURCES.items():
        if not winsupport.is_supported(agent):
            continue  # no Windows build: not silently broken, just absent
        existing = [os.path.abspath(r) for r in module.roots() if os.path.exists(r)]
        result[agent] = existing
    unsupported = winsupport.unsupported_agents()
    if args.json:
        # Every value must stay a list of paths: the app decodes this map as
        # agent -> [path]. The unsupported agents are listed by `kanjo doctor` and
        # in the text (non-JSON) output instead.
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        for agent, paths in result.items():
            for p in paths:
                print("%s\t%s" % (agent, p))
        for agent, reason in unsupported.items():
            print("%s\tnot supported on Windows: %s" % (agent, reason))
    return 0


def cmd_disk(args) -> int:
    if getattr(args, "disk_cmd", None) == "clean":
        try:
            days = parse_older_than(args.older_than) if args.older_than else None
        except ValueError:
            print("kanjo: --older-than expects a number of days like 30d", file=sys.stderr)
            return 2
        doc = disk_clean(args.ids, older_than_days=days, dry_run=bool(args.dry_run), yes=bool(args.yes))
        sys.stdout.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        return 0
    doc = disk_report(max_age=args.max_age, rescan=args.rescan)
    if args.json:
        sys.stdout.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    else:
        print(_format_disk(doc))
    return 0


def cmd_family_token(args) -> int:
    if not winsupport.is_windows():
        print("On macOS, the family token is managed in the Kanjo App Settings (stored in macOS Keychain).")
        return 0
    action = getattr(args, "token_action", None) or getattr(args, "action", None)
    if action == "set":
        import getpass
        if sys.stdin.isatty():
            token = getpass.getpass("Token: ").strip()
        else:
            token = sys.stdin.readline().strip()
        if not token:
            print("kanjo: empty token", file=sys.stderr)
            return 1
        if winsupport.cred_write("KanjoFamilyReport", token):
            print("token set")
            return 0
        else:
            print("kanjo: failed to save token to Windows Credential Manager", file=sys.stderr)
            return 1
    elif action == "status":
        secret = winsupport.cred_read("KanjoFamilyReport")
        if secret:
            print("set")
        else:
            print("not set")
        return 0
    elif action == "clear":
        winsupport.cred_delete("KanjoFamilyReport")
        print("token cleared")
        return 0
    return 0


def cmd_usage(args) -> int:
    import shutil
    from .tui.model import TimeRange, ViewMode
    from .tui.static import render_static_snapshot
    from .tui.term import HAVE_CURSES, run_curses_tui
    from .tui.i18n import resolve_lang

    lang = resolve_lang(getattr(args, "lang", "auto"))
    cfg = _config(args)
    cache = _cache(args)
    ascii_mode = getattr(args, "ascii", False)
    no_color = getattr(args, "no_color", False) or ("NO_COLOR" in os.environ)
    range_val = TimeRange(getattr(args, "range", "all"))
    view_val = ViewMode(getattr(args, "view", "projects"))
    interval = getattr(args, "interval", 60.0)
    once = getattr(args, "once", False)

    is_static = once or (not sys.stdout.isatty()) or (not HAVE_CURSES)

    use_cache = not getattr(args, "no_cache", False)
    data_path = getattr(args, "data", None)
    doc = None
    antigravity_accounts_data = None
    current_account = None

    if data_path:
        with open(data_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc.get("antigravity_accounts"), dict):
            antigravity_accounts_data = doc["antigravity_accounts"]
            current_account = antigravity_accounts_data.get("current")
    else:
        if is_static:
            if use_cache:
                fp = source_fingerprint(config=cfg)
                doc = load_fast_export(fp)
            if doc is None:
                doc = build_export(config=cfg, cache=cache)
                if use_cache:
                    fp = source_fingerprint(config=cfg)
                    save_fast_export(fp, doc)

            if isinstance(doc.get("antigravity_accounts"), dict):
                antigravity_accounts_data = doc["antigravity_accounts"]
                current_account = antigravity_accounts_data.get("current")
            else:
                try:
                    from .antigravity_accounts import get_account_index, compute_antigravity_accounts_window
                    idx = get_account_index()
                    current_account = idx.get_current_account()
                    from .sources import antigravity
                    roots = antigravity.roots()
                    scan_res = scan({"antigravity": roots}, cache=cache)
                    if scan_res.sessions:
                        antigravity_accounts_data = compute_antigravity_accounts_window(
                            scan_res.sessions, doc, current_account=current_account
                        )
                except Exception:
                    pass
        else:
            # curses mode: start fast! Check fast export cache; if cold, start with None to show "Loading…"
            if use_cache:
                fp = source_fingerprint(config=cfg)
                doc = load_fast_export(fp)
                if doc and isinstance(doc.get("antigravity_accounts"), dict):
                    antigravity_accounts_data = doc["antigravity_accounts"]
                    current_account = antigravity_accounts_data.get("current")

    now_dt = None
    if data_path and doc and doc.get("generated_at"):
        from .tui.model import parse_iso_dt, get_tz
        tz = get_tz(doc)
        now_dt = parse_iso_dt(doc["generated_at"], default_tz=tz)

    if is_static:
        width = 80
        if "COLUMNS" in os.environ:
            try:
                width = int(os.environ["COLUMNS"])
            except ValueError:
                pass
        elif sys.stdout.isatty():
            width = shutil.get_terminal_size().columns

        height = None
        if "LINES" in os.environ:
            try:
                height = int(os.environ["LINES"])
            except ValueError:
                pass

        snapshot = render_static_snapshot(
            doc=doc,
            width=width,
            height=height,
            no_color=no_color,
            ascii_mode=ascii_mode,
            now=now_dt,
            time_range=range_val,
            view_mode=view_val,
            version=__version__,
            antigravity_accounts_data=antigravity_accounts_data,
            current_account=current_account,
            lang=lang,
        )
        sys.stdout.write(snapshot)
        sys.stdout.flush()
        return 0

    import curses
    try:
        return curses.wrapper(
            run_curses_tui,
            initial_doc=doc,
            config=cfg,
            cache=cache,
            interval=interval,
            time_range=range_val,
            view_mode=view_val,
            ascii_mode=ascii_mode,
            no_color=no_color,
            version=__version__,
            antigravity_accounts_data=antigravity_accounts_data,
            current_account=current_account,
            data_path=data_path,
            use_cache=use_cache,
            lang=lang,
        )
    except KeyboardInterrupt:
        return 0


def _max_age(text: str) -> float:
    import math
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("--max-age must be a finite number >= 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kanjo",
        description="How much AI money did each git repo cost? Scans local Claude Code, "
                    "Antigravity CLI and Codex CLI logs and attributes every session to a project.")
    parser.add_argument("--version", action="version", version="kanjo " + __version__)
    sub = parser.add_subparsers(dest="command")

    def common(p, threshold=True):
        p.add_argument("--config", metavar="PATH",
                       help="attribution config (default ~/.config/kanjo/attribution.toml, "
                            "or %%APPDATA%%\\kanjo\\attribution.toml on Windows)")
        if threshold:
            p.add_argument("--threshold", type=float, metavar="F",
                           help="dominant project threshold, overrides dominant_threshold (default 0.8)")
        p.add_argument("--no-cache", action="store_true", help="re-parse every log file")

    p = sub.add_parser("export", help="write the JSON document defined in CONTRACT.md")
    p.add_argument("-o", "--output", metavar="FILE", help="output file (default: stdout)")
    p.add_argument("--compact", action="store_true", help="no indentation")
    p.add_argument("--mobile", action="store_true",
                   help="trim the document to the phone snapshot (CONTRACT.md section 11)")
    p.add_argument("--public-summary", action="store_true",
                   help="export public usage summary document (CONTRACT.md section 12)")
    p.add_argument("--family-report", action="store_true",
                   help="export family usage report document (CONTRACT.md section 13)")
    p.add_argument("--member-label", metavar="NAME",
                   help="display name for member in family report (optional)")
    p.add_argument("--account", action="append", dest="accounts", metavar="EMAIL",
                   help="Google account email to include in report (repeatable, overrides config)")
    p.add_argument("--hide-project-names", action="store_true",
                   help="with --mobile, replace project names and ids with opaque values")
    p.add_argument("--gzip", action="store_true", help="write gzip-compressed JSON to stdout")
    common(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("projects", help="print a table of projects by cost")
    p.add_argument("--limit", type=int, default=25, help="rows to show (default 25)")
    p.add_argument("--all", action="store_true", help="show every project")
    common(p)
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("doctor", help="list log directories, session counts and subscriptions")
    common(p, threshold=False)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("paths", help="list existing log roots per agent")
    p.add_argument("--json", action="store_true", help="output as JSON")
    p.set_defaults(func=cmd_paths)

    p = sub.add_parser("config", help="get, set or unset subscription and quota overrides")
    p.add_argument("config_cmd", choices=("get", "set", "unset", "path", "plans"))
    p.add_argument("key", nargs="?", help="subscriptions.<agent>.<field> or quota_windows.<agent>.weekly_reset")
    p.add_argument("value", nargs="?", help="override value (set only)")
    p.add_argument("--json", action="store_true", help="output as JSON (plans only)")
    p.add_argument("--config", metavar="PATH", help="attribution config; overrides.json is stored beside it")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("ledger", help="show the permanent session ledger")
    p.add_argument("--forget-orphans", action="store_true",
                   help="remove entries whose log file is gone (requires --yes)")
    p.add_argument("--yes", action="store_true", help="actually forget orphaned entries")
    p.set_defaults(func=cmd_ledger)

    p = sub.add_parser("disk", help="show how much disk each AI tool uses")
    p.add_argument("--json", action="store_true", help="print the CONTRACT.md section 10 document")
    p.add_argument("--max-age", type=_max_age, default=600, metavar="SECONDS",
                   help="reuse the disk report for this many seconds (default 600; 0 forces a scan)")
    p.add_argument("--rescan", action="store_true", help="ignore the disk report cache")
    p.set_defaults(func=cmd_disk, disk_cmd=None)
    disk_sub = p.add_subparsers(dest="disk_cmd", required=False)
    c = disk_sub.add_parser("clean", help="move entries into the Trash (nothing moves without --yes)")
    c.add_argument("ids", nargs="+", metavar="ID", help="entry ids from `kanjo disk`")
    c.add_argument("--older-than", metavar="ND", help="only files older than N days, for example 30d")
    c.add_argument("--dry-run", action="store_true", help="print the plan and do not move anything")
    c.add_argument("--yes", action="store_true", help="actually move files; without this, nothing moves")
    c.set_defaults(func=cmd_disk)

    p = sub.add_parser("publish-usage", help="commit and push public usage summary to website repo")
    p.add_argument("--repo", required=True, metavar="PATH", help="path to git repository")
    p.add_argument("--file", default="src/data/token-usage.json", metavar="PATH",
                   help="relative path for token usage JSON (default: src/data/token-usage.json)")
    p.add_argument("--branch", default="main", metavar="BRANCH", help="target branch (default: main)")
    p.add_argument("--dry-run", action="store_true", help="do not write, commit or push")
    common(p, threshold=False)
    p.set_defaults(func=cmd_publish_usage)

    p = sub.add_parser("accounts", help="list detected Antigravity accounts and message stats")
    p.add_argument("--json", action="store_true", help="output as JSON")
    common(p, threshold=False)
    p.set_defaults(func=cmd_accounts)

    p = sub.add_parser("agy-account", help="manage Antigravity CLI Google account logins and switch")
    p.add_argument("--json", action="store_true", help="output as JSON")
    p.set_defaults(func=cmd_agy_account, agy_action="list")
    agy_sub = p.add_subparsers(dest="agy_action", required=False)

    c = agy_sub.add_parser("list", help="list accounts and saved logins")
    c.add_argument("--json", action="store_true", help="output as JSON")
    c.set_defaults(func=cmd_agy_account, agy_action="list")

    c = agy_sub.add_parser("sync", help="sync slot token to saved copy for slot owner")
    c.add_argument("--json", action="store_true", help="output as JSON")
    c.set_defaults(func=cmd_agy_account, agy_action="sync")

    c = agy_sub.add_parser("switch", help="switch active login to email")
    c.add_argument("email", metavar="EMAIL", help="account email to switch to")
    c.add_argument("--json", action="store_true", help="output as JSON")
    c.set_defaults(func=cmd_agy_account, agy_action="switch")

    c = agy_sub.add_parser("forget", help="remove saved login for email")
    c.add_argument("email", metavar="EMAIL", help="account email to forget")
    c.add_argument("--json", action="store_true", help="output as JSON")
    c.set_defaults(func=cmd_agy_account, agy_action="forget")

    p = sub.add_parser("report-family", help="report usage summary to family server")
    p.add_argument("--url", required=True, metavar="URL", help="family server URL (e.g. https://usage.example.com)")
    p.add_argument("--member-label", metavar="NAME", help="display name for member (optional)")
    p.add_argument("--account", action="append", dest="accounts", metavar="EMAIL",
                   help="Google account email to include in report (repeatable, overrides config)")
    common(p, threshold=False)
    p.set_defaults(func=cmd_report_family)

    p = sub.add_parser("family-token", help="manage family report token (Windows Credential Manager)")
    p.add_argument("token_action", choices=("set", "clear", "status"), metavar="ACTION",
                   help="set, clear or check status of family report token")
    p.set_defaults(func=cmd_family_token)

    def add_usage_subcommand(cmd_name: str, help_text: str):
        up = sub.add_parser(cmd_name, help=help_text)
        up.add_argument("--interval", type=float, default=60, help="auto-refresh interval in seconds (default 60)")
        up.add_argument("--once", action="store_true", help="print one snapshot and exit")
        up.add_argument("--no-color", action="store_true", help="monochrome output (also respects NO_COLOR env)")
        up.add_argument("--ascii", action="store_true", help="plain ASCII output, no Unicode")
        up.add_argument("--range", choices=("all", "today", "7d", "30d", "reset", "cycle"), default="all",
                        help="initial time range (default: all)")
        up.add_argument("--view", choices=("projects", "models", "agents", "days", "accounts"), default="projects",
                        help="initial view (default: projects)")
        up.add_argument("--lang", choices=("auto", "en", "zh"), default="auto",
                        help="UI language: auto, en, zh (default: auto)")
        up.add_argument("--data", metavar="PATH", help=argparse.SUPPRESS)
        common(up)
        up.set_defaults(func=cmd_usage)

    add_usage_subcommand("usage", "htop-style full-screen terminal UI for token usage and quotas")
    add_usage_subcommand("top", "alias for `kanjo usage`")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except ConfigError as exc:
        print("kanjo: config error: %s" % " ".join(str(exc).splitlines()), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
