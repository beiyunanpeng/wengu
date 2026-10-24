# Changelog

本项目所有值得注意的变更都记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

设计已定稿（内部代号 StudyDesk、对外名 wengu，v2.4），代码尚未开工。下一步按 `TICKETS.md` 顺序推进：
- **P0-1 已跑首轮**（9 题 × 5 档，边界表本轮未回填）→ 下一轮补样本 + OCR 切题预处理 + qwen3.5-ocr 车道 + 关 thinking 后再回填。
- **P1-0 Repo 骨架** 待开工。

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
