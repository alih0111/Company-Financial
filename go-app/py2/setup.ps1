$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

& $Python -m pip install --upgrade pip
& $Python -m pip install -e .

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Configure DATABASE_URL and run setup.ps1 again."
    exit 1
}

& $Python -m codal_ingestor.cli init-schema

Write-Host "Codal ingestor installation completed."
Write-Host "Python executable: $Python"
