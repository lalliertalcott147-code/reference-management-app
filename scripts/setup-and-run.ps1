param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $workspace '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    py -3.12 -m venv (Join-Path $workspace '.venv')
}
if (-not $SkipInstall) {
    & $venvPython -m pip install -r (Join-Path $workspace 'requirements.txt')
    Push-Location (Join-Path $workspace 'frontend')
    try {
        pnpm install --config.node-linker=hoisted
    } finally {
        Pop-Location
    }
}

& (Join-Path $workspace 'scripts\run-dev.ps1')
