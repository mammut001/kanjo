# Smoke test for an installed Kanjo for Windows: run on a real Windows box after installing.
#
#   pwsh windows/scripts/smoke.ps1
#
# Checks (each prints PASS / FAIL, exit code 1 if anything failed):
#   1. %LOCALAPPDATA%\Kanjo\current\Kanjo.exe exists (Velopack per-user install)
#   2. the bundled Python runs the bundled CLI: <install>\python\python.exe -m kanjo --version
#   3. the bundled CLI can find its prices (cli\pricing.json next to cli\kanjo)
#   4. Kanjo.exe --snapshot <png> --route overview renders from the bundled sample.json
#
# Nothing here writes to real settings or data: --snapshot uses the isolated 'kanjo-preview'
# suite, and the CLI version check only imports the package.
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$SnapshotPath = ""
)

$ErrorActionPreference = "Continue"

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Kanjo\current"
}
if (-not $SnapshotPath) {
    $SnapshotPath = Join-Path $env:TEMP "kanjo-smoke.png"
}

$script:Failures = 0

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) {
        Write-Host ("PASS  " + $Name) -ForegroundColor Green
    } else {
        Write-Host ("FAIL  " + $Name) -ForegroundColor Red
        if ($Detail) { Write-Host ("      " + $Detail) -ForegroundColor DarkGray }
        $script:Failures++
    }
}

Write-Host "Kanjo for Windows smoke test" -ForegroundColor Cyan
Write-Host "install dir : $InstallDir"
Write-Host "snapshot    : $SnapshotPath"
Write-Host ""

# 1. Installed executable
$Exe = Join-Path $InstallDir "Kanjo.exe"
Write-Check "Kanjo.exe is installed" (Test-Path $Exe) $Exe

# 2. Bundled Python runs the bundled CLI (`_pth` lists ../cli)
$Python = Join-Path $InstallDir "python\python.exe"
if (-not (Test-Path $Python)) {
    Write-Check "bundled python.exe exists" $false $Python
} else {
    $version = & $Python -m kanjo --version 2>&1
    $ok = $LASTEXITCODE -eq 0 -and "$version" -match '^kanjo \d+\.\d+\.\d+'
    Write-Check "python -m kanjo --version" $ok ("exit $LASTEXITCODE, output: " + ($version -join " | "))
}

# 3. The CLI can load its pricing data from <install>\cli
$CliDir = Join-Path $InstallDir "cli"
$hasPricing = (Test-Path (Join-Path $CliDir "pricing.json")) -and
              (Test-Path (Join-Path $CliDir "pricing_overrides.json")) -and
              (Test-Path (Join-Path $CliDir "kanjo\__init__.py"))
Write-Check "cli\ has kanjo\ + pricing files" $hasPricing $CliDir

# 4. Off-screen render from the bundled sample.json (no window, no display needed)
if (-not (Test-Path $Exe)) {
    Write-Check "Kanjo.exe --snapshot --route overview" $false "Kanjo.exe missing"
} else {
    $sample = Join-Path $InstallDir "sample.json"
    if (-not (Test-Path $sample)) {
        Write-Check "bundled sample.json exists" $false $sample
    }
    Remove-Item -Force $SnapshotPath -ErrorAction SilentlyContinue
    # Kanjo.exe is a GUI (WinExe) binary: --snapshot still returns an exit code, but PowerShell
    # needs Start-Process -Wait to actually wait for it. --data pins the bundled sample.json so the
    # render does not depend on any settings the user changed.
    $snapshotArgs = @(
        "--snapshot", $SnapshotPath,
        "--route", "overview",
        "--snapshot-appearance", "light"
    )
    if (Test-Path $sample) { $snapshotArgs += @("--data", $sample) }
    $proc = Start-Process -FilePath $Exe -PassThru -Wait -ArgumentList $snapshotArgs
    $painted = (Test-Path $SnapshotPath) -and ((Get-Item $SnapshotPath).Length -gt 1024)
    Write-Check "Kanjo.exe --snapshot (route overview)" ($proc.ExitCode -eq 0 -and $painted) `
        "exit $($proc.ExitCode)"
    if ($painted) {
        Write-Host ("      PNG: $SnapshotPath ({0:N1} KB)" -f ((Get-Item $SnapshotPath).Length / 1KB)) -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($script:Failures -eq 0) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
}
Write-Host "$($script:Failures) CHECK(S) FAILED" -ForegroundColor Red
exit 1
