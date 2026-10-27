# Kanjo iOS + iCloud 同步：设计草案（待确认）

状态：草案，未开工。确认后再写代码。

## 1. 目标

- 手机上打开 Kanjo，就能看到 Mac 上算好的 AI 用量：总花费、订阅价值、5 小时 / 每周额度、项目、按模型。
- 手机只读、不计算：所有统计仍由 Mac 上的 `kanjo export` 完成。
- 数据只存在用户自己的 iCloud 私有空间，不经过任何服务器。

不在首版里做：在手机上改设置或订阅、磁盘清理、多台 Mac 合并（只取最新一台）。

## 2. 整体流程

```
Mac: kanjo export（每 5 分钟） → Kanjo.app 生成「手机快照」 → CloudKit 私有库
iPhone: 打开 App / 小组件刷新 → 读最新快照 → 用 KanjoCore 渲染
```

## 3. 同步方式：CloudKit 私有数据库（推荐）

| 方案 | 结论 |
|---|---|
| CloudKit 私有库 | 推荐。Apple 明确支持 Developer ID 分发的 Mac app；两端原生 API；有推送可选 |
| iCloud Drive 文件 | 备选。Developer ID 下的文档容器支持不如 CloudKit 明确，且文件下载时机不可控 |
| 自建服务器 | 不做。违背「数据不出用户 iCloud」 |

记录设计（容器 `iCloud.com.lanshuagent.kanjo`，私有库默认 zone）：

- 记录类型 `Snapshot`，一台 Mac 一条，recordName = Mac 的设备 ID（首次生成后存在本机设置里）。
- 字段：`deviceName`（如 “MacBook Pro”）、`generatedAt`、`schemaVersion`、`payload`（CKAsset，gzip 后的快照 JSON）。
- Mac 每次刷新成功后覆盖写这一条；内容 hash 没变就不上传。
- 手机读所有 `Snapshot`，取 `generatedAt` 最新的一条展示，同时显示“更新于 10:42 · MacBook Pro”。

## 4. 手机快照格式

在现有 export（CONTRACT.md §2）上瘦身，复用同一套 Swift 模型解码：

- 保留：`schema_version`、`generated_at`、`timezone`、`currency`、`cost_note`、`quota_windows`、`subscriptions`、`totals`、`buckets`（只留汇总）。
- 每个项目保留：`id`、`name`、`cost`、`tokens`、`sessions`、`last_active`、`by_agent`、`by_model`、`by_day`。
- 去掉：`paths`、`remote`、`by_branch`、`sessions_detail`（体积大头，且含路径）。
- 隐私选项（设置里，默认关）：「同步时隐藏项目名」→ 项目名替换为 “Project 1…n”。
- 预计大小：真实数据下 export 为数 MB，瘦身 + gzip 后目标 < 200 KB。

由 CLI 新增 `kanjo export --mobile` 生成（Python 侧裁剪，Swift 侧不改解码）。

## 5. iOS App 首版

- 新 Xcode 工程 `ios/`，引用 `ui/` 里的 `KanjoCore`（SwiftPM 本地包），中英法三语直接复用。
- 页面：
  1. 总览：总花费、时间范围（全部 / 今天 / 7 天 / 30 天）、订阅价值卡（含 5 小时 / 每周额度条）、项目列表。
  2. 项目详情：按 agent、按模型、按天柱状图。
  3. 按模型。
  4. 空状态：未开启同步 / 尚无数据时说明如何在 Mac 上打开同步。
- 小组件（第二步）：今天花费；Claude / ChatGPT 每周额度进度（锁屏圆环）。

## 6. 签名、公证、iCloud 配置（需要你用开发者账号操作）

