# run-trial.ps1 —— wengu 试用一键启动（原生，无 Docker）
# 用法：
#   .\run-trial.ps1            首次会自动 npm install；启动后端(8000)+前端(5173)各一个新窗口
#   .\run-trial.ps1 -Install   强制重装前端依赖
#   .\run-trial.ps1 -Stop      停止（按端口杀；也可直接关掉那两个窗口）
# 若脚本被执行策略拦截：先执行  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
[CmdletBinding()]
param(
  [switch]$Stop,
  [switch]$Install
)

$ErrorActionPreference = "Stop"
$root    = $PSScriptRoot
$api     = Join-Path $root "wengu-api"
$web     = Join-Path $root "wengu-web"
$py      = Join-Path $api "venv\Scripts\python.exe"
$apiPort = 8000
$webPort = 5173
$inbox   = Join-Path $api "data\inbox"

function Stop-OnPort([int]$port) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
      Write-Host "  已停止占用端口 $port 的进程 PID $($c.OwningProcess)"
    }
  } catch { }
}

if ($Stop) {
  Write-Host "停止 wengu 试用服务…"
  Stop-OnPort $webPort
  Stop-OnPort $apiPort
  Write-Host "已停止。"
  return
}

# 预检
if (-not (Test-Path $py)) {
  throw "找不到 venv：$py`n先创建：cd `"$api`"; python -m venv venv; .\venv\Scripts\pip install -r requirements.txt"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "找不到 npm，请先安装 Node.js（含 npm）。"
}

# 幂等重启：先清占用端口的旧进程
Stop-OnPort $apiPort
Stop-OnPort $webPort

# 数据库迁移（前台执行，失败即停）
Write-Host "应用数据库迁移（alembic upgrade head）…"
Push-Location $api
try {
  & $py -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw "alembic 迁移失败" }
} finally { Pop-Location }

# 后端（新窗口，日志可见）
Write-Host "启动后端 http://127.0.0.1:$apiPort （新窗口）"
Start-Process -FilePath $py -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$apiPort) -WorkingDirectory $api | Out-Null

# 前端依赖（首次或 -Install）
if ($Install -or -not (Test-Path (Join-Path $web "node_modules"))) {
  Write-Host "安装前端依赖（npm install，首次较慢）…"
  Push-Location $web
  try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
  } finally { Pop-Location }
}

# 前端（新窗口，cmd /k 保持窗口以看日志；/api 代理到后端 8000）
Write-Host "启动前端 http://localhost:$webPort （新窗口）"
Start-Process -FilePath "cmd.exe" -ArgumentList @("/k","npm run dev") -WorkingDirectory $web | Out-Null

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "✅ 已启动："
Write-Host "   后端 API : http://127.0.0.1:$apiPort   （/docs 看接口）"
Write-Host "   前端 Web : http://localhost:$webPort"
Write-Host "   监听目录 : $inbox   （把转录 JSON 丢这里 → 核对页确认）"
Write-Host "停止：.\run-trial.ps1 -Stop   （或直接关掉那两个新窗口）"
