$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name catalyst-preflight-probe `
  (Join-Path $workspace 'probes\package_probe.py')

& (Join-Path $workspace 'dist\catalyst-preflight-probe.exe')