1. Apple Developer 后台：给 `com.lanshuagent.kanjo` 开 iCloud（CloudKit），建容器 `iCloud.com.lanshuagent.kanjo`。
2. 生成 **Developer ID** 描述文件（含该容器），下载。
3. 存 notarytool 凭据：`xcrun notarytool store-credentials kanjo-notary …`。
4. iOS：新建 iOS App ID（同一容器），开发阶段 Xcode 自动签名即可。

我这边要改的：

- `ui/package.sh`：嵌入描述文件（`Contents/embedded.provisionprofile`），entitlements 加 iCloud 容器和 `com.apple.developer.icloud-container-environment = Production`，然后签名 → 公证 → staple。
- 风险点：从 Xcode 运行正常、装进「应用程序」后连不上 CloudKit，通常是描述文件未生效或环境混用。需要在真机上实测，不能只靠读代码。

### package.sh 还需要什么（T3/T4 代码已就位，打包步骤未做）

T3 的代码在 `#if canImport(CloudKit)` 后面，没有 entitlements 也能编译和跑测试；没有开关 / iCloud 账户时不会发起任何 CloudKit 请求。等账号和描述文件就绪后，`ui/package.sh` 还需要：

1. 把含 `iCloud.com.lanshuagent.kanjo` 的 **Developer ID** 描述文件复制到 `Kanjo.app/Contents/embedded.provisionprofile`。
2. 生成并传入 entitlements 文件，至少包含：
   - `com.apple.developer.icloud-container-identifiers` = `["iCloud.com.lanshuagent.kanjo"]`
   - `com.apple.developer.icloud-services` = `["CloudKit"]`
   - `com.apple.developer.icloud-container-environment` = `Production`（本地调试可用 `Development`）
3. 用这份 entitlements 对主可执行文件签名（`codesign --entitlements … --options runtime`），再走公证 / staple。
4. 在 CloudKit Dashboard 把 `Snapshot` 记录类型和 `deviceName` / `generatedAt` / `schemaVersion` / `payload` 字段从 Development 部署到 Production；否则发布版查询会失败。
5. 真机验证：Developer ID 签名的 app 装进「应用程序」后仍能 `accountStatus == .available` 并成功写入私有库。模拟器 / 无描述文件的构建只能验证编译和 UI。

## 7. 分步计划

| 步骤 | 内容 | 依赖 |
|---|---|---|
| 1 | `kanjo export --mobile` + 测试 | 无 |
| 2 | Mac：设置里「同步到 iCloud」开关 + CloudKit 上传 | 第 6 节 1–3 |
| 3 | 打包：描述文件 + entitlements + 公证跑通 | 第 6 节 1–3 |
| 4 | iOS App 首版（读快照 + 三个页面） | 第 6 节 4 |
| 5 | 小组件 | 4 |

第 1 步现在就能做，不依赖你的账号操作。

## 8. 已确认（2026-10-27）

1. 同步用 CloudKit 私有库（与 dogether 同一套做法：Team `Z5D5N7CU6L`，`com.apple.developer.icloud-services = CloudKit`）。
2. 手机快照去掉会话明细和路径；「隐藏项目名」做成可选开关，默认关。
3. iOS 首版页面：总览 / 项目详情 / 按模型。
4. 直接上 App Store。

## 9. 任务拆分（OpenCode 免费模型写，主会话审）

| 任务 | 范围 | 可并行 |
|---|---|---|
| T1 | CLI `kanjo export --mobile [--hide-project-names]` + 测试 | 是 |
| T2 | KanjoCore 支持 iOS（`Package.swift` 加 `.iOS(.v17)`，去掉 KanjoCore 里的 AppKit 依赖）+ `ios/` XcodeGen 工程 + 三个页面，先读内置示例快照 | 是 |
| T3 | Mac：设置里「同步到 iCloud」开关 + CloudKit 上传 | 需第 6 节 1–3 |
| T4 | iOS：从 CloudKit 读取快照，替换内置示例 | T2、T3 |
| T5 | 打包：描述文件 + entitlements + 公证；App Store 提交 | 第 6 节 |
