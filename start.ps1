# narvi dev launcher — opens the FastAPI backend (:8078) and the Vite frontend
# (:5176) each in their own window, and keeps THIS window open so any error stays
# visible. Run it from a PowerShell prompt in the narvi folder:
#
#     .\start.ps1
#
# If you get a script-blocked error, run it once as:
#     powershell -ExecutionPolicy Bypass -File .\start.ps1
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Pause-Exit($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Yellow
    Read-Host "Press Enter to close this window"
    exit 1
}

if (-not (Test-Path $python)) {
    Pause-Exit "Python venv not found at $python. Create it: python -m venv .venv ; then pip install -e ."
}

# --- Backend (uvicorn :8078) in its own window (stays open via -NoExit) ---
# --reload-dir watches BOTH backend/app AND src/narvi (the editable engine) — without
# the src/narvi dir, changes to the engine are NOT picked up until a manual restart.
Write-Host "starting backend on http://127.0.0.1:8078 ..." -ForegroundColor Cyan
$src = Join-Path $root "src"
$backendCmd = "Set-Location '$backend'; & '$python' -m uvicorn app.main:app --port 8078 " +
    "--reload --reload-dir '$backend' --reload-dir '$src'"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd

# --- Frontend (vite :5176) in its own window, if it exists ---
if (Test-Path (Join-Path $frontend "package.json")) {
    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        Write-Host "frontend deps not installed — run 'npm install' in frontend\ first." -ForegroundColor Yellow
    }
    Write-Host "starting frontend on http://localhost:5176 ..." -ForegroundColor Cyan
    $frontendCmd = "Set-Location '$frontend'; npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd
    if (-not $NoBrowser) {
        Start-Sleep -Seconds 4
        Start-Process "http://localhost:5176"
    }
} else {
    Write-Host "frontend/ not built yet — backend only. API docs: http://127.0.0.1:8078/docs" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Two windows should now be open (backend + frontend)." -ForegroundColor Green
Write-Host "  app:      http://localhost:5176" -ForegroundColor Green
Write-Host "  api docs: http://127.0.0.1:8078/docs" -ForegroundColor Green
Read-Host "This launcher can be closed with Enter (the two server windows keep running)"
