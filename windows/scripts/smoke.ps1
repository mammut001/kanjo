# Smoke test for an installed Kanjo for Windows: run on a real Windows box after installing.
#
#   pwsh windows/scripts/smoke.ps1
#   pwsh windows/scripts/smoke.ps1 -InstallDir "D:\Apps\KanjoApp\current"
#
# Checks (each prints PASS / FAIL, exit code 1 if anything failed):
#   1. %LOCALAPPDATA%\KanjoApp\current\Kanjo.exe exists (Velopack per-user install)
#   2. the bundled Python runs the bundled CLI: <install>\python\python.exe -m kanjo --version
#   3. the bundled CLI can find its prices (cli\pricing.json next to cli\kanjo) and its VERSION
#   4. `python\python.exe -m kanjo export` from the install dir exits 0 with JSON on stdout
#   5. --print-source resolves the bundled python, the bundled cli dir, and the CLI data source
#      (never the sample JSON; the install folder must not be a data folder)
#   6. Kanjo.exe --snapshot <png> --route overview renders a PNG
#
# The snapshot run uses --data <install>\sample.json and the isolated 'kanjo-preview' settings
# suite, so it never reads or writes the real settings file. Everything else is read-only.
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$SnapshotPath = ""
)

$ErrorActionPreference = "Continue"

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "KanjoApp\current"
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

function Invoke-Captured {
    # Kanjo.exe is a GUI (WinExe) binary: Start-Process -Wait is the only reliable way to wait
    # for it and get its exit code. -ArgumentList joins with spaces and does not quote, so
    # arguments that may contain spaces (TEMT paths) are quoted here.
    param([string]$File, [string[]]$Arguments)
    $quoted = $Arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }
    $proc = Start-Process -FilePath $File -PassThru -Wait -NoNewWindow -ArgumentList $quoted
    return $proc.ExitCode
}

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

# 3. The CLI can load its pricing data and version from <install>\cli
$CliDir = Join-Path $InstallDir "cli"
$hasPricing = (Test-Path (Join-Path $CliDir "pricing.json")) -and
              (Test-Path (Join-Path $CliDir "pricing_overrides.json")) -and
              (Test-Path (Join-Path $CliDir "kanjo\__init__.py"))
Write-Check "cli\ has kanjo\ + pricing files" $hasPricing $CliDir
Write-Check "cli\VERSION exists (Bundled CLI <version> in Settings)" `
    (Test-Path (Join-Path $CliDir "VERSION")) (Join-Path $CliDir "VERSION")

# 4. `python -m kanjo export` from the install dir must succeed and print JSON.
if (Test-Path $Python) {
    Push-Location $InstallDir
    try {
        $json = & $Python -m kanjo export 2>&1
        $jsonExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $text = ($json | Out-String).Trim()
    $looksJson = $text.StartsWith("{") -and $text.EndsWith("}")
    Write-Check "python -m kanjo export exits 0 with JSON" ($jsonExit -eq 0 -and $looksJson) `
        ("exit $jsonExit, " + $text.Length + " chars: " + $text.Substring(0, [Math]::Min(160, $text.Length)))
}

# 5. --print-source: the app must use the bundled python + bundled cli, and the CLI data source.
$sourceFile = Join-Path $env:TEMP "kanjo-source.txt"
Remove-Item -Force $sourceFile -ErrorAction SilentlyContinue
if (Test-Path $Exe) {
    $code = Invoke-Captured $Exe @("--print-source=$sourceFile")
    if (Test-Path $sourceFile) {
        $map = @{}
        foreach ($line in Get-Content $sourceFile) {
            $i = $line.IndexOf('=')
            if ($i -gt 0) { $map[$line.Substring(0, $i)] = $line.Substring($i + 1) }
        }
        Write-Host ("      --print-source: source={0} python={1} cliDir={2}" -f `
            $map['source'], $map['python'], $map['cliDir']) -ForegroundColor DarkGray

        Write-Check "--print-source exits 0" ($code -eq 0) "exit $code"
        Write-Check "resolved python is <install>\python\python.exe" `
            ((Resolve-Path -LiteralPath $map['python'] -ErrorAction SilentlyContinue).Path -eq
             (Resolve-Path -LiteralPath $Python -ErrorAction SilentlyContinue).Path) `
            ("expected $Python, got " + $map['python'])
        Write-Check "resolved CLI dir is <install>\cli" `
            ((Resolve-Path -LiteralPath $map['cliDir'] -ErrorAction SilentlyContinue).Path -eq
             (Resolve-Path -LiteralPath $CliDir -ErrorAction SilentlyContinue).Path) `
            ("expected $CliDir, got " + $map['cliDir'])
        Write-Check "data source is the CLI (not a file)" `
            ($map['source'] -eq 'cli' -and $map['sampleData'] -ne 'true') `
            ("source=" + $map['source'] + " sampleData=" + $map['sampleData'])
        Write-Check "CLI version reported from cli\VERSION" `
            ($map['cliVersion'] -match '^\d+\.\d+\.\d+$') ("cliVersion=" + $map['cliVersion'])

        # The install root must not be any of the CLI / app data folders (case-insensitive:
        # %LOCALAPPDATA%\Kanjo used to be the same folder as the CLI's %LOCALAPPDATA%\kanjo).
        $installRoot = Split-Path -Parent $InstallDir
        $dataDirs = @(
            (Join-Path $env:LOCALAPPDATA 'kanjo'),
            (Join-Path $env:LOCALAPPDATA 'kanjo\data'),
            (Join-Path $env:LOCALAPPDATA 'kanjo\cache'),
            (Join-Path $env:APPDATA 'Kanjo'),
            (Join-Path $env:APPDATA 'kanjo'),
            (Join-Path $env:LOCALAPPDATA 'KanjoFamily')
        )
        $collision = $dataDirs | Where-Object {
            $_.TrimEnd('\') -ieq $installRoot.TrimEnd('\')
        }
        Write-Check "install root differs from every data folder" (-not $collision) `
            ("install root: $installRoot; collides with: " + ($collision -join ', '))
    } else {
        Write-Check "--print-source writes its report" $false $sourceFile
    }
}

# 6. Off-screen render (no window, no display needed)
if (-not (Test-Path $Exe)) {
    Write-Check "Kanjo.exe --snapshot --route overview" $false "Kanjo.exe missing"
} else {
    $sample = Join-Path $InstallDir "sample.json"
    if (-not (Test-Path $sample)) {
        Write-Check "bundled sample.json exists" $false $sample
    }
    Remove-Item -Force $SnapshotPath -ErrorAction SilentlyContinue
    $snapshotArgs = @(
        "--snapshot", $SnapshotPath,
        "--route", "overview",
        "--snapshot-appearance", "light"
    )
    if (Test-Path $sample) { $snapshotArgs += @("--data", $sample) }
    $code = Invoke-Captured $Exe $snapshotArgs
    $painted = (Test-Path $SnapshotPath) -and ((Get-Item $SnapshotPath).Length -gt 1024)
    Write-Check "Kanjo.exe --snapshot (route overview)" ($code -eq 0 -and $painted) "exit $code"
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
