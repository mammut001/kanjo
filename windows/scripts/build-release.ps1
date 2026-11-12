# Build the Windows release folder for one architecture.
#
#   pwsh windows/scripts/build-release.ps1 -Version <version> -Rid <rid>
#
# <rid> = win-x64 | win-arm64 (the version normally comes from the repo VERSION file)
#
# Output: windows/dist/<rid>/   the folder Velopack packs (Kanjo.exe + .NET runtime + python\ + cli\)
#         windows/dist/Kanjo-<rid>-<version>.zip
#         windows/dist/releases/<rid>/   Setup.exe / nupkg / RELEASES
#
# Same layout as build-release.sh (macOS local cross-builds): the Python + CLI bundle mirrors
# scripts/install-family-windows.ps1 (same official embeddable Python 3.12.8 archives, same
# SHA-256 pins) and the kanjo-cli.zip step in CI:
#   python\   official embeddable Python, `._pth` extended with `../cli` so `python.exe -m kanjo`
#             finds the CLI (the CLI is stdlib-only, so `import site` is not needed)
#   cli\      cli/kanjo (no __pycache__ / *.pyc) + cli/pricing.json + cli/pricing_overrides.json
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Rid
)

$ErrorActionPreference = "Stop"

$Version = $Version.Trim().TrimStart("v")
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "invalid version (expected X.Y.Z): $Version"
}
switch ($Rid) {
    "win-x64" { $PyArch = "amd64" }
    "win-arm64" { $PyArch = "arm64" }
    default { throw "invalid rid (expected win-x64 or win-arm64): $Rid" }
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $Here "..\..")).Path
$Dist = Join-Path $Repo "windows\dist"
$Out = Join-Path $Dist $Rid
$Icon = Join-Path $Repo "windows\src\Kanjo.App\Assets\Kanjo.ico"

# Keep the app version and the CLI version in step: both read the repo VERSION file.
$RepoVersion = (Get-Content -Raw (Join-Path $Repo "VERSION")).Trim()
if ($Version -ne $RepoVersion) {
    Write-Warning "version $Version differs from VERSION ($RepoVersion)"
}

$PyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-$PyArch.zip"
# Same pins as scripts/install-family-windows.ps1 (keep the two files in sync).
$PySha256 = if ($PyArch -eq "arm64") {
    "D34DB37675973785A2A539CD1C8DDE1B6D45665F48C615EF55274B3798BF9FD3"
} else {
    "8D3F33BE9EB810F23C102F08475AF2854E50484B8E4E06275E937BE61CE3D2FB"
}

Write-Host "==> publish $Rid (self-contained, ReadyToRun, single folder)" -ForegroundColor Cyan
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Path $Out -Force | Out-Null

# Single folder, not single-file: Avalonia's native libraries have to sit next to the exe.
# Not trimmed: Avalonia uses reflection and trimming is not supported there.
dotnet publish (Join-Path $Repo "windows\src\Kanjo.App") `
    -c Release `
    -r $Rid `
    --self-contained true `
    -p:Version=$Version `
    -p:PublishSingleFile=false `
    -p:PublishReadyToRun=true `
    -p:PublishTrimmed=false `
    -o $Out
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with $LASTEXITCODE" }

Get-ChildItem -Path $Out -Filter *.pdb | Remove-Item -Force

Write-Host "==> bundle python ($PyArch, official embeddable 3.12.8)" -ForegroundColor Cyan
$PyDir = Join-Path $Out "python"
$PyZip = Join-Path ([System.IO.Path]::GetTempPath()) ("kanjo-python-embed-" + [guid]::NewGuid().ToString("N") + ".zip")
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host "  downloading $PyUrl"
    Invoke-WebRequest -Uri $PyUrl -OutFile $PyZip -UseBasicParsing
    $Actual = (Get-FileHash -Path $PyZip -Algorithm SHA256).Hash
    if ($Actual.ToUpperInvariant() -ne $PySha256.ToUpperInvariant()) {
        throw "python embeddable SHA-256 mismatch: expected $PySha256, got $Actual"
    }
    New-Item -ItemType Directory -Path $PyDir -Force | Out-Null
    Expand-Archive -Path $PyZip -DestinationPath $PyDir -Force
}
finally {
    Remove-Item -Force $PyZip -ErrorAction SilentlyContinue
}

