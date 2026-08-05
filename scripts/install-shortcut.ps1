param(
    [string]$DestinationDirectory = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$appName = -join ([char[]](0x50AC, 0x5316, 0x6587, 0x732E))
$shortcutPath = Join-Path $DestinationDirectory ($appName + '.lnk')
New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $workspace 'scripts\run-dev.ps1') + '"'
$shortcut.WorkingDirectory = $workspace
$shortcut.Description = 'Launch the local Catalyst Literature App'
$shortcut.Save()
Write-Output $shortcutPath
