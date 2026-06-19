param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "CSUStudentWiFi"),
    [string]$UserDataDir = (Join-Path $env:APPDATA "CSUStudentWiFi"),
    [string]$TaskName = "CSUStudentWiFi Auto Re-login",
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $TaskName"
}

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "Removed app files: $InstallDir"
}

if ($RemoveConfig -and (Test-Path $UserDataDir)) {
    Remove-Item -Recurse -Force $UserDataDir
    Write-Host "Removed config and logs: $UserDataDir"
}

Write-Host "Uninstall complete."
