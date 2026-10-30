# wengu-api · 后端工程

**Python 3.11+ · FastAPI · SQLite（WAL + Alembic）**——本目录是 wengu 项目的后端。

> **实现约束请严格遵守仓库根的 [`AGENTS.md`](../AGENTS.md)**：单实例单用户、模块化单体、无 Redis/Celery/外部 MQ、无 agent 编排框架。
> **v2.5 起内核零模型**：后端不调用任何云端 VLM/OCR/文本模型，也没有 provider 抽象；
> 真实作业的识别、批改、讲解全部在系统外完成，外部 agent 的转录 JSON 经监听目录导入为草稿。

## 目录约定（详见 `../目录结构.md`）

```
wengu-api/
├─ app/
│  ├─ main.py                    # FastAPI 入口 + /health + inbox 监听生命周期
│  ├─ core/                      # config / database / security（本地 PIN，预留）
│  ├─ api/                       # 路由
│  ├─ models/                    # SQLAlchemy
│  ├─ schemas/                   # Pydantic（考核题面安全视图）
│  ├─ services/                  # intake / inbox / grading / mistakes / review / quiz / bank
│  ├─ judge/                     # judgeAnswer 规范化 + AST 白名单沙箱 verify
│  └─ seed/                      # seed 装载 + 题库内存索引（bank.py / svg.py）
├─ migrations/                   # Alembic（head = 0013_drop_model_tables）
├─ scripts/                      # import_seed / import_questions / export_topics_junior
├─ tests/                        # unit / integration
├─ requirements.txt
├─ .env.example                  # 零模型：通常无需任何 Key
└─ Dockerfile
```

## 快速开始

```bash
# 从仓库根跑
make install-api                    # 创建 venv（Python 3.12）+ 安装依赖
make upgrade                        # SQLite 建库并升到最新迁移
make dev-api                        # http://localhost:8000/health 与 /docs

# 测试与检查
make test
make lint
make migration-test
make downgrade D=base               # 回退到空库（保留空的 alembic_version 表）
```

> 端口：默认 8000。若被系统保留（Windows Hyper-V 常见），`make dev-api PORT=8100`。
> 数据库文件：默认 `wengu-api/data/wengu.db`（`WENGU_DB_PATH` 可改），首次运行自动建目录。
> 监听目录：默认 `wengu-api/data/inbox`（`WENGU_INBOX_DIR` 可改）——外部 agent 把转录 JSON
> 放进该目录即被后台扫描校验入库为**草稿**（不自动转正、不判分、不建错题），
> 处理完归档到 `.processed/`（非法报文为 `.invalid.json`），停机期间文件不丢、重启补扫。
> 健康检查返回：`{"status":"ok","service":"wengu-api","version":"0.0.0","database":"ok"}`。

## 当前状态（v2.5 零模型 / P1-12）

- 主入本通道：外部 agent 整页拍 → 按 `../docs/templates/` 版本化模板转录已批改错题 →
  `data/inbox/` 监听导入 → `ingestion_drafts` → **核对页人工确认** → 错题 + 首次复习排期。
- 唯一写入路径不变：`services/intake.promote_draft` → `services/grading` 的
  `append_user_decision` → `sync_mistake_for_verdict`；正答必填、含 `〔?〕` 一律拒转正；
  `primary_topic_id` / `student_answer` 可空（无主考点只做原题重做自评）。
- 系统内仅判**自造同类题考核**：运行时走 `judge/normalize.py`（NFKC / 多答案 / 有理数精确 /
  坐标 / 单位别名），题库入库时 `verify` 过 AST 白名单沙箱；**禁用 Python 内置 `eval()`**。
- 到期队列三态：`quiz`（可答题，服务端判分）/ `self_eval`（解答大题、依赖题图 → 纸上自评）/
  `redo`（题库缺口 → 原题重做自评）；手动组卷按知识点 + 固定 seed 可重放。
- 已退役（P1-12）：系统内视觉栈（采集上传 / OCR 切题 / VLM 提取）、`ai_gateway`、
  provider 适配层、讲解服务、HTTP 模型判分端点、`model_runs` / `ai_jobs`（迁移 0013 DROP）。

## 主要端点

| 域 | 端点 |
|---|---|
| 健康 / seed | `GET /health`、`GET /api/seed/summary`、`GET /api/seed/topics` |
| 导入 | `POST /api/imports`、`GET /api/imports/{batch_id}`、`GET /api/imports/inbox` |
| 核对入本 | `GET /api/imports/drafts`、`GET /api/imports/{batch_id}/drafts`、`POST /api/imports/drafts/{draft_id}/confirm` |
| 错题 / 标签 | `GET /api/mistakes`、`GET /api/mistakes/{id}`、`GET /api/mistakes/options`、`POST /api/mistakes/{id}/labels` |
| 概念 | `GET /api/concepts`、`POST /api/concepts`、`POST /api/concepts/merge` |
| 题库 | `POST /api/problem-bank/import`、`GET /api/problem-bank/items/{id}` |
| 复习 | `GET /api/reviews/due`、`POST /api/reviews/{mistake_id}/quiz`、`POST /api/reviews/{mistake_id}/complete` |
| 组卷 | `GET /api/quizzes/topics`、`GET /api/quizzes/paper`、`POST /api/quizzes/paper/submit` |
| 练习记录 | `GET /api/attempts`、`DELETE /api/attempts`、`GET /api/practice-records`、`POST /api/practice-records`、`DELETE /api/practice-records` |

所有 GET 均为纯查询，零模型调用（内核已无模型可调）。

## 关键纪律（不要绕过）

- **模型只提、代码才判**（作用域收缩为自造同类题）：判分只走 `judge/normalize.py`，
  `verify` 只走 `judge/verify_sandbox.py`；禁止 `eval()`。
- **核对页是唯一转正入口**：草稿不得静默转正、不得自动排复习；Skill / 定时任务只写草稿。
- **事件溯源**：`learning_events` append-only，UNIQUE 防重复；掌握度 / 复习排期 / 毕业状态
  一律由事实推导、可整体重算、不存易变字段。
- **PII**：日志与事件 payload **不落题目全文、答案、文件 URL、密钥**；作答原文不入库
  （`attempts.answer_text` 恒为 NULL）。
