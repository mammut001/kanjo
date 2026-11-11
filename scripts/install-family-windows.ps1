# PowerShell 5.1 compatible installer for Kanjo Family Reporter on Windows (no admin rights required)
[CmdletBinding()]
param(
    [string]$Server = "",
    [switch]$Uninstall,
    [string]$Version = "latest",
    [switch]$SkipReport,
    [string]$PythonExe = "",
    [string]$CliZip = "",
    [switch]$NoSchedule,
    [switch]$NoPrompt
)

# Set strict mode and error preferences
$ErrorActionPreference = "Stop"

# Top notice about company IT policy (Chinese + English)
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Kanjo 家庭用量上报安装程序 / Kanjo Family Usage Reporter Setup" -ForegroundColor Cyan
Write-Host "注意：在公司电脑上运行脚本并向外部服务器上报用量可能违反公司 IT 规定。" -ForegroundColor Yellow
Write-Host "请确认符合公司策略后再继续。" -ForegroundColor Yellow
Write-Host "Notice: Running scripts and reporting usage on corporate computers" -ForegroundColor Yellow
Write-Host "may violate company IT policies. Please verify compliance before proceeding." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

# Check execution policy early if possible
try {
    $execPolicy = Get-ExecutionPolicy
    if ($execPolicy -eq "Restricted" -or $execPolicy -eq "AllSigned") {
        Write-Warning "PowerShell 执行策略受限 (Current ExecutionPolicy is $execPolicy)."
        Write-Warning "如遇权限错误，请使用: powershell -ExecutionPolicy Bypass -NoProfile -File ... 运行本脚本。"
    }
} catch {
    # Non-fatal
}

$InstallDir = Join-Path $env:LOCALAPPDATA "KanjoFamily"
$CliDir = Join-Path $InstallDir "cli"
$PythonDir = Join-Path $InstallDir "python"
$TaskName = "Kanjo 家庭上报"
$Interactive = [Environment]::UserInteractive -and -not $NoPrompt

# -----------------------------------------------------------------------------
# Uninstall Mode
# -----------------------------------------------------------------------------
if ($Uninstall) {
    Write-Host "`n正在卸载 Kanjo 家庭上报 / Uninstalling Kanjo Family Reporter..." -ForegroundColor Cyan

    # 1. Remove scheduled task
    try {
        if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
    } catch {}
    try {
        & schtasks.exe /delete /tn "$TaskName" /f 2>$null | Out-Null
    } catch {}
    Write-Host "  [✓] 计划任务已删除 (Scheduled task removed)"

    # 2. Clear stored credential from Credential Manager
    $pyForClear = if ($PythonExe -and (Test-Path $PythonExe)) {
        $PythonExe
    } elseif (Test-Path (Join-Path $PythonDir "python.exe")) {
        Join-Path $PythonDir "python.exe"
    } else {
        (Get-Command python -ErrorAction SilentlyContinue).Source
    }

    if ($pyForClear -and (Test-Path $CliDir)) {
        try {
            $env:PYTHONPATH = $CliDir
            & $pyForClear -m kanjo family-token clear 2>$null | Out-Null
        } catch {}
    }
    # Fallback deletion via cmdkey
    try {
        & cmdkey /delete:KanjoFamilyReport 2>$null | Out-Null
    } catch {}
    Write-Host "  [✓] 凭据已清理 (Credential cleared)"

    # 3. Remove install directory
    if (Test-Path $InstallDir) {
        try {
            Remove-Item -Recurse -Force -Path $InstallDir -ErrorAction Stop
            Write-Host "  [✓] 安装目录已删除 (Folder removed: $InstallDir)"
        } catch {
            Write-Warning "无法完全删除目录 ${InstallDir}: $_"
        }
    }

    Write-Host "`n卸载完成！/ Uninstall complete." -ForegroundColor Green
    exit 0
}

