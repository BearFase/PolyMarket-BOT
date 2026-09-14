param([string]$TaskName = "Polymarket NFL Research Hourly")
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
# pythonw.exe never opens a console window; python.exe put a terminal window on
# screen every hour. workflow_service.py keeps the workflow's output in a log.
$Python = Join-Path $Project ".venv\Scripts\pythonw.exe"
$Workflow = Join-Path $Project "nfl_daily_update.py"
$Service = Join-Path $Project "workflow_service.py"
if (-not (Test-Path -LiteralPath $Python)) { throw "Virtual-environment Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Workflow)) { throw "Workflow not found: $Workflow" }
if (-not (Test-Path -LiteralPath $Service)) { throw "Workflow service not found: $Service" }
$Action = New-ScheduledTaskAction -Execute $Python -Argument 'workflow_service.py' -WorkingDirectory $Project
# Anchor to :07 past the hour, the cadence the task has always had. Starting at
# "now + 2 minutes" moved the hourly run to whatever minute setup was re-run.
$Now = Get-Date
$Start = $Now.Date.AddHours($Now.Hour).AddMinutes(7)
if ($Start -le $Now) { $Start = $Start.AddHours(1) }
$Trigger = New-ScheduledTaskTrigger -Once -At $Start -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Hourly, research-only canonical NFL workflow" -Force | Out-Null
Write-Host "Installed or updated scheduled task: $TaskName"
Write-Host "The task runs hourly while this Windows user is logged in; the dashboard does not need to be open."
Write-Host "Running while fully logged out requires reinstalling from an elevated PowerShell window with an S4U principal."
