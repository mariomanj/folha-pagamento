# Gera dist\FolhaPagamento.exe (arquivo único, não precisa de Python nem internet no outro computador).
# Uso:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv-build)) {
    python -m venv .venv-build
    .\.venv-build\Scripts\python.exe -m pip install --quiet pyinstaller lxml cryptography
}

.\.venv-build\Scripts\python.exe -m unittest
if ($LASTEXITCODE -ne 0) { throw "Testes falharam; executável não gerado." }

.\.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed `
    --add-data "folha\esocial\recursos;folha\esocial\recursos" `
    --name FolhaPagamento app.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável." }

Write-Host "`nPronto: $PSScriptRoot\dist\FolhaPagamento.exe"
