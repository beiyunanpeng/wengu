# 试用机升级清单：v0.4.0 → v0.5.0

> 面向已经在跑本仓库的机器（自家试用机）。**先备份，再拉代码，最后起服务**——顺序不可颠倒，
> 原因见第 2 节。全新装机不需要本文，直接看 [`docker.md`](./docker.md)。

## 1. 这次升级跨了什么

| 项 | v0.4.0 | v0.5.0 |
|---|---|---|
| 提交 | `3ad0718`（标签指向） | 见 `git log -1` |
| alembic head | `0018_practice_dedup` | **`0020_recitation`** |
| 新增迁移 | — | `0019_drop_orphan_photo_tables`、`0020_recitation` |
| 提交数 | — | 31（= 29 个工单/文档提交 + 本清单与 CHANGELOG 切版两个发布提交），含 12 张工单：P5-6 / P0-3 / P0-4 / P3-3a / P3-3b / P3-3c / P5-1a / P5-1b / P1-3e / P1-3f / P1-13 / P1-13b |
| 新依赖 | — | 无（Python 与 npm 依赖均未增加；前端测试用 Node 内置 `node --test`） |
| 需要改 `.env` | — | 不需要；`.env.example` 无新增必填项 |

> `v0.4.0` 标签指向 `3ad0718`，而 CHANGELOG 排版修订提交在 `b481943`——两者不是同一个 commit，
> 对比区间时别按标签名找提交。

## 2. ⚠️ 为什么必须先备份：起服务就会自动落刀

`wengu-api/Dockerfile` 的启动命令是

```
alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**`docker compose up -d --build` 一执行就自动迁移，没有任何确认提示。**而本次区间里的
`0019_drop_orphan_photo_tables` 是**破坏性迁移**：按孩子优先、父表在后的顺序
`DROP` 掉 `problem_extractions` → `photo_capture_items` → `photo_captures` 三张孤儿表（v2.5 退役
视觉栈遗留）。这三张表在你机器上可能还留着早期试验数据。

`0019` 的 `downgrade` 会**重建表结构**，但**建不回数据**——唯一真正的退路是备份 zip。
`0020_recitation` 只是新建 `recitation_items` / `recitation_reviews` 两张表，不碰旧数据。

所以硬闸门是：**第 3 节的备份全部通过校验，才允许拉代码 / 起服务。**

## 3. 备份：两个数据目录要分别备份

本仓库有两种运行形态，**数据目录不是同一个**，很多机器上两份都存在：

| 形态 | 数据目录 | 库文件 |
|---|---|---|
| Docker Compose | `<仓库>/data/`（compose 里 `./data:/app/data`） | `data/wengu.db` |
| 原生 `run-trial.ps1` | `<仓库>/wengu-api/data/` | `wengu-api/data/wengu.db` |

**先确认哪一份是活的**（看错题数和最后修改时间），两份都备份，别猜。

```powershell
# 家长区解锁 → 「备份」→ 立即导出（服务运行中可安全执行，走 SQLite VACUUM INTO 一致性快照）
# 产物：<data_dir>\backups\wengu-backup-<UTC时间戳>.zip
curl.exe -X POST http://127.0.0.1:8000/api/backup/export   # 等价命令（需已带家长会话 cookie）
```

导出后**必须校验**，不是"文件存在"就算备份成功：

```powershell
$zip = "<data_dir>\backups\wengu-backup-XXXXXXXXThhmmssSSSZ.zip"
# 1) CRC 完整性 + 条目数
Expand-Archive -Path $zip -DestinationPath (New-Item -ItemType Directory "_verify") -Force
# 2) 解出来的 wengu.db 能开、integrity_check = ok、alembic 版本与 manifest 一致
```

校验点（`manifest.json` 里都有）：`alembic_version`、`counts`（`mistakes` /
`learning_events` / `review_schedules` / `attempts` / `recitation_items` /
`ingestion_drafts` 等）、`files` 每项的 `sha256` 与 `size_bytes`、顶层 zip 的 `sha256`。
备份含 `wengu.db` + `uploads/` + `seeds_local/` + 未处理的 `inbox/` + `app-config.json`；
`.processed/` 已处理归档按设计**不进**备份。

> 🔒 备份 zip 里有全部错题、订正答案与原图，属家庭敏感数据。`data/` 与 `backups/` 都已在
> `.gitignore` 内——**不要**把它拷进工作目录、提交进仓库（本仓库是公开仓库），也不要放公开网盘链接。

### 3.1 本次发布前已实跑的备份（审核方留的基线）

2026-11-04 22:47（本地时区）在开发机上跑的是 `create_backup(settings)`，即
`POST /api/backup/export` 内部 `asyncio.to_thread` 调的同一个函数；HTTP + PIN 那一层由
`tests/integration/test_backup_api.py` 覆盖（当次 **6 passed**）。两份都通过了
zip CRC、`PRAGMA integrity_check = ok`、manifest 计数与解出快照逐表相等、备份前后业务库不变、
`backups_tmp/` 无残留。

| 数据目录 | 备份文件 | 大小 | alembic | 计数 | zip sha256 |
|---|---|---|---|---|---|
| `<仓库>/data` | `wengu-backup-20261104T144737729978Z.zip` | 9,096,787 B | `0012_attempts_mistake_nullable` | 错题 3 / 事件 20 / 排期 2 / 作答 5 / 草稿 8（40 个文件，含 uploads） | `0fe4c70a51ec0cc7137271282bc592ccbe46baa5a6f918a454d182b0b55c4fd0` |
| `<仓库>/wengu-api/data` | `wengu-backup-20261104T144738417231Z.zip` | 3,914,872 B | `0011_v25_intake_and_quiz` | 错题 2 / 事件 13 / 排期 3 / 作答 1 / 草稿 1（20 个文件） | `4e5f117724f648ffa826356446c0172b3fd3ecc544e24007d89eeeef4c731190` |

**注意这两个库都落后于 head**（`0012` 与 `0011`，head 是 `0020`），升级时会一口气跨 7～9 个迁移。
`recitation_items` 在两份库里都还不存在，背诵功能的数据结构靠本次 `0020` 建表。

## 4. 升级步骤

```powershell
cd <仓库>
git fetch --tags
git status --porcelain        # 必须为空；有未提交改动先处理
git checkout v0.5.0

