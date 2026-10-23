param(
    [Parameter(Mandatory = $true)]
    [string]$WheelPath,
    [string]$InstallRoot = "K:\tools\mcp-servers\musicbee-tags",
    [string]$BinRoot = "K:\bin"
)

$ErrorActionPreference = "Stop"

$resolvedWheel = (Resolve-Path -LiteralPath $WheelPath).Path
$installPath = [System.IO.Path]::GetFullPath($InstallRoot)
$binPath = [System.IO.Path]::GetFullPath($BinRoot)
$venvPath = Join-Path $installPath ".venv"
$dataPath = Join-Path $installPath "data"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $installPath, $dataPath, $binPath | Out-Null

if (-not (Test-Path -LiteralPath $pythonPath)) {
    & py -3 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the release virtual environment. Install Python 3.10 or newer and the Windows Python launcher."
    }
}

& $pythonPath -m pip install $resolvedWheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the release wheel into the dedicated virtual environment."
}

$serverExe = Join-Path $venvPath "Scripts\musicbee-tagger-mcp.exe"
$applyExe = Join-Path $venvPath "Scripts\musicbee-tagger-apply.exe"
if (-not (Test-Path -LiteralPath $serverExe) -or -not (Test-Path -LiteralPath $applyExe)) {
    throw "The installed wheel is missing one or more expected command entry points."
}

$encoding = New-Object System.Text.UTF8Encoding($false)
$serverLauncher = @"
@echo off
setlocal
if not defined MUSICBEE_TAGGER_DATA_DIR set "MUSICBEE_TAGGER_DATA_DIR=$dataPath"
"$serverExe" %*
"@
$applyLauncher = @"
@echo off
setlocal
if not defined MUSICBEE_TAGGER_DATA_DIR set "MUSICBEE_TAGGER_DATA_DIR=$dataPath"
"$applyExe" %*
"@

[System.IO.File]::WriteAllText(
    (Join-Path $binPath "musicbee-tagger-mcp.cmd"),
    $serverLauncher,
    $encoding
)
[System.IO.File]::WriteAllText(
    (Join-Path $binPath "musicbee-tagger-apply.cmd"),
    $applyLauncher,
    $encoding
)

Write-Host "Installed MusicBee Tagger MCP."
Write-Host "Application: $installPath"
Write-Host "Private data: $dataPath"
Write-Host "Launchers: $binPath"
