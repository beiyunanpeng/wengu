# 备份与恢复（v1：导出一致性快照 + 停机整库替换）

> 适用范围：单机 / Docker Compose 自托管（`./data` 卷）。恢复**必须在服务停止时整库替换**，
> wengu 不提供运行中热替换 SQLite 的在线恢复（WAL/SHM 与正在写入的连接极易把库弄坏）。

## 1. 一键备份里有什么

家长区解锁后进入「备份」页，点「立即导出」生成
`data/backups/wengu-backup-<UTC 时间戳>.zip`，包内结构：

```
wengu.db                 # SQLite VACUUM INTO 一致性快照（含全部已提交数据，不含 -wal/-shm）
manifest.json            # version / created_at / alembic 版本 / 各表计数 / 每个文件的 sha256
app-config.json          # 运行时热参数（daily_review_limit / daily_recitation_limit / exam_day_limit_factor），存在才打包
uploads/                 # 历史图片等上传文件（若存在）
seeds_local/             # 家长自建章级 seed（含 _id_counters.json）
inbox/                   # 监听目录里尚未处理的转录 JSON（若存在；.processed/ 不进包）
```

> P5-1a 起运行时配置真源是 `<data>/app-config.json`，因此随 data 卷一起备份、换机恢复后
> 热参数不再回默认值。仓库根 `config/app-config.json` 只是原生老用户的**兼容只读回退**，
> 不会自动搬运，也不在备份包内——请按 `config/README.md` 的提示迁移到 data 目录后再备份。

- 快照过程只读业务库：导出前后各表行数与内容不变。
- 备份目录只保留最近 **10** 份，超出按时间删除最旧；删除日志只记文件名。
- 备份**不包含**：仓库里的 `seeds/data`（随代码分发）、`data/.session_secret`（本机密钥）、
  仓库根 `config/app-config.json`（仅兼容回退路径；真源已移到 `<data>/app-config.json` 并进包）、
  `data/ai-cache`、`data/ai-raw`（v2.5 已退役的旧缓存，不再产生）。
- 恢复后家长 PIN 沿用备份库里的 `user_role`；`data/.session_secret` 保留本机现有文件，
  因此恢复前后已解锁的浏览器会话仍可继续使用（如需强制失效，删掉该文件重启即可）。

## 2. 导出与下载

1. 头部右上角「家长区」输入 PIN 解锁；
2. 进入「备份」；
3. 点「立即导出」，页面显示文件名、大小、sha256 与错题/事件计数；
4. 在下方列表点「下载」（或在服务器上直接取 `data/backups/` 里的 zip）。

命令行等价操作（需家长会话 cookie；curl 示例仅本机调试）：

```bash
curl -X POST http://127.0.0.1:8000/api/backup/export \
  -b cookies.txt
curl -OJ http://127.0.0.1:8000/api/backup/download/<文件名> -b cookies.txt
```

未解锁时三个接口（export / list / download）一律 `403`。文件名只接受
`wengu-backup-<UTC 时间戳>.zip`，含 `../`、反斜杠、盘符或绝对路径一律 `400/404`。

### 2.1 命令行 / 计划任务备份（服务未起也能用）

家长区「备份」页之外还有一条命令行入口，专门解决"升级前服务已经停了，但还没备份"：

必须在 `wengu-api` 目录下执行（`scripts.backup_cli` 是该包的模块路径；在仓库根执行会报
`No module named scripts.backup_cli`）。`--data-dir` 按**当前目录**解析，所以 Docker 形态写 `..\data`：

```powershell
# 原生 run-trial.ps1 形态：默认库就在 wengu-api\data
cd D:\wengu\wengu-api
venv\Scripts\python -m scripts.backup_cli --dry-run   # 先看会备份哪一份库
venv\Scripts\python -m scripts.backup_cli

# Docker 形态：数据在 <仓库>\data（相对 wengu-api 就是 ..\data）
venv\Scripts\python -m scripts.backup_cli --data-dir ..\data --dry-run
venv\Scripts\python -m scripts.backup_cli --data-dir ..\data
```

嫌路径麻烦就用 Makefile，它已经处理了 `cd wengu-api`，且 `DATA_DIR` **相对仓库根**解析
（与上面 `--data-dir` 的基准不同，别混用）：

```powershell
make backup
make backup DATA_DIR=data
```

