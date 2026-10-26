# Kanjo (macOS menu bar app)

Menu bar app that answers "how much AI money has this git repo cost?" by rendering
the JSON produced by `kanjo export` (format: [`../CONTRACT.md`](../CONTRACT.md)).

- Swift 5.9+, macOS 13+, SwiftUI `MenuBarExtra` + Swift Charts. SwiftPM only, no Xcode project, no dependencies, no network.

## Build / run / test

```bash
cd ui
swift build
swift run Kanjo                       # menu bar icon + total cost; click it for the panel
swift test
```

Development helpers:

```bash
swift run Kanjo --data /path/to/data.json     # use this file (overrides Settings)
KANJO_DATA=/path/to/data.json swift run Kanjo
swift run Kanjo --window                      # also show the panel in a transparent normal window (screenshots/debugging)
swift run Kanjo --window --route project:0    # open straight on a page (for screenshots)
swift run Kanjo --window --route project:0:locations   # project page scrolled to the bottom, Locations expanded
swift run Kanjo --window --route disk --disk-data fixtures/disk-sample.json
swift run Kanjo --window --route disk:expanded --disk-data fixtures/disk-sample.json
```

`--route` values: `overview`, `overview-bottom` (overview scrolled to the buckets and reconciliation),
`project:<index>` (0-based, in cost order), `project:<index>:bottom` (scrolled to the bottom),
`project:<index>:locations` (bottom, with Locations expanded), `bucket:unattributed`, `bucket:excluded`,
`disk`, `disk:expanded` (disk page with every agent expanded, for screenshots), `settings`, `settings-bottom` (Settings scrolled to the bottom).

`--disk-data <path>` loads that disk-report JSON instead of running the CLI. It does not change the usage source (`--data` / Settings).

## Overview: mosaic, heat strips, hide / pin

The overview reads top to bottom as text → graphic → list: the total (with one summary line —
date range · projects · sessions · tokens — and the cost note), the mosaic, then the project list.
The panel is 360 pt wide; its background is Liquid Glass on macOS 26+ and `.regularMaterial` on 13–25.

- **Colors** — one color per agent, light / dark (`Views/Components/AgentPalette.swift`): Claude clay
  `#D97757` / `#E8926F`, Codex blue `#3E79D6` / `#6FA0F0`, Antigravity violet `#7A6AD8` / `#9B8DF0`;
  "+N more" and unknown agents neutral grey `#9A9A9A` / `#6E6E73`. Mosaic tiles, heat strips,
  the project page chart and agent dots all use this set.
- **Mosaic** — under the total, a squarified treemap (`KanjoCore/Treemap.swift`): one tile per project,
  area = cost, color = the project's dominant agent at full saturation (corner radius 4, 2 pt gaps, no stroke).
  Projects under 1.5% of the area merge into a grey "+N more" tile. Click a tile to open the project.
  Labels are never truncated: name + amount only on tiles at least 72 × 40 pt, name alone when the tile is
  at least 72 pt wide but shorter, nothing on smaller tiles or when the name does not fit; every tile has a
  tooltip with the full name and amount.
  On macOS 26+ the tiles are tinted Liquid Glass (`Views/Components/Glass.swift`); older systems get solid fills.
- **Project list** — rows sit directly on the panel (hairline separators, hover highlight). First line: name,
  1–3 agent dots (agents the project used, by cost), `local` / `path missing`, amount. Second line:
  sessions · tokens (`tokens.total`, k / M / B) · last active, and the heat strip.
- **Heat strip** — the last 8 weeks (Mon–Sun) of spend (`KanjoCore/HeatStrip.swift`), summed per agent from
  `by_day[].by_agent`. Each cell is split vertically into up to 3 bands by that week's agent cost shares (largest on top,
  shares under 10% merged into the largest band, no gaps); the whole cell's opacity is one of 5 shades relative to the
  project's busiest week; empty weeks are a neutral grey. Days without `by_agent` (older CLI output) count fully toward
  the project's dominant agent. Hover a cell for the week, the amount and one line per agent (by cost).
  The project page header shows a larger copy.
- **Project page** — the header holds the name, amount + heat strip, sessions · date range, the cost note and one
  remote line (`local repository` when there is none). Local paths live in a **Locations** section at the very bottom,
  collapsed to one line (`7 paths · 16 temporary` · Show); expanded, it lists the main paths (monospaced, middle-truncated,
  full path on hover, selectable) with temporary ones behind their own toggle, struck through when `path_missing`.
- **Hide / pin** — hover a row for the pin and hide buttons (next to the heat strip), or right-click (Pin, Hide, Open in Terminal,
  Show in Finder, Copy path, Copy remote). Pinned projects go first. Hidden projects leave the list and the mosaic;
  "N hidden · $X · Show" at the bottom of the list brings them back. The total stays the report total.
  Stored as newline-separated project ids in `@AppStorage` keys `hiddenProjects` / `pinnedProjects`
  (parsing in `KanjoCore/ProjectPrefs.swift`); Settings has "Unhide all".

