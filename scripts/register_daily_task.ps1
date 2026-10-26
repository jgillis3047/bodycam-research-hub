# Registers a Windows Task Scheduler job that runs the research pipeline every day,
# without the dashboard needing to be open.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 06:30
param(
    [string]$Time = "06:30",
    [string]$TaskName = "Bodycam Research Hub - Daily Research"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "run_research.py"
if (-not (Test-Path $pyw)) {
    Write-Host "Virtual environment not found. Run scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
try { $at = [datetime]::ParseExact($Time, "HH:mm", $null) }
catch { Write-Host "Time must be HH:mm (24h), e.g. 06:30" -ForegroundColor Red; exit 1 }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$script`" --trigger scheduled" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $at
# StartWhenAvailable: if the laptop was asleep/off at the scheduled time, run as soon as possible afterwards.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Searches news, YouTube and agency sites for bodycam opportunities." -Force | Out-Null

Write-Host "Scheduled '$TaskName' daily at $Time." -ForegroundColor Green
Write-Host "Test it now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Results appear in the dashboard; the log is in %LOCALAPPDATA%\BodycamResearchHub\research.log"