它与家长区导出**共用同一份实现、同一个 `backups/` 目录、同一命名和同一套"保留最近 10 份"的
轮转**：两条入口互相看得见对方导出的文件，不会出现各留 10 份的情况。产物结构、`manifest.json`
与恢复流程完全相同，恢复仍走 §3。

- 输出只有路径、文件名、大小、sha256、alembic 版本与错题/事件计数；失败时退出码非 0，
  并打印一行原因。不做推送/锁屏告警。
- **这条命令没有 PIN、没有会话**。能在这台机器上执行命令的人，本来就能直接读 `wengu.db`
  与 `uploads/`；因此"能跑命令 = 能导出全部错题、订正答案与上传原图"。别把仓库目录共享给
  不信任的账号，也不要在公共/CI 机器上保留数据卷。
- **先确认备份的是哪一份库**：同一台机器上可能有两份平行数据（原生 `wengu-api\data`、
  Docker `<仓库>\data`），版本与错题数都可能不同。`--dry-run` 会打印数据目录、实际 db 路径、
  现有备份份数与错误计数，升级前对照一下，别备份错那份。

#### Windows 计划任务（定时自动备份）

图形界面：任务计划程序 → 创建任务 → 「操作」→ 启动程序：

- 程序：`cmd.exe`
- 参数：`/c cd /d D:\wengu\wengu-api && venv\Scripts\python -m scripts.backup_cli --data-dir ..\data >> "%TEMP%\wengu-backup.log" 2>&1`
  （原生形态去掉 `--data-dir ..\data`；日志路径可自改）
- 触发：每天一次；需要机器没登录也跑就勾"不管用户是否登录"，并保存账户密码。

命令行等价（PowerShell 5.1 实测通过，2026-11-05）：

```powershell
$tr = 'cmd /c cd /d D:\wengu\wengu-api && venv\Scripts\python -m scripts.backup_cli --data-dir ..\data >> "%TEMP%\wengu-backup.log" 2>&1'
schtasks /Create /TN "wengu-backup" /SC DAILY /ST 22:00 /F /TR $tr
schtasks /Run /TN "wengu-backup"                    # 先手动跑一次
schtasks /Query /TN "wengu-backup" /FO LIST /V      # 看"上次结果"：0 = 成功
```

> 实测记录：用上面的 `/TR` 形式创建一次性任务并 `/Run`，任务正常执行，日志输出为
> "备份完成 / size_bytes / sha256 / alembic / 计数"。**不要**在 `/TR` 里写
> `set PYTHONUTF8=1 && ...`——`cmd /c` 会把值带成 `1 `（尾随空格），Python 直接报
> `invalid PYTHONUTF8 environment variable value` 并退出。

**为什么在升级前跑**：`docker compose up` 与 `run-trial.ps1` 启动时会跑 `alembic upgrade head`，
破坏性迁移执行后旧代码已无法读新库。服务停着的时候正好用这条命令留一份快照，再升级。

## 3. 恢复（Windows PowerShell，推荐）

前置：已拿到备份 zip；在仓库根目录执行；Docker Desktop 可用。

```powershell
.\scripts\restore.ps1 -ZipPath .\data\backups\wengu-backup-20261031T120000000000Z.zip
```

脚本会：

1. 打印目标并等待输入 `RESTORE` 确认（脚本化场景可加 `-Force`）；
2. `docker compose stop api`；
3. 把当前 `data/` 的 `wengu.db* / uploads / seeds_local / inbox / app-config.json / .session_secret`
   拷到 `backups/pre-restore-<时间戳>/`（回滚用）；
4. 检查 zip 条目无路径遍历，并用 `manifest.json` 核对 `wengu.db` 的 sha256；
5. 删除旧 `wengu.db / -wal / -shm`，覆盖 `wengu.db`、`uploads/`、`seeds_local/`、`inbox/`；
   包内有 `app-config.json` 时一并覆盖（旧包没有则保留现有运行时配置）；
6. `docker compose up -d api`，轮询 `/health` 最多 60 秒。

只演练文件替换、不碰容器：

```powershell
.\scripts\restore.ps1 -ZipPath .\backup.zip -DataDir .\_drill\data `
  -SkipServiceControl -SkipHealthCheck -Force