# -----------------------------------------------------------------------------
# Verify / Prompt for Family Server URL
# -----------------------------------------------------------------------------
if (-not $Server) {
    if ($Interactive) {
        while (-not $Server) {
            $inputServer = Read-Host "请输入家庭服务器地址 / Enter family server URL (e.g. https://usage.example.com)"
            if ($inputServer) {
                $trimmed = $inputServer.Trim()
                if ($trimmed.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
                    $Server = $trimmed
                } else {
                    Write-Warning "服务器地址必须以 https:// 开头 / Server URL must start with https://"
                }
            }
        }
    } else {
        Write-Error "缺少必填参数 -Server。非交互或 -NoPrompt 模式下必须指定家庭服务器地址 (e.g. -Server https://usage.example.com) / Missing required parameter: -Server. In non-interactive or -NoPrompt mode, you must provide the family server URL."
        exit 1
    }
} else {
    $Server = $Server.Trim()
    if (-not $Server.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Error "服务器地址必须以 https:// 开头 / Server URL must start with https://: ${Server}"
        exit 1
    }
}

# -----------------------------------------------------------------------------
# 1. Detect or Download Python (>= 3.9)
# -----------------------------------------------------------------------------
Write-Host "`n[1/5] 检查 Python 环境 / Checking Python environment..." -ForegroundColor Cyan

$SelectedPython = ""
if ($PythonExe) {
    if (Test-Path $PythonExe) {
        $SelectedPython = $PythonExe
    } else {
        $resolved = (Get-Command $PythonExe -ErrorAction SilentlyContinue).Source
        if ($resolved) {
            $SelectedPython = $resolved
        }
    }
    if (-not $SelectedPython) {
        Write-Error "指定的 Python 未找到 (Specified -PythonExe not found): $PythonExe"
        exit 1
    }
}

if (-not $SelectedPython -and (Test-Path (Join-Path $PythonDir "python.exe"))) {
    $SelectedPython = Join-Path $PythonDir "python.exe"
}

if (-not $SelectedPython) {
    foreach ($cand in @("python", "py -3")) {
        try {
            $tokens = $cand.Split()
            $cmdName = $tokens[0]
            $cmdArgs = if ($tokens.Length -gt 1) { $tokens[1..($tokens.Length-1)] } else { @() }
            $res = & $cmdName $cmdArgs -c "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')" 2>$null
            $exe = "$res".Trim()
            if ($exe -and (Test-Path $exe)) {
                $SelectedPython = $exe
                break
            }
        } catch {}
    }
}

if ($SelectedPython) {
    Write-Host "  [✓] 使用 Python: $SelectedPython"
} else {
    Write-Host "  未找到兼容的 Python (>= 3.9)，将下载官方免安装包 (Downloading official embeddable Python)..."
    New-Item -ItemType Directory -Path $PythonDir -Force | Out-Null

    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
    if ($arch -eq "arm64") {
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-arm64.zip"
        $expectedHash = "D34DB37675973785A2A539CD1C8DDE1B6D45665F48C615EF55274B3798BF9FD3"
    } else {
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
        $expectedHash = "8D3F33BE9EB810F23C102F08475AF2854E50484B8E4E06275E937BE61CE3D2FB"
    }

    $pyZip = Join-Path $InstallDir "python-embed.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host "  正在下载 / Downloading: $pyUrl"
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyZip -UseBasicParsing
    } catch {
        Write-Error "下载 Python 失败 (Failed to download Python): $_. 可能被公司网络代理拦截或防火墙限制 (May be blocked by corporate proxy or firewall)."
        exit 1
    }

    # Verify SHA-256
    $actualHash = (Get-FileHash -Path $pyZip -Algorithm SHA256).Hash
    if ($actualHash.ToUpper() -ne $expectedHash.ToUpper()) {
        Remove-Item -Force $pyZip -ErrorAction SilentlyContinue
        Write-Error "Python 压缩包 SHA-256 校验不匹配 (Checksum verification failed): expected $expectedHash, got $actualHash"
        exit 1
    }
    Write-Host "  [✓] SHA-256 校验通过 (Checksum verified)"

    Expand-Archive -Path $pyZip -DestinationPath $PythonDir -Force
    Remove-Item -Force $pyZip -ErrorAction SilentlyContinue

    # Configure ._pth so embeddable python can import from ../cli
    $pth = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
    if ($pth) {
        Add-Content -Path $pth.FullName -Value "../cli"
    }

    $SelectedPython = Join-Path $PythonDir "python.exe"
    Write-Host "  [✓] Python 解压完成: $SelectedPython"
}

