param([string]$ComPort)

$host.UI.RawUI.WindowTitle = "RabbitTun SOCKS5 Client"
Write-Host "========================================"
Write-Host " RabbitTun SOCKS5 Client (gost)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/2] Starting tunnel bridge on :9000 ($ComPort) ..."
try {
    $null = Start-Process -FilePath "uv" -ArgumentList "run python -m tunnel $ComPort --mode tcp --listen 9000" -NoNewWindow
} catch {
    Write-Host "[!] Failed to start tunnel."
    Read-Host "Press Enter to exit"
    exit 1
}
Start-Sleep -Seconds 2

Write-Host "[2/2] Starting gost SOCKS5 proxy :1080 -> tunnel :9000 ..."
Write-Host ""
Write-Host "     Apps use SOCKS5 proxy at 127.0.0.1:1080"
Write-Host ""
.\gost.exe -L socks://:1080 -F socks5://127.0.0.1:9000

Read-Host "Press Enter to exit"
