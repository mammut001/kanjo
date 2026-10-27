# kanjo (CLI)

How much AI money did each git repo cost? `kanjo` scans the local logs of
**Claude Code**, **Antigravity CLI** and **Codex CLI** once, attributes every
session to a project (a git repo, identified by its remote) and reports cost by
project rather than by day or by agent.

- Rules: [`../ATTRIBUTION.md`](../ATTRIBUTION.md). The code implements them as written.
- Output format: [`../CONTRACT.md`](../CONTRACT.md). This is the only interface to the UI.

It needs Python 3.9+ and uses only the standard library. It never touches the
network. `export`, `projects` and `doctor` only read logs. `disk clean` moves
files into the Trash; it does not delete them.

## Install

You can run it straight from this directory:

```bash
cd cli
python3 -m kanjo --help
```

To get a `kanjo` command on your PATH, run `../install.sh` from the repo. It copies this
directory to `~/.local/share/kanjo/cli` and writes a launcher to `~/.local/bin/kanjo`
(`../install.sh --uninstall` removes both). The menu bar app finds the CLI there on its own.

## Usage

```bash
kanjo export                 # CONTRACT.md JSON on stdout
kanjo export -o data.json    # ... or to a file (written atomically)
kanjo export --compact       # no indentation
kanjo projects               # readable table, top 25 projects (--all, --limit N)
kanjo doctor                 # log directories, session counts, ledger, subscriptions
kanjo ledger                 # permanent ledger: path, sessions, orphaned, empty, errors, size
kanjo ledger --forget-orphans --yes
kanjo disk                   # disk usage table
kanjo disk --json            # CONTRACT.md section 10
kanjo disk clean <id>... [--older-than 30d] [--dry-run] [--yes]
```

These options work with `export`, `projects` and `doctor`:

| option | meaning |
|---|---|
| `--config PATH` | attribution config (default `~/.config/kanjo/attribution.toml`, or `attribution.json`) |
| `--threshold F` | dominant project threshold, overrides `dominant_threshold` (export, projects) |
| `--no-cache` | re-parse every log file |

Only the JSON document goes to stdout. Status messages and invariant warnings go to stderr.

### Log locations