# Resolve pythonw.exe for background execution
$pyDir = Split-Path $SelectedPython
$PythonwExe = Join-Path $pyDir "pythonw.exe"
if (-not (Test-Path $PythonwExe)) {
    $PythonwExe = $SelectedPython
}

# -----------------------------------------------------------------------------
# 2. Extract or Download Kanjo CLI
# -----------------------------------------------------------------------------
Write-Host "`n[2/5] 部署 Kanjo CLI / Deploying Kanjo CLI..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $CliDir -Force | Out-Null

if ($CliZip) {
    Write-Host "  从本地压缩包部署 (Deploying from local zip): $CliZip"
    if (-not (Test-Path $CliZip)) {
        Write-Error "指定的 CLI 压缩包不存在 (Specified -CliZip does not exist): $CliZip"
        exit 1
    }
    Expand-Archive -Path $CliZip -DestinationPath $CliDir -Force
} else {
    $cliUrl = if ($Version -eq "latest") {
        "https://github.com/mammut001/kanjo/releases/latest/download/kanjo-cli.zip"
    } else {
        "https://github.com/mammut001/kanjo/releases/download/$Version/kanjo-cli.zip"
    }

    $cliZipPath = Join-Path $InstallDir "kanjo-cli.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host "  正在下载 / Downloading: $cliUrl"
        Invoke-WebRequest -Uri $cliUrl -OutFile $cliZipPath -UseBasicParsing
    } catch {
        Write-Error "下载 Kanjo CLI 失败 (Failed to download Kanjo CLI): $_. 可能被公司网络代理拦截或防火墙限制 (May be blocked by corporate proxy or firewall)."
        exit 1
    }

    Expand-Archive -Path $cliZipPath -DestinationPath $CliDir -Force
    Remove-Item -Force $cliZipPath -ErrorAction SilentlyContinue
}
$Launcher = Join-Path $CliDir "kanjo_family_report.pyw"
Set-Content -Path $Launcher -Encoding ASCII -Value @'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kanjo.cli import main
sys.exit(main())
'@
Write-Host "  [✓] Kanjo CLI 部署至: $CliDir"

# -----------------------------------------------------------------------------
# 3. Setup Family Report Token
# -----------------------------------------------------------------------------
Write-Host "`n[3/5] 配置上报令牌 / Configuring report token..." -ForegroundColor Cyan

# Set PYTHONPATH so python runs kanjo CLI modules cleanly
$env:PYTHONPATH = $CliDir

$tokenStatus = ""
try {
    $tokenStatus = & $SelectedPython -m kanjo family-token status 2>$null
} catch {}

$hasExistingToken = ($tokenStatus -match "set") -and (-not ($tokenStatus -match "not set"))

$needPrompt = $true
if ($hasExistingToken) {
    Write-Host "  凭据管理器中已有家庭令牌 (Family token already exists in Windows Credential Manager)."
    if ($Interactive -and -not $SkipReport) {
        $answer = Read-Host "  是否更换令牌？/ Replace token? [y/N]"
        if ($answer -notmatch '^[yY]') {
            $needPrompt = $false
        }
    } else {
        $needPrompt = $false
    }
}

