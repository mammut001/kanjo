# aicost

**How much AI money did each git repo cost?**

`aicost` scans the local logs of your AI coding agents once, attributes every session to a
project, and answers one question per repo: what did it cost in total. Not per day, not per
agent. Per project, across every agent you used.

> Working name. The project is not published yet.

## What it looks like

A macOS menu bar app shows the total in the status bar. The panel lists projects by cost,
and each project breaks down by agent, model, day, branch and session.

```
FocusApp            $1,196.29   153 sessions   Claude Code · Codex CLI · Antigravity CLI
tcf-canada          $1,035.33   192 sessions
Conveyor              $422.12    40 sessions
```

Every number is an **API-equivalent cost**: tokens × public API price. It is what the same
work would have cost on pay-as-you-go billing. If you pay a subscription, it is not what
you paid. The app shows this note and does not let you hide it.

## Supported agents

| Agent | Logs read |
|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` |
| Antigravity CLI | `~/.gemini/antigravity-cli/conversations/*.db` |
| Codex CLI | `~/.codex/sessions/**/*.jsonl` |

Everything runs locally. Nothing is uploaded. Only token counts, paths and timestamps are
read; conversation text is never stored.

## How attribution works

A session is attributed by **what it touched**, not where it was started. Every file the
agent read, wrote or ran a command on scores a point for the repo that file lives in. One
repo with 80 % or more of the points takes the whole session; otherwise the cost is split
by points. Sessions that touched nothing fall back to their working directory, and
sessions that cannot be placed go to an explicit *unattributed* bucket that is always
shown.

A project is identified by its git remote, so worktrees, forks on disk and multiple clones
of the same repo count as one project.

The full rules are in [ATTRIBUTION.md](ATTRIBUTION.md). The code implements them as written.

## Quick start

CLI (Python 3.9+, standard library only):

```bash
cd cli
python3 -m aicost doctor      # which logs were found
python3 -m aicost projects    # table of projects by cost
python3 -m aicost export -o data.json
```

Menu bar app (macOS 13+, Swift 5.9+, no dependencies):

```bash
cd ui
swift run AICost
```

By default the app runs `python3 -m aicost export` from the `cli/` directory next to it and
refreshes every five minutes. Settings let you point it at a different command or at an
exported JSON file instead. A packaged `.app` will ask once for access to the folders
that hold your repos (for example Documents), because attribution reads `.git` files there.

## Repository layout

```
ATTRIBUTION.md   attribution rules (normative)
CONTRACT.md      JSON format between CLI and app (the only interface)
cli/             Python CLI: parsers, attribution, pricing, export
ui/              SwiftUI menu bar app (SwiftPM; AICostCore library + AICost executable)
```

The CLI and the app are developed independently and meet only at the JSON described in
[CONTRACT.md](CONTRACT.md).

## Configuration

Optional, at `~/.config/aicost/attribution.toml` (or `attribution.json` on Python < 3.11):
merge identities with `aliases`, force a path prefix onto a project with `overrides`, drop
paths with `exclude`, and tune `dominant_threshold`. See ATTRIBUTION.md section 8.

## Pricing

Prices come from [Tokei](https://github.com/cclank/tokei)'s `pricing.json` (MIT). Models
missing from the table are priced by their closest known relative and marked *estimated*
in the output and the app.

## Relationship to Tokei

Tokei is a menu bar dashboard for quotas and daily usage across many tools. `aicost` asks a
different question, the total bill of one repo, and is built to be run inside a repo and
shared with collaborators. They read the same logs and share a price table, nothing else.

## License

MIT.
