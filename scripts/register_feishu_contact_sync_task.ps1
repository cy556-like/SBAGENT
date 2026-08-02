param(
    [string]$ProjectPath = "C:\beifen\SBAGENT",
    [string]$TaskName = "SBAGENT-Feishu-Contact-Sync",
    [string]$DailyAt = "02:30"
)

$ErrorActionPreference = "Stop"
$resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$python = (Get-Command python -ErrorAction Stop).Source
$logDirectory = Join-Path $resolvedProject "data\logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logPath = Join-Path $logDirectory "feishu_contact_sync.log"

$command = "cd /d `"$resolvedProject`" && `"$python`" -m app.feishu_contacts_cli sync --full >> `"$logPath`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/d /c $command"
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily full synchronization of Feishu contacts for SBAGENT" `
    -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Daily at: $DailyAt"
Write-Host "Log: $logPath"
