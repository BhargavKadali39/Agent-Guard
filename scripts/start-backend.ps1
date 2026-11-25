# Start the FastAPI backend on http://127.0.0.1:8000 (SQLite by default).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "backend")
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run .\scripts\setup-local.ps1 first." }
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
