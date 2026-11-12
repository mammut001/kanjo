# 移植对照（Swift → C#）

`ui/Tests/KanjoTests/*.swift` 里的每个测试文件在 `windows/tests/Kanjo.Core.Tests/` 都有一份同名 C# 文件，
测试方法名用 PascalCase（`testFooBar` → `TestFooBar`）。下面是逐一对照与跳过说明。

## 逐文件对照

| Swift（ui/Tests/KanjoTests） | C#（windows/tests/Kanjo.Core.Tests） | Swift 用例数 | C# 用例数 | 备注 |
|---|---|---|---|---|
| `AgentColorsTests.swift` | `AgentColorsTests.cs` | 4 | 5 | 新增「未知 agent 回退中性色」 |
| `AppDefaultsTests.swift` | `AppDefaultsTests.cs` | 11 | 11 | UserDefaults → JSON 设置文件 |
| `ConfigCommandTests.swift` | `ConfigCommandTests.cs` | 7 | 7 | 命令前缀改成 `python.exe` / `C:\…` |
| `DecodingTests.swift` | `DecodingTests.cs` | 24 | 23 | `testCLIDataSourceReadsStdout` / `testCLIDataSourceReportsFailure` 移到 `CliRunnerTests.cs`（同名方法）；`testCLIDataSource*` 里用 `cat` 的部分改成假 python 脚本 |
| `DiskTests.swift` | `DiskTests.cs` | 16 | 16 | |
| `FamilyReportMigrationTests.swift` | `FamilyReportMigrationTests.cs` | 6 | 4 | UserDefaults suite → 内存 `AppSettings`；状态计算的两条用例合并进 `FamilyReportScheduleTests.cs` |
| `FamilyReportScheduleTests.swift` | `FamilyReportScheduleTests.cs` | 10 | 11 | 吸收 `testFamilyReportStatusCalculation` |
| `FirstScanHintTests.swift` | `FirstScanHintTests.cs` | 8 | 8 | |
| `FormattingTests.swift` | `FormattingTests.cs` | 11 | 11 | |
| `HeatStripTests.swift` | `HeatStripTests.cs` | 15 | 15 | |
| `HoverCardLayoutTests.swift` | `HoverCardLayoutTests.cs` | 6 | 6 | CGRect/CGSize → 自带的 `HoverRect` / `HoverSize` |
| `KnownPlanTests.swift` | `KnownPlanTests.cs` | 5 | 6 | 新增 fallback 档位覆盖检查 |
| `LocalizationTests.swift` | `LocalizationTests.cs` | 9 | 11 | 新增 `.strings` 解析器与 printf→.NET 格式转换；Bundle 相关用例换成目录查找 |
| `ModelAggregationTests.swift` | `ModelAggregationTests.cs` | 5 | 6 | 新增最大余额法精确性检查 |
| `PathKindsTests.swift` | `PathKindsTests.cs` | 3 | 4 | 新增 Windows 临时目录（`%TEMP%`、`%LOCALAPPDATA%\Temp`）与盘符路径 |
| `ProjectPrefsTests.swift` | `ProjectPrefsTests.cs` | 4 | 4 | |
| `PublishScheduleTests.swift` | `PublishScheduleTests.cs` | 9 | 9 | |
| `RangeCaptionTests.swift` | `RangeCaptionTests.cs` | 11 | 12 | 新增「caption 走 report 与走 spec 结果一致」 |
| `RefreshSchedulerTests.swift` | `RefreshSchedulerTests.cs` | 9 | 9 | |
| `SubscriptionOrderTests.swift` | `SubscriptionOrderTests.cs` | 6 | 6 | |
| `SubscriptionTests.swift` | `SubscriptionTests.cs` | 14 | 14 | |
| `SyncFingerprintTests.swift` | `SyncFingerprintTests.cs` | 2 | 2 | |
| `TimeRangeTests.swift` | `TimeRangeTests.cs` | 23 | 23 | |
| `TooltipBuilderTests.swift` | `TooltipBuilderTests.cs` | 11 | 11 | |
| `TreemapTests.swift` | `TreemapTests.cs` | 12 | 12 | CGRect → `TreemapRect` |

C# 额外的文件（Swift 里没有对应测试文件的纯新增覆盖）：

