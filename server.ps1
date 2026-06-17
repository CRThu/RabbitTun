param([string]$ComPort)

$host.UI.RawUI.WindowTitle = "RabbitTun SOCKS5 Relay Server"
Write-Host "========================================"
Write-Host " RabbitTun SOCKS5 Relay Server (gost)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/3] Starting gost SOCKS5 proxy on :1080 ..."
$null = Start-Process -FilePath ".\gost.exe" -ArgumentList "-L socks://:1080" -NoNewWindow -RedirectStandardOutput "NUL"
Start-Sleep -Seconds 1

Write-Host "[2/3] Starting tunnel bridge on :9001 ($ComPort) ..."
$null = Start-Process -FilePath "uv" -ArgumentList "run python -m tunnel $ComPort --mode tcp --listen 9001" -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "[3/3] Bridging tunnel :9001 -> gost :1080 ..."
Write-Host ""
Write-Host "     Ready! Client can now connect through serial tunnel."
Write-Host ""
uv run python -m tunnel.bridge 9001 1080

Read-Host "Press Enter to exit"
