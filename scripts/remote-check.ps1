#Requires -Version 5.1
<#
.SYNOPSIS
    wengu 远程可达性只读自检：监听地址 / Docker 端口映射 / Tailscale / 本机健康检查。

.DESCRIPTION
    打印 web 与 api 的实际监听地址和端口、是否只绑回环、docker compose 的端口映射、
    `tailscale status` 与 `tailscale serve status`（未安装就打印"未安装"并继续）、
    本机 http://127.0.0.1:<web>/health 的状态码，最后给出一句判定：
    仅本机可达 / 局域网可达 / tailnet 已转发。

    本脚本只读：不修改配置、不重启服务、不写数据库、不读取 cookie 或密钥。
    分享输出前请自行打码 tailscale status 里的设备名 / 邮箱。

.PARAMETER WebPort
    宿主机 web 端口，默认 5173（Docker 用 WENGU_WEB_PORT，原生 run-trial 固定 5173）。

.PARAMETER ApiPort
    宿主机 api 端口，默认 8000（可用 WENGU_API_PORT 覆盖）。

.PARAMETER ComposeFile
    docker-compose.yml 路径，默认当前目录。

.EXAMPLE
    .\scripts\remote-check.ps1

.EXAMPLE
    .\scripts\remote-check.ps1 -WebPort 5000 -ApiPort 8100