| 文件 | 覆盖 |
|---|---|
| `SettingsStoreTests.cs` | JSON 设置文件的读写、类型容错、suite 隔离、时间戳 |
| `CliRunnerTests.cs` | 进程直连（不经 shell）、参数 / 工作目录 / 环境变量、stdin 关闭、超时杀进程、空输出、CLI 目录与 Python 查找顺序 |
| `TrayTooltipTests.cs` | Windows 托盘 tooltip（`Kanjo · $3,057 · 30d`）与状态 |
| `DevRouteTests.cs` | `--route` 解析（含需要报告才能解析的取值、索引越界、订阅编辑路由、悬停锚点） |
| `DiskSelectionTests.cs` | 磁盘可选条目、选择集与失效条目、清理计划分组（整条目 vs 子路径、最深的条目优先、报告顺序、Other 分组）、`DiskReportState` 状态机、Older than 档位与 caption、扫描时间文案、`DiskStore` 文件源拒绝清理 |
| `SettingsValidationTests.cs` | 订阅编辑表单校验与字段计算（计划必填 / 价格必填 / 非法价格 / 已知档位用标价 / 覆盖价 / 自定义档位 / 续费日越界）、菜单标题、选择回填、`config` 参数顺序、agent 列表顺序、家庭范围文案、额度重置取值、Windows 专属文案覆盖（三语）、凭据存储假实现与 `ReportActivity` |
| `RefreshEngineTests.cs` | 文件事件 → 防抖 / 最大等待 / 刷新中合并、兜底定时器取值与重排、睡眠 / 唤醒 / 节电模式、面板打开只在过期时刷、用户刷新取消待触发任务、监听器重建 |
| `DiskPrefetchTests.cs` | 第一次预取等 15 秒、之后立即、取消与释放 |
| `ReportStoresTests.cs` | 发布 / 家庭上报的命令行参数、令牌只走环境变量、`pushed` / `unchanged` / `sent` / `error` / 非 0 退出 / 超时的结果解析、状态文案与持久化、调度（退避与间隔）不满足时不发 |
| `SingleInstanceTests.cs` | 主实例监听、第二实例发送激活、启动瞬间的激活请求补发、假传输层与命名（真实实现只验证名字生成与 Mutex 互斥） |
| `LogWatchPathsTests.cs` | 只有 CLI 数据源且没有 `--data` 才监听、`paths --json` 跨 agent 去重（Windows 路径忽略大小写）、过滤不存在的目录 |
| `FileSystemLogWatcherTests.cs` | 真实 `FileSystemWatcher`：缺失目录不建监听、写文件会触发回调、释放后不再触发 |
| `AppServicesBackgroundTests.cs` | 后台接线：刷新保留上一份报告、磁盘预取（含 `--disk-data` 跳过）、文件来源 / `--data` 不挂监听、兜底定时器跟着设置、电源事件到达调度器、截图模式静止、`ApplySettings` 重排 |

## 跳过的 Mac 专属用例

| Swift 用例 | 原因 |
|---|---|
| `PythonCheckTests.testMissingToolsDiagnostic` | 检查 Xcode Command Line Tools（`xcode-select`）；Windows 版内置 Python，不需要这一步。对应的 Windows 行为（内置 Python → `py -3` → PATH）由 `CliRunnerTests.TestPythonLookupOrder` / `TestCliDirectoryLookupOrder` 覆盖。 |
| `SnapshotRecordTests.testGzipDecompressesKnownPayload` | iCloud 快照用的 gzip 解压；Windows 没有 iCloud 同步（spec 第 3 节明确不做）。 |
| `SnapshotRecordTests.testAccountCodeIsStableShortHex` | CloudKit 账号码，同上。 |
| `SnapshotRecordTests.testLatestRecordNameConstant` | CloudKit record name，同上。 |
| `SnapshotRecordTests.testMakeRecordUsesCustomRecordNameOrDefaultsToDeviceID` | CloudKit record 构造（`#if canImport(CloudKit)`），同上。 |
| `SnapshotRecordTests.testGzipRejectsNonGzipData` | gzip，同上。 |
| `SnapshotRecordTests.testContentHashIgnoresGeneratedAt` | gzip + 内容哈希，同上。 |
| `SnapshotRecordTests.testFieldDictionaryRoundTrip` | CloudKit 字段字典，同上。 |
| `SnapshotRecordTests.testParseRejectsMissingFields` | CloudKit 记录解析，同上。 |
| `SnapshotRecordTests.testNewestPicksLatestGeneratedAt` / `testNewestTieBreaksDeterministically` | CloudKit 记录挑选，同上。 |
| `SnapshotRecordTests.testDeviceIDIsStableAndPersisted` | 依赖 UserDefaults suite；设备 ID 属于批次 3 的云端同步。 |
| `SnapshotRecordTests.testMobileSnapshotDecodesWithoutFullExportFields` | **未跳过**：等价用例是 `DecodingTests.TestSlimMobileSessionsDecode` + `TestMissingSubscriptionsDecodesAsNil`（手机快照的字段缺失语义已在解码层覆盖）。 |
| `SnapshotRecordTests.testSplitPayload*`（4 条） | CloudKit 分片上传，Windows 不做 iCloud。 |
| `FamilyTokenKeychain`（`MockFamilyTokenStorage` 那部分） | macOS Keychain；Windows 版用凭据管理器（`WindowsCredentialFamilyTokenStorage`，非 Windows 开发运行退回内存实现）。等价的假实现用例是 `SettingsValidationTests.TestInMemoryTokenStorage` / `TestCredentialStorageFallsBackOffWindows`。 |
| `RefreshSchedulerTests` 之外的 FSEvents / `NSWorkspace` 相关行为 | Mac 的 `LogWatcher` 直接包了 CoreServices 的 `FSEventStream`，没有单元测试；Windows 版把监听器抽象成 `ILogWatcherFactory`，`RefreshEngineTests` 用假实现验证防抖链路，`FileSystemLogWatcherTests` 用临时目录验证真实的 `FileSystemWatcher`。电源事件同理（`FakePowerMonitor` + `WindowsPowerMonitor.QueryLowPowerMode` 的守卫）。 |

`KanjoTestCase.swift` 没有测试用例；对应的是 `KanjoTestCase.cs`（每个测试强制英文 + 隔离内存设置）。
