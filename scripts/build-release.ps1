param(
    [string]$Version = '0.1.0',
    [switch]$SkipFrontendBuild,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$releaseRoot = Join-Path $workspace ('build\release\CatalystLiterature-' + $Version)
$releaseParent = Split-Path -Parent $releaseRoot
if (-not (Test-Path $python)) { throw 'The .venv Python environment is missing.' }

if (-not $SkipFrontendBuild) {
    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) { $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue }
    if (-not $pnpmCommand) { throw 'pnpm is required to build the frontend.' }
    Push-Location (Join-Path $workspace 'frontend')
    try {
        & $pnpmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
    } finally {
        Pop-Location
    }
}

$llamaServer = Join-Path $workspace 'vendor\llama.cpp\llama-server.exe'
if (-not (Test-Path $llamaServer)) {
    & (Join-Path $workspace 'scripts\fetch-llama-runtime.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'llama.cpp runtime setup failed.' }
}

$specification = Join-Path $workspace 'CatalystLiterature.spec'
$packageCache = Join-Path $workspace 'build\package-cache\paddlex'
New-Item -ItemType Directory -Path $packageCache -Force | Out-Null
$env:PADDLE_PDX_CACHE_HOME = $packageCache
if (-not $SkipPyInstaller) {
    & $python -m PyInstaller --noconfirm --clean $specification
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
}

$resolvedBuild = [IO.Path]::GetFullPath((Join-Path $workspace 'build\release'))
$resolvedTarget = [IO.Path]::GetFullPath($releaseRoot)
if (-not $resolvedTarget.StartsWith($resolvedBuild, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release staging directory escaped the expected build root.'
}
if (Test-Path -LiteralPath $resolvedTarget) {
    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $workspace 'dist\CatalystLiterature') -Destination (Join-Path $resolvedTarget 'app') -Recurse
Copy-Item -LiteralPath (Join-Path $workspace 'packaging\install.ps1') -Destination $resolvedTarget
Copy-Item -LiteralPath (Join-Path $workspace 'packaging\uninstall.ps1') -Destination $resolvedTarget
Copy-Item -LiteralPath (Join-Path $workspace 'README.md') -Destination $resolvedTarget
Copy-Item -LiteralPath (Join-Path $workspace 'LICENSE') -Destination $resolvedTarget
Copy-Item -LiteralPath (Join-Path $workspace 'THIRD_PARTY_NOTICES.md') -Destination $resolvedTarget
Copy-Item -LiteralPath (Join-Path $workspace 'docs\USER_GUIDE.md') -Destination $resolvedTarget
$licenseRoot = Join-Path $resolvedTarget 'licenses'
New-Item -ItemType Directory -Path $licenseRoot -Force | Out-Null
$sitePackages = Join-Path $workspace '.venv\Lib\site-packages'
Get-ChildItem -LiteralPath $sitePackages -Directory -Filter '*.dist-info' | ForEach-Object {
    $packageLicenseRoot = Join-Path $licenseRoot $_.BaseName
    Get-ChildItem -LiteralPath $_.FullName -Recurse -File | Where-Object {
        $_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE)'
    } | ForEach-Object {
        New-Item -ItemType Directory -Path $packageLicenseRoot -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $packageLicenseRoot $_.Name) -Force
    }
}
foreach ($nodePackage in @('react', 'react-dom', 'pdfjs-dist')) {
    $nodePackageRoot = Join-Path (Join-Path $workspace 'frontend\node_modules') $nodePackage
    $license = Join-Path $nodePackageRoot 'LICENSE'
    if (Test-Path $license) {
        $destination = Join-Path $licenseRoot $nodePackage
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        Copy-Item -LiteralPath $license -Destination $destination
    }
}
Copy-Item -LiteralPath (Join-Path $workspace 'packaging\licenses\llama.cpp-LICENSE') -Destination (Join-Path $licenseRoot 'llama.cpp-LICENSE')

$archive = Join-Path $releaseParent ('CatalystLiterature-' + $Version + '-windows-x64.zip')
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $resolvedTarget '*') -DestinationPath $archive -CompressionLevel Optimal
Write-Output $archive
