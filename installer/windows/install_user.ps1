param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "CSUStudentWiFi"),
    [string]$UserDataDir = (Join-Path $env:APPDATA "CSUStudentWiFi"),
    [string]$TaskName = "CSUStudentWiFi Auto Re-login"
)

$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerSource = Join-Path $SourceDir "csu-auto-relogin.exe"
$ConfigExampleSource = Join-Path $SourceDir "config.example.toml"
$RunScriptSource = Join-Path $SourceDir "run_once.ps1"
$UninstallScriptSource = Join-Path $SourceDir "uninstall_user.ps1"

if (-not (Test-Path $RunnerSource)) {
    throw "csu-auto-relogin.exe not found next to install_user.ps1. Build the Windows package first."
}
if (-not (Test-Path $ConfigExampleSource)) {
    throw "config.example.toml not found next to install_user.ps1."
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null

Copy-Item -Force $RunnerSource (Join-Path $InstallDir "csu-auto-relogin.exe")
Copy-Item -Force $ConfigExampleSource (Join-Path $InstallDir "config.example.toml")
Copy-Item -Force $RunScriptSource (Join-Path $InstallDir "run_once.ps1")
Copy-Item -Force $UninstallScriptSource (Join-Path $InstallDir "uninstall_user.ps1")

$ConfigPath = Join-Path $UserDataDir "config.toml"
if (-not (Test-Path $ConfigPath)) {
    Copy-Item $ConfigExampleSource $ConfigPath
}

$RunScript = Join-Path $InstallDir "run_once.ps1"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`""

$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn
$RepeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Hours 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($LogonTrigger, $RepeatTrigger) `
    -Settings $Settings `
    -Description "CSU campus Wi-Fi low-frequency auto re-login check." `
    -Force | Out-Null

Write-Host "Installed CSUStudentWiFi for the current user."
Write-Host "App: $InstallDir"
Write-Host "Config: $ConfigPath"
Write-Host "Scheduled task: $TaskName"
Write-Host ""
Write-Host "Edit config.toml first, then run this once to test:"
Write-Host "`"$InstallDir\csu-auto-relogin.exe`" --config `"$ConfigPath`" --once --force-relogin --verbose"
