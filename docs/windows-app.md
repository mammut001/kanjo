# Kanjo for Windows · 规则文档

> 目标：做一个 Windows 原生桌面版 Kanjo，界面照搬 Mac 版，功能 100% 迁移。
> 这份文档是写码的依据；每一批任务都按这里的规则验收。

## 1. 技术选型

- **C# / .NET 10 + Avalonia 11（Fluent 主题）**，原生编译的桌面程序，不是网页套壳。
  - 选 Avalonia 而不是 WinUI 3：能在 Mac 上编译、跑单元测试、离屏截图，Windows 上照样是原生窗口；
    WinUI 3 只能在 Windows 上编译，我们没法在 Mac 上快速验证。
- 数据仍然由现有 Python CLI（`kanjo export` 等）计算，App 只负责界面，和 Mac 版同一个 JSON 契约（`CONTRACT.md`）。
- CLI 和一份官方免安装 Python 一起打进安装包，用户**不需要自己装 Python**。
- 打包用 **Velopack**：生成 `Kanjo-Setup.exe`，装在当前用户目录，**不需要管理员权限**，支持从 GitHub Releases 自动更新。
- 支持 Windows 10 22H2 和 Windows 11，x64 和 Arm64。

## 2. 界面（照搬 Mac）

- Mac 的菜单栏图标 → Windows 任务栏右下角的**托盘图标**。
  - 左键点击：在托盘上方弹出和 Mac 一样大小（360×620）的面板；点到别处自动收起。
  - 托盘图标不能显示文字，所以 Mac 菜单栏上的金额改为**鼠标悬停提示**（例如「Kanjo · $3,057 · 30d」），图标本身随状态变化（正常 / 出错）。
  - 右键菜单：打开面板、刷新、设置、退出。
  - 不在任务栏显示窗口按钮（和 Mac 不显示 Dock 图标一致）。
- 面板里的页面、卡片、顺序、文案、颜色、悬停卡片、空状态、错误状态都和 Mac 版一致：
  概览（总额、时间范围、订阅价值卡、方块图、项目列表、按模型、不在项目里）、项目详情、未归属/已排除、磁盘、设置。
- 背景：Windows 11 用 Mica 效果，Windows 10 用纯色；跟随系统浅色/深色。
- 语言：English / 简体中文 / Français，直接读取 Mac 版的 `Localizable.strings`（同一份翻译，不复制）。

## 3. Mac 专属功能的 Windows 替代

| Mac | Windows |
|---|---|
| 菜单栏 MenuBarExtra | 托盘图标 + 弹出面板 |
| UserDefaults 设置 | `%APPDATA%\Kanjo\settings.json` |
| Keychain 存家庭令牌 | Windows 凭据管理器，目标名 `KanjoFamilyReport`（和现在的 Windows 上报脚本、CLI 共用） |
| FSEvents 监听日志变化 | `FileSystemWatcher`，同样的防抖规则 |
| 睡眠/唤醒、低电量模式 | 系统电源事件、节电模式 |
| `/bin/zsh -l -c` 跑 CLI | 直接运行内置 Python：`python.exe -m kanjo …`，不经过 shell |
| 访达「在 Finder 中显示」 | 资源管理器中选中该文件夹 |
| 「在终端中打开」 | Windows Terminal（没有就用 PowerShell） |
| 废纸篓 | 回收站（CLI 的 `disk clean` 要支持 Windows） |
| 缓存 `~/Library/Caches` | `%LOCALAPPDATA%\Kanjo` |
| Command Line Tools 提示 | 不需要（Python 已内置） |
| 打开网址 | 默认浏览器 |
| 文件/文件夹选择框 | Windows 原生选择框 |
| `--snapshot` 离屏截图、`--route`、`--data`、`--window` | 全部保留，参数名不变，用于测试和截图 |

**iCloud 同步到 iPhone**：Windows 没有可用的 iCloud 接口，这一项是唯一做不了的；设置里这一节显示「仅 Mac 可用」。

## 4. CLI 要补的 Windows 支持

- 各家 agent 在 Windows 上的日志位置（如 `%APPDATA%`、`%LOCALAPPDATA%`、`%USERPROFILE%\.claude` 等）全部能找到；找不到的 agent 在 Windows 上标明不支持，而不是报错。
- `kanjo disk` 和 `disk clean` 支持 Windows，清理时移到回收站。
- 完整 CLI 测试在 Windows CI 上全部通过（目前只跑上报相关的几组）。
- Claude 额度读取：Mac 从钥匙串读，Windows 从 Claude Code 在 Windows 上存凭据的位置读。

## 5. 分批

1. **核心层**：数据模型和 JSON 解码、设置存储、CLI 调用、格式化、时间范围、方块图布局、热力条、订阅/上报调度等纯逻辑，照着 Mac 的单元测试逐条移植。外加最小外壳：托盘图标 + 面板，能读 `sample.json` 显示概览页。
2. **全部页面**：概览、项目详情、桶页、磁盘、设置，悬停卡片、右键菜单、拖动排序。
3. **后台行为**：文件监听、自动刷新、电源事件、定时发布、家庭上报、凭据管理器。
4. **CLI Windows 化**（第 4 节）。
5. **打包发布**：Velopack 安装包、自动更新、GitHub Release，Windows CI 构建和测试。

## 6. 验收

- 每批：我审代码、在 Mac 上跑全部 .NET 测试和原有测试（CLI / Swift / 服务端）、看离屏截图和 Mac 版逐页对比。
- 每个页面都对照 Mac 版同一路由的截图，差异要么修掉，要么写明原因。
- 最后在 GreenCloud 的 Windows Server 2022 上用安装包从零安装，逐项过一遍功能清单。
- Mac 版和 CLI 现有行为不能变。

## 不做

- 不做 iCloud / iPhone 同步（见上）。
- 暂不做代码签名证书（首次运行 Windows 可能提示「未知发布者」），等有证书再加。
