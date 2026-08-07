param([string]$TaskName = "Polymarket NFL Research Hourly")
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$Workflow = Join-Path $Project "nfl_daily_update.py"
if (-not (Test-Path -LiteralPath $Python)) { throw "Virtual-environment Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Workflow)) { throw "Workflow not found: $Workflow" }
$Action = New-ScheduledTaskAction -Execute $Python -Argument 'nfl_daily_update.py' -WorkingDirectory $Project
$Trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Hourly, research-only canonical NFL workflow" -Force | Out-Null
Write-Host "Installed or updated scheduled task: $TaskName"
Write-Host "The task runs hourly while this Windows user is logged in; the dashboard does not need to be open."
Write-Host "Running while fully logged out requires reinstalling from an elevated PowerShell window with an S4U principal."
