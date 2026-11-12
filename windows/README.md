# Kanjo for Windows

Kanjo（勘定）的 Windows 原生桌面版：托盘图标 + 360×620 弹出面板，界面照搬 Mac 版。
数据仍然由现有 Python CLI 计算（`kanjo export` / `kanjo disk` / `kanjo config`），App 只负责界面，和 Mac 版同一个
JSON 契约（见仓库根目录的 `CONTRACT.md`）。设计决策见 `docs/windows-app.md`。

已完成：核心层（模型 / 解码 / 格式化 / 时间范围 / 方块图 / 热力条 / 订阅 / 调度 / 设置存储 / CLI 调用 / 本地化）
+ 外壳（托盘图标、弹出面板、底栏）+ 全部页面（总览、项目详情、桶详情、磁盘、设置）+ 悬停卡 / 右键菜单 / 拖动排序
+ 后台行为（文件监听、兜底定时器、睡眠 / 唤醒 / 节电模式、磁盘预取、定时发布、家庭上报、单实例）。

## 结构

```
windows/
  Kanjo.Windows.sln
  src/Kanjo.Core      # net10.0 类库，无 UI 依赖（从 Mac 的 KanjoCore 移植）
  src/Kanjo.App       # Avalonia 11 桌面应用（Fluent 主题）
  tests/Kanjo.Core.Tests  # xUnit，逐条移植 ui/Tests/KanjoTests
  snapshots/          # 各路由的离屏截图（见下）
  scripts/snapshots.sh    # 一次生成全部截图
```

本地化文案直接链接 Mac 版的 `ui/Sources/KanjoCore/Resources/{en,zh-Hans,fr}.lproj/Localizable.strings`
（不复制文件、不复制翻译）；只有必须按平台改写的句子放在 `Core/WindowsL10n.cs`（「Move to Recycle Bin」
「Show in Explorer」「iCloud sync is Mac only」等，含中英法三语）。示例数据链接 `ui/fixtures/sample.json`。
Swift → C# 的测试逐一对照与跳过说明见 [`tests/PORTING.md`](tests/PORTING.md)。

## 构建与测试

macOS 上 dotnet 没有在 PATH 里，用 `$HOME/.dotnet/dotnet`：

```bash
# macOS（开发）
$HOME/.dotnet/dotnet build windows/Kanjo.Windows.sln
$HOME/.dotnet/dotnet test  windows/Kanjo.Windows.sln

# Windows
dotnet build windows/Kanjo.Windows.sln
dotnet test  windows/Kanjo.Windows.sln
```

## 运行

```bash
# macOS
$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- --data ui/fixtures/sample.json

# Windows
dotnet run --project windows\src\Kanjo.App -- --data ui\fixtures\sample.json
```

默认是托盘应用（Windows 上是右下角通知区域图标）。开发时用普通窗口：

```bash
$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- --window --data ui/fixtures/sample.json
$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- --window --route project:0 --data ui/fixtures/sample.json
```

### 参数

| 参数 | 作用 |
|---|---|
| `--data <file>` / `KANJO_DATA` | 直接读一份导出的 JSON，不跑 CLI |
| `--disk-data <file>` | 磁盘页读这份磁盘报告 JSON，不跑 `kanjo disk` |
| `--window` | 普通窗口（开发 / 调试），不使用托盘 |
| `--defaults-suite <name>` / `KANJO_DEFAULTS_SUITE` | 用 `settings-<name>.json` 隔离设置；`--window` / `--snapshot` 会自动用 `kanjo-preview` |
| `--route <value>` | 启动时打开哪一页（见下） |
| `--snapshot <out.png>` | 离屏渲染面板到 PNG 后退出 0 |
| `--snapshot-scale <n>` | 截图倍率（默认 2） |
| `--snapshot-appearance light\|dark` | 截图外观 |

### 路由

和 Mac 的 `--route` 逐字一致（`MenuPanelView.swift` 里的 `DevRoute`）：

`overview`、`overview-bottom`、`project:<i>[:bottom|:locations|:hover:…]`、`bucket:unattributed`、`bucket:excluded`、
`disk`、`disk:expanded`、`settings`、`settings-bottom`、`settings:subscriptions:<agent>[:edit]`、`loading[:sec]`。

