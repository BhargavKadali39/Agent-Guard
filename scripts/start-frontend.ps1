# Start the Next.js dashboard on http://localhost:3000 (proxies /api to the backend).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { throw "Run .\scripts\setup-local.ps1 first." }
npm run dev
