param([switch]$WhatIf, [switch]$DryRun)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$pythonVersion = "3.11"
$versionFile = Join-Path $root ".python-version"
if (Test-Path -LiteralPath $versionFile) {
    $resolvedVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    if ($resolvedVersion) { $pythonVersion = $resolvedVersion }
}

if ($WhatIf -or $DryRun) {
    Write-Host "Dry run: resolved Python version $pythonVersion"
    Write-Host "Would launch go.py from $root"
    return
}

$activate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) { . $activate }
python (Join-Path $root "go.py") @args