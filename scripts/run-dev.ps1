$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $workspace 'backend'
$env:CATALYST_DATA_DIR = Join-Path $workspace '.dev-data'

& $python -m catalyst_literature
