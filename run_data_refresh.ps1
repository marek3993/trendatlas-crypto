[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$officialEntrypoint = Join-Path $repoRoot "scripts\daily_refresh_app_pipeline.py"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $pythonCommand = $venvPython
} else {
    $pythonCommand = (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}

if (-not $pythonCommand) {
    throw "Python interpreter not found. Create .venv or make `python` available on PATH."
}

& $pythonCommand $officialEntrypoint @ForwardArgs
exit $LASTEXITCODE
