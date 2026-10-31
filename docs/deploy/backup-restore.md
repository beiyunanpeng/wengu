# 备份与恢复（v1：导出一致性快照 + 停机整库替换）

> 适用范围：单机 / Docker Compose 自托管（`./data` 卷）。恢复**必须在服务停止时整库替换**，
> wengu 不提供运行中热替换 SQLite 的在线恢复（WAL/SHM 与正在写入的连接极易把库弄坏）。

## 1. 一键备份里有什么

家长区解锁后进入「备份」页，点「立即导出」生成
`data/backups/wengu-backup-<UTC 时间戳>.zip`，包内结构：

```
wengu.db                 # SQLite VACUUM INTO 一致性快照（含全部已提交数据，不含 -wal/-shm）
manifest.json            # version / created_at / alembic 版本 / 各表计数 / 每个文件的 sha256
uploads/                 # 历史图片等上传文件（若存在）
seeds_local/             # 家长自建章级 seed（含 _id_counters.json）
inbox/                   # 监听目录里尚未处理的转录 JSON（若存在；.processed/ 不进包）
```

- 快照过程只读业务库：导出前后各表行数与内容不变。
- 备份目录只保留最近 **10** 份，超出按时间删除最旧；删除日志只记文件名。
- 备份**不包含**：仓库里的 `seeds/data`（随代码分发）、`data/.session_secret`（本机密钥）、
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

## 3. 恢复（Windows PowerShell，推荐）

前置：已拿到备份 zip；在仓库根目录执行；Docker Desktop 可用。

```powershell
.\scripts\restore.ps1 -ZipPath .\data\backups\wengu-backup-20261031T120000000000Z.zip
```

脚本会：

1. 打印目标并等待输入 `RESTORE` 确认（脚本化场景可加 `-Force`）；
2. `docker compose stop api`；
3. 把当前 `data/` 的 `wengu.db* / uploads / seeds_local / inbox / .session_secret`
   拷到 `backups/pre-restore-<时间戳>/`（回滚用）；
4. 检查 zip 条目无路径遍历，并用 `manifest.json` 核对 `wengu.db` 的 sha256；
5. 删除旧 `wengu.db / -wal / -shm`，覆盖 `wengu.db`、`uploads/`、`seeds_local/`、`inbox/`；
6. `docker compose up -d api`，轮询 `/health` 最多 60 秒。

只演练文件替换、不碰容器：

```powershell
.\scripts\restore.ps1 -ZipPath .\backup.zip -DataDir .\_drill\data `
  -SkipServiceControl -SkipHealthCheck -Force
```

## 4. 恢复（Linux / macOS 手动步骤）

```bash
# 0) 停写：只停 api 即可，web 静态页可留着（会显示后端不可用）
docker compose stop api

# 1) 安全副本
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "backups/pre-restore-$stamp"
cp -a data/wengu.db data/wengu.db-wal data/wengu.db-shm \
      data/uploads data/seeds_local data/inbox data/.session_secret \
      "backups/pre-restore-$stamp/" 2>/dev/null || true

# 2) 解包（只取需要覆盖的条目）
rm -f data/wengu.db data/wengu.db-wal data/wengu.db-shm
unzip -o backup.zip wengu.db -d data
rm -rf data/uploads data/seeds_local data/inbox
unzip -o backup.zip 'uploads/*' 'seeds_local/*' 'inbox/*' -d data 2>/dev/null || true
mkdir -p data/uploads data/seeds_local data/inbox

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
