# Changelog

本项目所有值得注意的变更都记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

下一步按 `TICKETS.md` 顺序推进：**P1-3 拍照上传链路**。

### Added

- **P1-2 Provider 适配层 + 成本护栏**（2026-10-24）：视觉/文本双供应商可插拔落地，零厂商 SDK。
  - 适配器：`providers/openai_vision.py` 共享 OpenAI-compat 实现（httpx 直连 chat/completions，
    请求体绝不进错误消息），`doubao.py`（方舟 `/api/v3`）与 `qwen_vl.py`（DashScope
    compatible-mode）薄子类；`text.py` OpenAITextProvider（DeepSeek 默认，GLM/Kimi 同构可扩）；
    `tencent.py` 显式占位（调用即抛未实现）。基座 `http.py`：usage/latency 解析、
    `extract_json_object` 宽松抢救（严格校验归 Schema 层，P1-4）、图片 data URL。
  - 契约升级（`providers/base.py`）：三任务方法改收 gateway 渲染好的 `prompt: str`、
    返回 `(结果, CallMeta)`——**代码不留 prompt 正文**，调用元数据（供应商/模型/token/延迟）
    可审计；新增 `TextProvider`。mock 同步升级并新增 `MockTextProvider`。
  - 路由注册表 `providers/registry.py`：`DEFAULT_ROUTING` 按 Phase 0 实测落点
    （提取/判分/讲解→doubao，字形默写→qwen_vl，文本→deepseek），
    `config/app-config.json` 的 `provider_routing` 热覆盖；缺密钥/模型名 fail-fast
    （`ProviderConfigError`，模型名绝不猜），性价比/旗舰双档按 `model_tier_default` 选模型。
  - 三级内容哈希缓存 `providers/cache.py`：L1 内存 → L2 `data/ai-cache/*.json`（原子写），
    key = sha256(task+供应商+模型+prompt 版本+输入摘要)；prompt 改版本即全量失效
    （回归可重放）；命中零模型调用、不计护栏。
  - 成本护栏 `services/model_audit.py`：`check_daily_guard` 双闸——当日真实调用次数
    （`WENGU_DAILY_CALL_LIMIT`，默认 200）+ 按 `model_prices` token 单价的成本估算
    （`WENGU_DAILY_CALL_BUDGET_CNY`）；每次真实调用落 `model_runs`（P1-1 表复用：
    prompt 版本/供应商/token 用量/状态，错误也留痕，**零题目全文/答案/URL**）。
  - 网关 `services/ai_gateway.py`：业务唯一入口，管线 = 路由→护栏→缓存→调用→审计
    （独立 session 提交，业务回滚不丢审计）；L3 原始响应落 `data/ai-raw/{date}/`。
  - 配置：`.env.example` 重写 Provider 段（`WENGU_DOUBAO_/WENGU_QWEN_/WENGU_DEEPSEEK_`
    value/flagship 分档）；`config/README.md` 补 `provider_routing`/`model_prices` 热配置说明。
  - 验证：64 tests 全绿（新增 http/适配器/缓存/审计/gateway 端到端共 28 个用例，
    MockTransport 零网络零密钥）；ruff 零告警；容器重建 healthy，`/api/seed/summary`
    数据完好，容器内路由冒烟通过。
  - **真实连通冒烟**（2026-10-24，`python -m scripts.smoke_providers [--prefer-dotenv]`）：
    四家全验——百炼 `qwen3.5-ocr`（244 ms）/`qwen3.8-max`（1539 ms）文本调用通过；
    方舟 `doubao-seed-2-1-lite/pro-260915` **带图视觉调用通过**（64×64 试色图均正确
    答"红色"）。沉淀的坑进 `.env.example` 注释：模型 ID 全小写大小写敏感（展示名
    ≠ API id）、百炼 OpenAI 兼容地址 `.../compatible-mode/v1`（非 `/api/v1`）、
    方舟模型需控制台"开通"后才可调用、seed-2.1 为推理模型（有 reasoning_tokens，
    延迟/成本偏高，P1-4 选型再测）；`turbo-260628` 可用但 Phase 0 实测更差更贵，默认不用。