#>
[CmdletBinding()]
param(
    [int]$WebPort = 5173,
    [int]$ApiPort = 8000,
    [string]$ComposeFile = "docker-compose.yml"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Test-Loopback([string]$Address) {
    return ($Address -eq "127.0.0.1") -or ($Address -eq "::1") -or ($Address -eq "::ffff:127.0.0.1")
}

function Invoke-NativeText([scriptblock]$Command) {
    # PS 5.1 下 EAP=Stop 时，原生命令写 stderr 会抛 NativeCommandError；
    # 这里临时放宽，只按退出码与输出判断成功与否（docker 未运行 / tailscale 未登录都不该中断自检）。
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $text = (& $Command 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Text = $text; Code = $code }
}

function Get-ListenRows([int]$Port) {
    $rows = @()
    $hasCmdlet = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if ($hasCmdlet) {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($conn in $conns) {
            $procName = "?"
            try { $procName = (Get-Process -Id $conn.OwningProcess -ErrorAction Stop).ProcessName } catch { }
            $rows += [pscustomobject]@{
                Address = [string]$conn.LocalAddress
                Port    = [int]$conn.LocalPort
                Owner   = [int]$conn.OwningProcess
                Process = $procName
            }
        }
        return $rows
    }
    # 兜底：没有 NetTCPIP 模块时解析 netstat
    $netstat = & netstat -ano 2>$null
    foreach ($line in @($netstat)) {
        if ($line -notmatch "LISTENING") { continue }
        $parts = @($line.Trim() -split "\s+")
        if ($parts.Count -lt 5) { continue }
        $local = $parts[1]
        $idx = $local.LastIndexOf(":")
        if ($idx -lt 1) { continue }
        $portValue = 0
        if (-not [int]::TryParse($local.Substring($idx + 1), [ref]$portValue)) { continue }
        if ($portValue -ne $Port) { continue }
        $address = $local.Substring(0, $idx).Trim("[", "]")
        $owner = [int]$parts[$parts.Count - 1]
        $procName = "?"
        try { $procName = (Get-Process -Id $owner -ErrorAction Stop).ProcessName } catch { }
        $rows += [pscustomobject]@{ Address = $address; Port = $portValue; Owner = $owner; Process = $procName }
    }
    return $rows
}

$webRows = @(Get-ListenRows $WebPort)
$apiRows = @(Get-ListenRows $ApiPort)

Write-Section "本机监听"
$targets = @(
    [pscustomobject]@{ Name = "web"; Port = $WebPort; Rows = $webRows },
    [pscustomobject]@{ Name = "api"; Port = $ApiPort; Rows = $apiRows }
)
foreach ($target in $targets) {
    if ($target.Rows.Count -eq 0) {
        Write-Host ("  {0} :{1}  未发现监听（服务可能没启动）" -f $target.Name, $target.Port) -ForegroundColor Yellow
        continue
    }
    foreach ($row in $target.Rows) {
        $scope = "非回环"
        if (Test-Loopback $row.Address) { $scope = "回环" }
        Write-Host ("  {0} {1}:{2}  ({3}, PID {4} {5})" -f $target.Name, $row.Address, $row.Port, $scope, $row.Owner, $row.Process)
    }
    $allLoopback = $true
    foreach ($row in $target.Rows) {
        if (-not (Test-Loopback $row.Address)) { $allLoopback = $false }
    }
    if ($allLoopback) {
        Write-Host ("  {0} 仅绑回环" -f $target.Name) -ForegroundColor Green
    }
    else {
        Write-Host ("  {0} 绑定了非回环地址（同网段设备可访问）" -f $target.Name) -ForegroundColor Yellow
    }
}

Write-Section "Docker 端口映射"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Host "  未安装 docker（跳过）" -ForegroundColor Yellow
}
elseif (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
    Write-Host ("  未找到 {0}（跳过）" -f $ComposeFile) -ForegroundColor Yellow
}
else {
    $webMap = Invoke-NativeText { docker compose -f $ComposeFile port web 80 }
    if ($webMap.Code -eq 0 -and $webMap.Text) {
        Write-Host ("  web 80 -> {0}" -f $webMap.Text)
    }
    else {
        Write-Host "  web 80 -> （Docker 未运行或未发布端口）" -ForegroundColor Yellow
    }
    if ($webMap.Code -eq 0) {
        $apiMap = Invoke-NativeText { docker compose -f $ComposeFile port api 8000 }
        if ($apiMap.Code -eq 0 -and $apiMap.Text) {
            Write-Host ("  api 8000 -> {0}" -f $apiMap.Text)
        }
        else {
            Write-Host "  api 8000 -> （服务未运行或未发布端口）" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "  Docker daemon 不可达，端口映射一项跳过；监听地址与判定不受影响。" -ForegroundColor Yellow
    }
}

Write-Section "Tailscale"
$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
$serveForwarded = $false
if (-not $tailscale) {
    Write-Host "  未安装 Tailscale（跳过）" -ForegroundColor Yellow
}
else {
    Write-Host "  -- tailscale status --"
    $statusResult = Invoke-NativeText { tailscale status }
    if ($statusResult.Code -eq 0 -and $statusResult.Text) {
        Write-Host $statusResult.Text
    }
    else {
        Write-Host "  无法读取（未登录或 tailscaled 未运行）" -ForegroundColor Yellow
    }
    Write-Host "  -- tailscale serve status --"
    $serveResult = Invoke-NativeText { tailscale serve status }
    if ($serveResult.Code -eq 0 -and $serveResult.Text) {
        Write-Host $serveResult.Text
        if ($serveResult.Text -match "https://") { $serveForwarded = $true }
    }
    else {
        Write-Host "  未配置 serve 转发" -ForegroundColor Yellow
    }
}

Write-Section "本机健康检查"
$healthUrl = "http://127.0.0.1:$WebPort/health"
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
    Write-Host ("  {0} -> {1}" -f $healthUrl, [int]$resp.StatusCode) -ForegroundColor Green
}
catch {
    $code = $null
    if ($_.Exception.Response) {
        try { $code = [int]$_.Exception.Response.StatusCode } catch { }
    }
    if ($null -ne $code) {
        Write-Host ("  {0} -> {1}" -f $healthUrl, $code) -ForegroundColor Yellow
    }
    else {
        Write-Host ("  {0} -> 连接失败（{1}）" -f $healthUrl, $_.Exception.Message) -ForegroundColor Yellow
    }
}

$lanExposed = $false
foreach ($row in @($webRows) + @($apiRows)) {
    if (-not (Test-Loopback $row.Address)) { $lanExposed = $true }
}

Write-Section "判定"
if ($lanExposed) {
    Write-Host "  局域网可达（web/api 至少一个绑在非回环地址，同网段设备可直接访问）" -ForegroundColor Yellow
    if ($serveForwarded) {
        Write-Host "  另外：tailnet 也已转发" -ForegroundColor Green
    }
}
elseif ($serveForwarded) {
    Write-Host "  tailnet 已转发（本机只绑回环，Tailscale serve 提供 tailnet 内访问）" -ForegroundColor Green
}
else {
    Write-Host "  仅本机可达（未发现非回环监听，也未检测到 tailscale serve 转发）" -ForegroundColor Green
}
if ($webRows.Count -eq 0 -and $apiRows.Count -eq 0) {
    Write-Host "  提示：两个端口都没有监听，先启动服务再看本判定。" -ForegroundColor Yellow
}
