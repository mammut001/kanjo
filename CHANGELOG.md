# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Kanjo for Windows.** A native Avalonia app (`windows/`) with the same tray panel, pages, hover cards and background behaviour as the Mac app, sharing the Python CLI and the same JSON contract. Ships as `Kanjo-win-x64-Setup.exe` / `Kanjo-win-arm64-Setup.exe`: per-user install in `%LOCALAPPDATA%\Kanjo` with **no admin rights**, official embeddable Python 3.12.8 and the CLI bundled, so no Python install is needed. Start menu shortcut, no desktop shortcut, automatic updates from GitHub Releases (checked 30 s after launch and every 6 h, applied on the next start; a "Restart to update" tray item appears once a download is ready). Uninstall keeps your data (`%APPDATA%\Kanjo`, `%LOCALAPPDATA%\kanjo`).
- **Windows app CI** (`windows-app` job): `dotnet build -warnaserror` + `dotnet test` on every push, and installer builds for win-x64 / win-arm64 on `v*` tags, uploaded as artifacts and attached to the matching release when it exists.
- **The CLI runs on Windows.** Agent logs are found in their real Windows locations (`%USERPROFILE%\.claude`, `%USERPROFILE%\.codex`, `%USERPROFILE%\.gemini`, `%APPDATA%\<app>`, `%LOCALAPPDATA%\<app>`); Kanjo's own files live in `%APPDATA%\kanjo` (config) and `%LOCALAPPDATA%\kanjo` (ledger, cache). `kanjo disk` and `disk clean` work on Windows and move files to the **Recycle Bin** (`SHFileOperationW`) instead of `~/.Trash`; the result reports `"trash_dir": "Recycle Bin"`. Claude quota reads the OAuth token from `%USERPROFILE%\.claude\.credentials.json`. A file locked by a running agent is a per-item `move_failed`, not a failed run.
- **Windows CI runs the full CLI suite** (Python 3.9 and 3.12), not just the reporter tests.

### Changed

