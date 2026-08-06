param(
    [string]$DestinationDirectory = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$appName = -join ([char[]](0x6587, 0x732E, 0x7BA1, 0x7406, 0x5668))
$shortcutPath = Join-Path $DestinationDirectory ($appName + '.lnk')
New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $workspace 'scripts\run-dev.ps1') + '"'
$shortcut.WorkingDirectory = $workspace
$shortcut.Description = 'Launch the local Reference Manager App'
$shortcut.Save()
Write-Output $shortcutPath
