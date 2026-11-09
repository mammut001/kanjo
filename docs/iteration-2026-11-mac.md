# Mac 端迭代（2026-11）规则草案

> 先确认规则再写码。确认后交给 agy 在独立 worktree 实现，Claude 监工审 diff、跑测试。

## 调查结论

| # | 诉求 | 现状 | 是否要改 |
|---|------|------|----------|
| A | 订阅价值 hover 显示账号（邮箱） | 导出里没有任何账号信息 | **要改** |
| B | 「解析失败 · 花费未知」 | 本机当前 `parse_failed` = 0 个文件；这一行不管有没有失败都会显示，所以看起来像出了问题 | **要改**（为 0 时隐藏） |
| C | 「重置以来」按 agent 各自的重置日 | **已经是按 agent 各算**：`TimeRange.sinceReset` 给每个 agent 用自己的 `weekly_resets_at` 往回推一周作为起点（Claude 周二 14:00、Codex、Grok、Antigravity 各不相同），没有额度信息的 agent 不计入 | 暂不改，见文末问题 |
| D | Pi agent 的 Step 5 没统计 | Kanjo **完全不支持 Pi agent**（`~/.pi/agent/sessions`），本机 34 个项目目录、约 3700 条 `step-5-preview` 记录都没算；`pricing.json` 也没有 `step-5-preview` | **要改** |

## A. 订阅账号信息

**CLI（`subscriptions.py`）**：每个订阅条目加可选字段 `account`：

```json
"account": { "email": "a@b.com", "name": "显示名或组织名，可为 null" }
```

来源（只读本地文件，不发任何请求）：
- Claude：`~/.claude.json` → `oauthAccount.emailAddress`，`name` = `organizationName` 或 `displayName`
- Codex：`~/.codex/auth.json` → `tokens.id_token` 的 JWT payload `email`（只解 payload，不验签）
- Grok：`~/.grok/auth.json` 第一个条目的 `email`
- Antigravity：如果现有的 language server 额度请求（`quota_fetch.py`）响应里本来就带邮箱就取；没有就留空，不额外加请求
- 其他 agent / 拿不到：不输出 `account` 字段
- 手动订阅（`source: manual`）也照样附上检测到的账号
- **绝不**读取或输出 token / key 本身

**隐私**：`--mobile` 导出（iPhone 同步）**不带** `account`。CONTRACT.md 补字段说明。

**UI**：订阅价值卡每一行 hover 时，在现有提示里加一行「账号：邮箱（名称）」；没有账号就不加这一行。

## B. 解析失败行

- `parse_failed.sessions == 0` 时整行不显示（连同上面的分隔线）。
- `> 0` 时保持现在的样子（可展开文件列表）。

## D. Pi agent 支持

- 新数据源 `pi`，读 `~/.pi/agent/sessions/<编码目录>/*.jsonl`（`$KANJO_PI_DIR` 可覆盖）。
- 每个文件 = 一个会话：第一行 `type: session` 给 `id`、`cwd`、`timestamp`；`cwd` 走现有归属逻辑分到 repo。
- 用量：`type: message` 且 `message.role == assistant` 且有 `message.usage` 的行；`input` / `output` / `cacheRead` / `cacheWrite` 映射到现有四类 token；模型 = `message.model`，provider 前缀 = `message.provider`。
- 花费：按 Kanjo 价格表算（不信 pi 自带的 `cost`，它对订阅制 provider 写的是 0）。
- 价格：`pricing_overrides.json` 加 `stepfun/step-5-preview`：输入 $1.00 / 输出 $2.70 / 缓存读 $0.05 每百万 token（第三方目录汇总，StepFun 官方价目表未完整公开；缓存价有来源写 $0.10）。
- 和现有 agent 一样接入：缓存、doctor、颜色 / 标签（标签 “Pi”）、测试 fixture（脱敏的小 jsonl）。
- 不加 Pi 的订阅 / 额度检测（StepFun Step Plan 以后再说）。

