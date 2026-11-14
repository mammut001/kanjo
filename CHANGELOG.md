# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Antigravity accounts: no more phantom accounts from interleaved log lines.** When two `agy` log
  lines get written on top of each other, the email is now only accepted up to a boundary, so a torn
  line no longer shows up as a bogus second account. The account cache is re-parsed automatically.
- **Antigravity account switching actually finds the current login.** Slot ownership now comes from the
  launch logs' login and token-refresh events (and a keychain reload by a freshly launched `agy`), so
  `kanjo agy-account sync`/`switch` save and switch the right account instead of always reporting
  "Sign in once with agy". Ambiguous evidence is never guessed.
- **Antigravity quota: Claude/GPT windows are labelled, not duplicated.** The Claude/GPT weekly and
  5-hour buckets get their own label ("Claude/GPT · Weekly" / "Claude/GPT · 5-hour", localized) instead
  of echoing the generic "… Limit Remaining" text next to the Gemini rows.
- **Windows CI: the TUI test module imports without `curses`.** Tests that drive the interactive UI are
  skipped when `curses` is unavailable; everything else still runs on the Windows Python jobs.
- **Antigravity switch note.** `kanjo agy-account switch`/`list` now report `running_agy` (how many `agy`
  processes are running), and the app and `kanjo usage` warn that running sessions must be quit or
  restarted or they will switch the account back at their next token refresh.

## [0.6.0] - 2026-11-13

### Added

- **`kanjo usage` (alias `kanjo top`): an htop-style terminal view.** For Linux servers over SSH and any
  terminal: totals and agent share bar, quota meters per subscription (weekly, 5-hour and extra windows,
  yellow from 80 %, red from 95 %), and a scrollable table with Projects (agent dots, 8-week heat strip),
  Models, Agents, Days and Antigravity Accounts views. Enter opens a project's detail pane; `/` filters,
  `s` sorts, `1`–`6` switch the time range, `?` shows help. Refreshes in the background every 60 s
  (`--interval`). English and Chinese (`--lang`, follows the app language or `LANG`; Chinese uses 万/亿).
  `--once`, or piping the output, prints a single snapshot; on Windows it always prints a snapshot.
  Pure Python, no dependencies. Mouse works like htop: click a range tab, an F-key, a row (click again to
  open it) or a column header to sort; the wheel scrolls; `--no-mouse` keeps normal text selection.
- **Antigravity accounts.** Kanjo works out which Google account each Antigravity CLI message was sent
  from (from the CLI's launch logs) and lists every account with its usage this quota week: in the Mac app
  (click the Antigravity row of the Subscription value card), in `kanjo usage` (Accounts view) and with
  `kanjo accounts`. Usage the desktop app made stays "unattributed".
- **Switch the Antigravity CLI account in one click (macOS).** Each account you have signed in with once is
  saved in your Keychain; the Mac app's Switch button, Enter in `kanjo usage`'s Accounts view, or
  `kanjo agy-account switch EMAIL` puts it back. The login is passed to `security` on stdin and never
  printed; a login Kanjo has not saved yet is never overwritten. Running agy sessions keep their account
  until restarted.
- **Family report: choose accounts.** `family.accounts` in `attribution.toml` or
  `kanjo report-family --account EMAIL` reports only those Antigravity accounts. Emails are never sent.
- **Family usage reporting on Linux.** `scripts/install-family-linux.sh` installs the reporter without root,
  asks for the server, token (hidden input, stored with mode 600) and label, reports every 30 minutes
  through cron or a systemd user timer and sends a first report. `--uninstall` removes everything.

Updating:
- **Mac:** use in-app update (menu-bar panel or Settings → Check for Updates…), or `brew upgrade --cask kanjo`.
- **Windows:** the installed app updates itself.

## [0.5.4] - 2026-11-12

### Fixed

- **Windows: the family token Save button stayed disabled after pasting a token.** The Settings →
  Family usage → Report token prompt worked out whether Save was available once, while the box was still
  empty, so the button kept its disabled look and the click handler kept the empty string it had captured —
  typing or pasting a token never got you any closer to saving it. Save now follows the text box as you type
  (whitespace-only still counts as empty), the token is read at click time, Enter saves and Escape cancels,
  and the same build-time-`enabled` mistake is fixed on **Report now**, which also depends on the server URL
  field. Both buttons switch between the normal accent button and the existing disabled look, so a disabled
  button still reads as unavailable. `StateButton` in the Fluent theme is the shared helper, and a headless
  test drives the whole prompt (open it, type, click, check what the token storage received).

## [0.5.3] - 2026-11-12

### Added

- **In-app updates on macOS (Sparkle).** Kanjo now ships Sparkle 2 in the `Kanjo` executable (only;
  `KanjoCore` stays dependency-free for the iOS app) and checks
  `https://github.com/mammut001/kanjo/releases/latest/download/appcast.xml` once a day. A found update
  appears as a "Kanjo X is available — Update" row at the top of the menu-bar popover, because a scheduled
  check in an `LSUIElement` app otherwise shows its window behind every other app; clicking the row brings
  Sparkle's window forward, and Install installs in place and relaunches. Settings gained an **Updates**
  section (current version, automatic checks, "Check for Updates…", last check time). `package.sh` now
  embeds and signs `Sparkle.framework` inside-out and derives `CFBundleVersion` from the version
  (`0.5.2` → `502`), and `scripts/make-appcast.sh` signs the release zip into `appcast.xml` with
  `sign_update --account kanjo`. The updater only starts from a packaged `.app` whose `Info.plist` has a
  real `SUFeedURL` / `SUPublicEDKey`, so `swift run`, `--snapshot`, `--window` and `--data` are unaffected.
- **Windows: update banner and Check for updates in Settings.** When a release is downloaded, the panel now
  shows a Fluent InfoBar-style banner at the top of every page — "Kanjo X.Y.Z is ready" with a
  **Restart to update** accent button that runs the same `UpdateService.RestartToUpdate` path as the tray menu.
  While downloading it reads "Downloading Kanjo X.Y.Z… NN%" with a progress bar underneath. The ✕ dismisses it
  for the current run only; a relaunch brings it back if the update is still pending. Settings has a new
  **Updates** card below Appearance with the current version, the last check time and a button that follows the
  state: **Check for updates** / *Checking for updates…* / *Downloading… NN%* / **Restart to update**, plus a
  short retryable message on failure. When the app isn't a Velopack install (dev run, portable / unzipped
  folder, `--snapshot` / `--window`) the card shows the version and "Updates are only available in the
  installed version" with the button disabled, and nothing touches the network.
  `UpdateService` now exposes an `UpdateStatus` (Idle / Checking / UpToDate / Downloading(progress) /
  Ready(version) / Failed) driven by a small `UpdateCoordinator` state machine in Core that takes an
  `IUpdateManager`, so concurrent scheduled / manual checks collapse into one and the status is unit-tested
  with a fake manager; download progress comes from Velopack's `DownloadUpdatesAsync` callback. Notifications
  are marshalled to the UI thread like the rest of the app, and the existing 30 s / 6 h schedule and
  auto-apply-on-startup are unchanged. All new strings are localised (en / zh-Hans / fr through
  `WindowsL10n`), and `--snapshot-update ready|downloading|not-installed|…` renders the banner and the
  Updates card in both themes (`update-banner-*-light/dark.png`, `settings-update-*-light/dark.png`).

