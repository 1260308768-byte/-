param(
    [int]$Port = 9222
)

$ErrorActionPreference = "Stop"

$programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$localAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")

$chromeCandidates = @(
    (Join-Path -Path $programFiles -ChildPath "Google\Chrome\Application\chrome.exe"),
    (Join-Path -Path $programFilesX86 -ChildPath "Google\Chrome\Application\chrome.exe"),
    (Join-Path -Path $localAppData -ChildPath "Google\Chrome\Application\chrome.exe")
)

$chromePath = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $chromePath) {
    throw "未找到 Chrome，请先安装 Google Chrome。"
}

$projectRoot = (Resolve-Path ".").Path
$profileDir = Join-Path -Path $projectRoot -ChildPath "data\chrome_debug_profile"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

Start-Process -FilePath $chromePath -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$profileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "https://login.1688.com/"
)

Write-Host "Chrome 调试浏览器已启动：http://127.0.0.1:$Port"
Write-Host "请在打开的 Chrome 窗口里登录 1688。登录完成后不要关闭这个窗口。"
