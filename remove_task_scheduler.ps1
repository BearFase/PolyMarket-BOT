param([string]$TaskName = "Polymarket NFL Research Hourly")
$ErrorActionPreference = "Stop"
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Existing) { Write-Host "Scheduled task is not installed: $TaskName"; exit 0 }
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
