# Build RabbitTun standalone executable
# Run this on a machine WITH a C compiler (MSVC/MinGW).

$ErrorActionPreference = "Stop"

$env:PYTHONPATH = "$PSScriptRoot\.venv\Lib\site-packages"

# temp runner so relative imports work inside the package
$runner = @"
from tunnel.__main__ import main
main()
"@
$runner | Out-File -Encoding utf8 $PSScriptRoot\_run_tunnel.py

try {
    uvx --from nuitka nuitka.cmd `
        --standalone `
        --include-package=tunnel `
        --include-module=serial `
        --output-dir="$PSScriptRoot\dist" `
        --output-filename=rabbit-tun.exe `
        --assume-yes-for-downloads `
        "$PSScriptRoot\_run_tunnel.py"
} finally {
    Remove-Item "$PSScriptRoot\_run_tunnel.py" -ErrorAction SilentlyContinue
}

Write-Host "Done! dist\rabbit-tun.exe is ready to copy."
