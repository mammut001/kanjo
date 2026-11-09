# Kanjo iOS — App Store 提交资料

iOS 版是 Mac 版 Kanjo 的只读配套 App：Mac 上的 Kanjo 把用量快照写进用户自己的 iCloud 私有库，
iPhone 读出来展示。这份文档收集提交 App Store 需要填写的内容和上架前的检查清单。

## 1. 上架前检查清单

- [ ] **CloudKit 结构部署到生产环境**：CloudKit Console → 容器 `iCloud.com.lanshuagent.kanjo` →
      Schema → Deploy Schema Changes，把开发环境的 `Snapshot` 记录类型部署到 Production。
      不做这一步，TestFlight 和正式版都读不到 Mac 上传的数据。
- [ ] **用正式环境的 Mac 版验证一次**：Mac 版用 Developer ID 正式签名（entitlements 为 Production），
      打开 iCloud 同步，确认 TestFlight 版 iPhone 能读到快照。
- [ ] **隐私政策页已上线**：<https://cv.paytonpei.top/kanjo/privacy> 能打开。
- [ ] **截图**：iPhone 6.9 英寸（1320 × 2868 或 1290 × 2796），至少 3 张。用「Preview Sample Data」示例数据截图，
      不要露出自己的真实项目名。建议：总览、项目详情、按模型。
