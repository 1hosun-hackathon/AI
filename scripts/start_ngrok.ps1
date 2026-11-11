# AI 서버와 ngrok 터널(고정 도메인)을 창 없이 켜고, 둘 중 하나가 꺼지면 다시 켠다 (Windows PowerShell).
# 준비: Ollama 실행, ngrok 설치·authtoken 등록, .env에 API_KEY와 NGROK_DOMAIN 설정
# 직접 실행:   powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1
# 자동 시작:   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
# 로그: logs\server.log, logs\ngrok.log, logs\watchdog.log

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$envText = Get-Content (Join-Path $root ".env") -Raw -Encoding UTF8
function Get-EnvValue([string]$name) {
    if ($envText -match "(?m)^$name=(\S+)") { return $Matches[1] }
    return $null
}
$domain = Get-EnvValue "NGROK_DOMAIN"
if (-not (Get-EnvValue "API_KEY")) { throw ".env에 API_KEY가 없습니다. 외부에 공개하기 전에 반드시 설정하세요." }
if (-not $domain) { throw ".env에 NGROK_DOMAIN이 없습니다. (ngrok 대시보드 > Domains)" }

$ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
if (-not $ngrok) { $ngrok = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ngrok.exe" }
$python = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONIOENCODING = "utf-8"

function Write-Log([string]$msg) {
    Add-Content -Path (Join-Path $logs "watchdog.log") -Value "$(Get-Date -Format s) $msg" -Encoding UTF8
}
function Start-Server {
    Write-Log "AI 서버 시작"
    Start-Process -FilePath $python -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1" `
        -RedirectStandardOutput (Join-Path $logs "server.out.log") -RedirectStandardError (Join-Path $logs "server.log")
}
function Start-Tunnel {
    Write-Log "ngrok 시작: https://$domain"
    Start-Process -FilePath $ngrok -WindowStyle Hidden -PassThru `
        -ArgumentList "http", "--url=$domain", "127.0.0.1:8000", "--log", (Join-Path $logs "ngrok.log")
}

$server = Start-Server
$tunnel = Start-Tunnel
try {
    while ($true) {
        Start-Sleep -Seconds 30
        if ($server.HasExited) { Write-Log "AI 서버 종료 감지 (코드 $($server.ExitCode))"; $server = Start-Server }
        if ($tunnel.HasExited) { Write-Log "ngrok 종료 감지 (코드 $($tunnel.ExitCode))"; $tunnel = Start-Tunnel }
    }
}
finally {
    foreach ($p in @($server, $tunnel)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
    Write-Log "중지"
}
