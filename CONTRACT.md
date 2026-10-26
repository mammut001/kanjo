# CLI ↔ UI 数据契约 (Data Contract)

CLI 和 UI 分别独立开发，唯一的接口是这份 JSON。
CLI 负责产出它，UI 负责消费它。双方都不能改这份格式而不改本文档。

正式名：**Kanjo（勘定）**。命令和包名 `kanjo`，菜单栏应用 `Kanjo`。

---

## 1. 产出方式

```bash
kanjo export            # 输出 JSON 到 stdout
kanjo export -o data.json
```

UI 是 macOS 菜单栏 SwiftUI 应用。它有两种取数方式：
执行 `kanjo export` 读 stdout，或直接读一个已导出的 JSON 文件。
两种方式的内容完全相同，都是本文档定义的格式。

---

## 2. 顶层结构

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-23T10:00:00Z",     // ISO 8601 UTC
  "generated_by": "kanjo 0.1.0",             // 产出工具和版本
  "timezone": "Asia/Shanghai",                // IANA 时区名；所有 YYYY-MM-DD 日期按此时区划分
  "currency": "USD",                          // 第一版固定 USD，UI 不需要处理其他币种
  "cost_note": "API-equivalent cost estimated from public API prices. Not actual subscription spend.",
  "config": {
    "dominant_threshold": 0.8
  },
  "quota_windows": {                          // 各 agent 的额度窗口，供 UI 的「Since reset」范围用；拿不到的 agent 不出现
    "claude": {
      "weekly_resets_at": "2026-10-27T10:00:00Z",   // 下次周重置，ISO 8601 UTC
      "weekly_window_hours": 168,
      "five_hour_resets_at": "2026-10-24T09:30:00Z", // 可为 null
      "source": "tokei"                              // 数据来源：tokei（读 ~/.tokei 缓存）或 manual
    },
    "codex": { "weekly_resets_at": "...", "weekly_window_hours": 168, "five_hour_resets_at": "...", "source": "tokei" }
  },
  "subscriptions": {                          // 各 agent 的订阅档位，供 UI 的「Subscription value」卡和「This billing cycle」范围用；拿不到的 agent 不出现
    "claude": {
      "plan": "max_5x",                       // 内部 key：claude 用 pro | max_5x | max_20x；codex 用 free | go | plus | pro | team；antigravity 用 google_ai_pro | google_ai_ultra；未知档位原样给出
      "plan_label": "Claude Max 5x",          // 显示名
      "monthly_price_usd": 100.0,             // 档位未知时为 null
      "cycle_start": "2026-10-25T00:00:00Z",  // 当前账期起点，ISO 8601 UTC（按 anchor_day 在报告 timezone 的 00:00 折算）
      "cycle_end": "2026-11-25T00:00:00Z",    // 下一账期起点
      "anchor_day": 25,                       // 每月几号开新账期；rolling_30d 时为 null
      "cycle_source": "subscription_date",    // subscription_date（从订阅创建日推出）| manual（用户设置）| rolling_30d（不知道续费日：cycle_start = 现在往前 30 天，cycle_end = 现在，anchor_day 为 null；UI 标「day assumed」并引导设置）
      "extra_usage_enabled": false,           // Claude 的 hasExtraUsageEnabled：true 表示超额会真实扣款，UI 要单独标出
      "source": "detected"                    // detected（本机读到）| manual（用户配置）
    }
  },
  "totals": { /* Aggregate */ },
  "projects": [ /* Project */ ],              // 按 cost 降序
  "buckets": {
    "unattributed": { /* Aggregate */ },
    "excluded":     { /* Aggregate */ },
    "parse_failed": { "sessions": 0, "files": [] }
  }
}
```

**不变量**：`totals.cost == sum(projects[].cost) + buckets.unattributed.cost + buckets.excluded.cost`
（浮点误差容忍 0.01）。tokens 和 sessions 同理。UI 可以用它做对账显示。

- `parse_failed` 没有金额，不参与不变量。不变量覆盖的是**所有成功解析的日志**。
- `sessions` 的口径是「各项之和」：按比例拆分的会话在每个项目各算 1，所以 `totals.sessions` 可能大于真实会话数。
  `totals` 另有 `unique_sessions` 字段给出去重后的真实会话数（见下）。

---

## 3. 共用类型

### Tokens

```jsonc
{
  "input": 0,          // 非缓存输入
  "output": 0,         // 含 thinking
  "cache_read": 0,
  "cache_write": 0,
  "thinking": 0,       // output 的子集，仅供展示；有的 agent 为 0
  "total": 0           // input + output + cache_read + cache_write
}
```

### Aggregate

```jsonc
{
  "cost": 12.34,          // USD，保留 4 位小数
  "tokens": Tokens,
  "sessions": 10,         // 去重后的会话数；按比例拆分的会话在每个项目各算 1
  "first_active": "2026-08-01",   // YYYY-MM-DD，按顶层 timezone 划分，可为 null
  "last_active":  "2026-10-22"
}
```

`totals` 在 Aggregate 之上多一个字段：

```jsonc
{ "unique_sessions": 118 }   // 去重后的真实会话数（含未归属和已排除，不含 parse_failed）
```

### Agent 标识

`agent` 字段用固定小写 key，`label` 用显示名：

| agent | label |
|---|---|
| `claude` | Claude Code |
| `antigravity` | Antigravity CLI |
| `codex` | Codex CLI |
| `grok` | Grok CLI |
| `qwen` | Qwen Code |
| `commandcode` | Command Code |
| `minimax` | MiniMax |
| `opencode` | OpenCode |
| `copilot` | Copilot CLI |

后续接入的 agent 在此表追加。UI 对未知 key 要能正常显示（用 label 兜底）。

---

## 4. Project

```jsonc
{
  "id": "github.com/cclank/tokei",     // 规范化 remote，或无 remote 时的绝对路径
  "name": "tokei",                      // 显示名：remote 最后一段或目录名
  "remote": "github.com/cclank/tokei",  // 无 remote 时为 null
  "paths": [                            // 映射到此项目的所有本地路径，含 worktree
    "/Users/dogecoin/Documents/GitHub/tokei"
  ],
  "path_missing": false,                // 所有 paths 都不存在时为 true

  // Aggregate 字段直接平铺
  "cost": 80.1,
  "tokens": Tokens,
  "sessions": 40,
  "first_active": "2026-08-01",
  "last_active": "2026-10-22",

  "by_agent": [
    { "agent": "claude", "label": "Claude Code", "cost": 60.0, "tokens": Tokens, "sessions": 30 }
  ],
  "by_model": [
    { "model": "claude-opus-5-5", "agent": "claude", "cost": 50.0, "tokens": Tokens, "estimated": false }
  ],
  "by_day": [
    { "day": "2026-10-22", "cost": 3.2, "tokens": 120000,     // 按 day 升序；tokens 是 total
      "by_agent": { "claude": 2.1, "codex": 1.1 },             // 当天各 agent 的 cost，和等于 cost；没用过的 agent 不出现
      "by_agent_tokens": { "claude": 80000, "codex": 40000 } } // 当天各 agent 的 tokens.total，和等于 tokens
  ],
  "by_branch": [
    { "branch": "main", "cost": 40.0, "sessions": 12 }
  ],
  "sessions_detail": [ /* Session */ ]                       // 按 started 降序
}
```

- `by_agent`、`by_model` 按 cost 降序。
- `by_model.estimated = true` 表示该模型价格是按家族回退估的。
- `by_day` 覆盖项目活跃的每一天，没活动的天不出现。每天的 `by_agent` 是 {agent key: cost}，
  各项之和等于当天 `cost`（容忍 0.01）。UI 遇到缺这个字段的旧数据要能回退到项目级的主力 agent。
- `by_branch`：项目下**没有任何会话带分支**时给空数组；否则分支未知的会话归 `"(unknown)"`。按 cost 降序。
- `path_missing = true` 的项目：目录已不存在，读不到 remote，所以 `id` 是路径、`remote` 为 null，
  除非用户在配置的 aliases 里把该路径映射到了某个 remote。

---

## 5. Session

```jsonc
{
  "id": "4993772f-f370-4207-898b-fdca6ed5fe59",
  "agent": "claude",
  "label": "Claude Code",
  "started": "2026-10-12T09:30:00Z",   // 第一条消息的时间戳
  "ended":   "2026-10-12T11:02:00Z",   // 最后一条消息的时间戳；只有一条时等于 started。必填
  "cwd": "/Users/dogecoin/Documents/GitHub/FocusApp",   // 日志里没有工作目录时为 null
  "branch": "release-1.4.5",          // 可为 null
  "models": ["claude-opus-5-5", "claude-haiku-5-5"],
  "cost": 4.21,                        // 此会话归到本项目的那部分
  "tokens": Tokens,                    // 同上，已按 share 拆分
  "share": 1.0,                        // 归到本项目的比例，0 < share <= 1
  "attribution": "dominant",           // 见下表
  "subagents": 3,                      // 跟随本会话归属的子代理数
  "title": "fix quota reset"           // 会话首条用户消息的前 80 字，可为 null
}
```

`attribution` 取值：

| 值 | 含义 |
|---|---|
| `dominant` | 文件操作信号 ≥ 阈值，整个会话归此项目 |
| `split` | 多项目按比例拆分，`share < 1` |
| `cwd` | 零文件信号，按 cwd 归属 |
| `scratchpad` | 零文件信号，按 scratchpad 路径归属 |
| `override` | 用户配置强制归属 |

---

## 6. 桶 (Buckets)

`unattributed` 和 `excluded` 是 Aggregate，另加 `sessions_detail`（Session 数组，`share = 1`，`attribution` 分别为 `"none"` 和 `"excluded"`）。

`parse_failed`：

```jsonc
{ "sessions": 2, "files": ["/Users/.../broken.jsonl"] }
```

`files` 列出每个解析失败的日志文件，`sessions == len(files)`。

---

## 6.1 时间范围（UI 侧计算）

UI 提供范围切换：`All`、`7d`（含今天的最近 7 个自然日）、`30d`、`Last week`（上一个周一到周日）、
`Since reset`（各 agent 自己的周窗口起点 = `weekly_resets_at - weekly_window_hours`，缺 `quota_windows` 的 agent 在该范围下不计入并在 UI 标明）、
`Billing cycle`（各 agent 自己的 `subscriptions[agent].cycle_start` 到现在，缺 `subscriptions` 的 agent 不计入并标明）。
范围内的项目 cost / tokens 由 `by_day` 的 `by_agent` / `by_agent_tokens` 按天累加得出，sessions 数按 `sessions_detail[].started` 落在范围内计数。
对账行只在 `All` 下显示。`cost_note` 在任何范围下都显示。

## 7. UI 必须展示的内容

1. 顶部横幅：`cost_note` 原文，不可隐藏。
2. 项目列表，按 cost 降序，每行：name、cost、sessions、last_active，以及能看出用了哪些 agent 的标记（色点、色块或小条形均可）。
3. 项目详情：by_agent、by_model、by_day 时间线、by_branch、sessions_detail 表。
4. 三个桶各一行，显示数量和金额，即使为 0。
4.1 **Subscription value 卡**（`subscriptions` 非空时）：每个有订阅的 agent 一行：plan_label、月费、本账期 API 等价用量、倍数（用量 ÷ 月费，月费为 null 时不显示倍数）、`extra_usage_enabled` 为 true 时标「extra usage on」。卡片固定一句说明：
   「You pay the flat fee on the left. The number on the right is what the same work would cost on API billing.」不可隐藏。
   项目详情页：对每个有订阅的 agent 显示一行「This repo: N% of your <plan_label> usage this cycle」。
5. 对账行：`totals.cost` 与各项之和，差异超过 0.01 时高亮。

---

## 8. 版本

`schema_version` 变更规则：加字段不升版本，改字段含义或删字段升版本。
UI 遇到更高的 `schema_version` 显示警告但继续渲染。

---

## 9. 账本 (Ledger)

CLI 把每个解析过的会话永久存入账本 `~/.local/share/kanjo/ledger.json`（目录可用 `KANJO_DATA_DIR` 覆盖）。
原始日志文件被删除后，它的会话仍从账本读出并计入导出，所以**清理磁盘不会丢统计**。
导出文档顶层多一个可选对象：

```jsonc
"ledger": {
  "path": "/Users/alice/.local/share/kanjo/ledger.json",
  "sessions": 611,            // 账本里的会话数
  "orphaned": 120,            // 其中原始文件已不存在、只靠账本保留的
  "updated_at": "2026-10-25T10:00:00Z"
}
```

## 10. 磁盘报告 (`kanjo disk --json`)

和 `export` 是两份独立的文档。UI 的 Disk 页读这一份。

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-25T10:00:00Z",
  "total_bytes": 59000000000,
  "reclaimable_bytes": 31000000000,     // 所有 deletable != "never" 且 blocked 为空的条目之和
  "agents": [
    {
      "agent": "codex", "label": "Codex CLI",
      "bytes": 11800000000,
      "entries": [
        {
          "id": "codex:sessions",              // 稳定标识，clean 用它指定目标
          "kind": "sessions",                  // sessions | scratch | worktrees | cache | memory | other
          "path": "/Users/alice/.codex/sessions",
          "bytes": 4600000000, "files": 248,
          "oldest": "2026-06-30", "newest": "2026-10-25",   // YYYY-MM-DD
          "deletable": "after_import",         // always | after_import | when_clean | never
          "blocked": [],                       // 非空表示现在不能删，每项是原因：
                                               //   "not_imported"（账本未收录全部文件）
                                               //   "uncommitted_changes"（worktree 有未提交改动）
                                               //   "active"（24 小时内有修改，或被运行中的进程占用）
          "note": "Session logs. Numbers are kept in the ledger after deletion."
        }
      ]
    }
  ]
}
```

- `kind` 与 `deletable` 的默认对应：`cache` → always；`sessions` → after_import；`scratch` / `worktrees` → when_clean；`memory`（如 Antigravity 的跨会话记忆）→ never；`other` → never。
- `kanjo disk clean <id>... [--older-than 30d] [--dry-run] [--yes]`：只对 `blocked` 为空的条目生效；文件移入 `~/.Trash/kanjo-<时间戳>/`，不直接删除；git worktree 通过主仓库 `git worktree remove` 拆除；没有 `--yes` 时等同 `--dry-run`。输出 JSON：`{ "moved": [...路径], "freed_bytes": N, "skipped": [{ "id", "reason" }] }`。
- UI 永远不自己删文件，只调用 `kanjo disk clean`，并且先用 `--dry-run` 展示将要移动的内容，用户确认后再带 `--yes` 执行。