# Docker 形态
docker compose down
docker compose up -d --build --wait
docker compose logs api | Select-String "alembic|Application startup"   # 看到 upgrade head 完成

# 原生形态
cd wengu-api
.\venv\Scripts\python.exe -m alembic upgrade head        # 这一步才是落刀点
```

迁移本身想先验一遍可逆性（可选，但推荐）：

```powershell
make migration-test         # tests/integration/test_migrations.py
```

## 5. 升级后核对（花 5 分钟）

1. `alembic current` = `0020_recitation`；
2. 错题本条数与备份 `manifest.counts.mistakes` 一致，**复习排期正常重算**（事实源可确定性重算，
   不该出现"到期队列空了"）；
3. 背诵页能新建条目、能导入教材词表 CSV/TSV、能从错题抽词（`0020` 建的表）；
4. 归并弹窗（家长区 → 错题详情 → 归并知识点）：打开时**源/目标两个下拉都为空**、
   未选齐时不发 `merge-preview`、确认按钮禁用；选齐后才显示
   "源 → 目标 · 将并入 N 个别名 · 影响 M 道错题"（P1-13b）；
5. 首次运行横幅与 `/setup` 页正常（P5-1b）；家长区改运行时参数后**重启不丢**（P5-1a，
   落 `<data_dir>/app-config.json`）；
6. `/import` 粘贴整段转录 JSON 与读 `.json` 文件都能进核对页（P1-3e/P1-3f）。

## 6. 出问题怎么退

- **恢复 = 停机整库替换**，没有运行中热恢复：`scripts/restore.ps1`（PowerShell 5.1 需 UTF-8 **带 BOM**）
  或按 [`backup-restore.md`](./backup-restore.md) 第 4 节手动做。
- 只想撤销结构变更：`alembic downgrade 0018_practice_dedup` 会 drop 掉 `0020` 的两张背诵表
  并**重建** `0019` 的三张照片表**空壳**——数据回不来，回不来就靠第 3 节的 zip。
- 降级后仍异常：清空 `data/backups_tmp/`（临时快照目录，允许整个删掉），再走一次恢复。

## 7. 本次发布没做的事

- 没有 GitHub Release 页面与二进制产物，`v0.5.0` 只是一个 annotated tag；
- CHANGELOG 底部的版本对比链接仍写作 `github.com/<你>/wengu/...` 占位，未逐条补齐；
- P4-1 Tailscale 未做——**别把 8000 端口直接暴露到公网**（AGENTS §4 红线）。
