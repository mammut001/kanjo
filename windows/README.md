# Kanjo for Windows

Kanjo（勘定）的 Windows 原生桌面版：托盘图标 + 360×620 弹出面板，界面照搬 Mac 版。
数据仍然由现有 Python CLI 计算（`kanjo export` / `kanjo disk` / `kanjo config`），App 只负责界面，和 Mac 版同一个
JSON 契约（见仓库根目录的 `CONTRACT.md`）。设计决策见 `docs/windows-app.md`。

已完成：核心层（模型 / 解码 / 格式化 / 时间范围 / 方块图 / 热力条 / 订阅 / 调度 / 设置存储 / CLI 调用 / 本地化）
+ 外壳（托盘图标、弹出面板、底栏）+ 全部页面（总览、项目详情、桶详情、磁盘、设置）+ 悬停卡 / 右键菜单 / 拖动排序
+ 后台行为（文件监听、兜底定时器、睡眠 / 唤醒 / 节电模式、磁盘预取、定时发布、家庭上报、单实例）
+ 打包（Velopack 安装包、内置 Python + CLI、自动更新、Windows CI）。

## 结构

```
windows/
  Kanjo.Windows.sln
  src/Kanjo.Core      # net10.0 类库，无 UI 依赖（从 Mac 的 KanjoCore 移植）
  src/Kanjo.App       # Avalonia 11 桌面应用（Fluent 主题）
  src/Kanjo.App/Assets    # Kanjo.ico（应用图标）/ Tray.ico / TrayError.ico（托盘）
  tests/Kanjo.Core.Tests  # xUnit，逐条移植 ui/Tests/KanjoTests
  snapshots/          # 各路由的离屏截图（见下）
  scripts/snapshots.sh    # 一次生成全部截图
  scripts/build-release.sh / .ps1   # 打包：publish + python + CLI + vpk（见下）
  scripts/smoke.ps1       # 安装后冒烟测试（真机）
  scripts/make-icons.py   # 由 ui/Resources/Kanjo.png 生成 .ico（需要 Pillow）
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

## 设计（Design）

界面按 **Windows 11（Fluent / WinUI）** 的规范来做，而不是照搬 Mac 版的外观。所有颜色与间距常量
都集中在 `Theme/Palette.cs`，视图里不出现裸 16 进制。

### 表面与版式

| | 浅色 | 深色 |
|---|---|---|
| 窗口 / 页面底色（没有 Mica 时的实底） | `#F3F3F3` | `#202020` |
| 卡片底 | `#FFFFFF` | `#2B2B2B` |
| 卡片描边 / 分割线 | `#CFCFCF` | `#4C4C4C` |

- 窗口优先用 **Mica**（`PanelWindow` 里 `TransparencyLevelHint`）；Windows 10 / Server 2022 没有 Mica 时
  退回上面那层实色，再配 1px 描边，所以两种环境下都是「卡片浮在底色上」。
- **横向空间只有两层**：页面左右留白 12（`Metrics.PagePadding`）+ 卡片左右内边距 12（`Metrics.RowInset`），
  一行的可用宽度就是 `Metrics.RowContentWidth`（332）。面板只有 360，再厚一层就会把内容挤两次 ——
  review 里的「Cycle 被切成 Cy」「Edit 被切掉」都是这么来的。卡片：圆角 8、1px 描边；
  同一分组里卡片之间 4px，分组之间 24px。唯一的例外是总览的马赛克卡片，它贴到面板边缘（出血），
  这样色块才有足够宽度显示标签。
- 放不下的整行控件**换行而不是溢出**：额度重置行（日期一行、控件一行、Apply / Reset 右对齐一行）
  和订阅行的三个按钮都是右对齐的独立一行。
- 总览 header 的范围胶囊是**横向可滚动的单行**（不画滚动条，右缘有渐隐提示还有更多），
  7 个胶囊永远不折行、不切词；"Total cost" 标签独占一行。
- 设置页照 Windows 11「设置」的版式：分组标题（BodyStrong）在上，下面一卡一项（左边标题 + 一行说明，
  右边右对齐的控件，最小宽 200）。面板只有 360px，放不下「标题 + 200px 控件」时控件落到下一行（和 Win11 窄窗一致）。

### 字号（`Type`）

Title 28 semibold（页面标题、大额数字）/ Subtitle 20 / BodyStrong 14 semibold（分组标题）/
Body 14 / Caption 12。Windows 上用 Segoe UI Variable（回退 Segoe UI）。

### 对比度（WCAG 2.1）

`tests/.../ContrastTests.cs` 把下面每一对都算一遍并在明 / 暗两种外观下断言：

