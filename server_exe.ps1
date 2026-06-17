param([string]$ComPort)

$exe = Join-Path $PSScriptRoot "dist\_run_tunnel.dist\rabbit-tun.exe"

$host.UI.RawUI.WindowTitle = "RabbitTun Server (exe)"
Write-Host "========================================"
Write-Host " RabbitTun Server (exe)"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/2] Starting gost relay+ws server on :8443 ..."
Start-Process -FilePath (Join-Path $PSScriptRoot "gost.exe") -ArgumentList "-L relay+ws://:8443" -WindowStyle Hidden
Start-Sleep -Seconds 1

Write-Host "[2/2] Starting tunnel ($ComPort -> :8443) ..."
Write-Host ""
Write-Host "     Ready!"
Write-Host ""
& $exe $ComPort --mode tunnel --target 127.0.0.1:8443

Read-Host "Press Enter to exit"