- **P1-1b 知识点 seed 装载**（2026-10-24）：`cn-math-taxonomy` 初中部分入库。
  - 转换脚本 `wengu-api/scripts/import_seed.py`（`make seed-load`，开发者一次性跑）：
    过滤 grade 7–9（664 点 = 数学 315 + 英语 257 + 物理 92），12 核心字段直映 + 按前缀显式化
    subject，`unaudited: true` 全打、`blind_verified: true` 仅数学；先修边 1018 条仅留两端点
    均在装载集内的（跨学段 74 条丢弃并计数）；`_source.json` 内嵌署名（URL/CC BY-NC 4.0/NC 声明）。
  - seed 包 `seeds/data/{topics,dependencies,_source}.json` 随仓库分发（JSON = 唯一真源；
    SQLite 为幂等装载副本 + FK 锚点）；`seeds/local/`（化学/语文自建）与 `seeds/mappings/`
    （教材包对照，status: example|draft|reviewed）家长自建、不进 Git。
  - 运行时装载器 `app/seed/loader.py`：启动自动装载（幂等可重入、fail-fast 校验、
    先修边全量同步、内存索引邻接表供回溯诊断）；教材包机制照抄、数据不附带。
  - 迁移 `0003`：`knowledge_seed` 补 `domain` 列；`GET /api/seed/summary` 只读返回
    各学科点数 + `unaudited`/`blind_verified` 计数（透传路径，纯查询不触发模型）。
  - 容器实测：`topics_total 664 / edges 1018`，数学 315/315/315、物理 92/92/0、英语 257/257/0。
  - 数据范围口径：`.gitignore` 原注释"不分发"指**外部原始仓**（`cn-math-taxonomy-main/`，
    仍被忽略、永不入库）；本次按 AGENTS §2.6 让**转换后的初中 seed 包**随仓库分发，
    `seeds/README.md`、`THIRD-PARTY-NOTICES.md §1` 同步；并修复 `.gitignore` 的 `data/`
    通配误伤 `seeds/data/` 的问题。

- **P1-1 数据模型 + 事件溯源/幂等骨架**（2026-10-24）：迁移 `0002_p1_1_core_schema` 建 13 张表——
  `learning_events`（append-only 事实源，`idempotency_key UNIQUE`，触发器钉死禁 UPDATE/DELETE）、
  `attempts`、`mistake_versions`（只追加，`UNIQUE(mistake_id, version)`，建议值/确认值分离存储）、
  `knowledge_seed`、`concepts` + `concept_aliases`、`import_batches`（sha256 去重）+ `ingestion_drafts`、
  `review_schedules`（只存排期决策事实，不存掌握度/毕业）、`ai_jobs`（`idempotency_key` + `to_event_id` 水位）、
  `model_runs`（审计不落题目全文/PII）、`user_role`、`prerequisite_edges`（hard/soft）。
  确定性重算骨架 `services/recompute.py`（mastery / is_graduated 尾部连对≥3 / stats，纯函数可重放）；
  幂等写入骨架 `services/events.py`（`record_event` / `create_import_batch` / `append_mistake_version`，
  SAVEPOINT 消化冲突、同事务不污染）。
- **P1-0 Repo 骨架**（2026-10-24）：
  - FastAPI 应用工厂 + `/health`（含数据库连通检查，失败返回 503）。
  - 配置层：`wengu-api/.env` 读取 + `config/app-config.json` mtime 热加载（优先级高于 `.env`）。
  - SQLite：异步引擎（aiosqlite）+ WAL / `foreign_keys=ON` / `busy_timeout=5000`。
  - Alembic 迁移骨架 + 初始空基线 `0001_initial_empty`（upgrade/downgrade 已验证）。
  - `VisionProvider` 抽象 + 确定性 mock provider；`llm_prompts/*.md` 版本化加载器（frontmatter `id`+`version`，重复/缺失 fail-fast）。
  - 本地 PIN scrypt 哈希/校验工具（单用户，无 JWT/多租户）。
  - React 19 + Vite + TypeScript + Mantine + KaTeX 空壳，显示 `wengu · 温故`。
  - API/web Dockerfile + compose 健康检查与 `--wait` 支持；GitHub Actions（ruff + pytest + compose config + tsc + build）。
  - 测试：12 项（配置热加载、PIN、SQLite pragma/CRUD、health、迁移、mock provider、prompt loader）。

### Changed

- Makefile 支持 Windows `cmd.exe` 与 `PYTHON`/`PORT`/`M`/`D` 变量；`install-web` 改用 `npm ci`；新增 `downgrade`；`up` 使用 `--wait`。
- compose：`wengu-api/.env` 改为可选 `env_file`，默认无需密钥即可起；挂载 `config/`；健康检查不再依赖 curl。
- API Dockerfile 增加 `PIP_INDEX_URL` 构建参数（默认清华源，加速国内构建；`docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple` 可还原）。

### Verified

