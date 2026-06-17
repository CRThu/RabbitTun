@echo off
echo Testing RabbitTun connection...
echo.

echo [1] SOCKS5 proxy...
curl -x socks5://127.0.0.1:1080 -s --connect-timeout 5 http://ifconfig.me && (echo. & echo [OK] SOCKS5 works) || echo [FAIL] SOCKS5 unreachable
echo.

echo [2] HTTP proxy...
curl -x http://127.0.0.1:8080 -s --connect-timeout 5 http://ifconfig.me && (echo. & echo [OK] HTTP works) || echo [FAIL] HTTP unreachable
echo.

echo Done.
pause
