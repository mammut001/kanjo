# kanjo (CLI)

How much AI money did each git repo cost? `kanjo` scans the local logs of
**Claude Code**, **Antigravity CLI** and **Codex CLI** once, attributes every
session to a project (a git repo, identified by its remote) and reports cost by
project rather than by day or by agent.

- Rules: [`../ATTRIBUTION.md`](../ATTRIBUTION.md). The code implements them as written.
- Output format: [`../CONTRACT.md`](../CONTRACT.md). This is the only interface to the UI.

It needs Python 3.9+ and uses only the standard library. It never touches the
network and only reads the logs.

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
kanjo doctor                 # log directories found, session/sub-agent/failure counts
```

These options work with every command:

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
| Antigravity CLI | `~/.gemini/antigravity-cli/conversations/<id>.db` (SQLite + protobuf) | `KANJO_ANTIGRAVITY_DIR` |
| Codex CLI / Desktop | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/` | `KANJO_CODEX_DIR` |

Each override takes a list of directories separated by `:`.

### Cache

Parsed sessions are cached per file in `~/.cache/kanjo/parse-cache-v3.json`, keyed on
size and mtime (plus the `-wal` file for SQLite). You can move it with
`KANJO_CACHE_DIR` or `XDG_CACHE_HOME`. The cache stores derived numbers and paths,
plus the 80-character session title. It never stores conversation text.
A cold scan of about 10 GB of logs takes about 30 s; a warm one takes about 5 s.

### Quota windows (`quota_windows`)

The UI's "Since reset" range needs each agent's weekly quota window. `kanjo` fills the
top-level `quota_windows` field on a best-effort basis. A missing, unreadable or stale
Tokei cache never fails the export: that agent is left out, and the field is `{}` when
nothing is found. A malformed manual entry is a config error, like any other.

Sources, per agent (the first one found wins):

1. **Manual**, from the attribution config (`"source": "manual"`):

   ```toml
   [quota_windows.claude]
   weekly_resets_at = "2026-10-27T10:00:00Z"   # any past or future reset, ISO 8601
   weekly_window_hours = 168                   # optional, default 168
   five_hour_resets_at = "2026-10-24T09:30:00Z" # optional
   ```

   In `attribution.json` this is `{"quota_windows": {"claude": {...}}}`.
2. **Tokei** (https://github.com/cclank/tokei), if it is installed (`"source": "tokei"`).
   `kanjo` reads Tokei's cache files and does not call any API:

   | agent | file in `~/.tokei/` | weekly reset | 5-hour reset | fetched at |
   |---|---|---|---|---|
   | `claude` | `claude_quota_swift_cache.json` | `snapshot.q7Reset` (168 h) | `snapshot.q5Reset` | `snapshot.updated` |
   | `codex` | `codex_quota_cache.json` | `limits.secondary.resets_at` (`window_minutes` / 60) | `limits.primary.resets_at` | `fetched_at` |

   A cache file fetched more than 14 days ago is ignored. `KANJO_TOKEI_DIR` replaces `~/.tokei`.

A weekly reset time that is already past moves forward by whole windows to the next
reset. A 5-hour reset time that is already past becomes `null`, because the next 5-hour
window only starts with the next request.

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
  cli.py          argparse: export / projects / doctor
  config.py       attribution.toml / .json
  quota.py        quota_windows from the config or Tokei's ~/.tokei caches
  identity.py     path -> project (remote normalization, worktrees, scratchpad decoding)
  attribution.py  scoring and decision
  pricing.py      price lookup, family fallback, estimated flag
  export.py       scan, de-duplicate, aggregate, CONTRACT.md JSON, invariant check
  cache.py        per-file parse cache
  sources/        base.py (Session/Message), claude.py, antigravity.py, codex.py
```
