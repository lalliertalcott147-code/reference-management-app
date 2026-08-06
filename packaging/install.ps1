param(
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\CatalystLiterature'),
    [string]$ShortcutDirectory = [Environment]::GetFolderPath('Desktop'),
    [switch]$SkipStartMenu,
    [switch]$SkipRegistry
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'app'
if (-not (Test-Path (Join-Path $source 'CatalystLiterature.exe'))) {
    throw 'The package is incomplete: CatalystLiterature.exe is missing.'
}

$target = [IO.Path]::GetFullPath($InstallDirectory)
$root = [IO.Path]::GetPathRoot($target)
if ($target -eq $root -or $target.Length -lt ($root.Length + 8)) {
    throw 'Refusing an unsafe installation directory.'
}
if (Get-Process -Name 'CatalystLiterature' -ErrorAction SilentlyContinue) {
    throw 'Close Reference Manager before installing or upgrading.'
}

if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $target -Force
foreach ($document in @('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'USER_GUIDE.md')) {
    $documentPath = Join-Path $PSScriptRoot $document
    if (Test-Path -LiteralPath $documentPath) {
        Copy-Item -LiteralPath $documentPath -Destination $target -Force
    }
}
$licenseDirectory = Join-Path $PSScriptRoot 'licenses'
if (Test-Path -LiteralPath $licenseDirectory) {
    Copy-Item -LiteralPath $licenseDirectory -Destination (Join-Path $target 'licenses') -Recurse -Force
}

New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
$shortcutName = -join ([char[]](0x6587, 0x732E, 0x7BA1, 0x7406, 0x5668))
$legacyShortcutName = -join ([char[]](0x50AC, 0x5316, 0x6587, 0x732E))
$legacyShortcutPath = Join-Path $ShortcutDirectory ($legacyShortcutName + '.lnk')
Remove-Item -LiteralPath $legacyShortcutPath -Force -ErrorAction SilentlyContinue
$shortcutPath = Join-Path $ShortcutDirectory ($shortcutName + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $target 'CatalystLiterature.exe'
$shortcut.WorkingDirectory = $target
$shortcut.Description = 'Launch the local Reference Manager App'
$shortcut.Save()

if (-not $SkipStartMenu) {
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    Remove-Item -LiteralPath (Join-Path $startMenu ($legacyShortcutName + '.lnk')) -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    $startShortcut = Join-Path $startMenu ($shortcutName + '.lnk')
    $startLink = $shell.CreateShortcut($startShortcut)
    $startLink.TargetPath = Join-Path $target 'CatalystLiterature.exe'
    $startLink.WorkingDirectory = $target
    $startLink.Description = 'Launch the local Reference Manager App'
    $startLink.Save()
}

if (-not $SkipRegistry) {
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CatalystLiterature'
    New-Item -Path $uninstallKey -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name DisplayName -Value $shortcutName -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value '0.1.0' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $uninstallKey -Name Publisher -Value 'Local User' -PropertyType String -Force | Out-Null
    $uninstallCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $target 'uninstall.ps1') + '"'
    New-ItemProperty -Path $uninstallKey -Name UninstallString -Value $uninstallCommand -PropertyType String -Force | Out-Null
}

Write-Output "Installation completed: $target"
Write-Output 'Library data remains in %LOCALAPPDATA%\CatalystLiterature during upgrades.'