截图用的固定悬停卡：`overview:quota:<agent>`、`overview:tile:<n>`、`overview:hover:legend`、
`overview:hover:heat:<i>:<week>`、`overview:hover:dots:<i>`、`overview:hover:model:<i>`、
`project:<i>:hover:tokens|model:<j>|branch:<j>|day|session:<j>`。

### 截图

```bash
# macOS
bash windows/scripts/snapshots.sh            # 全部路由，写进 windows/snapshots/
bash windows/scripts/snapshots.sh /opt/homebrew/bin/dotnet

# 单张
$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- \
  --snapshot windows/snapshots/overview-light.png --route overview \
  --snapshot-appearance light --data ui/fixtures/sample.json \
  --disk-data ui/fixtures/disk-sample.json
```

`--snapshot` 用 Avalonia.Headless + Skia 离屏渲染，所以在 macOS 上也能出图，不依赖显示器 / 窗口管理器。
可滚动的页面按整页高度渲染（和 Mac 的 TALL 截图一致）。面板会挂进一个不显示的 `Window`（TopLevel）再截：
`TextBox`、`Button` 这类模板控件只有在 TopLevel 下才会套用 ControlTheme，否则截出来是空白的。

**相对日期与「现在」：** 正常运行（托盘 / `--window`）时「现在」就是真实时钟，和 Mac 一致
（「active yesterday」「renews in 2 days」都跟着当天走）。只有 `--snapshot` 会把「现在」固定在报告的
`generated_at`，这样同一份数据每次截出的图逐像素一致。

## 设置与数据位置

- 设置：`%APPDATA%\Kanjo\settings.json`（键名与 Mac 版 `SettingsKeys.swift` 一致）。
  `--defaults-suite <name>` 用 `settings-<name>.json`。
- 磁盘报告缓存：`%LOCALAPPDATA%\Kanjo\disk-report.json`。
- 家庭上报令牌：Windows 凭据管理器，目标名 `KanjoFamilyReport`（P/Invoke `advapi32` 的
  `CredRead` / `CredWrite` / `CredDelete`）。非 Windows 开发运行退回内存实现，绝不碰真实凭据。
- CLI 目录：内置 `<appdir>\cli` → 仓库 `cli/`（仅 Debug）→ `%LOCALAPPDATA%\KanjoFamily\cli`。
- Python：内置 `<appdir>\python\python.exe` → `py -3` → PATH 上的 `python`。

## Windows 与 Mac 的差异（有意为之）

- **清理按钮说「Move to Recycle Bin」**，不是 Trash：Windows 上回收站才是对应概念。文案在
  `Core/WindowsL10n.cs`，其余全部复用 Mac 的字符串表。
- **右键菜单是「Show in Explorer」**（Mac 是 Finder），终端优先 Windows Terminal（`wt -d <path>`），
  没有就用 `powershell -NoExit -Command Set-Location`。
- **iCloud sync 一节只显示标题 + 「Mac only」说明**，没有开关（Windows 版不做手机快照上传）。
- **CLI 命令不走 shell**：直接起 `python` 子进程（Mac 走 `/bin/zsh -l -c`），所以设置里的
  「Runs as a subprocess…」文案不同。
- **强调色按钮跟随窗口激活状态**：SwiftUI 的 `.borderedProminent` 只在活动窗口里是蓝的；
  面板弹出时是活动窗口（蓝色），失焦 / 收起后变灰白。截图（`--snapshot`）和 Mac 的参考图一样按非活动窗口渲染。
- Mac 的「Install Command Line Tools」提示不适用：Windows 版内置 Python。

## 后台行为（批次 3）

启动顺序和 Mac 的 `ReportStore.init` 一致：先刷一次用量（`refresh()`），再建兜底定时器（`restartTimer()`），
最后解析日志目录挂监听（`setupWatcher()`）。整条链路在 `Core/BackgroundRefresh.cs`（`RefreshEngine`），
纯逻辑、计时器和系统事件都由外面注入，测试用假实现，不碰真实时钟。

