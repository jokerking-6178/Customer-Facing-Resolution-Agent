# SkyAssist - one-command local run (Windows PowerShell).
# Mirrors run.sh. Usage:  .\run.ps1
#
#   $env:LLM_PROVIDER = "mock"    # no LLM needed, deterministic (default here)
#   $env:LLM_PROVIDER = "ollama"  # local llama3.1:8b via Ollama
#   $env:LLM_PROVIDER = "groq"    # hosted; also set $env:GROQ_API_KEY

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "mock" }

# --- Python environment -------------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r backend\requirements.txt

# --- Frontend build -----------------------------------------------------------
if (-not (Test-Path "frontend\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Building frontend..." -ForegroundColor Cyan
        Push-Location frontend
        if (-not (Test-Path "node_modules")) { npm install }
        npm run build
        Pop-Location
    }
    else {
        Write-Warning "npm not found - serving the API only. Install Node 20+ to build the UI."
    }
}

# --- Run ----------------------------------------------------------------------
Write-Host ""
Write-Host "SkyAssist running on http://localhost:8000  (engine: $env:LLM_PROVIDER)" -ForegroundColor Green
Write-Host ""
& $py -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
