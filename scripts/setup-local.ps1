# AgentGuard - one-time local setup on Windows (PowerShell).
# Usage (from the repository root):  .\scripts\setup-local.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}

Push-Location (Join-Path $root "backend")
try {
    if (-not (Test-Path ".venv")) {
        Invoke-Checked "Creating Python virtual environment" { python -m venv .venv }
    }
    $py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    Invoke-Checked "Upgrading pip" { & $py -m pip install --upgrade pip }
    Invoke-Checked "Installing backend (with dev tools)" { & $py -m pip install -e ".[dev]" }
    if (-not (Test-Path ".env")) {
        $secret = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
        (Get-Content ".env.example") -replace '^JWT_SECRET=.*$', "JWT_SECRET=$secret" | Set-Content ".env" -Encoding ascii
        Write-Host "Created backend\.env with a random JWT_SECRET" -ForegroundColor Green
    }
}
finally { Pop-Location }

Push-Location (Join-Path $root "frontend")
try {
    Invoke-Checked "Installing frontend dependencies" { npm install }
}
finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete. Next:" -ForegroundColor Green
Write-Host "  Terminal 1:  .\scripts\start-backend.ps1"
Write-Host "  Terminal 2:  .\scripts\start-frontend.ps1"
Write-Host "  Then open http://localhost:3000"
