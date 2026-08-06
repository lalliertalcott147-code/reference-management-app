param(
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\CatalystLiterature'),
    [string]$ShortcutDirectory = [Environment]::GetFolderPath('Desktop'),
    [switch]$DeleteUserData,
    [switch]$ConfirmDeleteUserData,
    [switch]$SkipStartMenu,
    [switch]$SkipRegistry
)

$ErrorActionPreference = 'Stop'
if ($DeleteUserData -and -not $ConfirmDeleteUserData) {
    throw 'Permanent data deletion requires both -DeleteUserData and -ConfirmDeleteUserData.'
}
if (Get-Process -Name 'CatalystLiterature' -ErrorAction SilentlyContinue) {
    throw 'Close Reference Manager before uninstalling.'
}

$target = [IO.Path]::GetFullPath($InstallDirectory)
$root = [IO.Path]::GetPathRoot($target)
if ($target -eq $root -or $target.Length -lt ($root.Length + 8)) {
    throw 'Refusing to delete an unsafe installation directory.'
}
$shortcutName = -join ([char[]](0x6587, 0x732E, 0x7BA1, 0x7406, 0x5668))
$legacyShortcutName = -join ([char[]](0x50AC, 0x5316, 0x6587, 0x732E))
$desktopShortcut = Join-Path $ShortcutDirectory ($shortcutName + '.lnk')
Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $ShortcutDirectory ($legacyShortcutName + '.lnk')) -Force -ErrorAction SilentlyContinue
if (-not $SkipStartMenu) {
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $startShortcut = Join-Path $startMenu ($shortcutName + '.lnk')
    Remove-Item -LiteralPath $startShortcut -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $startMenu ($legacyShortcutName + '.lnk')) -Force -ErrorAction SilentlyContinue
}

if (-not $SkipRegistry) {
    Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CatalystLiterature' -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

$dataDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CatalystLiterature'))
if ($DeleteUserData -and (Test-Path -LiteralPath $dataDirectory)) {
    $localRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
    if (-not $dataDirectory.StartsWith($localRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The user data directory is outside LOCALAPPDATA; deletion refused.'
    }
    Remove-Item -LiteralPath $dataDirectory -Recurse -Force
    Write-Output 'The local library, PDFs, models, and settings were deleted after confirmation.'
} else {
    Write-Output 'The program was removed; library data, PDFs, models, and settings were preserved.'
}
