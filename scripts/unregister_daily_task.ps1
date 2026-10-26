# Removes the daily research task.
param([string]$TaskName = "Bodycam Research Hub - Daily Research")
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task '$TaskName' (if it existed)."