## E. 对齐 Tokei 的全部 agent

参照 `~/Documents/GitHub/tokei/usage.30s.py`（MIT，上游 `cclank/tokei`）里的 `scan_*` 函数移植解析逻辑，每个做成 `cli/kanjo/sources/<agent>.py`，接口和现有数据源一致。README 致谢里注明解析逻辑参考 Tokei（MIT）。

Kanjo 已有：claude、codex、antigravity、grok、commandcode、copilot、minimax、opencode、qwen。

要补的（★ = 本机有数据，必须用真实数据验证）：

| agent | Tokei 函数 | 数据位置 |
|-------|-----------|----------|
| ★ pi | `scan_pi` | `~/.pi/agent/sessions`（同上 D） |
| ★ workbuddy / workbuddy_ai | `scan_workbuddy*` | `~/.workbuddy/projects`、`~/.workbuddy-ai/projects` |
| codebuddy | `scan_codebuddy` | `~/.codebuddy/projects` |
| ★ grok_bot | `scan_grok_bot` | `~/Library/Application Support/Grok Bot/sand-client-persistence` |
| ★ qoderwork / qodercli / qodercli_cn | `scan_qoder`、`scan_qodercli` | `~/.qoder`、`~/.qoder-cn` |
| qoder_ide | `scan_qoder_ide` | Qoder `SharedClientCache/.../local.db` |
| ★ zcode | `scan_zcode` | `~/.zcode/cli/db/db.sqlite` |
| ★ kimicode | `scan_kimicode` | `~/.kimi-code`（旧版 `~/.kimi`） |
| ★ musecode | `scan_musecode` | `~/.local/share/muse` |
| hermes | `scan_hermes` | `~/.hermes/state.db` |
| openclaw | `scan_openclaw` | `~/.openclaw` |
| devin | `scan_devin` | Devin / Windsurf 支持目录 + devin CLI `sessions.db` |
| mimocode | `scan_mimocode` | mimocode data 目录 |
| prime_agent / omp | `scan_prime_agent`、`scan_pi` 的 omp 分支 | `~/.prime/agent/sessions`、`~/.omp/agent/sessions` |
| deepseek_harness | `scan_deepseek_harness` | `~/.tokei/cache/dsh-sessions` |
| antigravity 补目录 | `scan_gemini` | `~/.gemini/antigravity-ide/conversations`、`~/.gemini/gemini-cli/conversations` |

规则：
- 只移植**用量解析**，不移植 Tokei 的额度 / 套餐抓取（不发网络请求、不读 Keychain）。
- 会话能拿到工作目录就走现有归属逻辑；拿不到的进「未归属」，不猜。
- 花费统一用 Kanjo 价格表；价格表里没有的模型照现有规则显示为未定价，并补进 `pricing_overrides.json`（能查到公开价的）。
- 每个新数据源一个脱敏的最小 fixture + 测试；本机没数据的 agent 用 Tokei `tests/` 里的样例格式造 fixture。
- 颜色 / 标签加进 `AgentColors`、三种语言的 Localizable。

## F. 后台安静：性能优化

### 实测（本机，2026-11-09）

| 动作 | 频率 | 耗时 | CPU | 峰值内存 |
|------|------|------|-----|----------|
| `kanjo export`（有缓存） | 每 5 分钟（定时器） | 6.1 s | 5.5 s | **1.0 GB** |
| `kanjo disk --json` | 每次用量刷新完成后立刻跑（预取） | **45 s** | **48 s**（41 s 是系统调用） | 0.7 GB |

平均下来后台每 5 分钟烧约 55 秒 CPU（≈ 一个核的 18%），这就是「有体感」的来源。

