param(
    [string]$PackageRoot = ''
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'The .venv Python environment is missing.' }

$node = $env:CATALYST_NODE_EXE
if (-not $node) {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand) { $node = $nodeCommand.Source }
}
if (-not $node) {
    $node = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
}
if (-not (Test-Path $node)) { throw 'Node.js not found; set CATALYST_NODE_EXE.' }

function Invoke-Checked([string]$Name, [scriptblock]$Command) {
    Write-Output "[VERIFY] $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE." }
}

Push-Location $workspace
try {
    Invoke-Checked 'Repository hygiene' { & $python scripts/repository_hygiene.py }
    Invoke-Checked 'Backend Ruff' { & $python -m ruff check backend tests scripts }
    Invoke-Checked 'Backend Mypy' { & $python -m mypy backend/catalyst_literature }
    $preflightExecutable = Join-Path $workspace 'dist\catalyst-preflight-probe.exe'
    if (-not (Test-Path $preflightExecutable)) {
        Invoke-Checked 'M0 packaged probe build' { & (Join-Path $workspace 'scripts\build-m0-probe.ps1') }
    }
    $pytestBaseTemp = Join-Path $workspace 'build\test-artifacts\pytest-verify'
    New-Item -ItemType Directory -Path (Split-Path -Parent $pytestBaseTemp) -Force | Out-Null
    Invoke-Checked 'All Python tests' {
        & $python -m pytest tests backend/tests -q --ignore=tests/artifacts "--basetemp=$pytestBaseTemp"
    }
    Invoke-Checked 'Frontend ESLint' { & $node frontend/node_modules/eslint/bin/eslint.js frontend/src }
    Invoke-Checked 'Frontend typecheck' { & $node frontend/node_modules/typescript/bin/tsc -b frontend --pretty false }
    Invoke-Checked 'Frontend unit tests' { & $node frontend/node_modules/vitest/vitest.mjs run --root frontend }
    Invoke-Checked 'Frontend production build' { & $node frontend/node_modules/vite/bin/vite.js build frontend }
    Invoke-Checked 'Browser E2E' { & $node tests/e2e/run.mjs }
    if ($PackageRoot) {
        & (Join-Path $workspace 'scripts\smoke-package.ps1') -PackageRoot $PackageRoot
    }
    Write-Output '[VERIFY] All checks passed.'
} finally {
    Pop-Location
}