- **Windows: an Appearance setting.** Settings has a new Appearance card right below Language with
  **Dark** (the new default on Windows), **Light** and **System** (follow Windows). The label and the three
  choices are localised like the rest of the app. The choice is stored in the same settings file as Language
  (`appearance`; a missing value means Dark) and applies live — no restart — by switching
  `Application.RequestedThemeVariant`; **System** maps to `ThemeVariant.Default`. Every palette brush and
  colour token is re-resolved on the switch, including the ones pages read from code (panel background,
  window surface, card and control fills), so nothing keeps a light colour in the dark theme or the other way
  round. The macOS app is unchanged and still follows the system appearance. `--snapshot` still renders both
  themes explicitly (`--snapshot-appearance light|dark`), and there is a new dark Settings snapshot showing
  the card. Four new tests cover the Dark default, the settings round-trip, the System mapping and the live
  theme-variant change.

### Fixed

- **Windows: settings controls no longer look disabled when they are not.** The day and time ComboBoxes in the
  quota-reset rows painted their selected value ("Fri", "16:40") in the disabled grey, so an untouched row read
  as unavailable; the selected text now uses the primary text colour whenever the control is enabled. Apply and
  Reset still look disabled until something changes, which is correct.
- **Windows: the subscription Edit button looks enabled.** It was styled with the disabled foreground even
  though it is always usable (it only opens the local edit form; Apply, Cancel and Remove inside the form are
  what the CLI actually gates). It now uses the normal enabled button style, matching the macOS
  `SubscriptionSettingsRow` rules.
- **Windows: a readable renewal-day stepper.** The renewal day used a bare numeric input whose two arrows were
  drawn as 10px glyphs beside each other. It is now a pair of 30×30 stepper buttons with a solid control surface,
  a 1px stroke and a thickened chevron, with the disabled colours kept for out-of-range values; both themes were
  checked in the regenerated snapshots.

- **Windows: nothing is clipped at the card edge any more.** The page margin and the card padding were adding up
  to a 32px double inset inside a 360px panel, so the regenerated snapshots had content squeezed against the
  right edge. The horizontal rhythm is now 12px page margin + 12px card padding (`Metrics.RowContentWidth`),
  and anything that does not fit moves to its own line instead of overflowing: the "Total cost ⓘ" label sits
  above a horizontally scrollable, single-line range-pill bar (no scrollbar, right-edge fade, so "Cycle" is
  never cut mid-word — same on the project page, which no longer wraps the pills onto two lines), overview
  project subtitles truncate before the 8-week heat strip, the `--data` InfoBar wraps its path inside the card,
  and the quota-reset and subscription rows keep their controls on a right-aligned second line. The treemap card
  bleeds to the panel edges so its tiles regain the width they need for labels.
