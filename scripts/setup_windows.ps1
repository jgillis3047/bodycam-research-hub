# Bodycam Research Hub - one-time Windows setup
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "Project folder: $root"

function Test-Python([string[]]$cmd) {
    try {
        $exe = $cmd[0]
        $pa = @()
        if ($cmd.Count -gt 1) { $pa = $cmd[1..($cmd.Count - 1)] }
        $v = & $exe @pa -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = $v.Trim().Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 12) { return $true }
        }
    } catch { }
    return $false
}

$candidates = @("py -3.14", "py -3.13", "py -3.12", "python", "python3")
$py = $null
foreach ($c in $candidates) {
    [string[]]$parts = $c.Split(" ")
    if (Test-Python $parts) { $py = $parts; break }
}
if (-not $py) {
    Write-Host "Python 3.12 or newer was not found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run this script."
    exit 1
}
Write-Host "Using Python: $($py -join ' ')"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment (.venv)..."
    $exe = $py[0]; $pargs = @()
    if ($py.Count -gt 1) { $pargs = $py[1..($py.Count - 1)] }
    & $exe @pargs -m venv .venv
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "Installing packages (this can take a few minutes)..."
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Package installation failed." -ForegroundColor Red; exit 1 }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env (add your API keys there or on the Settings page)."
}

& $venvPy -c "from bch.db import init_db; from bch import config; init_db(); print('Database ready at', config.db_path())"

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  Start the dashboard:      double-click start_app.bat"
Write-Host "  Daily automatic research: powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 06:30"
Write-Host "  Run tests:                .venv\Scripts\python.exe -m pytest -q"
