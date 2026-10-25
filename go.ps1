$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$activate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) { . $activate }
python (Join-Path $root "go.py") @args