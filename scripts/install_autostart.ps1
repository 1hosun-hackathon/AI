# Windows 로그인 시 scripts\start_ngrok.ps1을 창 없이 자동 실행하도록 작업 스케줄러에 등록한다.
# 등록:  powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
# 해제:  powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Remove
# 지금 바로 켜기/끄기:  Start-ScheduledTask -TaskName GeuljeokAI / Stop-ScheduledTask -TaskName GeuljeokAI

param([switch]$Remove)

$ErrorActionPreference = "Stop"
$name = "GeuljeokAI"
$script = Join-Path $PSScriptRoot "start_ngrok.ps1"

if ($Remove) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "자동 시작을 해제했습니다."
    return
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Ollama가 먼저 뜨도록 로그인 30초 뒤 시작. 시간 제한 없이 계속 실행, 실패하면 1분 뒤 재시도.
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "글적글적 AI 서버 + ngrok 터널" -Force | Out-Null
Write-Host "등록했습니다. 다음 로그인부터 자동으로 켜집니다. 지금 켜려면: Start-ScheduledTask -TaskName $name"