原因：
- 磁盘缓存只要任何一个会话文件的修改时间比扫描时间新就作废；只要你在用 agent，缓存永远不命中，每次都全量遍历（含 worktree 里的 node_modules 等，外加每个 worktree 一次 `git status`）。
- `export` 每次都把 69 MB 的解析缓存和 87 MB 的账本整个重写（用的是 Python 慢速的 `json.dump(handle)`），占了一半 CPU，哪怕什么都没变。
- 不管日志有没有变化都固定 5 分钟全量重建一次。

### 规则

1. **刷新由文件变化触发，不靠固定定时器**
   - App 用 FSEvents 监听各 agent 的日志目录（目录列表由 CLI 提供，例如 `kanjo doctor --json` 或新加 `kanjo paths --json`）。
   - 有变化后**去抖 60 秒**再刷新，两次刷新最少隔 **2 分钟**；正在刷新时再来的变化合并成刷新完后补跑一次。
   - 保底定时器改为 **30 分钟**（额度窗口、账期跨天这类不产生文件变化的更新），设置里的「刷新间隔」改成保底间隔，最小 15 分钟。
   - 打开面板时如果上次刷新超过 2 分钟，立即刷新一次（这是用户能感知的时刻，要准）。
   - 系统睡眠 / 低电量模式时不刷新，唤醒后补一次。
2. **没变化就不干活（CLI）**
   - `export` 先对所有日志文件做 stat 指纹（路径 + 大小 + mtime），与上次一致且距上次 < 30 分钟（额度信息）时直接输出上次结果，不重新解析。
   - 解析缓存、账本只在内容真的变了才写；写的时候用 `json.dumps` 再一次性写入（C 编码器），不要 `json.dump(handle)`。
   - 目标：无变化时 export < 0.5 s CPU；有一个会话变化时 < 2 s CPU；峰值内存降一半以上。
3. **磁盘报告不跟着用量刷新跑**
   - 删掉「用量刷新完 → 立即预取磁盘」。只在打开磁盘页、用户点刷新、或距上次扫描超过 **6 小时**时才扫。
   - 缓存有效性改为时间判断（默认 6 小时），不再因为某个会话文件 mtime 变了就整份作废；只有被改过的条目重新测量大小。
   - 只读计数，不进 node_modules / .build / DerivedData 这类目录内部逐文件遍历（用目录总大小即可，或至少对这类目录用 `du -sk` 一次性取值）；worktree 的 `git status` 结果按 HEAD + index mtime 缓存。
   - 目标：缓存命中 < 1 s；全量扫描 CPU 降到现在的一半以下。
4. **子进程低优先级**
   - App 拉起的 CLI 进程设 `qualityOfService = .background`（或 `nice 10`），让它永远不抢前台。
5. **不变的东西**：统计口径、归属规则、手动刷新按钮的行为（立即全量刷新）都不变。

### 验收

- 前后对比同一台机器：空闲 1 小时内 App + 子进程累计 CPU（`ps -o time`），目标降到现在的 1/10 以下。
- 新会话写入后 ≤ 3 分钟内面板数字更新。
- 现有测试全过；新增 CLI 指纹命中 / 未命中、缓存不写盘的测试；Swift 去抖 / 最小间隔逻辑做成 KanjoCore 纯函数并测试。

## 分批

1. 第一批：A + B + D（pi、step-5 价格）
2. 第二批：F 性能（先做，因为后面每加一个 agent 都会让全量扫描更慢）
3. 第三批：E 里 ★ 的 agent
4. 第四批：E 里其余 agent

每批一个分支 / PR，测试全过再合并。

## 验收

- `cli` 全部测试 + 新增 pi / account 测试通过；`ui` `swift test` 通过。
- 本机真实数据跑 `kanjo export`：出现 `pi` agent、`step-5-preview` 有花费；Claude / Codex / Grok 有 `account.email`；`--mobile` 输出里搜不到 `@`。
- 按测试实例隔离规则启动测试版 app 看 hover 和解析失败行。
