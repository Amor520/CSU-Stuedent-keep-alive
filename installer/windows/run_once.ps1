$ErrorActionPreference = "Stop"

$AppDir = $PSScriptRoot
$UserDataDir = Join-Path $env:APPDATA "CSUStudentWiFi"
$Runner = Join-Path $AppDir "csu-auto-relogin.exe"
$ConfigPath = Join-Path $UserDataDir "config.toml"
$TaskLog = Join-Path $UserDataDir "task_runner.log"

New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $TaskLog -Encoding UTF8 -Value ""
Add-Content -Path $TaskLog -Encoding UTF8 -Value "[$timestamp] starting scheduled check"

if (-not (Test-Path $Runner)) {
    Add-Content -Path $TaskLog -Encoding UTF8 -Value "Runner not found: $Runner"
    exit 1
}

if (-not (Test-Path $ConfigPath)) {
    Add-Content -Path $TaskLog -Encoding UTF8 -Value "Config not found: $ConfigPath"
    exit 1
}

& $Runner --config $ConfigPath --once *>> $TaskLog
exit $LASTEXITCODE
