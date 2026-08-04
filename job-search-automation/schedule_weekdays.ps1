param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$At = "09:00"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $projectRoot "run_daily.bat"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Run setup_windows.bat before creating the schedule."
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/d /c `"`"$runner`"`"" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName "David's Job Finder" `
    -Description "Deep Swiss ERP, consulting, finance, support and business-informatics job search" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Scheduled David's Job Finder for weekdays at $At."
Write-Host "Results will appear in $projectRoot\reports\latest.html"
