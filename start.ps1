# narvi dev launcher — starts the FastAPI backend (and the Vite frontend once it
# exists) in separate windows. Run from the repo root: .\start.ps1
param([switch]$NoBrowser)

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

# --- Backend (uvicorn :8078) ---
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; & '$python' -m uvicorn app.main:app --port 8078 --reload"
)

# --- Frontend (vite :5176), once it exists ---
if (Test-Path (Join-Path $frontend "package.json")) {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "Set-Location '$frontend'; npm run dev"
    )
    if (-not $NoBrowser) {
        Start-Sleep -Seconds 3
        Start-Process "http://localhost:5176"
    }
} else {
    Write-Host "frontend/ not built yet — backend only. API at http://127.0.0.1:8078/docs"
}