- Project attribution compares Windows paths case-insensitively and treats `\` and `/` alike, so session cwds written by Node tools (`c:/users/...`) match repos on disk; `%TEMP%` and `%LOCALAPPDATA%\Temp` count as temporary like `/tmp`.
- Timezones fall back to the current UTC offset when `zoneinfo` has no database (the normal case on Windows without `tzdata`): quota and billing-cycle dates still work, nothing crashes.
- macOS-only agents (Grok Bot, QoderWork, Qoder IDE, MiMo Code) are silently skipped on Windows and listed by `kanjo doctor` / `kanjo paths` instead of erroring.

## [0.5.1] - 2026-11-12

### Added

- **Windows family reporter.** A no-admin PowerShell installer (`install-family-windows.ps1`) sets up the CLI, stores the token in Credential Manager and reports every 30 minutes.
- **Homebrew.** `brew install --cask mammut001/kanjo/kanjo`.

### Changed

- **Family usage is self-hosted and opt-in.** No built-in server address: Settings asks whether you join a family (enter its address and token) or host one ([deployment guide](family-server/DEPLOY.md)). Existing members who had reporting on keep their old address. The Windows installer requires `-Server`.

## [0.5.0] - 2026-11-09

### Added

- **Family usage.** Opt-in reporting to a self-hosted family server (`family-server/`): per-member tokens, Keychain-stored token, reports after refreshes (at most every 15 minutes). The server shows a Google-sign-in dashboard (allowlisted emails only) with the Google AI Ultra quota pool (Gemini and Claude/GPT windows), per-member usage per manager-set billing cycle, and who used the pool. Reports default to Antigravity only and never contain project names, paths, titles or emails.
- **Publish usage to a website.** `kanjo export --public-summary` and `kanjo publish-usage`, plus a scheduled "Publish to website" setting.
- **29 agent sources (up from 9).** Pi, QwenWork and the Tokei-parity sources (WorkBuddy, Grok Bot, Qoder, ZCode, Kimi Code, Muse, CodeBuddy, Hermes, OpenClaw, Devin, MiMo Code, Prime Agent, OMP, DeepSeek Harness, …).
- **Subscription accounts.** The subscription hover card shows the detected account email (never sent to iPhone or any server).
- **Pricing.** StepFun Step 5 Preview and Gemini 4 Argon; model variants are merged in summaries.

### Changed

- **Quiet background refresh.** Refreshes follow log changes (FSEvents) instead of a 5-minute timer; the disk report no longer runs after every refresh; incremental export takes about 1.4 s of CPU. Background CPU over 5 minutes dropped from about 55 s to about 3 s.
- **Releases are notarized.** One universal build for Apple silicon and Intel Macs.

### Fixed

- The "Parse failed" row is hidden when nothing failed.

## [0.4.0] - 2026-11-01

### Added

- **First iOS companion app (`ios/`).** View token spend on iPhone powered by the shared `KanjoCore` package. Features full Overview (Total, Treemap Mosaic, Subscription Value, Projects), Project Detail, By Model breakdown, and live iCloud sync via CloudKit private database.
- **Collapsible subscription value card on iOS.** Mirrors macOS behavior on iOS, showing the top 3 subscriptions by default with a "Show N more" / "Show less" toggle button and preserving custom order.
- **Mobile export format (`kanjo export --mobile`).** Adds `--mobile` flag and optional `--hide-project-names` to export compact JSON snapshots tailored for mobile and cloud sync.
- **iCloud account matching code.** Displays a 4-character account verification code in macOS and iOS footers to verify device pairing.

### Fixed & Performance

- **Parse cache bloat and speedup (v4).** Fixed a session aliasing bug where multi-file rollouts (e.g. Codex) compounded `tool_paths` and `cwd_counts` across runs, bloating the parse cache up to 276 MB. Deep-copying sessions on cache load and copy-on-write merging reduced warm export times by ~3.3x and shrunk cache size by 75% to 69 MB.
- **O(depth) path prefix resolution.** Replaced linear $O(|table|)$ scans in `Resolver._lookup_prefix` with parent-component traversal.
- **Model price coverage & normalization.** Added `openai/gpt-6.1-terra` to pricing table; normalized Antigravity variant suffixes (`-low`, `-high`, `-thinking`, `-n`, `-tiered`, etc.) and Grok build suffixes (`-build`, `-build-fast`); added agent fallback defaults for `grok`, `qwen`, and `commandcode`; resolved `:free` tiers on uncatalogued models to $0 cost.
- **Refreshed README & deterministic sample screenshots.** Updated all screenshots in `docs/screenshots/` generated from test fixtures.

## [0.3.4] - 2026-10-27

### Added

- **Claude Desktop HTTP cache fallback for quota windows.** When Claude Code CLI credentials are absent or expired in Keychain, Kanjo falls back to scanning Claude Desktop's local Chromium HTTP cache (`~/Library/Application Support/Claude/Cache/Cache_Data`, configurable via `KANJO_CLAUDE_CACHE_DIR`) for recent `/usage` responses, parsing active 5-hour and weekly utilization and reset timestamps.
- **Refreshed README and screenshots.** Updated documentation and screenshots (generated strictly from deterministic sample fixtures) covering collapsible subscription cards, Antigravity multi-window quota hover cards, and standalone quota fetching.

## [0.3.3] - 2026-10-27

### Added

- **Independent provider quota fetching.** Kanjo can now fetch live quota windows directly from providers (Antigravity with Gemini 5h/weekly and Claude/GPT extra windows, Codex, Claude, Grok) without relying on Tokei, caching results locally with 5-minute TTL.
- **Quota source label.** Live-fetched quota windows are marked `source: "live"`; Tokei cache stays `"tokei"`.
- **Extra quota windows support.** Support for `extra_windows` in Antigravity's quota card rendering additional quota bars (e.g. Claude/GPT models) in the hover card.

### Fixed

- **Antigravity 2.0 app session discovery.** Antigravity 2.0 writes SQLite logs to `~/.gemini/antigravity/conversations/` in addition to the legacy CLI location `~/.gemini/antigravity-cli/conversations/`. Kanjo now scans both directories by default and deduplicates overlapping conversation IDs by preferring the most recently modified database.
- **Missing subscription hover card localizations.** Added missing localization keys `settings.subscriptions.price` and `overview.cycle_usage` across English, Simplified Chinese, and French, and added an automated source audit test ensuring all `L10n.tr` keys exist in localization catalogs.

## [0.3.2] - 2026-10-27

### Added

- **Collapsible, reorderable Subscription value card.** The card shows 3 rows by default with a
  "Show N more" toggle, and rows can be dragged to choose which 3 stay on top (order is saved).
- **Colored hover cards everywhere**, replacing all system tooltips.
- **Slow first scan hint** in the UI.

### Changed

- **Faster exports.** Faster warm export (repo resolution cache) and faster cold export.

### Fixed

- **Concurrent refresh crash.** `Ledger.save()` and `kanjo export -o` used a fixed `.tmp` file, so two
  simultaneous runs could fail with `FileNotFoundError`; they now use unique temp files.

## [0.3.1] - 2026-10-26

### Added

- **Subscription quota card on hover.** Hovering a row of the Subscription value card shows a quota
  card with the 5-hour and weekly windows (progress bar, percent, relative + absolute reset time;
  expired windows show '—'), from new `quota_windows` fields `weekly_used_percent`,
  `five_hour_used_percent`, and `five_hour_window_hours` read from Tokei caches.
- **Signed DMG and optional notarization.** The DMG is signed with the Developer ID, and
  `ui/package.sh` supports optional notarization via `KANJO_NOTARY_PROFILE` or `--notarize`.
- **Sample fixtures and README screenshots.** Updated sample data and disk fixtures cover all nine
  supported agents, with refreshed light and dark mode screenshots in the README.

### Changed

- **Cleaner session titles.** Session titles strip lead-in system tags, environment instructions,
  work paths, diff snippets, and standalone slash commands, falling back to the next meaningful
  prompt. Codex titles are extracted from the first actual user prompt rather than internal JSON
  payloads or boilerplate.
- **Safer packaging options.** `ui/package.sh` parses `--notarize` flags without mistaking version
  arguments for keychain profile names, strips optional `v` prefixes, and fails early with a clear
  message if notarization is requested without a Developer ID certificate.

### Fixed

- **DST-safe weekly quota resets.** Weekly 168-hour quota windows calculate resets using calendar week
  intervals instead of fixed hourly offsets, keeping the weekly reset at the same local wall-clock
  time across Daylight Saving Time transitions (spring forward and fall back).
- **MiniMax and OpenCode de-duplication safety.** OpenCode session scanning skips the scan if the
  MiniMax database exists but cannot be read to prevent double-counting shared sessions, and MiniMax
  usage parsing generates unique keys even when turn IDs repeat.
- **Case-insensitive localization lookup.** UI bundle lookup normalizes language codes and matches
  `.lproj` directories case-insensitively, resolving missing Chinese (`zh-Hans`) strings on newer
  Xcode and macOS CI runners.

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

[Unreleased]: https://github.com/mammut001/kanjo/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/mammut001/kanjo/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/mammut001/kanjo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mammut001/kanjo/releases/tag/v0.2.0
[0.1.0]: https://github.com/mammut001/kanjo/releases/tag/v0.1.0
