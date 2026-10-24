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
├─ scripts/                      # import_seed / export_openapi / run_evals
├─ tests/                        # unit / integration / e2e / memory
├─ requirements.txt
├─ .env.example                  # 密钥走 env；运行时可改参数走 config/app-config.json
└─ Dockerfile
```

## 快速开始

```bash
cd wengu-api
cp .env.example .env                # 填 API Key
make install-api                    # 从仓库根跑：建 venv + 装依赖
make dev-api                        # 从仓库根跑：http://localhost:8000/docs
```

## 第一张工单

**P1-0 Repo 骨架**（见 `../TICKETS.md`）——建 FastAPI + SQLite + `/health` + 冒烟测试 + CI 绿。
**不要提前写业务逻辑**：`AGENTS.md` §2 明确 Phase 0 边界表未回填前禁止实现"错题自动入库"和"自动排复习"。

## 关键纪律（不要绕过）

- **Provider 抽象**：所有模型调用必须过 `app/providers/base.py::VisionProvider`；业务代码里**禁止直接 import 某家 SDK**。
- **Prompt 版本化**：prompt 文本**绝不写在代码里**，全部走 `../llm_prompts/*.md`，启动加载、语义变更递增 frontmatter `version`；每次调用记录 `prompt_version` 进 `model_runs`。
- **判分分工**：**运行时判卷** = `judge/normalize.py`（NFKC/多答案/有理数/坐标/单位）；**入库时核验** = `judge/verify_sandbox.py`（AST 白名单沙箱跑 `verify` Python 表达式）。**禁用 Python 内置 `eval()`**。
- **事件溯源**：`learning_events` 表 append-only，UNIQUE 防重复；掌握度 / 复习排期 / 毕业状态**一律由事实推导、可整体重算、不存易变字段**。
- **PII**：日志与 `model_runs` **不落题目全文、答案、文件 URL、密钥**；`evals/**/data/` 与 `Phase0-实测/` 全 gitignore。
