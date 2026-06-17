param([string]$ComPort)

$host.UI.RawUI.WindowTitle = "RabbitTun Client"
Write-Host "========================================"
Write-Host " RabbitTun Client (tunnel + gost)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/2] Starting tunnel ($ComPort -> :9000) ..."
Start-Process -FilePath "uv" -ArgumentList "run python -m tunnel $ComPort --mode tunnel --listen 9000" -WindowStyle Hidden
Start-Sleep -Seconds 2

Write-Host "[2/2] Starting gost SOCKS5 :1080 + HTTP :8080 -> relay+ws://:9000 ..."
Write-Host ""
Write-Host "     SOCKS5 proxy: 127.0.0.1:1080"
Write-Host "     HTTP  proxy: 127.0.0.1:8080"
Write-Host ""
.\gost.exe -L socks://:1080 -L http://:8080 -F relay+ws://127.0.0.1:9000

Read-Host "Press Enter to exit"
