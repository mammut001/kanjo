# 家庭用量 · Windows 上报（规则草案）

> 场景：家庭成员只有一台 Windows 电脑（可能是公司电脑），装不了也没有 Kanjo App。
> 目标：不需要管理员权限，把这台电脑上的 Antigravity 用量和额度按时报到 `usage.paytonpei.top`。
> 先确认规则再写码。

## 0. 前提和边界

- **公司规定优先**：在公司电脑上运行脚本、把使用数据报到外部服务器，可能违反公司 IT 规定。README 和安装脚本开头都要写清楚，由成员自己确认后再装。
- 上报内容与 Mac 完全一样：只有汇总数字、模型名、Antigravity 额度百分比和重置时间；不含项目名、路径、对话内容、邮箱。默认只统计 Antigravity。
- **只做上报，不做界面**：Windows 上没有菜单栏 App，也不做 Kanjo 的其他功能（treemap、磁盘页等）。
- 可能被公司策略挡住的地方（遇到就如实报错，不绕过）：PowerShell 脚本执行策略被锁成 AllSigned、禁止下载 Python、禁止创建计划任务、出站访问被代理拦截。

## 1. 安装方式（不需要管理员）

一行命令，在 PowerShell（普通用户）里运行：

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://github.com/mammut001/kanjo/releases/latest/download/install-family-windows.ps1 | iex"
```

`-ExecutionPolicy Bypass` 只对这一个进程生效，不改系统设置，也不需要管理员。

脚本做的事：

1. 装到 `%LOCALAPPDATA%\KanjoFamily\`，不碰系统目录、不写注册表 HKLM。
2. **Python**：本机有 `python` 3.9+ 就直接用；没有就下载 python.org 官方的 *embeddable* 压缩包（免安装，校验 SHA-256），解压到 `KanjoFamily\python\`。
3. **Kanjo CLI**：下载 Release 里的 `kanjo-cli.zip`（同一版本），解压到 `KanjoFamily\cli\`。
4. **令牌**：用 `Read-Host -AsSecureString` 让用户粘贴，写进 **Windows 凭据管理器**（通用凭据，目标名 `KanjoFamilyReport`），不出现在命令行参数里，也不写明文文件。
5. **服务器地址**：默认 `https://usage.paytonpei.top`，可用参数改。
6. **定时任务**：当前用户的计划任务「Kanjo 家庭上报」，每 30 分钟用 `pythonw.exe -m kanjo report-family --url …` 运行一次（不弹黑窗）；电脑睡眠错过的次数不补跑。
7. 装完立即上报一次，把结果（成功 / 错误原因）打印出来。

卸载：`install-family-windows.ps1 -Uninstall` 删除计划任务、凭据和 `%LOCALAPPDATA%\KanjoFamily\`。

## 2. CLI 需要改的地方（Windows 兼容）

- `report-family`：环境变量 `KANJO_FAMILY_TOKEN` 没有时，在 Windows 上用 ctypes 调 `advapi32.CredReadW` 读 `KanjoFamilyReport`；Mac 上行为不变。
- Antigravity 额度：找语言服务进程时，Windows 用 PowerShell `Get-CimInstance Win32_Process` 取进程命令行（参照 Tokei 的 `_antigravity_running_processes`），其余逻辑不变；拿不到就不带额度，用量照常上报。
- 数据和缓存目录：Windows 用 `%LOCALAPPDATA%\kanjo\`。
- 只在 Mac/Linux 存在的调用（`os.getuid`、`du`、`/bin/ps`）在 Windows 上要有分支，至少不能让 `export` / `report-family` 崩。
- 日志路径：Antigravity 在 Windows 上同样位于 `%USERPROFILE%\.gemini\antigravity-cli` 和 `\.gemini\antigravity`，沿用现有 `expanduser` 写法。

## 3. 测试

- 我没有 Windows 机器，所以在 **GitHub Actions 的 `windows-latest`** 上跑：
  - 完整 CLI 测试套件；
  - 安装脚本的冒烟测试：用 embeddable Python 安装、写入/读取凭据、`export --family-report` 用测试 fixture 生成报文并通过服务器校验器、计划任务创建再删除；
  - **不向真实服务器发送**（测试用本地起的 HTTP 服务）。
- 真机验证由你在那台 Windows 上跑一次安装命令完成，我根据输出排错。

## 4. 发布

- Release 新增两个附件：`install-family-windows.ps1`、`kanjo-cli.zip`（只含 `cli/kanjo` 和 `cli/pricing*.json`）。
- README 的「家庭用量」表格里 Windows 一行改为上面的一行安装命令，并写清楚第 0 节的边界。