- [ ] **名称可用**：在 App Store Connect 新建 App 时确认「Kanjo」没有被占用；被占用就用备选名（见下文）。
- [ ] **版本号**：`ios/project.yml` 的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`，每次上传构建号要递增。
- [ ] **Archive 并上传**：Xcode → Product → Archive → Distribute App → App Store Connect。

加密出口合规已在构建设置里声明（`ITSAppUsesNonExemptEncryption = NO`），上传后不会再询问。

## 2. App Store Connect 基本信息

| 字段 | 内容 |
|---|---|
| 名称 | Kanjo（备选：Kanjo – AI Coding Cost） |
| 副标题（≤30 字符） | AI coding cost per repo |
| 主类别 / 次类别 | Developer Tools / Productivity |
| 年龄分级 | 4+（问卷全部选「无」） |
| 价格 | 免费 |
| 隐私政策网址 | https://cv.paytonpei.top/kanjo/privacy |
| 技术支持网址 | https://github.com/mammut001/kanjo/issues |
| 营销网址（可选） | https://github.com/mammut001/kanjo |
| 是否需要登录 | 否 |

### 关键词（≤100 字符，英文逗号分隔，不加空格）

```
AI,Claude,Codex,Gemini,tokens,usage,cost,developer,coding,agent,LLM,API,quota,repo,tracker
```

## 3. App 隐私（营养标签）

- **数据收集**：选「否，我们不从此 App 收集数据」。
  依据：App 只读取用户自己 iCloud 私有数据库里的记录，开发者无法访问；没有分析、广告、崩溃上报 SDK，
  也没有自己的服务器。
- **追踪**：否。`PrivacyInfo.xcprivacy` 中 `NSPrivacyTracking = false`，只声明了 UserDefaults（CA92.1）。

## 4. 审核备注（App Review Information → Notes，英文）

```
Kanjo for iPhone is a read-only companion to Kanjo for Mac, a free, open-source
menu bar app (https://github.com/mammut001/kanjo) that estimates how much AI coding
agents (Claude Code, Codex, Gemini/Antigravity and others) cost per git repository,
from local log files on the Mac.

The Mac app writes a usage snapshot to the user's own iCloud private database
(CloudKit). The iPhone app reads that snapshot and displays it. There is no account,
no server of ours, and no data collection.

How to review without a Mac running Kanjo:
1. Launch the app. With no snapshot in iCloud it shows "No snapshot yet".
2. Tap "Preview Sample Data". The app loads a bundled sample snapshot and shows the
   full interface: overview, subscription value, quota, projects, project details
   and the per-model breakdown.
3. Tap "Exit" in the sample banner to return.

All amounts are API-equivalent estimates (tokens x public API price), not money the
user has paid; the app states this next to every total.
```

## 5. 商店描述

### English

```
How much did your AI coding agents cost, per project?

Kanjo for iPhone shows the numbers Kanjo for Mac works out from your local AI coding
agent logs: total cost, tokens, sessions, and the split by project, agent and model.

• Overview: total cost and tokens for today, 7 days, 30 days or all time
• Projects: what each git repository cost across every agent you used on it
• Models: which models did the work
• Subscriptions: what your plan's usage would have cost on API billing, and your
  5-hour and weekly quota

Supports Claude Code, Codex CLI, Gemini / Antigravity, Grok, Qwen Code, OpenCode,
Copilot CLI and more.

Private by design: Kanjo for Mac does all the work on your Mac and syncs a summary
through your own iCloud. No account, no server, no tracking.

Requires Kanjo for Mac (free, open source): github.com/mammut001/kanjo

Costs are API-equivalent estimates from public prices, not what you actually paid.
```

### 简体中文

```
你的 AI 编程助手，每个项目花了多少钱？

Kanjo iPhone 版展示 Mac 版 Kanjo 根据本机 AI 编程工具日志算出的结果：总花费、token、会话数，
以及按项目、按工具、按模型的拆分。

• 总览：今天、7 天、30 天或全部时间的总花费和 token
• 项目：每个 git 仓库在所有 AI 工具上的累计花费
• 模型：哪些模型干了最多的活
• 订阅：订阅期内的用量换成 API 价格值多少钱，以及 5 小时和每周额度

支持 Claude Code、Codex CLI、Gemini / Antigravity、Grok、Qwen Code、OpenCode、Copilot CLI 等。

隐私优先：所有统计都在你的 Mac 上完成，只通过你自己的 iCloud 同步汇总结果。
无需账号，没有服务器，不做追踪。

需要配合 Mac 版 Kanjo 使用（免费开源）：github.com/mammut001/kanjo

金额为按公开 API 价格折算的等价成本，不是实际支出。
```

### Français

```
Combien vos agents de code IA ont-ils coûté, projet par projet ?

Kanjo pour iPhone affiche les chiffres que Kanjo pour Mac calcule à partir des
journaux locaux de vos agents de code IA : coût total, tokens, sessions, et la
répartition par projet, par agent et par modèle.

• Vue d'ensemble : coût et tokens sur aujourd'hui, 7 jours, 30 jours ou depuis le début
• Projets : le coût de chaque dépôt git, tous agents confondus
• Modèles : quels modèles ont fait le travail
• Abonnements : ce que votre usage aurait coûté au tarif de l'API, et vos quotas
  sur 5 heures et à la semaine

Prend en charge Claude Code, Codex CLI, Gemini / Antigravity, Grok, Qwen Code,
OpenCode, Copilot CLI et d'autres.

Confidentiel par conception : Kanjo pour Mac fait tout le travail sur votre Mac et
synchronise un résumé via votre propre iCloud. Pas de compte, pas de serveur,
pas de pistage.

Nécessite Kanjo pour Mac (gratuit, open source) : github.com/mammut001/kanjo

Les coûts sont des équivalents estimés à partir des prix publics des API, et non
des montants réellement payés.
```

## 6. 可能被拒的情况与回复要点

| 审核指南 | 可能的理由 | 回复要点 |
|---|---|---|
| 4.2 最低功能 | 「必须先装另一个 App 才能用」 | 这是 Mac App 的配套查看器；审核员可用示例数据完整体验；Mac App 免费开源、可公开下载 |
| 2.1 完整性 | 审核员看到空状态 | 指向审核备注里的「Preview Sample Data」步骤 |
| 5.2 知识产权 | 出现 Claude、OpenAI 等名称 | 只用名称说明兼容的工具，没有使用任何第三方 logo；App 名称和图标不含第三方品牌 |
| 2.3 准确元数据 | 金额被认为误导 | 每个总额旁都标注「API 等价估算，非实际支出」；描述里也写明 |
