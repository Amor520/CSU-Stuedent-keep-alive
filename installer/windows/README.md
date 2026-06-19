# CSUStudentWiFi Windows MVP

This is the first Windows packaging path for CSU Wi-Fi Auto Re-login.

## What it installs

- App binary: `%LOCALAPPDATA%\CSUStudentWiFi\csu-auto-relogin.exe`
- User config: `%APPDATA%\CSUStudentWiFi\config.toml`
- Logs/state next to the config by default
- A current-user Scheduled Task named `CSUStudentWiFi Auto Re-login`

The task runs once at user logon and then every 5 hours. Each run calls:

```powershell
csu-auto-relogin.exe --config "%APPDATA%\CSUStudentWiFi\config.toml" --once
```

## Build on Windows

Run PowerShell from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\windows\build_windows.ps1
```

The script creates:

```text
dist\windows\CSUStudentWiFi-1.4.6\
dist\CSUStudentWiFi-1.4.6-windows.zip
```

## Install on Windows

Unzip the package, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_user.ps1
```

Edit:

```text
%APPDATA%\CSUStudentWiFi\config.toml
```

Then test once:

```powershell
& "$env:LOCALAPPDATA\CSUStudentWiFi\csu-auto-relogin.exe" --config "$env:APPDATA\CSUStudentWiFi\config.toml" --once --force-relogin --verbose
```

## Uninstall

Keep config and logs:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\CSUStudentWiFi\uninstall_user.ps1"
```

Remove config and logs too:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\CSUStudentWiFi\uninstall_user.ps1" -RemoveConfig
```
