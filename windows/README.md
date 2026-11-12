# Kanjo for Windows

Kanjo（勘定）的 Windows 原生桌面版：托盘图标 + 360×620 弹出面板，界面照搬 Mac 版。
数据仍然由现有 Python CLI 计算（`kanjo export` / `kanjo disk`），App 只负责界面，和 Mac 版同一个
JSON 契约（见仓库根目录的 `CONTRACT.md`）。设计决策见 `docs/windows-app.md`。

本仓库这一批（batch 1）包含：核心层（模型 / 解码 / 格式化 / 时间范围 / 方块图 / 热力条 / 订阅 / 调度 /
设置存储 / CLI 调用 / 本地化）+ 最小外壳（托盘图标、弹出面板、概览页）。

## 结构

```
windows/
  Kanjo.Windows.sln
  src/Kanjo.Core      # net10.0 类库，无 UI 依赖（从 Mac 的 KanjoCore 移植）
  src/Kanjo.App       # Avalonia 11 桌面应用（Fluent 主题）
  tests/Kanjo.Core.Tests  # xUnit，逐条移植 ui/Tests/KanjoTests
  snapshots/          # 概览页离屏截图（light / dark）
```

本地化文案直接链接 Mac 版的 `ui/Sources/KanjoCore/Resources/{en,zh-Hans,fr}.lproj/Localizable.strings`
（不复制文件、不复制翻译）；示例数据链接 `ui/fixtures/sample.json`。
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
```

### 参数

| 参数 | 作用 |
|---|---|
| `--data <file>` / `KANJO_DATA` | 直接读一份导出的 JSON，不跑 CLI |
| `--window` | 普通窗口（开发 / 调试），不使用托盘 |
| `--defaults-suite <name>` / `KANJO_DEFAULTS_SUITE` | 用 `settings-<name>.json` 隔离设置；`--window` / `--snapshot` 会自动用 `kanjo-preview` |
| `--route overview` | 启动时打开哪一页（批次 1 只有 `overview`） |
| `--snapshot <out.png>` | 离屏渲染面板到 PNG 后退出 0 |
| `--snapshot-scale <n>` | 截图倍率（默认 2） |
| `--snapshot-appearance light\|dark` | 截图外观 |

### 截图

```bash
# macOS
$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- \
  --snapshot windows/snapshots/overview-light.png \
  --snapshot-appearance light --data ui/fixtures/sample.json

$HOME/.dotnet/dotnet run --project windows/src/Kanjo.App -- \
  --snapshot windows/snapshots/overview-dark.png \
  --snapshot-appearance dark --data ui/fixtures/sample.json
```

```powershell
# Windows
dotnet run --project windows\src\Kanjo.App -- --snapshot windows\snapshots\overview-light.png `
  --snapshot-appearance light --data ui\fixtures\sample.json
```

`--snapshot` 用 Avalonia.Headless + Skia 离屏渲染，所以在 macOS 上也能出图，
不依赖显示器 / 窗口管理器。

**相对日期与「现在」：** 正常运行（托盘 / `--window`）时「现在」就是真实时钟，和 Mac 一致
（「active yesterday」「renews in 2 days」都跟着当天走）。只有 `--snapshot` 会把「现在」固定在报告的
`generated_at`，这样同一份数据每次截出的图逐像素一致（相对日期、账期倒计时、页脚的
「Updated HH:MM」都不会变）。截图里的页脚因此显示报告的整点时间，而不是截图时刻。

## 设置与数据位置

- 设置：`%APPDATA%\Kanjo\settings.json`（键名与 Mac 版 `SettingsKeys.swift` 一致）。
  `--defaults-suite <name>` 用 `settings-<name>.json`。
- 磁盘报告缓存：`%LOCALAPPDATA%\Kanjo\disk-report.json`。
- CLI 目录：内置 `<appdir>\cli` → 仓库 `cli/`（仅 Debug）→ `%LOCALAPPDATA%\KanjoFamily\cli`。
- Python：内置 `<appdir>\python\python.exe` → `py -3` → PATH 上的 `python`。

## 这一批没做的

- 项目详情 / 桶页 / 磁盘 / 设置页（批次 2）
- 悬停卡片、右键菜单、拖动排序（批次 2）
- 文件监听、自动刷新、电源事件、定时发布、家庭上报、凭据管理器（批次 3）
- CLI 的 Windows 支持与收进安装包（批次 4）
- Velopack 安装包 / 自动更新 / CI（批次 5）
