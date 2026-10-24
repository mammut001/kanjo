"""Command line interface: ``kanjo export | projects | doctor``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .config import Config, ConfigError, load as load_config
from .export import COST_NOTE, SOURCES, build_export, check_invariants, scan
from .sources.base import AGENT_LABELS


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


def cmd_doctor(args) -> int:
    print("kanjo %s, Python %s" % (__version__, sys.version.split()[0]))
    try:
        cfg = load_config(args.config)
        print("config: %s" % (cfg.source or "none (defaults; looked in ~/.config/kanjo/attribution.toml|json)"))
        print("  dominant_threshold=%s aliases=%d overrides=%d exclude=%d"
              % (cfg.dominant_threshold, len(cfg.aliases), len(cfg.overrides), len(cfg.exclude)))
    except ConfigError as exc:
        print("config: ERROR %s" % exc)
    result = scan(cache=_cache(args))
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

    p = sub.add_parser("doctor", help="list the log directories found and their session counts")
    common(p, threshold=False)
    p.set_defaults(func=cmd_doctor)
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
        print("kanjo: config error: %s" % exc, file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
