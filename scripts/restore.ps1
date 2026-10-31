#Requires -Version 5.1
<#
.SYNOPSIS
    wengu 一键备份的停机恢复脚本：整库替换 data/ 后重启服务。

.DESCRIPTION
    恢复 = 整库替换，不在运行中热替换 SQLite。步骤：
    1. 确认（除非 -Force）；
    2. 停 api 服务（除非 -SkipServiceControl）；
    3. 把当前 data/ 拷到 backups/pre-restore-<时间戳>/；
    4. 校验 zip（路径遍历 / wengu.db sha256 对照 manifest）；
    5. 替换 wengu.db（连同 -wal/-shm）与 uploads/ seeds_local/ inbox/；
    6. 起服务并轮询 /health（除非 -SkipHealthCheck）。

    data/.session_secret 属于本机密钥，不在备份包内；恢复时保留现有文件，
    仅随安全副本一起拷走以便回滚。

.PARAMETER ZipPath
    wengu 导出的备份 zip（家长区「备份」页下载，或 data/backups/ 下的文件）。

.PARAMETER DataDir
    运行数据目录，默认当前目录下的 data（Docker Compose 的 ./data）。

.PARAMETER ComposeFile
    docker-compose.yml 路径，默认当前目录。

.EXAMPLE
    .\scripts\restore.ps1 -ZipPath .\data\backups\wengu-backup-20261031T120000000000Z.zip

.EXAMPLE
    # 仅演练解包与替换（不碰容器、不查健康）
    .\scripts\restore.ps1 -ZipPath .\backup.zip -DataDir .\_drill\data -SkipServiceControl -SkipHealthCheck -Force
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ZipPath,
    [string]$DataDir = "data",
    [string]$ComposeFile = "docker-compose.yml",
    [string]$Service = "api",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$HealthTimeoutSeconds = 60,
    [switch]$SkipServiceControl,
    [switch]$SkipHealthCheck,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Write-Step([string]$Message) {
    Write-Host "[restore] $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    throw "[restore] $Message"
}

function Resolve-FullPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $PathValue))
}

function Test-ZipEntries([string]$ArchivePath) {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName })
        foreach ($name in $names) {
            $normalized = $name.Replace("\", "/")
            if ($normalized.StartsWith("/") -or $normalized -match "^[A-Za-z]:") {
                Fail "压缩包含绝对路径条目：$name"
            }
            if (($normalized.Split("/") -contains "..")) {
                Fail "压缩包含路径遍历条目：$name"
            }
        }
        if (-not ($names -contains "wengu.db")) {
            Fail "压缩包缺少 wengu.db：$ArchivePath"
        }
    }
    finally {
        $archive.Dispose()
    }
}

$zipFull = Resolve-FullPath $ZipPath
$dataFull = Resolve-FullPath $DataDir
$composeFull = Resolve-FullPath $ComposeFile
if (-not (Test-Path -LiteralPath $zipFull -PathType Leaf)) {
    Fail "备份包不存在：$zipFull"
}

Test-ZipEntries $zipFull

Write-Step "备份包：$zipFull"
Write-Step "数据目录：$dataFull"
if ($SkipServiceControl) {
    Write-Host "[restore] 已跳过服务停止/启动（演练模式；真实恢复请去掉 -SkipServiceControl）" -ForegroundColor Yellow
}

if (-not $Force) {
    Write-Host ""
    Write-Host "这会停止服务、清空并替换数据目录，且不可在线撤销。" -ForegroundColor Yellow
    $answer = Read-Host "确认请输入 RESTORE"
    if ($answer -ne "RESTORE") {
        Write-Host "已取消。" -ForegroundColor Yellow
        exit 1
    }
}

$stamp = Get-Date -Format "yyyyMMddTHHmmssfffZ"
$parentDir = Split-Path -Parent $dataFull
$safetyDir = Join-Path (Join-Path $parentDir "backups") "pre-restore-$stamp"
$extractDir = Join-Path ([System.IO.Path]::GetTempPath()) "wengu-restore-$stamp"
$startedService = $false
$replaced = $false

