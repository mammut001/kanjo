"""Command line interface: ``kanjo export | projects | doctor | ledger | disk | config``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__, disk_cache
from .config import Config, ConfigError, load as load_config, subscription_value
from .config_cmd import cmd_config
from .disk import clean as disk_clean, parse_older_than, report as disk_report
from .export import COST_NOTE, SOURCES, build_export, check_invariants, scan
from .ledger import Ledger
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
    doc = build_export(config=_config(args), cache=_cache(args))
    text = json.dumps(doc, ensure_ascii=False, indent=None if args.compact else 2)
    if args.output and args.output != "-":
        tmp = args.output + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.replace(tmp, args.output)
        print("wrote %s (%d projects, total $%.2f)" % (args.output, len(doc["projects"]), doc["totals"]["cost"]),
              file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
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
    doc = build_export(config=_config(args), cache=_cache(args))
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
        print("  %s: %s, %s, anchor day %d (%s), source %s"
              % (agent, sub["plan_label"], price, sub["anchor_day"], origin, sub["source"]))


def cmd_doctor(args) -> int:
    print("kanjo %s, Python %s" % (__version__, sys.version.split()[0]))
    cfg = None
    try:
        cfg = load_config(args.config)
        print("config: %s" % (cfg.source or "none (defaults; looked in ~/.config/kanjo/attribution.toml|json)"))
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
        p.add_argument("--config", metavar="PATH", help="attribution config (default ~/.config/kanjo/attribution.toml)")
        if threshold:
            p.add_argument("--threshold", type=float, metavar="F",
                           help="dominant project threshold, overrides dominant_threshold (default 0.8)")
        p.add_argument("--no-cache", action="store_true", help="re-parse every log file")

    p = sub.add_parser("export", help="write the JSON document defined in CONTRACT.md")
    p.add_argument("-o", "--output", metavar="FILE", help="output file (default: stdout)")
    p.add_argument("--compact", action="store_true", help="no indentation")
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

    p = sub.add_parser("config", help="get, set or unset subscription overrides")
    p.add_argument("config_cmd", choices=("get", "set", "unset", "path"))
    p.add_argument("key", nargs="?", help="subscriptions.<agent>.<field>")
    p.add_argument("value", nargs="?", help="override value (set only)")
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
