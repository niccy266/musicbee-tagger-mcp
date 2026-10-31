[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallRoot = "K:\tools\mcp-servers\musicbee-tags",
    [string]$BinRoot = "K:\bin",
    [switch]$DryRun
)

$pythonVersion = "3.11"
$versionFile = Join-Path $PSScriptRoot ".python-version"
if (Test-Path -LiteralPath $versionFile) {
    $resolvedVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    if ($resolvedVersion) {
        $pythonVersion = $resolvedVersion
    }
}

$ErrorActionPreference = "Stop"

$repositoryRoot = $PSScriptRoot
$releaseInstaller = Join-Path $repositoryRoot "release\windows\install.ps1"
if (-not (Test-Path -LiteralPath $releaseInstaller)) {
    throw "Run this script from a MusicBee Tagger source checkout."
}

if ($DryRun -or $WhatIfPreference) {
    Write-Host "Dry run: resolved Python version $pythonVersion"
    Write-Host "Would build a wheel from $repositoryRoot"
    Write-Host "Would install to $InstallRoot and create launchers in $BinRoot"
    return
}

$wheelDirectory = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("musicbee-tagger-wheel-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $wheelDirectory | Out-Null

try {
    & py -3 -m pip wheel --no-deps --wheel-dir $wheelDirectory $repositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not build a wheel from this checkout. Install Python 3 and retry."
    }

    $wheels = @(Get-ChildItem -LiteralPath $wheelDirectory -Filter "*.whl" -File)
    if ($wheels.Count -ne 1) {
        throw "Expected one package wheel from the source checkout; found $($wheels.Count)."
    }

    & $releaseInstaller `
        -WheelPath $wheels[0].FullName `
        -InstallRoot $InstallRoot `
        -BinRoot $BinRoot
}
finally {
    Remove-Item -LiteralPath $wheelDirectory -Recurse -Force
}
