param()

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$version = 'b10276'
$archiveName = 'llama-b10276-bin-win-cpu-x64.zip'
$expectedSha256 = 'B1DB7FC5B3D2728DCEAD5B792B0565DA045DEC688DF81C9272CE5AEF5F55A3E8'
$url = 'https://github.com/ggml-org/llama.cpp/releases/download/b10276/llama-b10276-bin-win-cpu-x64.zip'
$vendorRoot = [IO.Path]::GetFullPath((Join-Path $workspace 'vendor'))
$downloadRoot = [IO.Path]::GetFullPath((Join-Path $vendorRoot 'downloads'))
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $vendorRoot 'llama.cpp'))
$archive = Join-Path $downloadRoot $archiveName
$partial = $archive + '.part'
$server = Join-Path $runtimeRoot 'llama-server.exe'

if (-not $downloadRoot.StartsWith($vendorRoot, [StringComparison]::OrdinalIgnoreCase) -or
    -not $runtimeRoot.StartsWith($vendorRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved llama.cpp paths escaped the workspace vendor directory.'
}
if (Test-Path -LiteralPath $server) {
    if (Test-Path -LiteralPath $archive) {
        $installedArchiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
        if ($installedArchiveHash -ne $expectedSha256) {
            throw 'The cached llama.cpp archive does not match the pinned SHA-256.'
        }
    }
    Write-Output "llama.cpp $version is already available: $runtimeRoot"
    exit 0
}
if (Test-Path -LiteralPath $runtimeRoot) {
    throw 'vendor\llama.cpp exists but is incomplete. Remove that generated directory and run this script again.'
}

New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
if (Test-Path -LiteralPath $archive) {
    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($archiveHash -ne $expectedSha256) {
        throw 'The existing llama.cpp archive has an unexpected SHA-256. Remove it and run this script again.'
    }
} else {
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    Write-Output "Downloading official llama.cpp $version Windows CPU runtime..."
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $partial
    $downloadHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
    if ($downloadHash -ne $expectedSha256) {
        Remove-Item -LiteralPath $partial -Force
        throw "llama.cpp SHA-256 mismatch: $downloadHash"
    }
    Move-Item -LiteralPath $partial -Destination $archive
}

New-Item -ItemType Directory -Path $runtimeRoot | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $runtimeRoot
if (-not (Test-Path -LiteralPath $server)) {
    throw 'The verified llama.cpp archive did not contain llama-server.exe.'
}
Write-Output "Verified and installed llama.cpp ${version}: $runtimeRoot"
