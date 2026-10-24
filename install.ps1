param(
    [string]$InstallRoot = "K:\tools\mcp-servers\musicbee-tags",
    [string]$BinRoot = "K:\bin"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = $PSScriptRoot
$releaseInstaller = Join-Path $repositoryRoot "release\windows\install.ps1"
if (-not (Test-Path -LiteralPath $releaseInstaller)) {
    throw "Run this script from a MusicBee Tagger source checkout."
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
