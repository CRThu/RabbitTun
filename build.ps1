# Build rabbit-tun.exe
# Requires: uv sync && uv pip install nuitka

$ErrorActionPreference = "Stop"

uv run python -m nuitka `
    --standalone `
    --include-package=tunnel `
    --include-module=serial `
    --output-dir=dist `
    --output-filename=rabbit-tun.exe `
    --assume-yes-for-downloads `
    run.py

Write-Host "`nDone! Copy dist\run.dist\ folder to target machine."