# `._pth` is read relative to python.exe: `../cli` puts <appdir>\cli on sys.path so
# `python.exe -m kanjo --version` works. `import site` stays commented out (not needed).
$Pth = Get-ChildItem -Path $PyDir -Filter "python*._pth" | Select-Object -First 1
if (-not $Pth) { throw "no python*._pth in $PyDir" }
$PthLines = Get-Content -Path $Pth.FullName
if ($PthLines -notcontains "../cli") {
    Add-Content -Path $Pth.FullName -Value "../cli" -Encoding ASCII
}
if ($PthLines -contains "import site") {
    Write-Warning "$($Pth.Name) enables 'import site' (not required by the CLI)"
}

Write-Host "==> bundle CLI" -ForegroundColor Cyan
$CliDir = Join-Path $Out "cli"
if (Test-Path $CliDir) { Remove-Item -Recurse -Force $CliDir }
New-Item -ItemType Directory -Path (Join-Path $CliDir "kanjo") -Force | Out-Null
Copy-Item -Recurse -Path (Join-Path $Repo "cli\kanjo\*") -Destination (Join-Path $CliDir "kanjo")
Get-ChildItem -Path (Join-Path $CliDir "kanjo") -Recurse -Include "__pycache__", "*.pyc" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $Repo "cli\pricing.json"), (Join-Path $Repo "cli\pricing_overrides.json") -Destination $CliDir
# Settings shows "Bundled CLI <version>" by reading cli/VERSION (same as the Mac bundle).
Copy-Item -Path (Join-Path $Repo "VERSION") -Destination (Join-Path $CliDir "VERSION")

Write-Host "==> verify bundle layout" -ForegroundColor Cyan
$required = @(
    (Join-Path $Out "Kanjo.exe"),
    (Join-Path $PyDir "python.exe"),
    (Join-Path $CliDir "kanjo\__init__.py"),
    (Join-Path $CliDir "pricing.json"),
    (Join-Path $CliDir "pricing_overrides.json"),
    (Join-Path $CliDir "VERSION"),
    (Join-Path $Out "sample.json")
)
foreach ($item in $required) {
    if (-not (Test-Path $item)) { throw "missing in bundle: $item" }
}
if ((Get-Content -Path $Pth.FullName) -notcontains "../cli") { throw "$($Pth.Name) does not list ../cli" }

Write-Host "==> zip folder" -ForegroundColor Cyan
$Zip = Join-Path $Dist "Kanjo-$Rid-$Version.zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
# ZipFile is much faster than Compress-Archive on a 300+ file tree and has no path-length surprises.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $Out, $Zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

Write-Host "==> vpk pack ($Rid)" -ForegroundColor Cyan
$Rel = Join-Path $Dist "releases\$Rid"
# Fresh output dir: vpk refuses to pack a version that already exists in the channel.
if (Test-Path $Rel) { Remove-Item -Recurse -Force $Rel }
$Vpk = Get-Command vpk -ErrorAction SilentlyContinue
if (-not $Vpk) { throw "vpk not found (dotnet tool install -g vpk --version 1.2.158)" }
# packId (KanjoApp) decides the install root %LOCALAPPDATA%\KanjoApp; it must differ from
# the CLI's %LOCALAPPDATA%\kanjo (see windows/src/Kanjo.Core/AppPaths.cs). --packTitle sets
# the Start Menu shortcut and Apps-list name back to "Kanjo".
vpk pack `
    --packId KanjoApp `
    --packTitle Kanjo `
    --packVersion $Version `
    --packDir $Out `
    --mainExe Kanjo.exe `
    --icon $Icon `
    --runtime $Rid `
    --channel $Rid `
    --outputDir $Rel `
    --noPortable `
    --shortcuts "StartMenuRoot"
if ($LASTEXITCODE -ne 0) { throw "vpk pack failed with $LASTEXITCODE" }

$FolderSize = "{0:N1} MB" -f ((Get-ChildItem -Recurse -Force $Out | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "release folder: $Out ($FolderSize)"
Write-Host "zip:            $Zip"
Write-Host "installer:      $Rel"
