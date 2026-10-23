# CLI ↔ UI 数据契约 (Data Contract)

CLI 和 UI 分别独立开发，唯一的接口是这份 JSON。
CLI 负责产出它，UI 负责消费它。双方都不能改这份格式而不改本文档。

工作名：`aicost`（repo 定名后统一替换）。

---

## 1. 产出方式

```bash
aicost export            # 输出 JSON 到 stdout
aicost export -o data.json
```

UI 是 macOS 菜单栏 SwiftUI 应用。它有两种取数方式：
执行 `aicost export` 读 stdout，或直接读一个已导出的 JSON 文件。
两种方式的内容完全相同，都是本文档定义的格式。

---

## 2. 顶层结构

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-23T10:00:00Z",     // ISO 8601 UTC
  "generated_by": "aicost 0.1.0",             // 产出工具和版本
  "timezone": "Asia/Shanghai",                // IANA 时区名；所有 YYYY-MM-DD 日期按此时区划分
  "currency": "USD",                          // 第一版固定 USD，UI 不需要处理其他币种
  "cost_note": "API-equivalent cost estimated from public API prices. Not actual subscription spend.",
  "config": {
    "dominant_threshold": 0.8
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
    { "day": "2026-10-22", "cost": 3.2, "tokens": 120000 }   // 按 day 升序；tokens 是 total
  ],
  "by_branch": [
    { "branch": "main", "cost": 40.0, "sessions": 12 }
  ],
  "sessions_detail": [ /* Session */ ]                       // 按 started 降序
}
```

- `by_agent`、`by_model` 按 cost 降序。
- `by_model.estimated = true` 表示该模型价格是按家族回退估的。
- `by_day` 覆盖项目活跃的每一天，没活动的天不出现。
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

## 7. UI 必须展示的内容

1. 顶部横幅：`cost_note` 原文，不可隐藏。
2. 项目列表，按 cost 降序，每行：name、cost、sessions、last_active、by_agent 的小条形或色块。
3. 项目详情：by_agent、by_model、by_day 时间线、by_branch、sessions_detail 表。
4. 三个桶各一行，显示数量和金额，即使为 0。
5. 对账行：`totals.cost` 与各项之和，差异超过 0.01 时高亮。

---

## 8. 版本

`schema_version` 变更规则：加字段不升版本，改字段含义或删字段升版本。
UI 遇到更高的 `schema_version` 显示警告但继续渲染。