## Time range

A compact segmented control — All · Today · 7d · 30d · Last week · Since reset · Cycle — sits right of "Total cost" on the overview
and under the name on the project page (one shared choice, `@AppStorage("timeRange")`, default `all`).
Definitions follow CONTRACT.md §6.1; the engine is `KanjoCore/TimeRange.swift` (pure, tested in `TimeRangeTests`):

- **Today** — `[today 00:00, now)`; **7d / 30d** — `[today − 6 (29) days 00:00, now)`; **Last week** — previous Monday 00:00 to this Monday 00:00;
  days are cut in the report's `timezone` (falls back to the Mac's).
- **Since reset** — each agent from the start of its own weekly window in `quota_windows`
  (`weekly_resets_at − weekly_window_hours`, shifted by whole windows so that start ≤ now < start + window).
  Agents without a quota window are left out and named in the caption ("Antigravity: no reset info").
  Without any `quota_windows` the segment is greyed out with the tooltip "No reset info".
- **Billing cycle** — each agent from its own `subscriptions[agent].cycle_start` through now.
  Agents without a subscription are left out and named in the caption ("Antigravity: no subscription").
  Without any `subscriptions` the segment is greyed out with the tooltip "No subscription info".
- Project cost / tokens add up `by_day[].by_agent` / `by_agent_tokens` for every day that overlaps the range
  (per agent for Since reset); days without those fields count fully toward the project's dominant agent.
  Session counts use `sessions_detail[].started`. Buckets have no daily data, so they are filtered by session start.
- Outside All: the hero, summary line, mosaic, rows (amount, sessions, tokens, heat strip), buckets and
  "N hidden · $X" use filtered values; projects with no usage in the range are dropped, with
  "N projects with no usage in this range" under the list; a caption under the summary explains the range;
  the reconciliation line is shown only for All; the cost note always. On the project page the token type
  breakdown is hidden (only the total is known per day), and By model / By branch keep all-time numbers with an "All time" tag.
- The menu bar amount follows the range too: the filtered total with a tiny prefix — `7d $…`, `30d $…`,
  `wk $…` (Last week), `rst $…` (Since reset), `cyc $…` (Billing cycle) — and the plain report total for All.
- Settings → **Quota reset** lists each agent's next weekly reset, its window start and the source
  (`tokei` / `manual` / `none`); reset times can be set by hand in `~/.config/kanjo/attribution.toml`.

Screenshot tip: `-timeRange days7` (or `all`, `today`, `days30`, `lastWeek`, `sinceReset`, `billingCycle`) presets the range for one launch.
Preferences can be preset for one launch without persisting them, through the
`NSArgumentDomain`, e.g. `.build/debug/Kanjo --window -hiddenProjects $'github.com/a/b\ngithub.com/c/d'`.

## Subscription value

