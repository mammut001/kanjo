# AICost (macOS menu bar UI)

Menu bar app that answers "how much AI money has this git repo cost?" by rendering
the JSON produced by `aicost export` (format: [`../CONTRACT.md`](../CONTRACT.md)).

- Swift 5.9+, macOS 13+, SwiftUI `MenuBarExtra` + Swift Charts. SwiftPM only, no Xcode project, no dependencies, no network.

## Build / run / test

```bash
cd ui
swift build
swift run AICost                      # menu bar icon + total cost; click it for the panel
swift test
```

Development helpers:

```bash
swift run AICost --data /path/to/data.json    # use this file (overrides Settings)
AICOST_DATA=/path/to/data.json swift run AICost
swift run AICost --window                     # also show the panel in a normal window (screenshots/debugging)
swift run AICost --window --route project:0   # open straight on a page (for screenshots)
```

`--route` values: `overview`, `overview-bottom` (overview scrolled to the buckets and reconciliation),
`project:<index>` (0-based, in cost order), `bucket:unattributed`, `bucket:excluded`, `settings`.

## Data source

Pick it in the panel's **Settings** (gear icon). Values are stored with `@AppStorage`.

| Source | What it does |
|---|---|
| JSON file (default) | Reads a contract JSON file. Leave the path empty to use `fixtures/sample.json`. |
| CLI command | Runs a command (default `python3 -m aicost export`) through `/bin/zsh -l -c` in the working directory you set (e.g. the `cli/` folder) and parses stdout. |

Lookup order: `--data` → `AICOST_DATA` → Settings → `fixtures/sample.json`.
Auto refresh defaults to every 5 minutes. You can also hide the dollar amount in the menu bar.

If loading fails, the panel shows the error: invalid JSON, a missing field with its path (e.g.
`projects[1].by_day`), or the command's exit status and stderr. If a refresh fails after a
successful load, the previous data stays on screen under a red banner.
If `schema_version` is newer than 1, a warning appears and the app keeps rendering.

## Layout

```
Package.swift
Sources/AICostCore/      contract models (Codable), data sources, formatting, reconciliation (no UI)
Sources/AICost/          SwiftUI app: AICostApp, Store/ReportStore, Views/…
Tests/AICostTests/       decoding + invariant tests on fixtures/sample.json, formatting tests
fixtures/sample.json     test data (8 projects, 3 agents, split/cwd sessions, estimated models, buckets)
fixtures/generate_sample.py   regenerates sample.json deterministically and asserts the invariants
```
