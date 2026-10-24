# Changelog

本项目所有值得注意的变更都记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Added

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
