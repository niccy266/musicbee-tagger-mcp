<#
.SYNOPSIS
    Convenience PowerShell launcher for the AI-supervised MusicBee tagging agent.
.DESCRIPTION
    Runs go_supervise.py with optional playlist path or job ID.
.EXAMPLE
    .\go_supervise.ps1
    .\go_supervise.ps1 "path\to\playlist.m3u"
    .\go_supervise.ps1 ec6b4168-5b54-4a60-a90d-0f35c5430460 --max-batches 1
#>

[CmdletBinding()]
param(
    [Parameter(Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$PythonExe = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $PythonExe = ".\.venv\Scripts\python.exe"
}

& $PythonExe "go_supervise.py" @Args
exit $LASTEXITCODE