| 用途 | 浅色 | 深色 | 门槛 | 实测（卡片 / 背景） |
|---|---|---|---|---|
| primary 文字 | `#1A1A1A` | `#FFFFFF` | ≥ 12:1 | 17.4 / 15.7（dark 14.2 / 16.3） |
| secondary 文字 | `#5D5D5D` | `#C8C8C8` | ≥ 4.5:1 | 6.6 / 5.9（dark 8.5 / 9.7） |
| tertiary / caption | `#616161` | `#BFBFBF` | ≥ 4.5:1 | 6.2 / 5.6（dark 7.7 / 8.9） |
| disabled 文字与描边 | `#8A8A8A` | `#8A8A8A` | ≥ 3:1 | 3.4 / 3.1（dark 4.1 / 4.7） |
| 卡片描边 / 分割线 | `#CFCFCF` | `#4C4C4C` | ≥ 1.5:1 | 1.56（dark 1.65） |
| 强调色上的文字 | 白 | 近黑 | ≥ 4.5:1 | 6.3（dark 10.6） |

- 强调色取系统色（`PlatformSettings.GetColorValues().AccentColor1`），拿不到时用 `#005FB8` / `#60CDFF`。
  系统色可能太浅（比如黄色）或刚好卡在 4.49:1，所以链接色与按钮底色会在保证 ≥ 4.5:1 的前提下
  朝安全方向微调（`Palette.LinkColor` / `AccentFillColor`）。
- **不用 alpha 叠在灰底上**：旧版用 `Foreground × 0.26` 叠出「次要色」，实际只有 1.9:1 —— 这就是
  用户报的「禁用按钮和占位符几乎看不见」。现在全部是实色，禁用控件也不再套 Fluent 模板的
  `#CCCCCC` 底（那配灰字只有 2.7:1），而是自绘一个 3:1 以上的静态禁用外观。
- agent 色保持不变（它们要跨 Mac / iOS / Windows 识别）；马赛克色块上的文字按块亮度选白或近黑，
  必要时把色块朝反方向微调最多 4%，保证 ≥ 4.5:1（`Palette.TileInk`）。

## 滚动与动效

- 所有可滚动页面继承 `ScrollPage`（`Theme/ScrollPage.cs`），它只是 `ScrollViewer` 加两件事：
  - 覆写 `StyleKeyOverride` 指回 `ScrollViewer`。**这是「设置页滚不动」的真正原因**：Avalonia 用样式键
    决定套哪个 ControlTheme，`OverviewPage : ScrollViewer` 的子类样式键是子类自己，于是 Fluent 主题里
    的 `ScrollViewer` 模板（含 `ScrollContentPresenter` 与滚动条）根本没套上 —— `Extent` 恒为 0，
    滚轮、拖滚动条、触摸板全都无效。
  - 在隧道路由里按 `WheelPolicy` 决定滚轮归谁：指针停在收起的 ComboBox / NumericUpDown / 单行 TextBox 上
    时滚页面、绝不改值（Windows 11 设置页的行为）；展开的下拉列表自己滚；嵌套滚动区到边界后链给外层。
- 触摸板 / 触摸屏开启 `IsScrollInertiaEnabled`，滚动条用 Fluent 的自动隐藏悬浮样式（悬停展开）。
- 页面切换 ≈150ms 淡入 + 8px 上滑；面板从托盘弹出同样 150ms（`Theme/Motion.cs`）。
  系统关掉动画（`UISettings.AnimationsEnabled`）或 `--snapshot` 时一律不做动画。
  返回总览会恢复上次的滚动位置。

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

## 打包、安装、更新（批次 5）

正式版用 **Velopack** 打成 per-user 安装包（`%LOCALAPPDATA%\Kanjo`，不需要管理员权限），
支持从 GitHub Releases 自动更新。版本号来自仓库根目录的 `VERSION`（App 的 `Version` 由 MSBuild 读这个文件，
所以 **App 版本 == CLI 版本**；`build-release` 也会核对传进来的版本号）。

### 产物