```

### 3.1 本机原生跑（没装 Docker）的恢复

试用机常见形态是 `run-trial.ps1` 直接起 uvicorn + Vite，此时**数据目录是
`wengu-api\data`，不是 Docker 的 `.\data`**，两者别弄混。步骤：

```powershell
.\run-trial.ps1 -Stop         # 1) 先停写；确认 8000 / 5173 都已释放
```

2. 用 `-SkipServiceControl -SkipHealthCheck` 只做文件替换（脚本不碰容器、不查健康）：

```powershell
.\scripts\restore.ps1 -ZipPath .\wengu-api\data\backups\wengu-backup-<时间戳>.zip `
  -DataDir .\wengu-api\data -SkipServiceControl -SkipHealthCheck
```

3. 重新起服务并核对：

```powershell
.\run-trial.ps1               # 3) 浏览器打开看板，核对错题数 / 到期队列与 manifest 计数一致
```

- 安全副本落在 `wengu-api\backups\pre-restore-<时间戳>\`（回滚就是把它拷回 `wengu-api\data`）。
- 原生形态没有 `/health` 轮询可用时，可再加 `-SkipHealthCheck` 后自行开浏览器确认。

## 4. 恢复（Linux / macOS 手动步骤）

```bash
# 0) 停写：只停 api 即可，web 静态页可留着（会显示后端不可用）
docker compose stop api

# 1) 安全副本
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "backups/pre-restore-$stamp"
cp -a data/wengu.db data/wengu.db-wal data/wengu.db-shm \
      data/uploads data/seeds_local data/inbox data/app-config.json data/.session_secret \
      "backups/pre-restore-$stamp/" 2>/dev/null || true

# 2) 解包（只取需要覆盖的条目）
rm -f data/wengu.db data/wengu.db-wal data/wengu.db-shm
unzip -o backup.zip wengu.db -d data
rm -rf data/uploads data/seeds_local data/inbox
unzip -o backup.zip 'uploads/*' 'seeds_local/*' 'inbox/*' -d data 2>/dev/null || true
mkdir -p data/uploads data/seeds_local data/inbox
# 运行时配置：旧包没有该条目时保留现有文件
unzip -o backup.zip app-config.json -d data 2>/dev/null || true

# 3) 起服务（容器入口会跑 alembic upgrade head；同版本快照是幂等 no-op）
docker compose up -d api

# 4) 核对
curl -fsS http://127.0.0.1:8000/health
```

## 5. 恢复后核对清单

- `GET /health` 返回 200；
- 看板「错题总数 / 事件数 / 到期队列」与导出时 manifest 的 `counts` 一致；
- 「练习记录」里加练分组仍在；「题库审核」「学科 seed」能看到本地数据；
- 家长 PIN 可正常解锁（PIN 哈希随 `wengu.db` 恢复）；
- `data/seeds_local/_id_counters.json` 存在，之后新建本地知识点 id 不回退。

## 6. 回滚

恢复脚本在替换前已把旧数据拷到 `backups/pre-restore-<时间戳>/`。回滚：

```bash
docker compose stop api
rm -f data/wengu.db data/wengu.db-wal data/wengu.db-shm
cp -a backups/pre-restore-<时间戳>/wengu.db data/
cp -a backups/pre-restore-<时间戳>/uploads data/
cp -a backups/pre-restore-<时间戳>/seeds_local data/
cp -a backups/pre-restore-<时间戳>/inbox data/
docker compose up -d api
```

## 7. 注意

- 备份 zip 含全部错题与家长 PIN 哈希，**不要上传网盘 / 群聊 / 公网**；manifest 只含
  文件名、大小、sha256 与计数，不含题目正文。
- 恢复是整库替换：备份包里没有的可选目录（如 `inbox/`）会被置空，而不是与现有文件合并。
- `seeds/data` 来自仓库（CC BY-NC 4.0），不随备份走；换机时请同时拷贝仓库或重新拉取代码。
- 运行中直接拷 `wengu.db`（尤其 Docker Desktop + WAL）可能拿到不一致数据；
  请一律用本页的导出功能，或先停服务再拷。
- 恢复脚本留下的 `backups/pre-restore-<时间戳>/` 安全副本**不参与"只保留最近 10 份"的轮转**，
  它们是全量数据副本；确认恢复无误后请手工删掉旧副本，别攒满磁盘。
- 导出若中途崩溃，`data/backups_tmp/` 可能残留 `snapshot-*` 临时目录，可手工清空
  （正常导出的临时目录会在结束时自动删除）。
