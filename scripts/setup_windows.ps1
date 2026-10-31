# One-shot setup for Clove on Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\pip install -r requirements.txt
Write-Host "Copy .env.example to .env and fill in GEMINI_API_KEY, then run .\run.ps1"
