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

$serverExe = Join-Path $venvPath "Scripts\musicbee-tagger-mcp.exe"
$applyExe = Join-Path $venvPath "Scripts\musicbee-tagger-apply.exe"
$registerPlaylistExe = Join-Path $venvPath "Scripts\musicbee-tagger-register-playlist.exe"
$clearRegistrationsExe = Join-Path $venvPath "Scripts\musicbee-tagger-clear-registrations.exe"
$runningServers = @(
    Get-CimInstance Win32_Process -Filter "Name = 'musicbee-tagger-mcp.exe'" |
        Where-Object { $_.ExecutablePath -eq $serverExe }
)
if ($runningServers.Count -gt 0) {
    $processIds = ($runningServers.ProcessId -join ", ")
    throw "Cannot upgrade while MusicBee Tagger MCP is running (PID(s): $processIds). Close MCP clients using this server, then rerun the installer."
}

& $pythonPath -m pip install $resolvedWheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the release wheel into the dedicated virtual environment."
}

if (
    -not (Test-Path -LiteralPath $serverExe) -or
    -not (Test-Path -LiteralPath $applyExe) -or
    -not (Test-Path -LiteralPath $registerPlaylistExe) -or
    -not (Test-Path -LiteralPath $clearRegistrationsExe)
) {
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
$registerPlaylistLauncher = @"
@echo off
setlocal
if not defined MUSICBEE_TAGGER_DATA_DIR set "MUSICBEE_TAGGER_DATA_DIR=$dataPath"
"$registerPlaylistExe" %*
"@
$clearRegistrationsLauncher = @"
@echo off
setlocal
if not defined MUSICBEE_TAGGER_DATA_DIR set "MUSICBEE_TAGGER_DATA_DIR=$dataPath"
"$clearRegistrationsExe" %*
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
[System.IO.File]::WriteAllText(
    (Join-Path $binPath "musicbee-tagger-register-playlist.cmd"),
    $registerPlaylistLauncher,
    $encoding
)
[System.IO.File]::WriteAllText(
    (Join-Path $binPath "musicbee-tagger-clear-registrations.cmd"),
    $clearRegistrationsLauncher,
    $encoding
)

Write-Host "Installed MusicBee Tagger MCP."
Write-Host "Application: $installPath"
Write-Host "Private data: $dataPath"
Write-Host "Launchers: $binPath"
