param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$PipIndexUrl = "https://mirrors.aliyun.com/pypi/simple/"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "[build] Installing worker build dependencies..."
& $Python -m pip install -r requirements.txt -i $PipIndexUrl
& $Python -m pip install -r requirements-worker-build.txt -i $PipIndexUrl

Write-Host "[build] Cleaning old build artifacts..."
if (Test-Path "build\AICommerceWorker") {
    Remove-Item "build\AICommerceWorker" -Recurse -Force
}
if (Test-Path "dist\AICommerceWorker") {
    Remove-Item "dist\AICommerceWorker" -Recurse -Force
}
if (Test-Path "AICommerceWorker.spec") {
    Remove-Item "AICommerceWorker.spec" -Force
}

Write-Host "[build] Building AICommerceWorker.exe..."
& $Python -m PyInstaller `
    --noconfirm `
    --onedir `
    --console `
    --name AICommerceWorker `
    --collect-all playwright `
    --hidden-import greenlet `
    scripts\local_worker.py

Write-Host "[build] Copying worker config template..."
Copy-Item "deploy\worker-client.env.example" "dist\AICommerceWorker\.env.example" -Force

@"
@echo off
chcp 65001 >nul
AICommerceWorker.exe
pause
"@ | Set-Content "dist\AICommerceWorker\start_worker.bat" -Encoding UTF8

Write-Host "[build] Done: dist\AICommerceWorker"
Write-Host "[build] Before sending it to users, copy .env.example to .env and fill WORKER_CLIENT_ID from the website top bar."
