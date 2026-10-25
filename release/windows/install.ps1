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
$installedExecutables = @($serverExe, $applyExe, $registerPlaylistExe, $clearRegistrationsExe)
$runningTools = @(
    Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -and $installedExecutables -contains $_.ExecutablePath }
)
if ($runningTools.Count -gt 0) {
    Write-Host "MusicBee Tagger processes are using files that must be upgraded:"
    $runningTools | ForEach-Object {
        Write-Host "  $($_.Name) (PID $($_.ProcessId))"
    }
    $answer = Read-Host "Ask these processes to close before continuing? [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        throw "Upgrade cancelled. Close the listed MusicBee Tagger processes and rerun the installer."
    }

    foreach ($process in $runningTools) {
        try {
            $liveProcess = Get-Process -Id $process.ProcessId -ErrorAction Stop
            if (-not $liveProcess.CloseMainWindow()) {
                Write-Host "  $($process.Name) (PID $($process.ProcessId)) has no closable window."
            }
        }
        catch {
            # The process may have exited between enumeration and the close request.
        }
    }
    Start-Sleep -Seconds 3
    $remainingTools = @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.ExecutablePath -and $installedExecutables -contains $_.ExecutablePath }
    )
    if ($remainingTools.Count -gt 0) {
        Write-Host "These processes did not close:"
        $remainingTools | ForEach-Object {
            Write-Host "  $($_.Name) (PID $($_.ProcessId))"
        }
        $forceAnswer = Read-Host "Terminate the remaining processes so installation can continue? [y/N]"
        if ($forceAnswer -notmatch '^(y|yes)$') {
            $remainingIds = ($remainingTools.ProcessId -join ", ")
            throw "Upgrade cancelled. Close the remaining process(es) manually (PID(s): $remainingIds) and rerun the installer."
        }
        foreach ($process in $remainingTools) {
            Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        $stillRunning = @(
            Get-CimInstance Win32_Process |
                Where-Object { $_.ExecutablePath -and $installedExecutables -contains $_.ExecutablePath }
        )
        if ($stillRunning.Count -gt 0) {
            $remainingIds = ($stillRunning.ProcessId -join ", ")
            throw "Could not stop remaining process(es) (PID(s): $remainingIds). Close them manually and rerun the installer."
        }
    }
}

# Interrupted pip uninstalls can leave renamed package files behind. Pip treats
# these as invalid distributions and warns on every later install, so clear only
# the known MusicBee Tagger leftovers from this environment's site-packages.
$sitePackages = Join-Path $venvPath "Lib\site-packages"
if (Test-Path -LiteralPath $sitePackages) {
    $pipLeftovers = @(Get-ChildItem -LiteralPath $sitePackages -Force | Where-Object {
        $_.Name -like "~usicbee-tagger-mcp*" -or
        $_.Name -like "~usicbee_tagger_mcp*"
    })
    foreach ($leftover in $pipLeftovers) {
        Remove-Item -LiteralPath $leftover.FullName -Recurse -Force
    }
}

& $pythonPath -m pip install $resolvedWheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the release wheel or its runtime dependencies."
}

# Resolve dependencies above, then force-refresh only the supplied wheel. This
# also deploys changed source when reinstalling a wheel with the same version.
& $pythonPath -m pip install --force-reinstall --no-deps $resolvedWheel
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
