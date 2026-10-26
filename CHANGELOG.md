# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Subscription quota card on hover.** Hovering a row of the Subscription value card shows a quota
  card with the 5-hour and weekly windows (progress bar, percent, relative + absolute reset time;
  expired windows show '—'), from new `quota_windows` fields `weekly_used_percent`,
  `five_hour_used_percent`, and `five_hour_window_hours` read from Tokei caches.
- **Signed DMG and optional notarization.** The DMG is signed with the Developer ID, and
  `ui/package.sh` supports optional notarization via `KANJO_NOTARY_PROFILE` or `--notarize`.

## [0.3.0] - 2026-10-26

### Added

- **Six new agents.** Reads logs from Grok CLI (`~/.grok/sessions`), Qwen Code (`~/.qwen`), Command Code
  (`~/.commandcode/projects`), MiniMax (`~/.minimax/sqlite.db`), OpenCode (`~/.local/share/opencode/opencode.db`),
  and Copilot CLI (`~/.copilot`). MiniMax and OpenCode shared sessions are identified
  and counted only once. Brand colors and a wrapping legend support all nine tools.
- **Subscriptions for all agents.** Grok plans are detected automatically from Tokei's cache
  (`grok_quota_cache.json`), joining Claude and Codex. Built-in list prices for standard plans across
  all nine supported agents. Manage subscriptions directly in Settings or via
  `kanjo config set subscriptions.<agent>.<field>`, with renewal day settings (1–28) and vendor billing
  page links for each service.
- Settings lets you pick a subscription plan from a list of known plans with list prices (or Other… for
  a custom plan).
- **Since reset for every subscription.** Grok's weekly reset is read from Tokei's
  `grok_quota_cache.json`, and any agent can get a manual weekly reset (`'tue 05:00'`) in Settings or
  via `kanjo config set quota_windows.<agent>.weekly_reset`. The `Since reset` and `Billing cycle`
  captions list agents with a window and summarise the rest in one phrase.
- **Localization (Simplified Chinese and French).** Complete UI localization in 简体中文 (`zh-Hans`)
  and Français (`fr`) alongside English, with an in-app language picker in Settings that switches
  immediately without restarting.
- **Localized token units.** Token counts format according to the active language: `k` / `M` / `B` in
  English, plain digits below 10,000, then `万` / `亿` / `万亿` with one decimal (e.g. 1.2万, 258.9亿)
  in Simplified Chinese, and `k` / `M` / `Md` with decimal commas in French.
- **Today time range.** New `Today` segment in the time range picker covering `[today 00:00, now)` in
  the report timezone, with a `· today` menu bar suffix and single-date formatting for one-day ranges.
- **Menu bar tokens mode.** Settings toggle to display either cost (`$`) or total token counts in the
  menu bar, with compact formatting and range suffixes (e.g. `23.5B · 30d`, `235亿 · 30d`).
- **By model breakdown.** Overview panel lists model token usage and API-equivalent cost across all
  projects and buckets for the active time range, sorted by total tokens, with agent dots, estimated
  indicators, and an expand toggle.

### Changed

- **Tidier menu bar label.** Compact amount tiers (< $100 shows cents, $100–$9,999 drops decimals
  with thousand separators, ≥ $10,000 uses compact K/M), time range shown as a middle-dot suffix
  (e.g. `$3,057 · 30d`, omitted for All time), and dropped the redundant dollar icon when an amount or
  token count is shown.
- **Overview header.** The redundant date caption is gone for fixed ranges (Today, 7d, 30d, Last week),
  and the API-equivalent note moved into an ⓘ tooltip next to Total cost.
- **Preview settings isolation (developer).** Preview launches with `--window`, or
  `--defaults-suite <name>` / `KANJO_DEFAULTS_SUITE`, use an isolated settings suite instead of the
  user's settings.

## [0.2.0] - 2026-10-25

### Added

- **Subscription value.** Detects your plan (Claude Max/Pro from `~/.claude.json`, ChatGPT plan
  from Tokei's cache) and shows, per plan, the flat fee next to the API-equivalent usage of the
  current billing cycle and the multiplier between them. Billing cycle dates and "renews in N days"
  on every row; `Billing cycle` time range; per-repo share of each plan's cycle usage.
- **Renewal day you can set.** Renewal days cannot be detected locally, so the app no longer assumes
  the 1st: unknown days use a rolling 30-day window labelled "set renewal day", one click leads to
  the Settings row, an "Open billing page" button opens the vendor's billing page, and
  `kanjo config set subscriptions.<agent>.anchor_day N` stores the day in `~/.config/kanjo/overrides.json`.
- **Permanent ledger.** Every parsed session is kept in `~/.local/share/kanjo/ledger.json`, so
  deleting log files no longer deletes your history. `kanjo ledger` reports counts.
- **Disk.** `kanjo disk` reports how much space each agent's sessions, scratch worktrees, caches
  and memory take, which entries are reclaimable and why others are blocked (not yet imported,
  uncommitted changes, active in the last 24 h). `kanjo disk clean` moves files to the Trash
  (`~/.Trash/kanjo-<timestamp>/`) and removes git worktrees properly. The app's Disk page
  (hard-drive icon in the bottom bar) previews the plan before anything moves. Reports are cached
  for 10 minutes and prefetched in the background, so the page opens instantly.
- Menu bar amount follows the selected time range (`7d $…`, `cyc $…`).

### Changed

- `by_day` entries carry `by_agent` and `by_agent_tokens`; `quota_windows` is read from Tokei's
  cache or set by hand; heat strip cells are split by agent share.
- Nested repositories without a remote fold into the enclosing project.

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

[Unreleased]: https://github.com/mammut001/kanjo/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mammut001/kanjo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mammut001/kanjo/releases/tag/v0.2.0
[0.1.0]: https://github.com/mammut001/kanjo/releases/tag/v0.1.0
