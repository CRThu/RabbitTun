$ErrorActionPreference = "SilentlyContinue"
$procs = @()

function Cleanup {
    foreach ($p in $procs) { $p | Stop-Process -Force -ErrorAction SilentlyContinue }
}
trap { Cleanup }

# Kill stale processes
taskkill /F /IM python.exe 2>$null
Start-Sleep -Seconds 1

Write-Host "[1] Starting relay (COM18) ..."
$procs += Start-Process -FilePath "uv" -ArgumentList "run python -m tunnel COM18 --mode relay" -NoNewWindow -PassThru
Start-Sleep -Seconds 2

Write-Host "[2] Starting proxy SOCKS5 (COM3 :1080) ..."
$procs += Start-Process -FilePath "uv" -ArgumentList "run python -m tunnel COM3 --mode proxy --listen 1080" -NoNewWindow -PassThru
Start-Sleep -Seconds 2

Write-Host "[3] Testing SOCKS5 proxy (timeout 15s) ..."
$result = curl.exe -v --proxy socks5://127.0.0.1:1080 --connect-timeout 10 --max-time 15 http://httpbin.org/ip 2>&1 | Out-String
Write-Host $result

Write-Host ""
Cleanup
Write-Host "[done]"
