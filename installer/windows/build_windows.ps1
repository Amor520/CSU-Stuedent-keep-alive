param(
    [string]$Version = "1.4.6",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$BuildDir = Join-Path $RootDir "build\windows"
$VenvDir = Join-Path $BuildDir ".venv"
$PackageDir = Join-Path $RootDir "dist\windows\CSUStudentWiFi-$Version"
$ZipPath = Join-Path $RootDir "dist\CSUStudentWiFi-$Version-windows.zip"
$BinName = "csu-auto-relogin"

Write-Host "[1/5] Preparing build directories"
Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $PackageDir -ErrorAction SilentlyContinue
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BuildDir, $PackageDir | Out-Null

Write-Host "[2/5] Preparing build virtualenv"
& $Python -m venv $VenvDir
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $RootDir "requirements.txt") pyinstaller

Write-Host "[3/5] Building standalone executable"
& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name $BinName `
    --distpath (Join-Path $BuildDir "dist") `
    --workpath (Join-Path $BuildDir "build") `
    --specpath $BuildDir `
    (Join-Path $RootDir "auto_relogin.py")

Write-Host "[4/5] Preparing portable installer package"
Copy-Item (Join-Path $BuildDir "dist\$BinName.exe") (Join-Path $PackageDir "$BinName.exe")
Copy-Item (Join-Path $RootDir "config.example.toml") (Join-Path $PackageDir "config.example.toml")
Copy-Item (Join-Path $PSScriptRoot "run_once.ps1") (Join-Path $PackageDir "run_once.ps1")
Copy-Item (Join-Path $PSScriptRoot "install_user.ps1") (Join-Path $PackageDir "install_user.ps1")
Copy-Item (Join-Path $PSScriptRoot "uninstall_user.ps1") (Join-Path $PackageDir "uninstall_user.ps1")
Copy-Item (Join-Path $PSScriptRoot "README.md") (Join-Path $PackageDir "README.md")

Write-Host "[5/5] Creating zip"
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath

Write-Host "Done"
Write-Host "Package: $PackageDir"
Write-Host "Zip: $ZipPath"
