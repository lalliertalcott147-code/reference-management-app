param(
    [Parameter(Mandatory=$true)][string]$PackageRoot
)

$ErrorActionPreference = 'Stop'
$package = [IO.Path]::GetFullPath($PackageRoot)
if (-not (Test-Path (Join-Path $package 'install.ps1'))) { throw 'Invalid package directory.' }
$projectLicense = Join-Path $package 'LICENSE'
if (-not (Test-Path -LiteralPath $projectLicense)) { throw 'The package is missing its project license.' }
if (-not (Select-String -LiteralPath $projectLicense -SimpleMatch 'Version 2.0, January 2004' -Quiet)) {
    throw 'The package does not contain the Apache License 2.0 text.'
}
$token = [Guid]::NewGuid().ToString('N')
$smokeRoot = Join-Path ([IO.Path]::GetTempPath()) ('catalyst-smoke-' + $token)
$install = Join-Path $smokeRoot 'program'
$shortcuts = Join-Path $smokeRoot 'shortcuts'
$data = Join-Path $smokeRoot 'data'
$process = $null
New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

try {
    & (Join-Path $package 'install.ps1') -InstallDirectory $install -ShortcutDirectory $shortcuts -SkipStartMenu -SkipRegistry
    $executable = Join-Path $install 'CatalystLiterature.exe'
    if (-not (Test-Path $executable)) { throw 'The installed executable is missing.' }
    if (-not (Test-Path (Join-Path $install 'LICENSE'))) { throw 'The installed project license is missing.' }
    if (-not (Test-Path (Join-Path $install 'THIRD_PARTY_NOTICES.md'))) { throw 'The installed third-party notice is missing.' }
    if (-not (Test-Path (Join-Path $install 'licenses'))) { throw 'The installed dependency licenses are missing.' }
    $shortcutName = -join ([char[]](0x6587, 0x732E, 0x7BA1, 0x7406, 0x5668))
    if (-not (Test-Path (Join-Path $shortcuts ($shortcutName + '.lnk')))) { throw 'The desktop shortcut is missing.' }

    $env:CATALYST_DATA_DIR = $data
    $env:CATALYST_NO_BROWSER = '1'
    $env:CATALYST_STARTUP_GRACE_SECONDS = '0.5'
    $env:CATALYST_IDLE_SHUTDOWN_SECONDS = '0.5'
    $env:CATALYST_MONITOR_INTERVAL_SECONDS = '0.1'
    $process = Start-Process -FilePath $executable -ArgumentList '--runtime-probe' -WorkingDirectory $install -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(120000)) {
        $process.Kill()
        throw 'Packaged native runtime probe timed out.'
    }
    if ($process.ExitCode -ne 0) { throw "Packaged native runtime probe failed with exit code $($process.ExitCode)." }
    $probeFile = Join-Path $data 'runtime\runtime-probe.json'
    $probe = Get-Content -LiteralPath $probeFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $probe.ok -or $probe.paddle_device -ne 'cpu') { throw 'Packaged native runtime probe returned an invalid result.' }
    $process.Dispose()
    $process = $null
    foreach ($attempt in 1..2) {
        $process = Start-Process -FilePath $executable -WorkingDirectory $install -WindowStyle Hidden -PassThru
        $runtimeFile = Join-Path $data 'runtime\server.json'
        $deadline = [DateTime]::UtcNow.AddSeconds(120)
        while (-not (Test-Path $runtimeFile) -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 100
        }
        if (-not (Test-Path $runtimeFile)) { throw "Launch attempt $attempt did not create runtime state." }
        $runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
        $health = Invoke-RestMethod -Uri ($runtime.origin + '/api/health') -TimeoutSec 5
        if ($health.status -ne 'ok' -or $health.database -ne 'ready') { throw 'Packaged health check failed.' }
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            throw 'Packaged idle shutdown timed out.'
        }
        if ($process.ExitCode -ne 0) { throw "Packaged exit code was $($process.ExitCode)." }
        $process.Dispose()
        $process = $null
    }

    Remove-Item Env:CATALYST_NO_BROWSER -ErrorAction SilentlyContinue
    $env:CATALYST_STARTUP_GRACE_SECONDS = '30'
    $process = Start-Process -FilePath $executable -WorkingDirectory $install -PassThru
    $runtimeFile = Join-Path $data 'runtime\server.json'
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    while (-not (Test-Path $runtimeFile) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path $runtimeFile)) { throw 'Desktop launch did not create runtime state.' }
    $runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
    if ($runtime.window_mode -ne 'desktop') { throw 'Desktop launch did not report desktop mode.' }
    $health = Invoke-RestMethod -Uri ($runtime.origin + '/api/health') -TimeoutSec 5
    if ($health.status -ne 'ok') { throw 'Desktop package health check failed.' }
    $windowDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 100
        $process.Refresh()
    } while ($process.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $windowDeadline)
    if ($process.MainWindowHandle -eq 0) { throw 'Desktop package did not create a native window.' }
    $expectedWindowTitle = -join [char[]](0x6587, 0x732E, 0x7BA1, 0x7406, 0x5668)
    if ($process.MainWindowTitle -ne $expectedWindowTitle) {
        throw "Unexpected window title: $($process.MainWindowTitle)"
    }

    $second = Start-Process -FilePath $executable -WorkingDirectory $install -PassThru
    if (-not $second.WaitForExit(10000)) {
        $second.Kill()
        throw 'Second desktop launch did not return to the existing instance.'
    }
    $second.Dispose()
    if ($process.HasExited) { throw 'Primary desktop instance exited during the second launch.' }

    if (-not $process.CloseMainWindow()) { throw 'Desktop window did not accept a close request.' }
    if (-not $process.WaitForExit(30000)) {
        $process.Kill()
        throw 'Desktop process did not stop after its window closed.'
    }
    if ($process.ExitCode -ne 0) { throw "Desktop package exit code was $($process.ExitCode)." }
    $process.Dispose()
    $process = $null
    if (-not (Test-Path (Join-Path $data 'data\core.db'))) { throw 'Core database was not persistent.' }
    & (Join-Path $install 'uninstall.ps1') -InstallDirectory $install -ShortcutDirectory $shortcuts -SkipStartMenu -SkipRegistry
    if (Test-Path $install) { throw 'Program directory remains after uninstall.' }
    if (-not (Test-Path (Join-Path $data 'data\core.db'))) { throw 'Default uninstall deleted permanent data.' }
    Write-Output 'Package smoke passed: install, shortcut, headless health, idle exit, native window, single instance, close shutdown, data preservation.'
} finally {
    if ($null -ne $process) {
        try {
            if (-not $process.HasExited) {
                $process.Kill()
                $process.WaitForExit(10000) | Out-Null
            }
            $process.Dispose()
        } catch {}
    }
    if (Test-Path -LiteralPath $smokeRoot) {
        foreach ($cleanupAttempt in 1..60) {
            try {
                Remove-Item -LiteralPath $smokeRoot -Recurse -Force
                break
            } catch {
                if ($cleanupAttempt -eq 60) { throw }
                Start-Sleep -Milliseconds 500
            }
        }
    }
}
