# AI 서버를 켜고 Cloudflare 빠른 터널로 외부 주소를 연다 (Windows PowerShell).
# 사용: 저장소 루트에서  powershell -ExecutionPolicy Bypass -File scripts\start_public.ps1
# 준비: Ollama 실행 중, .env에 API_KEY 설정, cloudflared 설치 (winget install --id Cloudflare.cloudflared)
# 종료: 이 창에서 Ctrl+C (서버도 함께 종료된다)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile) -or -not (Select-String -Path $envFile -Pattern '^API_KEY=\S+' -Quiet)) {
    Write-Error ".env에 API_KEY가 없습니다. 외부에 공개하기 전에 반드시 설정하세요. (.env.example 참고)"
}
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Error "cloudflared가 없습니다. 설치: winget install --id Cloudflare.cloudflared"
}

$python = Join-Path $root ".venv\Scripts\python.exe"
$server = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1" -PassThru -NoNewWindow
try {
    Write-Host "AI 서버 시작 (pid $($server.Id)). 아래에 나오는 https://...trycloudflare.com 주소를 백엔드에 전달하세요."
    cloudflared tunnel --url http://127.0.0.1:8000
}
finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
