# narvi dev launcher — opens the FastAPI backend (:8078) and the Vite frontend
# (:5176) each in their own window. Easiest: double-click start.cmd.
# Or from a PowerShell prompt in the narvi folder:  .\start.ps1
param([switch]$NoBrowser)

function Pause-Exit($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Yellow
    Read-Host "Press Enter to close this window"
    exit 1
}

function Wait-Port($port, $timeoutSec = 40) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $c = New-Object Net.Sockets.TcpClient
            $c.Connect("127.0.0.1", $port); $c.Close(); return $true
        } catch { Start-Sleep -Milliseconds 400 }
    }
    return $false
}

try {
    $root = $PSScriptRoot
    if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $python = Join-Path $root ".venv\Scripts\python.exe"
    $backend = Join-Path $root "backend"
    $frontend = Join-Path $root "frontend"
    $src = Join-Path $root "src"

    if (-not (Test-Path $python)) {
        Pause-Exit "Python venv not found at $python.`nCreate it: python -m venv .venv ; then pip install -e ."
    }

    # --- Backend (uvicorn :8078) in its own window (stays open via -NoExit) ---
    # --reload-dir watches backend/app AND src/narvi (the editable engine), else
    # engine edits aren't picked up until a manual restart.
    Write-Host "starting backend on http://127.0.0.1:8078 ..." -ForegroundColor Cyan
    $backendCmd = "`$host.ui.RawUI.WindowTitle='narvi backend (:8078)'; Set-Location '$backend'; " +
        "& '$python' -m uvicorn app.main:app --port 8078 --reload --reload-dir '$backend' --reload-dir '$src'"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd

    # --- Frontend (vite :5176) in its own window ---
    if (Test-Path (Join-Path $frontend "package.json")) {
        if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
            Write-Host "frontend deps not installed - run 'npm install' in frontend\ first." -ForegroundColor Yellow
        }
        Write-Host "starting frontend on http://localhost:5176 ..." -ForegroundColor Cyan
        $frontendCmd = "`$host.ui.RawUI.WindowTitle='narvi frontend (:5176)'; Set-Location '$frontend'; npm run dev"
        Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd
        if (-not $NoBrowser) {
            Write-Host "waiting for the frontend on :5176 (first compile + basemap take a few seconds) ..." -ForegroundColor Cyan
            [void](Wait-Port 5176 40)
            Start-Process "http://localhost:5176"
        }
    } else {
        Write-Host "frontend/ not built yet - backend only. API docs: http://127.0.0.1:8078/docs" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Two windows should now be open (backend + frontend)." -ForegroundColor Green
    Write-Host "  app:      http://localhost:5176" -ForegroundColor Green
    Write-Host "  api docs: http://127.0.0.1:8078/docs" -ForegroundColor Green
    Read-Host "This launcher can be closed with Enter (the two server windows keep running)"
}
catch {
    Pause-Exit "LAUNCHER ERROR: $($_.Exception.Message)`n$($_.ScriptStackTrace)"
}
