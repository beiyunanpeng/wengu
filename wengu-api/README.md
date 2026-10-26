# wengu-api · 后端工程

**Python 3.11+ · FastAPI · SQLite（WAL + Alembic）**——本目录是 wengu 项目的后端。

> **实现约束请严格遵守仓库根的 [`AGENTS.md`](../AGENTS.md)**：单实例单用户、模块化单体、无 Redis/Celery/外部 MQ、无 agent 编排框架、Prompt 版本化真源在 `../llm_prompts/`。

## 目录约定（详见 `../目录结构.md`）

```
wengu-api/
├─ app/
│  ├─ main.py                    # FastAPI 入口 + /health
│  ├─ core/                      # config / database / security（本地 PIN）
│  ├─ api/                       # 路由
│  ├─ models/                    # SQLAlchemy
│  ├─ schemas/                   # Pydantic（宽松解析 vs 严格校验分离）
│  ├─ services/                  # 业务
│  ├─ providers/                 # 按厂商拆文件：base/doubao/qwen_vl/tencent/mock
│  ├─ judge/                     # judgeAnswer 规范化 + AST 白名单沙箱 verify
│  ├─ jobs/                      # ai_jobs 表 + 进程内循环
│  ├─ prompts/loader.py          # 从 ../llm_prompts/ 加载真源
│  └─ seed/                      # 装载 knowledge_seed + prerequisite_edges
├─ migrations/                   # Alembic
├─ scripts/                      # import_seed / make_* / eval_* / smoke_providers
├─ tests/                        # unit / integration / e2e / memory
├─ requirements.txt
├─ .env.example                  # 密钥走 env；运行时可改参数走 config/app-config.json
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
> 健康检查返回：`{"status":"ok","service":"wengu-api","version":"0.0.0","database":"ok"}`。

## 当前状态（P1-8）

- 已完成：配置热加载、事件溯源 + 确定性重算、seed 装载、四家 provider 适配与成本护栏、
  采集/导入/切题、结构化提取与质量闸门、批改分级闸、保守入本与两级标签、
  **三段式讲解引擎**。
- P1-5 批改约定：
  - 客观题：**零模型调用**，由代码规范化比对（`app/judge/normalize.py`）。
  - 过程题：`grade.md` 保守初判 + 可选 1–3 次采样；不一致或模型不确定 → `uncertain`。
  - 开放题：只返回 `{"route": "explanation"}`，不建批改单、不进错题流，随后可调讲解端点。
  - 标准答案取 `problem_bank` 引用或请求显式 `answer`；缺失 → 人工，不调模型。
  - **Phase 0 边界表未回填：所有新单 `pending`，确认/申诉只追加版本，不自动建错题。**
- P1-8 讲解约定：
  - `POST /api/explanations`：`source_kind` = `mistake` / `problem_extraction` /
    `ingestion_draft`，`mode` = `auto` / `guide` / `full`。默认按错因选模式；
    引导 `hint_level` 1–3，完整讲解忽略层级。
  - **不硬拦看答案**：默认引导的错题直接请求 `full` 时返回内容，但 `soft_gate=true`
    并写事件；孩子先 `POST /api/explanations/attempts` 动手留痕后再看，`soft_gate=false`。
  - 质量/泄漏闸门：完整讲解 ≥2 步 + 非空 answer；引导丢弃 answer 字段并遮蔽标准答案
    与"答案是…"短语；`leak_flags` 只记代码，不回传讲解正文到审计。
  - 讲解端点无 GET；事件 payload 只含模式/层级/策略/prompt 版本/provider 等元数据，
    **不落题目、作答、标准答案或讲解正文**。
- 主要端点：
  - `POST /api/problem-bank/import` / `GET /api/problem-bank/items/{id}`
  - `POST /api/gradings` / `GET /api/gradings/{id}`
  - `POST /api/gradings/{id}/confirm` / `POST /api/gradings/{id}/appeal`（`base_version` 乐观锁）
  - `POST /api/explanations` / `POST /api/explanations/attempts`
  - `GET /api/mistakes` / `GET /api/mistakes/{id}` / `POST /api/mistakes/{id}/labels`

## 模型评测（真实模型，不进 CI）

```bash
# 过程题初判：4 道合成过程题 × 3 采样；只输出 JSON 合规/延迟/tokens/结论匹配
venv/Scripts/python scripts/eval_grading.py --prefer-dotenv

# 三段式讲解：4 个合成案例 × 引导 1/3 级 + 完整讲解；只输出结构/泄漏/步数/答案命中/延迟/tokens
venv/Scripts/python scripts/eval_explanation.py --prefer-dotenv
```

最近一次（2026-10-26，`explain_guide@1` + `explain_full@1`，
`doubao-seed-2-1-lite-260915`）：结构合规 12/12、引导零泄漏 8/8、
完整讲解 ≥2 步 4/4、答案命中 4/4、p50 33.0s、tokens in 10633 / out 27005。

过程题最近一次（2026-10-25，`grade@1`，同模型）：
JSON 合规 12/12、有效结论 4/4、p50 8.3s、tokens in 5616 / out 8590。
合成题只验证链路与提示词稳定性，不代表真实手写识别率。

## 第一张工单

**P1-0 Repo 骨架**（见 `../TICKETS.md`）——已完成：FastAPI + SQLite + `/health` + 冒烟测试 + CI。
**不要提前写业务逻辑**：`AGENTS.md` §2 明确 Phase 0 边界表未回填前禁止实现"错题自动入库"和"自动排复习"。

## 关键纪律（不要绕过）

- **Provider 抽象**：所有模型调用必须过 `app/providers/base.py::VisionProvider`；业务代码里**禁止直接 import 某家 SDK**。
- **Prompt 版本化**：prompt 文本**绝不写在代码里**，全部走 `../llm_prompts/*.md`，启动加载、语义变更递增 frontmatter `version`；每次调用记录 `prompt_version` 进 `model_runs`。
- **判分分工**：**运行时判卷** = `judge/normalize.py`（NFKC/多答案/有理数/坐标/单位）；**入库时核验** = `judge/verify_sandbox.py`（AST 白名单沙箱跑 `verify` Python 表达式）。**禁用 Python 内置 `eval()`**。
- **事件溯源**：`learning_events` 表 append-only，UNIQUE 防重复；掌握度 / 复习排期 / 毕业状态**一律由事实推导、可整体重算、不存易变字段**。
- **PII**：日志与 `model_runs` **不落题目全文、答案、文件 URL、密钥**；`evals/**/data/` 与 `Phase0-实测/` 全 gitignore。