| 行为 | Windows 实现 | 对应 Mac |
|---|---|---|
| 日志监听 | `FileSystemWatcher`（递归，200ms 合并事件），目录来自 `kanjo paths --json` | FSEvents `LogWatcher`，同一份 `paths --json` |
| 防抖 / 最小间隔 / 合并 | `RefreshScheduler`（60s 防抖、上不晚于首事件 180s、两次刷新区间 ≥120s、刷新中合并） | `KanjoCore.RefreshScheduler` |
| 兜底定时器 | 「Fallback refresh interval」设置，0 = 关；改设置立即重排 | `Timer.scheduledTimer` + `restartTimer()` |
| 睡眠 / 唤醒 | `SystemEvents.PowerModeChanged` → `Suspend()` / `Resume()` | `NSWorkspace.willSleep/didWake` |
| 节电模式 | `GetSystemPowerStatus` 的 `SystemStatusFlag`，30 秒轮询一次（Windows 没有对应事件） | `.NSProcessInfoPowerStateDidChange` |
| 面板打开 | 超过 120 秒没刷就后台刷一次（托盘点开 / 第二次启动激活都算） | `MenuPanelView.onAppear` → `onPanelOpened()` |
| 磁盘预取 | 第一次在用量刷新后 15 秒，之后立即；有新刷新会取消未触发的预取；只缺报告 / 过期时才跑 | `DiskStore.schedulePrefetch(delay:)` |
| 发布到网站 | 每次用量刷新后按频率 / 退避判断，跑 `publish-usage --repo … [--file …] [--branch …]`（120s 超时） | `PublishStore` |
| 家庭上报 | 同上条件（15 分钟间隔、失败退避 30 分钟），跑 `report-family --url … [--member-label …]`（45s 超时） | `FamilyReportStore` |
| 单实例 | 命名 Mutex + 命名管道：第二次启动发 `Activate` 让已运行实例弹面板，然后退出 0 | macOS 由系统激活已有实例 |

**家庭令牌只走环境变量。** 和 Mac 传给 CLI 的方式一致（`KANJO_FAMILY_TOKEN`）：凭据管理器里的令牌由 App 读出，
作为子进程环境变量传入，永远不出现在命令行参数里（`CliRunner.ReportFamily`）。

**日志目录：** Mac 用 `kanjo paths --json` 拿各 agent 的日志根目录；Windows 版**也走同一个命令**（CLI 第 4 批会在
Windows 上返回 `%USERPROFILE%` / `%APPDATA%` / `%LOCALAPPDATA%` 下的真实位置），所以不需要另外维护一份路径表。
不存在的目录直接跳过；一个都不剩就没有监听器，下一次刷新会再试一次（和 Mac 一样）。

**磁盘缓存：** `%LOCALAPPDATA%\Kanjo\disk-report.json`，预取 / 手动刷新成功后写入；启动时先读缓存再决定要不要扫描。
`--disk-data` 时不读也不写缓存（演示数据不该污染真实缓存）。

**状态文字（设置页）：** 发布 / 家庭上报的文案和 Mac 一字不差，包括「未联网」（`KANJO_NO_NETWORK=1` 或
报告的 `config.no_network`）时是橙色的提示而不是错误。超时文案也照抄：`Command timed out after 120s` / `45s`。

**和 PowerShell 上报脚本不要同时开：** Windows 上还有一个独立的 PowerShell 家庭上报脚本（计划任务
「Kanjo 家庭上报」）。它和这个 App 走同一个凭据条目和同一个服务器，两个都开着会重复上报。
**只用其中一个**：用 App 就把计划任务停掉（`Disable-ScheduledTask -TaskName "Kanjo 家庭上报"`），反之亦然。
Mac 上不存在这个脚本，所以 App 里没有对应提示。

**单实例：** 只有托盘模式限制单实例；`--window`（开发预览）和 `--snapshot`（离屏截图）可以随便开多个。
第二次启动会等 2 秒尝试连上主实例的管道，连不上就当作自己启动（宁可多开也不开不起来）。

## 这一批没做的

- 开机自启（批次 5 随安装包一起做）。
- Velopack 安装包 / 自动更新 / CI（批次 5）