Under the total (above the mosaic) when `subscriptions` is non-empty: one row per subscribed agent, sorted by this cycle's API-equivalent cost — plan, monthly price, usage from that agent's `cycle_start` through now across every project and both buckets, and the multiple of the flat fee (`usage ÷ monthly_price_usd`, shown as `15.7×`, or `—` when the price is null). An "extra usage on" badge appears when `extra_usage_enabled` is true. The rows ignore the selected range. The block always includes: "You pay the flat fee on the left. The number on the right is what the same work would cost on API billing." On a project, under By agent: "This repo: N% of your <plan> usage this cycle" (skipped when that agent's cycle total is zero). Known renewal days show cycle dates in the report timezone and a renewal countdown; project share lines show the cycle on hover.

When the day is unknown (`rolling_30d`, `anchor_day: null`), the row shows "Last 30 days · set renewal day for exact cycle". Clicking the caption opens Settings at that agent's Subscriptions row (`--route settings:subscriptions:codex` also works). The Cycle range explains these agents as "last 30 days (day not set)". Settings → Subscriptions starts an unknown day at 1 with "not set · using last 30 days", lets you apply a renewal day (1–28) or reset it through the configured CLI, and provides an "Open billing page" link to find the renewal date. Editing is disabled for JSON file sources; billing links remain available. A quiet "Renewal days not set … · Set now" reminder under the card opens the same row. Dismissing it stores the agent keys as a comma-separated list in `@AppStorage("renewalNudgeDismissed")`; only newly appearing rolling agents trigger another reminder.

## Disk

The disk page (internal-drive icon in the bottom bar, or `--route disk`) shows how much space each AI tool's data takes and what can be moved to the Trash. It reads a separate document from usage: `kanjo disk --json` ([`../CONTRACT.md`](../CONTRACT.md) §10).

Disk reports are prefetched in the background about 15 seconds after the first usage refresh finishes, then after each usage refresh tick; opening Disk shows the latest report while manual refresh and cleanup force a rescan.
The last report is atomically cached at `~/Library/Caches/com.lanshuagent.kanjo/disk-report.json` and restored at launch; missing or corrupt caches are ignored.

- **Hero** — `Total` and `Reclaimable` (the reclaimable number in the accent color). Reclaimable is every entry whose `deletable` is not `never` and whose `blocked` list is empty. The caption is "Numbers stay in the ledger after cleanup".
- **By agent** — one quiet bar per agent, same style as By agent on the project page, width proportional to bytes (`Codex CLI · 11.8 GB`). Expand an agent for its entries: kind badge, middle-truncated path (full path on hover), size, file count, newest date, and a state pill. `Reclaimable` is green. `Blocked: not imported`, `Blocked: uncommitted changes`, and `Blocked: active` are amber, each with a one-sentence tooltip. `Kept` is for `never`.
- **Cleanup** — check the reclaimable entries. `Older than` is Any / 7d / 30d / 90d and is passed as `--older-than` (Any omits the flag). `Clean N items · …` runs `kanjo disk clean <ids> [--older-than Nd] --dry-run`, then a confirmation sheet lists the paths grouped by entry with count and size. **Move to Trash** runs the same command with `--yes`. The CLI moves files into the Trash; the app never deletes files itself. The result shows `freed_bytes` and anything skipped (with the reason), then the report reloads.
- The disk command is the configured CLI command with the last standalone `export` replaced by `disk --json`, so a leading `export PATH=...` is left alone. The working directory is the same one usage export uses. Settings shows that derived command on one line in the CLI section.

`--disk-data <path>` (dev flag) reads a disk-report JSON file instead of the CLI, for screenshots and tests. Cleanup from a file source is refused — there is no CLI call, and nothing is moved. `--route disk:expanded` opens every agent; it exists for screenshots.

`fixtures/disk-sample.json` is generated by `fixtures/generate_disk_sample.py`.

## Data source

Pick it in the panel's **Settings** (gear icon). Values are stored with `@AppStorage`.

| Source | What it does |
|---|---|
| JSON file (default) | Reads a contract JSON file. Leave the path empty to use `fixtures/sample.json`. |
| CLI command | Runs a command (default `python3 -m kanjo export`) through `/bin/zsh -l -c` in the working directory you set and parses stdout. Left empty, the working directory is the bundled CLI, then the repo's `cli/` (DEBUG only), then `~/.local/share/kanjo/cli` (where `../install.sh` puts it), then `/usr/local/share/kanjo/cli`. |

Lookup order: `--data` → `KANJO_DATA` → Settings → `fixtures/sample.json`.
The default source is the CLI when one of those directories exists, otherwise the JSON file.
Auto refresh defaults to every 5 minutes. You can also hide the dollar amount in the menu bar.

If loading fails, the panel shows the error: invalid JSON, a missing field with its path (e.g.
`projects[1].by_day`), or the command's exit status and stderr. If a refresh fails after a
successful load, the previous data stays on screen under a red banner.
If `schema_version` is newer than 1, a warning appears and the app keeps rendering.

## Packaging

```bash
./package.sh            # version from ../VERSION
./package.sh 0.2.0      # explicit version
./package.sh --icon     # also re-render Resources/Kanjo.png and Kanjo.icns
```

Builds arm64 and x86_64 release slices separately with SwiftPM and merges them with `lipo`.
Outputs `build/Kanjo.app`, `build/Kanjo-<version>-macos.zip`, and a compressed DMG containing
Kanjo.app and an Applications link. Use `--no-dmg` to skip the DMG or `--arch arm64` for a quick build.
Build artifacts stay under `build/`. The bundle targets macOS 13+ and includes the CLI package,
pricing files, VERSION, and fallback sample JSON.

Signing uses `KANJO_CODESIGN_IDENTITY` when set; otherwise it detects a Developer ID Application
identity, falling back to ad-hoc (`-`). Developer ID signing uses hardened runtime and timestamps;
the binary, app, and DMG are signed and verified. No notarization is performed yet.

With an empty CLI working directory, lookup order is bundled CLI → repository cli/ (DEBUG only)
→ `~/.local/share/kanjo/cli` → `/usr/local/share/kanjo/cli`. Settings shows the selected CLI and bundled
version. Python 3 via Command Line Tools is required; missing tools show an installer button and Retry.
The icon is drawn by `Resources/make_icon.swift` (AppKit, offscreen); the PNG and `.icns` are committed.

## Layout

```
Package.swift
Sources/KanjoCore/       contract models (Codable), data sources, formatting, reconciliation,
                          treemap / heat strip / project prefs pure functions (no UI)
Sources/Kanjo/           SwiftUI app: KanjoApp, Store/ReportStore, Views/…
Tests/KanjoTests/        decoding + invariant tests on fixtures/sample.json, formatting, treemap, heat strip, prefs tests
fixtures/sample.json     test data (8 projects, 3 agents, split/cwd sessions, estimated models, buckets)
fixtures/generate_sample.py   regenerates sample.json deterministically and asserts the invariants
fixtures/disk-sample.json     disk page sample (5 agents); fixtures/generate_disk_sample.py regenerates it
Resources/                Kanjo.png / Kanjo.icns app icon and make_icon.swift that draws it
package.sh               universal .app + zip + DMG
```
