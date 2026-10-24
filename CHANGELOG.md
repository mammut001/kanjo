# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-24

First public release. Before publishing, the project went by the working name `aicost`.

### Added

- **Three agents.** Reads the local logs of Claude Code (`~/.claude/projects`), Codex CLI
  (`~/.codex/sessions`, `~/.codex/archived_sessions`) and Antigravity CLI
  (`~/.gemini/antigravity-cli/conversations`). Nothing is uploaded and conversation text is
  never stored.
- **Per-repo attribution.** Every session is attributed by the files it touched, not where it
  was started. One repo with 80 % of the points takes the whole session, otherwise the cost is
  split. Projects are identified by their git remote, so worktrees and clones merge. Sub-agents
  follow their parent. Unattributed, excluded and unparsable sessions are always shown.
  See `ATTRIBUTION.md`.
- **API-equivalent cost** from Tokei's price table, with family fallback for unknown models
  (marked *estimated*) and a cost note that cannot be hidden.
- **`kanjo` CLI** (Python 3.9+, standard library only): `export` (the JSON in `CONTRACT.md`),
  `projects`, `doctor`. Per-file parse cache, `~/.config/kanjo/attribution.toml` for aliases,
  overrides, excludes and the threshold, and quota windows from the config or Tokei's cache.
- **Kanjo menu bar app** (macOS 13+, SwiftUI, no dependencies):
  - treemap mosaic of projects by cost, colored by each project's dominant agent;
  - 8-week heat strip per project, split by agent share;
  - time range picker: All, 7d, 30d, Last week, Since reset (per-agent quota window);
  - hide and pin projects, with right-click actions (Open in Terminal, Show in Finder, copy
    path or remote);
  - project page with agents, models, daily chart, branches, sessions and locations;
  - Liquid Glass panel and tiles on macOS 26, materials on earlier systems.
- `install.sh` installs the CLI to `~/.local/share/kanjo/cli` with a `~/.local/bin/kanjo`
  launcher; the app finds it there automatically.
- `ui/package.sh` builds an ad-hoc signed `Kanjo.app` and a zip for release.
- GitHub Actions CI for the CLI (Python 3.9 and 3.12) and the app (`swift build`, `swift test`).

[Unreleased]: https://github.com/mammut001/kanjo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mammut001/kanjo/releases/tag/v0.1.0
