param([string]$ComPort)

$exe = Join-Path $PSScriptRoot "dist\_run_tunnel.dist\rabbit-tun.exe"

$host.UI.RawUI.WindowTitle = "RabbitTun Client (exe)"
Write-Host "========================================"
Write-Host " RabbitTun Client (exe + gost)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/2] Starting tunnel ($ComPort <-> :9000) ..."
try {
    $null = Start-Process -FilePath $exe -ArgumentList "$ComPort --mode tcp --listen 9000" -NoNewWindow
} catch {
    Write-Host "[!] Failed to start tunnel."
    Read-Host "Press Enter to exit"
    exit 1
}
Start-Sleep -Seconds 2

Write-Host "[2/2] Starting gost SOCKS5 proxy :1081 -> tunnel :9000 ..."
Write-Host ""
Write-Host "     Apps use SOCKS5 proxy at 127.0.0.1:1081"
Write-Host ""
& (Join-Path $PSScriptRoot "gost.exe") -L socks://:1081 -F socks5://127.0.0.1:9000

Read-Host "Press Enter to exit"