if ($needPrompt) {
    if ($Interactive) {
        $secToken = Read-Host -Prompt "  请输入家庭上报令牌 (Paste Family Report Token)" -AsSecureString
        if ($secToken) {
            $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secToken)
            $plainToken = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

            $res = $plainToken | & $SelectedPython -m kanjo family-token set 2>&1
            $plainToken = $null
            Write-Host "  [✓] 令牌已存入 Windows 凭据管理器 (Saved to Credential Manager): $res"
        } else {
            Write-Warning "  未输入令牌，可稍后运行: python -m kanjo family-token set"
        }
    } else {
        Write-Host "  非交互环境且未提供令牌。请在安装后通过管道运行: python -m kanjo family-token set"
    }
}

# -----------------------------------------------------------------------------
# 4. Member Label & Scheduled Task
# -----------------------------------------------------------------------------
Write-Host "`n[4/5] 配置计划任务 / Configuring scheduled task..." -ForegroundColor Cyan

$MemberLabel = $env:COMPUTERNAME
if ($Interactive -and -not $SkipReport) {
    $labelInput = Read-Host "  成员显示名 (Member label) [默认: $env:COMPUTERNAME]"
    if (-not [string]::IsNullOrWhiteSpace($labelInput)) {
        $MemberLabel = $labelInput.Trim()
    }
}
Write-Host "  成员显示名: $MemberLabel"

if (-not $NoSchedule) {
    $scheduledOk = $false
    # 1. Try Register-ScheduledTask (built-in Windows PowerShell)
    if (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue) {
        try {
            $taskAction = New-ScheduledTaskAction -Execute $PythonwExe -Argument "`"$Launcher`" report-family --url `"$Server`" --member-label `"$MemberLabel`"" -WorkingDirectory $CliDir
            $taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
            $taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable:$false -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
            Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Force | Out-Null
            $scheduledOk = $true
            Write-Host "  [✓] 计划任务创建成功 (每 30 分钟上报一次) / Scheduled task registered." -ForegroundColor Green
        } catch {
            Write-Warning "  Register-ScheduledTask 失败: $_. 尝试使用 schtasks.exe 兜底..."
        }
    }

    # 2. Fallback to schtasks.exe
    if (-not $scheduledOk) {
        try {
            $tr = "`"$PythonwExe`" `"$Launcher`" report-family --url `"$Server`" --member-label `"$MemberLabel`""
            $schOut = & schtasks.exe /create /tn "$TaskName" /tr "$tr" /sc minute /mo 30 /f 2>&1
            if ($LASTEXITCODE -eq 0) {
                $scheduledOk = $true
                Write-Host "  [✓] 计划任务创建成功 (通过 schtasks.exe) / Scheduled task registered." -ForegroundColor Green
            } else {
                throw $schOut
            }
        } catch {
            Write-Error "无法创建计划任务 (Failed to create scheduled task): $_. 可能被公司组策略禁止 (May be restricted by company Group Policy)."
            exit 1
        }
    }
} else {
    Write-Host "  [i] 已跳过计划任务配置 (-NoSchedule)"
}

# -----------------------------------------------------------------------------
# 5. Immediate First Report
# -----------------------------------------------------------------------------
if (-not $SkipReport) {
    Write-Host "`n[5/5] 执行首次上报 / Performing immediate first report..." -ForegroundColor Cyan
    try {
        $repOut = & $SelectedPython -m kanjo report-family --url "$Server" --member-label "$MemberLabel" 2>&1
        Write-Host "  上报输出: $repOut"
    } catch {
        Write-Warning "  首次上报遇到问题: $_"
    }
} else {
    Write-Host "`n[5/5] 跳过首次上报 (-SkipReport)"
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "Kanjo 家庭上报安装成功！/ Installation completed successfully!" -ForegroundColor Green
Write-Host "卸载方式 / To uninstall:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -NoProfile -File `"$PSCommandPath`" -Uninstall" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