- **Windows: the Settings page scrolls.** Scrollable pages derived from `ScrollViewer` (Settings, Overview,
  project / bucket detail, disk) were styling themselves under their own type name, so Avalonia never applied
  the Fluent `ScrollViewer` control theme: no `ScrollContentPresenter` was created and `Extent` stayed 0, which
  made the wheel, the scrollbar thumb and touch panning do nothing. They now share a `ScrollPage` base that
  restores the base style key. The mouse wheel over a closed ComboBox, a NumericUpDown or a single-line TextBox
  now scrolls the page instead of changing its value (an open ComboBox drop-down still scrolls its own list, and
  a nested scroller still wins until it reaches its edge).

### Changed

- **Windows: Fluent (Windows 11) redesign.** Surfaces, cards, type ramp and every colour token now follow
  WinUI: Mica when the OS has it and a solid `#F3F3F3` / `#202020` fallback otherwise, 8px cards with a 1px
  stroke and 12px padding (4px between cards in a group, 24px between groups), Segoe UI Variable with the
  28 / 20 / 14 / 14 / 12 ramp, sentence-case BodyStrong section headers instead of grey ALL-CAPS, the Windows
  accent colour (`AccentColor1`) for links and the primary button, Fluent ToggleSwitch / ComboBox / SelectorBar
  pills, and an InfoBar for the `--data` warning. Text colours are solid rather than alpha-on-grey: primary
  ≥ 12:1, secondary and captions ≥ 4.5:1, disabled text and strokes ≥ 3:1 against the surface they sit on
  (`ContrastTests` asserts every pair in light and dark). Text on the treemap picks white or near-black per tile.
- **Windows: smoother navigation.** Pages cross-fade with an 8px slide over 150 ms, the tray panel fades and
  slides up over the same 150 ms, hover and press states run at 90 ms, and going back to the overview restores
  its scroll position. All motion is skipped when the system animation setting is off or under `--snapshot`.
  Opening Settings no longer blocks the UI thread on the CLI plan list (it loads in the background), and agents
  without subscription info sit behind a "Show N more" link.

## [0.5.2] - 2026-11-12

### Added

- **Kanjo for Windows.** A native Avalonia app (`windows/`) with the same tray panel, pages, hover cards and background behaviour as the Mac app, sharing the Python CLI and the same JSON contract. Ships as `KanjoApp-win-x64-Setup.exe` / `KanjoApp-win-arm64-Setup.exe`: per-user install in `%LOCALAPPDATA%\KanjoApp` with **no admin rights**, official embeddable Python 3.12.8 and the CLI bundled, so no Python install is needed. Start menu shortcut, no desktop shortcut, automatic updates from GitHub Releases (checked 30 s after launch and every 6 h, applied on the next start; a "Restart to update" tray item appears once a download is ready). Uninstall keeps your data (`%APPDATA%\Kanjo`, `%LOCALAPPDATA%\kanjo`).
- **Windows app CI** (`windows-app` job): `dotnet build -warnaserror` + `dotnet test` on every push, and installer builds for win-x64 / win-arm64 on `v*` tags, uploaded as artifacts and attached to the matching release when it exists.
- **Distinct model count in the public summary.** Each period of `kanjo export --public-summary` now lists every model used (`models_used`), so a website can show how many models you used. `top_models` stays capped at 8.
- **App Store preparation for the iOS app.** Encryption export compliance is declared in the build settings, and `ios/APP_STORE.md` holds the submission checklist, store text, privacy answers and review notes.

### Fixed

- **Publishing retries a failed push.** If a publish committed but the push failed (for example a git credentials problem), the next run reported "unchanged" and the commit stayed on the Mac until the numbers changed. It now pushes the pending commit. The push retry also works when the website repository has other uncommitted changes.

### Changed

- **The CLI runs on Windows.** Agent logs are found in their real Windows locations (`%USERPROFILE%\.claude`, `%USERPROFILE%\.codex`, `%USERPROFILE%\.gemini`, `%APPDATA%\<app>`, `%LOCALAPPDATA%\<app>`); Kanjo's own files live in `%APPDATA%\kanjo` (config) and `%LOCALAPPDATA%\kanjo` (ledger, cache). `kanjo disk` and `disk clean` work on Windows and move files to the **Recycle Bin** (`SHFileOperationW`) instead of `~/.Trash`; the result reports `"trash_dir": "Recycle Bin"`. Claude quota reads the OAuth token from `%USERPROFILE%\.claude\.credentials.json`. A file locked by a running agent is a per-item `move_failed`, not a failed run.
- **Windows CI runs the full CLI suite** (Python 3.9 and 3.12), not just the reporter tests.
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