| agent | default location | override |
|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/<session>.jsonl`, sub-agents in `<session>/subagents/*.jsonl` | `KANJO_CLAUDE_DIR` |
| Antigravity (CLI / App) | `~/.gemini/antigravity-cli/conversations/<id>.db`, `~/.gemini/antigravity/conversations/<id>.db` (SQLite + protobuf) | `KANJO_ANTIGRAVITY_DIR` |
| Codex CLI / Desktop | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/` | `KANJO_CODEX_DIR` |

Each override takes a list of directories separated by `:`.

### Cache

Parsed sessions are cached per file in `~/.cache/kanjo/parse-cache-v3.json`, keyed on
size and mtime (plus the `-wal` file for SQLite). You can move it with
`KANJO_CACHE_DIR` or `XDG_CACHE_HOME`. The cache stores derived numbers and paths,
plus the 80-character session title. It never stores conversation text.
A cold scan of about 10 GB of logs takes about 30 s; a warm one takes about 5 s.

### Ledger

Parsed sessions are also stored permanently in `~/.local/share/kanjo/ledger.json`.
`KANJO_DATA_DIR` replaces that directory. The parse cache drops a file when its
log disappears; the ledger does not. After a log is deleted, `kanjo export` still
counts that session. The top-level `ledger` object says where the file is, how
many sessions it holds, how many of those are orphaned (the original file is
gone) and when it was last written. Logs with no billable messages, and logs
that fail to parse, are recorded too (`empty` and `errors` in `kanjo ledger`),
so cleanup is not blocked.

The ledger is loaded once per run and rewritten only when a file's size or mtime
changed. `--no-cache` still updates it. `kanjo ledger` prints the path, the
session count, the orphaned count, the empty and error counts, and the file
size. `kanjo ledger --forget-orphans` removes orphaned entries, and only when
`--yes` is passed.
Nothing else mutates the ledger.

`kanjo doctor` prints the ledger path and the orphan count.

### Disk

`kanjo disk` prints a table (agent, entry, size, files, newest, deletable or
blocked). Sessions rows show `imported/total` log files in the Files column.
`kanjo disk --json` prints the document in CONTRACT.md section 10. Each
sessions entry also carries `log_files` and `imported_files`.
Missing paths are skipped. Sizes are allocated disk usage (`st_blocks * 512`),
not apparent size.

Entries are sized concurrently with up to 8 threads (capped by the CPU count).
Claude scratch also splits its first-level subdirectories into separate jobs.
The complete report is cached atomically in `~/.cache/kanjo/disk-report.json`;
`KANJO_CACHE_DIR` replaces the cache directory (`XDG_CACHE_HOME` is also honored).
`kanjo disk` and `kanjo disk --json` reuse it for 600 seconds by default.
Use `--max-age SECONDS` to change that, or `--max-age 0` / `--rescan` to force a
fresh scan. Before reuse, each entry root is stat'ed: a missing root or a root
mtime newer than the scan invalidates the whole report. Changes deeper in a
tree may remain cached until the age limit; use `--rescan` to see them immediately.
The JSON includes `cached`, `scanned_at` (UTC scan time), and `scan_seconds`
(duration of the real scan). `kanjo doctor` shows the disk cache path and age.
Cleaning always rescans and invalidates the cache after moving anything.

| entry | default path | kind | deletable |
|---|---|---|---|
| Claude sessions | `~/.claude/projects` (`KANJO_CLAUDE_DIR`) | sessions | after_import |
| Claude shell snapshots | `~/.claude/shell-snapshots` | cache | always |
| Claude debug | `~/.claude/debug` | cache | always |
| Claude scratch | `/tmp/claude-<uid>` (`KANJO_SCRATCH_DIR`) | scratch | when_clean |
| Codex sessions | `~/.codex/sessions` | sessions | after_import |
| Codex archived sessions | `~/.codex/archived_sessions` | sessions | after_import |
| Codex worktrees | each git worktree under `~/.codex/worktrees` | worktrees | when_clean |
| Codex logs | `~/.codex/logs` | cache | always |
| Antigravity sessions | `~/.gemini/antigravity-cli/conversations`, `~/.gemini/antigravity/conversations` (`KANJO_ANTIGRAVITY_DIR`) | sessions | after_import |
| Antigravity scratch | `brain/<id>/scratch`, one entry per brain id | scratch | when_clean |
| Antigravity memory | the rest of `brain/` | memory | never |
| Antigravity cache | `~/.gemini/antigravity-cli/cache`, `~/.gemini/antigravity/cache` | cache | always |
| Grok sessions | `~/.grok/sessions` (`KANJO_GROK_DIR`) | sessions | after_import |
| Grok bundled | `~/.grok/bundled` | other | never |
| Claude desktop | `~/Library/Application Support/Claude/{Cache,Code Cache,GPUCache}` (`KANJO_CLAUDE_APP_CACHE`) | cache | always |

`KANJO_CODEX_DIR` replaces the Codex session directories the parser reads.
Shell snapshots, debug logs, Codex worktrees and logs, and the Antigravity
brain and cache are siblings of those directories, so the defaults above stay
put when the variables are unset. Claude scratch is one entry for the whole
`/tmp/claude-<uid>` tree (each `<encoded-cwd>/<session>/scratchpad` is a unit;
the report sums them). It is `active` when any file changed in the last 24
hours. A worktree is `active` on the same rule, and `uncommitted_changes` when
`git -C <wt> status --porcelain` is not empty.

Deletable classes: `cache` → `always`; `sessions` → `after_import`; `scratch`
and `worktrees` → `when_clean`; `memory` and `other` → `never`. A log file
counts as imported when the ledger has any entry for that agent and path, so
a file that changed after import still counts; `not_imported` is set only when
`imported_files` is less than `log_files`. Grok is not parsed yet, so its
sessions stay `not_imported`. `when_clean` entries are blocked with `active`,
and worktrees also with `uncommitted_changes`.

`kanjo disk clean <id>... [--older-than 30d] [--dry-run] [--yes]` only touches
entries whose `blocked` list is empty. The one exception is `--older-than` on
a sessions entry blocked only by `not_imported`: each old log file with no
ledger entry is listed in `skipped` with reason `not_imported`, and the other
old files (imported logs, plus non-logs such as images, json, zst and
`.DS_Store`) are moved. Files move into
`~/.Trash/kanjo-<timestamp>/<id>/` (`KANJO_TRASH_DIR` replaces `~/.Trash`).
Across volumes, a failed rename falls back to a move. Git worktrees are removed
with `git worktree remove` from the main repo named by the worktree's `.git`
file, not by unlinking the directory. `--older-than 30d` keeps files newer than
30 days; a worktree is removed only when every file in it is old enough.
Without `--yes` the command prints the plan and moves nothing. Cleaning
session logs does not remove their numbers from the ledger.

The UI never deletes files itself. It only calls `kanjo disk clean`, first with
`--dry-run`, then with `--yes` after the user confirms.

### Quota windows (`quota_windows`)

The UI's "Since reset" range needs each agent's weekly quota window. `kanjo` fills the
top-level `quota_windows` field on a best-effort basis. A missing, unreadable or stale
Tokei cache never fails the export: that agent is left out, and the field is `{}` when
nothing is found. A malformed manual entry is a config error, like any other.

Sources, per agent (the first one found wins):

1. **Manual**, from the attribution config (`"source": "manual"`):

   ```toml
   [quota_windows.claude]
   weekly_reset = "tue 05:00"                  # weekday + local time in the report timezone
   # or: weekly_resets_at = "2026-10-27T10:00:00Z"   # any past or future reset, ISO 8601
   weekly_window_hours = 168                   # optional, default 168
   five_hour_resets_at = "2026-10-24T09:30:00Z" # optional
   ```

   In `attribution.json` this is `{"quota_windows": {"claude": {...}}}`.
   You can also set or unset overrides via `kanjo config set quota_windows.<agent>.weekly_reset "tue 05:00"` and `kanjo config unset quota_windows.<agent>.weekly_reset`.
2. **Direct fetch** (`"source": "live"`):
   `kanjo` independently queries the provider's local language server or official usage endpoint (Antigravity on 127.0.0.1 with Gemini 5h/weekly and Claude/GPT `extra_windows`, Codex, Claude, Grok) using existing local credentials. Credentials are kept in memory only and never stored in caches or logs. Results are cached in `~/.local/share/kanjo/quota_cache.json` with a 5-minute TTL. Set `KANJO_NO_NETWORK=1` or `no_network = true` in config to disable outbound network requests.
   For Claude, `kanjo` checks: 1) live OAuth API using the macOS Keychain token; 2) Claude Desktop's local Chromium HTTP cache (`~/Library/Application Support/Claude/Cache/Cache_Data`, configurable via `KANJO_CLAUDE_CACHE_DIR`); 3) `~/.claude.json` `cachedUsageUtilization` (only if the window has not ended).
3. **Tokei** (https://github.com/cclank/tokei) cache fallback (`"source": "tokei"`):
   `kanjo` reads Tokei's cache files if present as a fallback:

   | agent | file in `~/.tokei/` | weekly reset | 5-hour reset | fetched at |
   |---|---|---|---|---|
   | `claude` | `claude_quota_swift_cache.json` | `snapshot.q7Reset` (168 h) | `snapshot.q5Reset` | `snapshot.updated` |
   | `codex` | `codex_quota_cache.json` | `limits.secondary.resets_at` (`window_minutes` / 60) | `limits.primary.resets_at` | `fetched_at` |
   | `grok` | `grok_quota_cache.json` | `quota.reset` (168 h for "week", 24 h for "day") | `null` | `fetched_at` |

   A cache file fetched more than 14 days ago is ignored. `KANJO_TOKEI_DIR` replaces `~/.tokei`.

A weekly reset time that is already past moves forward by whole windows to the next
reset. A 5-hour reset time that is already past becomes `null`, because the next 5-hour
window only starts with the next request.

### Subscriptions (`subscriptions`)

The UI's "Subscription value" card and "Billing cycle" range need each agent's plan
and the current billing cycle. `kanjo` fills the top-level `subscriptions` field.
An agent with nothing detected and nothing configured is left out. The field is `{}`
when nothing is found. A bad manual entry is a config error (exit code 2), like any other.

These monthly prices are public list prices. They may change, and a manual
`monthly_price_usd` overrides them. They are not the API-equivalent cost in `cost_note`.

Manual settings merge per field. Precedence is `overrides.json` > `attribution.toml`
(or `attribution.json`) > detected values > defaults. Fields you leave out keep
their detected values. Setting any field makes `source` `"manual"`; setting
`anchor_day` also makes `cycle_source` `"manual"`.

Use `kanjo config` to change subscription settings without editing TOML:

```sh
kanjo config set subscriptions.codex.anchor_day 8
kanjo config get subscriptions.codex.anchor_day
# subscriptions.codex.anchor_day = 8 (overrides)
kanjo config set subscriptions.codex.plan plus
kanjo config set subscriptions.codex.monthly_price_usd 20
kanjo config unset subscriptions.codex.anchor_day
kanjo config path
```

`get`, `set` and `unset` print the effective value and its origin: `overrides`,
`toml`, `detected`, or `default`. `unset` removes only the JSON override and falls
back to the next source. Supported agents are `claude`, `codex`, and `antigravity`;
editable fields are `anchor_day` (integer 1–28), `plan` (a known key, or a custom
key with a configured price), and `monthly_price_usd` (a finite number ≥ 0).
Validation errors exit with code 2 and a one-line message.

The command atomically writes `~/.config/kanjo/overrides.json`, preserving other
keys and leaving the attribution file untouched. For example:

```json
{"subscriptions": {"codex": {"anchor_day": 8}}}
```

Every command loads this file. `KANJO_CONFIG_DIR` changes the config directory;
`--config PATH` selects an attribution file and takes precedence over that env
variable, with `overrides.json` beside the selected file. For example,
`kanjo config get subscriptions.codex.anchor_day --config /tmp/kanjo/attribution.toml`.
`config path` prints both file paths. `doctor` shows each subscription's anchor
and origin, such as `anchor day 8 (overrides.json)`, or
`anchor day: unknown (rolling 30 days)` when the renewal day is unknown.
`config get subscriptions.<agent>.anchor_day` then prints `unset (rolling 30 days)`.

Sources, per agent:

1. **Manual**, from the attribution config (`"source": "manual"`):

   ```toml
   [subscriptions.claude]
   plan = "max_20x"            # a known key, or any string
   monthly_price_usd = 200     # optional; known plans fill it in, unknown plans need it
   anchor_day = 25             # optional, 1-28; sets cycle_source = "manual"
   extra_usage_enabled = false # optional; otherwise keeps detection, or defaults false

   [subscriptions.antigravity]
   plan = "google_ai_pro"
   ```

   In `attribution.json` this is `{"subscriptions": {"claude": {...}}}`.
   `plan` alone is enough for a known key and fills its label and list price;
   an explicit `monthly_price_usd` takes precedence over the list price.
   Without `anchor_day` the detected cycle is kept, falling back to a rolling
   30-day window (`"cycle_source": "rolling_30d"`, `"anchor_day": null`).
   An anchor or price alone updates a detected subscription; without a detected plan, configure `plan` too.

2. **Claude**, detected from `~/.claude.json` (`"source": "detected"`).
   `KANJO_CLAUDE_CONFIG` replaces that path. `oauthAccount.billingType` must be a
   string containing `subscription`. The plan comes from `userRateLimitTier` when
   it is not null, otherwise `organizationRateLimitTier`. Match by substring,
   longer keys first:

   | substring | plan | label | USD/month |
   |---|---|---|---|
   | `max_20x` | `max_20x` | Claude Max 20x | 200 |
   | `max_5x` | `max_5x` | Claude Max 5x | 100 |
   | `pro` | `pro` | Claude Pro | 20 |
   | anything else | the raw tier | `Claude (<tier>)` | null |

   `subscriptionCreatedAt` sets `anchor_day` to that timestamp's own day of the month
   (`"cycle_source": "subscription_date"`). If it is missing or invalid, the cycle
   uses a rolling 30-day window (`"rolling_30d"`) with a null anchor.
   `hasExtraUsageEnabled` is copied to `extra_usage_enabled`
   (false when it is absent or not a boolean).

3. **Codex**, detected from Tokei's `~/.tokei/codex_quota_cache.json`
   (`plan`, or else `limits.plan_type`). The same 14-day staleness rule as quota
   windows applies (`fetched_at`, or the file mtime when that is missing).
   `KANJO_TOKEI_DIR` replaces `~/.tokei`. No subscription date is known, so the
   cycle uses a rolling 30-day window (`"rolling_30d"`) with a null anchor, and
   `extra_usage_enabled` is false.

   | plan | label | USD/month |
   |---|---|---|
   | `free` | ChatGPT Free | 0 |
   | `go` | ChatGPT Go | 8 |
   | `plus` | ChatGPT Plus | 20 |
   | `pro` | ChatGPT Pro | 200 |
   | `team` | ChatGPT Team | 30 |
   | `business` | ChatGPT Business | 30 |
   | anything else | `ChatGPT (<plan>)` | null |

4. **Antigravity** is not detectable. It appears only from a manual table.

   | plan | label | USD/month |
   |---|---|---|
   | `google_ai_pro` | Google AI Pro | 19.99 |
   | `google_ai_ultra` | Google AI Ultra | 249.99 |

When the renewal day is unknown, `cycle_start` is now minus 30 days and
`cycle_end` is now, preserving the current time of day in UTC. The app can use
`"cycle_source": "rolling_30d"` to prompt you to set the real renewal day.
Setting `anchor_day` switches to a monthly billing cycle; unsetting its override
returns to the next configured or detected day, or to the rolling window.

With a known anchor, the billing cycle starts at the most recent `anchor_day`
at 00:00 in the report `timezone` that is still at or before now. `cycle_end` is the anchor day of the
next month at 00:00 in that timezone. A short month clamps the anchor to its last
day, and the next month clamps on its own (anchor 31 in February is the 28th, or
the 29th in a leap year, and March is the 31st again). `cycle_start` and
`cycle_end` are those local midnights written as ISO 8601 UTC.

## About `cost_note`

Every output says:

> API-equivalent cost estimated from public API prices. Not actual subscription spend.

The cost is **token usage × public per-token API price**. It is what the same work
would have cost on pay-as-you-go API billing. It is **not** what you paid:
with a subscription (Claude Max, ChatGPT Pro, Google AI plans for Antigravity, ...)
your actual spend is the flat fee. Use the number to compare projects and agents,
not to reconcile an invoice. The UI must show this note and must not let it be hidden.

Pricing details:

- Prices come from Tokei (https://github.com/cclank/tokei, MIT License). `pricing.json` and
  `pricing_overrides.json` are verbatim copies, and Tokei's built-in official prices are
  in `kanjo/pricing.py`. Layering is builtin < `pricing.json` < overrides.
- Each message is priced with its own model, counting input, output (thinking
  included), cache reads and cache writes. Claude 1-hour cache writes are priced at
  2× input.
- Some models are not in the price table. These get `"estimated": true` in `by_model`.
  The fallback order is:
  1. the closest known model, either by stripping variant suffixes
     (`gemini-3.8-flash-n` → `gemini-3.8-flash`) or by taking the previous version on
     the same line;
  2. otherwise the family keyword (`opus`, `sonnet`, `gemini … pro` / `flash`, `gpt`, …),
     which falls back to the family's most expensive tier.
- `<synthetic>` Claude messages cost 0.

## How sessions are attributed (summary)

See ATTRIBUTION.md for the normative version.

1. **Project identity.** The project is the normalized `origin` remote
   (`github.com/owner/repo`). Worktrees fold into their main repo, and that includes
   worktrees whose admin dir was pruned and deleted worktrees that `git worktree list`
   still shows. Clones with the same remote merge. A repo without a remote is identified
   by its root path. Directories that are not git repos are not projects. `kanjo` reads
   `.git` files directly and does not need `git` installed.
2. **Signals.** Each tool call scores 1 point per distinct path it touched, for the
   project that path maps to. The paths come from these sources:
   - Claude: `file_path`, `path`, … and absolute paths in `Bash` commands.
   - Antigravity: `AbsolutePath`, `TargetFile`, `Cwd`, … and paths in `CommandLine`.
   - Codex: `workdir`, `path`, … plus paths in `cmd`/`exec` code and the file headers
     of `apply_patch`.
3. **Decision.** A project with ≥ 80 % of the points takes the whole session
   (`dominant`). Otherwise the cost is split by points (`split`). With no points, the
   session goes to the cwd's project (`cwd`). Failing that, it goes to the project
   encoded in a Claude scratchpad path such as
   `/tmp/claude-501/-Users-me-Documents-GitHub-repo/...` (`scratchpad`). If neither
   applies, the session lands in the **unattributed** bucket.
4. **Sub-agents** follow their parent's decision, including its split ratio.
   - Claude: `subagents/*.jsonl`.
   - Antigravity: conversations whose `root_cascade_id` is another conversation.
   - Codex: rollouts with `parent_thread_id`.

   Orphan sub-agents are scored on their own.
5. **De-duplication.** A message is billed once:
   - Claude: per `message.id`, where the last streaming line wins. Resumed or forked
     sessions copy earlier messages into a new file, so de-duplication is global across
     files.
   - Codex: per `(total_token_usage, last_token_usage)`. This drops the history that
     forks and sub-agents replay.
   - Antigravity: per generation record.
6. **Time.** Days are local dates in the reported `timezone`, taken from each message's
   timestamp.

### Configuration (`~/.config/kanjo/attribution.toml`)

```toml
[aliases]                      # merge identities (fork -> upstream, old path -> remote)
"github.com/cclank/tokei" = ["github.com/me/tokei", "/Users/me/old-tokei"]

[overrides]                    # session cwd prefix -> project, beats scoring
"/Users/me/experiments/tokei-" = "github.com/cclank/tokei"

exclude = ["/Users/me/scratch"]   # session cwd prefix -> "excluded" bucket
dominant_threshold = 0.8
```

Overrides and excludes match the session's working directory as a plain string
prefix, and the longest prefix wins. Python < 3.11 has no `tomllib`, so `kanjo` falls
back to a small parser for this subset. You can also use `attribution.json` with the
same keys. In real TOML, keys written after `[overrides]` belong to that table, so
`kanjo` also accepts `exclude` and `dominant_threshold` there.

## Tests

```bash
cd cli
python3 -m unittest -v
```

`tests/fixtures/` holds cropped, sanitized samples of real logs for each agent. In
them, user names are replaced by `alice`, all conversation text is removed, and shell
commands are rebuilt from the paths they used. The fixtures also include
`export_sample.json`, a sanitized real export that the UI uses. The tests build fake
git repos in a temp directory, which `Resolver(fs_root=...)` treats as `/`.

## Layout

```
kanjo/
  cli.py          argparse: export / projects / doctor / ledger / disk
  config.py       attribution.toml / .json
  quota.py        quota_windows from the config or Tokei's ~/.tokei caches
  quota_fetch.py  direct provider quota fetching
  quota_claude_cache.py  Claude Desktop HTTP cache fallback scanner
  subscriptions.py  subscription plans and billing cycles (Claude config, Tokei, manual)
  identity.py     path -> project (remote normalization, worktrees, scratchpad decoding)
  attribution.py  scoring and decision
  pricing.py      price lookup, family fallback, estimated flag
  export.py       scan, de-duplicate, aggregate, CONTRACT.md JSON, invariant check
  cache.py        per-file parse cache
  ledger.py       permanent session ledger (survives log deletion)
  disk.py         disk usage report and Trash-only clean
  sources/        base.py (Session/Message), claude.py, antigravity.py, codex.py
```
