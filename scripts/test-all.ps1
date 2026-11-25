# Run the backend and frontend test suites (end-to-end tests: see CONTRIBUTING.md).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}

Push-Location (Join-Path $root "backend")
try {
    $py = ".\.venv\Scripts\python.exe"
    Invoke-Checked "Backend lint" { & $py -m ruff check app tests }
    Invoke-Checked "Backend tests" { & $py -m pytest }
}
finally { Pop-Location }

Push-Location (Join-Path $root "frontend")
try {
    Invoke-Checked "Frontend lint" { npm run lint }
    Invoke-Checked "Frontend unit tests" { npm test }
    Invoke-Checked "Frontend production build" { npm run build }
}
finally { Pop-Location }

Write-Host "All checks passed." -ForegroundColor Green
