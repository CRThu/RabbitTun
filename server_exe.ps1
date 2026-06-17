param([string]$ComPort)

$exe = Join-Path $PSScriptRoot "dist\_run_tunnel.dist\rabbit-tun.exe"

$host.UI.RawUI.WindowTitle = "RabbitTun Server (exe)"
Write-Host "========================================"
Write-Host " RabbitTun Server (exe + gost)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/3] Starting gost SOCKS5 proxy on :1080 ..."
$null = Start-Process -FilePath (Join-Path $PSScriptRoot "gost.exe") -ArgumentList "-L socks://:1080" -NoNewWindow -RedirectStandardOutput "NUL"
Start-Sleep -Seconds 1

Write-Host "[2/3] Starting tunnel ($ComPort <-> :9001) ..."
$null = Start-Process -FilePath $exe -ArgumentList "$ComPort --mode tcp --listen 9001" -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "[3/3] Bridging :9001 -> :1080 ..."
Write-Host ""
Write-Host "     Ready!"
Write-Host ""
uv run python -m tunnel.bridge 9001 1080

Read-Host "Press Enter to exit"