| 文件 | 说明 |
|---|---|
| `windows/dist/<rid>/` | 发布文件夹：`Kanjo.exe` + .NET 10 运行时 + `python\` + `cli\` + `sample.json` |
| `windows/dist/Kanjo-<rid>-<version>.zip` | 同一个文件夹的 zip（本地试用 / 手动分发） |
| `windows/dist/releases/<rid>/KanjoApp-<rid>-Setup.exe` | 安装包（`vpk pack` 生成），装到 `%LOCALAPPDATA%\KanjoApp` |
| `windows/dist/releases/<rid>/KanjoApp-<version>-<rid>-full.nupkg` | 更新包（自动更新下载这个） |
| `windows/dist/releases/<rid>/RELEASES-<rid>` | 更新清单（`UpdateManager` 读它） |

`<rid>` 是 `win-x64` 或 `win-arm64`；通道名也用 `<rid>`，两种架构的更新互不干扰。

### 构建

Windows（CI 走这条）：

```powershell
dotnet tool install -g vpk --version 1.2.158   # 一次性
pwsh windows/scripts/build-release.ps1 -Version (Get-Content -Raw VERSION).Trim() -Rid win-x64
```

macOS（本地交叉编译，dotnet publish 支持；vpk 用 `[win]` 指令也能从 macOS 打 Windows 安装包）：

```bash
dotnet tool install -g vpk --version 1.2.158
bash windows/scripts/build-release.sh "$(tr -d '[:space:]' < VERSION)" win-x64
```

两个脚本做的事一样：`dotnet publish -c Release -r <rid> --self-contained`（单文件夹，不做 single-file——
Avalonia 的原生库必须和 exe 并排；**不做 trimming**，Avalonia 依赖反射）→ 下载官方免安装 Python 3.12.8
（和 `scripts/install-family-windows.ps1` 同 URL、同 SHA-256 校验）→ 拷贝 CLI → `vpk pack`。

`PublishReadyToRun=true` 在 macOS 上交叉编译也能用（产物是 win-x64 的 R2R，已核对 CLR 头不是 ILOnly）。

### Python + CLI 是怎么装进包里的

```
<install>\Kanjo.exe
<install>\sample.json                 CLI 不可用时的兜底数据（只在「文件来源 + 路径留空」时读）
<install>\python\python.exe           官方 embeddable 3.12.8（amd64 / arm64 各一份）
<install>\python\python312._pth       末尾加了 ../cli
<install>\cli\kanjo\...               cli/kanjo 去掉 __pycache__ / *.pyc
<install>\cli\pricing.json
<install>\cli\pricing_overrides.json
<install>\cli\VERSION                 设置页「Bundled CLI <版本>」读这个（和 Mac 的 .app 一样）
```

- `python312._pth` 里的 `../cli` 是相对 `python.exe` 的，所以 `<install>\cli` 直接进了 `sys.path`，
  `<install>\python\python.exe -m kanjo --version` 就能跑。CLI 只用标准库，**不需要** `import site`
  （那一行保持注释）。
- App 的 `CliRunner` 找的正是 `<appdir>\python\python.exe` 和 `<appdir>\cli`（`DefaultPaths.BundledPython` /
  `BundledCliDirectory`；`<appdir>` 是 `AppContext.BaseDirectory`，安装版里就是
  `%LOCALAPPDATA%\KanjoApp\current\`），所以装好后不用装任何 Python，也不用改设置。
- **默认数据源是 CLI**（`Core/SourceResolution.cs`，对应 Mac 的 `ReportStore.init`）：
  找得到内置 CLI 就用 CLI，找不到才用 JSON 文件；文件来源下只有路径留空才会读 `sample.json`。
  所以安装版永远不会悄悄显示示例数据——没有 agent 日志时，面板显示的是 Mac 那套「首次扫描 / 空报告」状态，
  CLI 失败时显示 Mac 的错误状态（`OverviewPage.ErrorOrLoading`）。
- 设置页的命令占位符就是实际执行的命令：有内置 Python 时是
  `<appdir>\python\python.exe -m kanjo export`（`DefaultPaths.DefaultCliCommand`）。
- `cli\` 的内容除了多一个 `VERSION`，和 CI 里 `kanjo-cli.zip` 那一步完全一样（同一个目录结构、同样剔掉字节码）。

### 安装

双击 `KanjoApp-win-x64-Setup.exe`（Arm64 机器用 `KanjoApp-win-arm64-Setup.exe`）。不需要管理员权限：
装到 `%LOCALAPPDATA%\KanjoApp\current`，开始菜单出现「Kanjo」，**不会**创建桌面快捷方式
（`vpk pack --shortcuts StartMenuRoot`）。安装完自动启动一次。

**为什么安装目录叫 `KanjoApp` 而不是 `Kanjo`：** Windows 路径不区分大小写，`%LOCALAPPDATA%\Kanjo`
和 CLI 的数据 / 缓存目录 `%LOCALAPPDATA%\kanjo`（批次 4 起就在这里）是**同一个文件夹**。先用过 CLI /
家庭上报的机器上，Setup.exe 会以为「已经装过了」，而卸载会连账本一起删掉。所以包的 id（决定安装根目录）
是 `KanjoApp`，产品名仍然是 `Kanjo`（`--packTitle Kanjo`：开始菜单和应用列表都显示 Kanjo），
**所有数据目录保持原样**，老用户的数据不受影响。`Core/AppPaths.cs` 是这几条路径的唯一来源，
`AppPathsTests` 会断言安装根目录和每个数据 / 缓存目录都不同。

包**没有代码签名**，所以 Windows 可能弹「Windows 已保护你的电脑」：点「更多信息 → 仍要运行」。

### 自动更新

- `UpdateManager` 用 `GithubSource("https://github.com/mammut001/kanjo")`，检查当前 `<rid>` 通道的
  `RELEASES-<rid>`；启动 30 秒后检查一次，之后每 6 小时一次（`Core/UpdatePolicy.cs`）。
- 有新版就在后台**下载**；装的时候是「下次启动」：Velopack 的 `SetAutoApplyOnStartup` 在下次启动时
  换掉文件再拉起新版本。**不会**自己重启。
- Mac 版没有更新界面，所以这里也不弹窗、不在面板里提示。唯一的 UI 是托盘菜单里多一项
  **「重启以更新 / Restart to update」**，而且只在更新已经下载好之后才出现（`WindowsL10n` 里的
  `update.restart_to_install`）。
- 这些情况**完全不碰更新**：`--snapshot`、`--window`、Debug 构建、不是 Velopack 装的（开发运行、
  解压出来的文件夹、便携版）。

### 卸载

「设置 → 应用 → 已安装的应用 → Kanjo → 卸载」，或者运行 `%LOCALAPPDATA%\KanjoApp\Update.exe --uninstall`。
Velopack 会删掉程序目录 `%LOCALAPPDATA%\KanjoApp`、开始菜单快捷方式和 `Run` 键（如果曾经有）。
**用户数据保留**（数据目录都不在安装根目录里，所以卸载不会碰到它们）：

- `%APPDATA%\Kanjo`（设置 `settings.json`）
- `%LOCALAPPDATA%\kanjo`（CLI 的账本 / 缓存）
- Windows 凭据管理器里的 `KanjoFamilyReport`（和 CLI 共用；要清就 `python -m kanjo family-token clear`）

和 Mac 的 zap 规则一致：卸载不删数据，想彻底清干净得手动删上面两个目录。

**开机自启：** Mac 版没有开机自启（`ui/` 里没有 Login Item 注册），所以 Windows 版默认也不注册
`HKCU\...\Run\Kanjo`。卸载钩子仍然会把这个键清掉（`Core/WindowsStartup.RemoveRunEntry`），
免得旧版本或手动设置留下的项指向已删除的 exe。

### 冒烟测试（真机装完后跑）

```powershell
pwsh windows/scripts/smoke.ps1                 # 默认查 %LOCALAPPDATA%\KanjoApp\current
pwsh windows/scripts/smoke.ps1 -InstallDir "D:\KanjoApp\current"
```

逐项打印 PASS / FAIL，任何一项失败退出码 1：

1. `Kanjo.exe` 在 `%LOCALAPPDATA%\KanjoApp\current`；
2. `python\python.exe -m kanjo --version` 输出 `kanjo <版本>`（和仓库 VERSION 一致）；
3. `cli\` 里 `kanjo\`、两个 pricing 文件和 `VERSION` 齐全；
4. 在安装目录里跑 `python\python.exe -m kanjo export` 退出 0 且 stdout 是 JSON；
5. `Kanjo.exe --print-source=<file>`：解析出来的 python 是 `<appdir>\python\python.exe`、
   CLI 目录是 `<appdir>\cli`、数据源是 CLI（不是示例数据 / 文件），并且安装根目录和每个数据目录都不同；
6. `Kanjo.exe --snapshot` 能出 PNG。

`--print-source` 是批次 5 加的诊断开关，只读（不跑 CLI、不写设置），输出 `key=value` 一行一条：

```text
appDir / installRoot / settingsFile
source=cli|file, sourceStored, sampleData=true|false
python, pythonArgs, bundledPython
cliDir, bundledCli, cliVersion
workingDirectorySetting, commandSetting, defaultCommand
file
```

### CI

`.github/workflows/ci.yml` 的 `windows-app` 任务（`windows-latest`）：`dotnet build -warnaserror` +
`dotnet test windows/Kanjo.Windows.sln`（每次 push / PR）。打 tag（`v*`）时额外跑
`build-release.ps1` 的 win-x64 与 win-arm64、`vpk pack`，把 `Setup.exe` / `nupkg` / `RELEASES` / zip
作为 workflow artifact 上传；如果维护者已经建好了对应的 GitHub Release，再用 `gh release upload` 附上去
（release 还不存在只记一条 warning，不会让任务失败）。tag 名必须和 `VERSION` 一致。

## 这一批没做的

- 代码签名（spec 的「不做」一节）：首次运行会有 SmartScreen 提示。