- `docker compose up -d --build --wait` 双服务 healthy（2026-10-24，Docker Desktop 29.9.2）：`wengu-api` 8100→8000 `/health` 200、`wengu-web` 5000→80 页面正常；容器内 Alembic 自动 `upgrade head`。
- GitHub Actions 首跑全绿（2026-10-24，run 40095188340）：api 32s / web 19s，ruff + pytest 12 + compose config + tsc + build 全过。
- 前置：Docker Engine 配置 registry mirrors `docker.m.daocloud.io` + `docker.1ms.run`；本机 8000/5173 被 Hyper-V 动态保留段占用，用 `WENGU_API_PORT` / `WENGU_WEB_PORT` 覆盖。

### Still blocked

- P0-1 边界表未回填：P1-0 不含任何自动入库/自动排复习逻辑（AGENTS §2 闸门）。

## [0.0.0] - 2026-10-24

### Added
- 项目仓库初始化。
- 顶层文档：`README.md`（中英）、`LICENSE`（MIT）、`THIRD-PARTY-NOTICES.md`（`cn-math-taxonomy` CC BY-NC 4.0 归属 + KuroTutor / wrong-notebook / MistakeNotebook 借鉴清单）、`AGENTS.md`（编码 agent 缰绳）、`TICKETS.md`（分 Phase 工单 P0-1 ~ P5-5）、`目录结构.md`。
- 设计文档：`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`（v2.4，唯一事实来源）。
- 方法论：`docs/methodology/phase0.md`、`docs/methodology/evals.md`。
- 骨架目录：`wengu-api/`、`wengu-web/`、`evals/`、`llm_prompts/`、`seeds/`、`docs/{requirements,design,specs,manuals}/`。
- 工程配置：`pyproject.toml`、`Makefile`、`docker-compose.yml`、`.gitignore`。

### Design decisions locked（v1 → v2.4 演化摘要）

- **产品定性**：家用、自托管 Web+PWA、开源分发 = 每家长自托管单实例；不做 Hosting 多租户 / 公网账号体系 / 商业化。
- **技术栈**：Python + FastAPI + async；SQLite + WAL + Alembic；React + Vite + TS + Mantine + KaTeX + PWA；Docker Compose；Tailscale。
- **AI 工程纪律**：`learning_events` 事件溯源 + 幂等 + 确定性重算；prompt 版本化真源；`model_runs` 审计不落 PII；建议值/确认值分离；【依赖图形】题不判分；提示注入防御；三档核验模式。
- **判分架构**：**模型只提、代码才判**（客观题）；AST 白名单沙箱跑 `verify`（入库时）；`judgeAnswer` 规范化（运行时）。
- **知识点**：粗粒度预置 seed（来自 `cn-math-taxonomy`）+ 细粒度受控生长 + alias 归并 + 人工确认。
- **复习调度**：固定间隔阶梯 + 掌握度自适应因子 `× (1 + mastery × 4)` + 抗挫败三规则；FSRS 留接口。
- **变式题**：只检索真题组卷，**绝不 LLM 编题**；作答记 `practice_records` 派生表，不进错题本。
- **信奥**：判题在外部洛谷 / 一本通，**不建判题 infra**；只承接"卡壳→引导→待重做清单"。
- **家长看板**：观察复盘型，非遥控监控；两角色 + 本地 PIN；提醒只做"打开弹窗" + 家长低频周报。
- **外部对照**：KuroTutor / wrong-notebook 独立实证支持三条硬约束（禁 agent 框架 / 变式绝不进本 / 只检索真题），并吸收 7 处实现细节借鉴。
- **Phase 0 实测结论**（2026-10-21 首轮）：15 个 题型×供应商 组合全落"低置信/讲解"（题目识别 0.0–0.5 是主要瓶颈）→ 边界表本轮未回填 → Phase 1 全量按"待确认"保守起步。

### External validation
两条独立路线（本项目 16 轮"拷问式"设计盘问 vs. 用户自研 `LearnDesk-原始方案/`"调研+逐步砍"路径）+ 已实现同类开源项目（KuroTutor / wrong-notebook / MistakeNotebook）——**三方独立收敛到同一份"已砍清单"**（判题 infra / AI 编题 / 口语 ASR / 时间块日程 / 实时监控 / 多租户账号 / 云 GPU / 微服务 / Redis / K8s / 向量库 / 积分徽章 / agent 编排框架），视为方向被强验证。

[Unreleased]: https://github.com/<你>/wengu/compare/v0.0.0...HEAD
[0.0.0]: https://github.com/<你>/wengu/releases/tag/v0.0.0