try {
    if (-not $SkipServiceControl) {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if (-not $docker) {
            Fail "未找到 docker 命令；如只做文件替换，请加 -SkipServiceControl"
        }
        Write-Step "停止服务 $Service ..."
        & docker compose -f $composeFull stop $Service
        if ($LASTEXITCODE -ne 0) {
            Fail "docker compose stop 失败（退出码 $LASTEXITCODE）"
        }
    }

    # 1) 现有 data/ 安全副本（可回滚）
    $copyNames = @(
        "wengu.db", "wengu.db-wal", "wengu.db-shm",
        "uploads", "seeds_local", "inbox", ".session_secret"
    )
    $existing = @()
    if (Test-Path -LiteralPath $dataFull -PathType Container) {
        foreach ($name in $copyNames) {
            $candidate = Join-Path $dataFull $name
            if (Test-Path -LiteralPath $candidate) {
                $existing += $candidate
            }
        }
    }
    if ($existing.Count -gt 0) {
        New-Item -ItemType Directory -Path $safetyDir -Force | Out-Null
        foreach ($item in $existing) {
            Copy-Item -LiteralPath $item -Destination $safetyDir -Recurse -Force
        }
        Write-Step "当前数据已备份到：$safetyDir"
    }
    else {
        Write-Step "数据目录为空，跳过安全副本"
    }

    # 2) 解包到临时目录并核对 manifest
    if (Test-Path -LiteralPath $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zipFull, $extractDir)

    $extractedDb = Join-Path $extractDir "wengu.db"
    $manifestPath = Join-Path $extractDir "manifest.json"
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $dbInfo = @($manifest.files | Where-Object { $_.path -eq "wengu.db" }) | Select-Object -First 1
        if ($dbInfo) {
            $actual = (Get-FileHash -LiteralPath $extractedDb -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne [string]$dbInfo.sha256) {
                Fail "wengu.db 校验失败：manifest=$($dbInfo.sha256) actual=$actual"
            }
            Write-Step "wengu.db sha256 校验通过"
        }
        else {
            Write-Host "[restore] manifest 未登记 wengu.db，跳过哈希核对" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "[restore] 备份包无 manifest.json（旧包），跳过哈希核对" -ForegroundColor Yellow
    }

    # 3) 整库替换（先删 -wal/-shm，防止旧日志污染新库）
    New-Item -ItemType Directory -Path $dataFull -Force | Out-Null
    foreach ($name in @("wengu.db-wal", "wengu.db-shm", "wengu.db")) {
        $target = Join-Path $dataFull $name
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    Copy-Item -LiteralPath $extractedDb -Destination (Join-Path $dataFull "wengu.db") -Force
    $replaced = $true
    Write-Step "wengu.db 已替换"

    foreach ($name in @("uploads", "seeds_local", "inbox")) {
        $source = Join-Path $extractDir $name
        $target = Join-Path $dataFull $name
        if (Test-Path -LiteralPath $source -PathType Container) {
            if (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Recurse -Force
            }
            Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
            Write-Step "$name/ 已替换"
        }
        else {
            if (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Recurse -Force
            }
            New-Item -ItemType Directory -Path $target -Force | Out-Null
            Write-Host "[restore] 包内无 $name/，已置空以保持一致" -ForegroundColor Yellow
        }
    }

    # 4) 起服务并核对健康
    if (-not $SkipServiceControl) {
        Write-Step "启动服务 $Service ..."
        & docker compose -f $composeFull up -d $Service
        if ($LASTEXITCODE -ne 0) {
            Fail "docker compose up 失败（退出码 $LASTEXITCODE）"
        }
        $startedService = $true
    }

    if (-not $SkipHealthCheck) {
        Write-Step "等待健康检查：$HealthUrl"
        $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
        $healthy = $false
        while ((Get-Date) -lt $deadline) {
            try {
                $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
                if ([int]$response.StatusCode -eq 200) {
                    $healthy = $true
                    break
                }
            }
            catch {
                Start-Sleep -Seconds 2
            }
        }
        if (-not $healthy) {
            Fail "健康检查超时（$HealthTimeoutSeconds 秒）；请查看 docker compose logs $Service"
        }
        Write-Step "健康检查通过"
    }

    Write-Step "恢复完成。请打开看板核对错题数 / 到期队列 / 练习记录与备份前一致。"
    if (Test-Path -LiteralPath $safetyDir) {
        Write-Step "如需回滚：停服务后把 $safetyDir 内容拷回 $dataFull，再启动服务。"
    }
}
catch {
    Write-Host ""
    Write-Host "[restore] 失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($replaced) {
        Write-Host "[restore] 数据目录可能已被部分替换。" -ForegroundColor Yellow
    }
    if (Test-Path -LiteralPath $safetyDir) {
        Write-Host "[restore] 回滚副本：$safetyDir" -ForegroundColor Yellow
        Write-Host "[restore] 回滚 = 把该目录内容拷回 $dataFull 后启动服务。" -ForegroundColor Yellow
    }
    if ($startedService) {
        Write-Host "[restore] 服务已尝试启动，请查看 docker compose logs $Service。" -ForegroundColor Yellow
    }
    exit 1
}
finally {
    if (Test-Path -LiteralPath $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
