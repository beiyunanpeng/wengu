# STATUS.md — 开发计划与完成情况

> 快照日期：2026-10-27
> 分支 / HEAD：`main` / `5f037c4`（P1-2b + P1-2c 交付提交）
> 工作区：干净
> CI：run `40484394010`（`5f037c4`）api / web 全绿
> 全量测试：**343 passed**（本机 2026-10-27，68.30s）

本文件是**状态快照**，不替代以下事实源；冲突时以它们为准：

- 计划与验收标准：[`TICKETS.md`](../TICKETS.md)
- 逐项交付记录与实测证据：[`CHANGELOG.md`](../CHANGELOG.md)
- 设计与硬约束：[`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`](./specs/architecture/StudyDesk-设计说明文档-v2.md)、[`AGENTS.md`](../AGENTS.md)
- 代码与提交：`git log`

---

## 1. 结论摘要

- **Phase 1 核心闭环的"识别 → 批改 → 入本 → 标签 → 讲解 → 复习排期 → 最小 UI"已完成**，共 14/16 张工单交付。
- **供应商互备已落地（P1-2b）**：routing 改为有序 provider 列表，gateway 逐家尝试（每家 1 次），按错误分类决定是否转移；`model_runs` 记录完整尝试链；全部失败聚合报错。豆包欠费/错 key 时提取自动走 Qwen-VL。
- **VLM 与 OCR 已按 task 分工（P1-2c）**：独立 `task_models` 配置（`.env` / `app-config.json`）；提取/批改/讲解默认走 Qwen VLM（flagship），默写提取默认走 OCR（value）；显式模型缺失 fail-fast，不静默退回。
- **复习排期已落库（用户触发）**：P1-7a 完成——确认/申诉 `wrong` 建错题时自动建首次排期，复习完成排下一次，满足条件毕业；状态全部由事件重放推导。P1-7b（前置回溯诊断）未开工；P1-7c（自动排复习）仍被 Phase 0 边界表闸门阻塞。
- **P1-9 最小 Web UI 已完成**：采集 / 批改回显确认 / 错题本（含详情）/ 复习 / 讲解五页可用；孩子可独立走通"拍 → 确认 → 入本 → 复习 → 卡住看讲解"。确认答错时强制选分类，兼作复习阶梯的学科来源。
- **Phase 0 边界表未回填**：所有新批改单仍落 `pending`，错题必须经孩子/家长确认 `wrong` 才入本；任何"模型判错即建错题/即排复习"的逻辑都未实现。
- **P0-2 黄金评测集未开始**：`evals/` 只有目录骨架；现有评测是各提示词的合成样本脚本，不是 CI 可调用的 ≥30 条黄金集。
- **下一步建议先做 P0-1 样本扩容 + P0-2 黄金集**：这是解锁 P1-7c 与提升真实可信度的长期主线；P1-7b 在前两者之后。详见 §11。

## 2. 总体路线图状态

| 阶段 | 目标 | 状态 | 说明 |
|---|---|---|---|
| Phase 0 | 摸底 + 回归基线 | 部分完成 | P0-1 首轮已跑但边界表未回填；P0-2 未开始 |
| Phase 1 | 核心闭环 | 进行中（14/16） | P1-0～P1-6、P1-2b/2c、P1-7a、P1-8、P1-9 完成；P1-7b/7c 未完成 |
| Phase 2 | 每日任务 + 家长看板 | 未开始 | 日队列、番茄钟、课表、两角色、看板、打卡、PDF 导出 |
| Phase 3 | 内容与扩展 | 未开始 | 真题库流水线、组卷、英语背诵、听力默写、语文、信奥、长期计划 |
| Phase 4 | 基础设施演进 | 未开始 | Tailscale、可移植部署、可选本地 GPU |
| Phase 5 | 开源分发与打包 | 未启动（部分基线已有） | 已有 LICENSE / README / CHANGELOG / `.env.example` / 第三方署名；首次运行向导、备份恢复、鉴权开关、教材包安装器未做 |

## 3. Phase 0 状态

| 工单 | 状态 | 已完成 | 缺口 / 下一步 |
|---|---|---|---|
| P0-1 手写识别 + 分题型判分实测 → 《自动入库边界表》 | 进行中，闸门未解锁 | 首轮 9 题 × 5 档 = 45 次调用；15 个题型×供应商组合全落"低置信/讲解"；方法论与结论已写入 `docs/methodology/phase0.md` | 补 ≥5 道"孩子做错"样本测漏判；每题型 ≥20 样本；识别链路优化（`qwen3.5-ocr` 车道、豆包 `thinking.type=disabled`）；复核其余 8 题真值 |
| P0-2 evals 黄金集脚手架 + 首日填充 | 未开始 | `evals/{import,analysis,generation,regressions}/` 目录骨架与 README | ≥30 条脱敏黄金样本；代码判定阈值；一键回归脚本；CI 可调用 |

**闸门影响**：边界表回填前，P1-5 全题型初始结论一律落 `pending`（待确认）；P1-7c 不实现。用户确认/申诉后 `grading_results.status` 才转 `confirmed` / `appealed`，错题只由确认/申诉 `wrong` 产生。

## 4. Phase 1 工单完成情况

| 工单 | 状态 | 完成日期 | 提交 | 交付摘要 |
|---|---|---|---|---|
| P1-0 Repo 骨架 | 已完成 | 2026-10-24 | `ce496e0` | FastAPI + `/health` + SQLite WAL + Alembic + React 空壳 + Docker Compose + CI |
| P1-1 数据模型 + 事件溯源/幂等 | 已完成 | 2026-10-24 | `45d4e3b` | 13 张核心表；`learning_events` 只追加；确定性重算；幂等写入骨架 |
| P1-1b 知识点 seed 装载 | 已完成 | 2026-10-24 | `25c9370` | 664 个初中知识点 + 1018 条先修边；`unaudited` / `blind_verified` 透传；教材包机制 |
| P1-2 Provider 适配层 + 成本护栏 | 已完成 | 2026-10-24 | `fb8c3ec` | 豆包 / Qwen / DeepSeek / 腾讯（占位）/ mock；按题型路由；三级缓存；每日上限；`model_runs` 审计 |
| P1-2b 供应商自动故障转移 | 已完成 | 2026-10-27 | `5e9e38f` | 有序 provider 列表；每家 1 次；错误分类决定转移；全失败聚合；`model_runs` 尝试链（`0010`）；API 只增不改 |
| P1-2c 按 task 配模型 | 已完成 | 2026-10-27 | `5e9e38f` | 独立 `task_models`（`.env` / app-config）；Qwen VLM(flagship) 与 OCR(value) 分档；显式缺失 fail-fast；缓存按 `(provider, model)` |
| P1-3 采集双通道 | 已完成 | 2026-10-24 | `9f9ae93` | 拍照上传（sha256 去重）+ 豆包 JSON 导入（批次去重 + 草稿）；全程零模型调用 |
| P1-3b OCR 行聚类切题 | 已完成 | 2026-10-25 | `9f9ae93` | 本地 OCR + 题号锚点 + 垂直间隙 + 双栏检测；无锚点拒绝切分；裁图落盘 |
| P1-4 结构化提取 + 质量闸门 | 已完成 | 2026-10-25 | `7853f78` | VLM 提取题目/作答/完整性；确定性闸门拦残题/占位/空作答；整页兜底恒人工 |
| P1-5 批改分级闸 | 已完成 | 2026-10-25 | `dbee72c` | 客观题零模型规范化判分；过程题保守初判 + 多次采样；开放题转讲解；确认/申诉乐观锁 |
| P1-6 保守入本 + 两级标签 + 派生表 | 已完成 | 2026-10-25 | `dbee72c` | 唯一写入路径；category + concept 受控生长；部分更新 + 归并；`practice_records` 隔离 |
| P1-7a 复习排期服务（用户触发） | 已完成 | 2026-10-26 | `5121d1b` | `0009` 幂等索引；`services/review.py` 首排期/完成/到期队列；`api/reviews.py`；状态从事件重放；毕业生效 |
| P1-7b 前置知识回溯诊断 | 未开始 | — | — | P1-7a 已完成；`prerequisite_edges` 已装载 |
| P1-7c 自动排复习 | 阻塞 | — | — | 仅对边界表"高置信自动"题型开放；边界表未回填 |
| P1-8 三段式讲解引擎 | 已完成 | 2026-10-26 | `a9a84db` | 定位 → 引导/讲解 → 巩固；按错因预选；引导 1–3 级；软闸门留痕；答疑复用 |
| P1-9 最小 Web UI | 已完成 | 2026-10-26 | `5121d1b` | 五页最小闭环；拍照→确认→入本→复习→讲解；确认/申诉可选 `category_id`；Vite/nginx 同源代理 |

> 注：P1-5 与 P1-6 合并在同一提交交付；`0eb0199` 为 Phase 0 闸门语义、P1-7 拆分、mastery=min-concept 口径与防答案泄漏护栏的文档/注释修订，不改运行逻辑；P1-7a 与 P1-9 合并交付于 `5121d1b`；P1-2b 与 P1-2c 相互依赖（按 task 选模型复用故障转移循环），合并交付于 `5e9e38f`。

## 5. 已完成能力（当前系统实际能做什么）

### 5.1 采集与预处理

- 手机拍照上传：JPEG / PNG / WebP 白名单、magic bytes 校验、20MB 上限、流式写盘、sha256 幂等去重。
- 豆包 JSON 兜底导入：封套校验、逐项归一、批次 sha256 去重、坏项逐条报告、草稿打标。
- 本地 OCR 切题：RapidOCR 行检测 → 题号锚点 + 行距聚类 → 双栏检测 → 裁单题子图；零锚点拒绝瞎切。
- 全程采集/切题不调用 VLM；切片端点显式触发，符合 Phase 0 闸门。

### 5.2 提取与批改

- VLM 结构化提取：题目、孩子作答、完整性、置信度；识别不清用 `〔?〕`，不猜。
- 提取质量前置闸门：题目空/残缺/占位/作答空/整页未切题 → 人工复核；图形依赖题 → 只回显不判分。
- 客观题判分：**模型只提、代码才判**；NFKC、多答案拆分、分数/百分比/坐标/单位/大小写归一。
- 过程题：`grade.md` 保守初判，1–3 次采样；不一致或模型不确定 → `uncertain`，默认待确认。
- 开放题：不建批改单，直接返回讲解路由。
- 题库入库：`verify` 在 AST 白名单沙箱求值，mismatch 拒绝；不用 Python 内置 `eval()`。
- 所有结论默认 `pending`；确认/申诉只追加版本，旧版本 409；改判不重复计掌握度。

### 5.3 错题与标签

- 错题唯一写入路径：只有确认/申诉 `wrong` 才建或复活；`correct` 只作废不删历史。
- 两级标签：粗粒度 `category` 挂 `knowledge_seed`；细粒度 `concept` 受控生长、优先复用、别名归一、人工归并。
- 标签建议值与确认值分离；部分更新保留未提交字段；错因固定 7 项。
- `practice_records` 派生表：变式/加练不进错题、不排复习、不影响掌握度，可整表清空。
- 错题检索支持 status / category / concept / error_cause + 分页；所有 GET 零模型调用。

### 5.4 讲解（P1-8）

- 一个引擎同时服务错题订正与拍照答疑；入口 `mistake` / `problem_extraction` / `ingestion_draft`。
- 默认模式按已确认错因预选：前置缺失/概念不清 → 完整讲解；方法不会/计算/审题/表达 → 引导；记忆科 → 语境复述；答疑默认完整讲解。
- 引导 1–3 级，只推进一步；`answer` 恒为 `null`。
- "看完整讲解"不硬拦：未动手时仍返回，但事件记 `soft_gate=true`；动手留痕后 `soft_gate=false`。
- 质量/泄漏闸门：拒占位、控制字符、HTML；完整讲解 ≥2 步且答案非空；引导丢弃 answer 并遮蔽标准答案与"答案是…"短语，返回 `leak_flags`。
- 只写 `learning_events`（`explanation_attempted` / `explanation_shown`），payload 仅元数据，不含题目/作答/标准答案/讲解正文。

### 5.5 复习排期（P1-7a，用户触发）

- 触发点唯一：确认/申诉 `wrong` 新建错题时排首次复习；复活已有错题不动既有排期，不自动开新周期。
- 首次排期 = 第 0 档 + `times_wrong=1`，间隔 = 基础档 ×（1 + mastery×4），最少 1 天；不把首次答错重复计一次。
- 完成后调用 `review_policy.decide()`：答对前进并减 `times_wrong`，答错不倒退只折半；`times_wrong=0` 且尾部连对 ≥3 毕业，毕业不生成新排期。
- 当前状态一律从 `learning_events` 重放（`review_scheduled` + `kind="review"` 的 `attempt_correct`/`attempt_wrong`）推导，表里不存 mastery/毕业；完成时校验排期 rung 与重放一致。
- 幂等：首排期键 `review:schedule:{mistake_id}:init`，完成键 `review:attempt:{schedule_id}`；`source_event_id` 唯一 + 每题仅一条未完成排期的部分唯一索引。
- 到期队列：active 错题 + 最新版 + 未完成 + `due_date <= today`；GET 零模型调用。
- 掌握度 = 该错题所有已确认 concept 的最小值；无 concept = 0.0。**当前事实普遍无 `concept_id`，mastery 实际恒 0.0**。
- 学科决定阶梯（数学/物理/化学 1/10/30；语文/英语/历史/道法/生物/地理 1/3/7/14/30）；学科缺失或未配置 → 422 并整体回滚确认，不落回默认阶梯。

### 5.6 最小 Web UI（P1-9）

- 五页闭环：采集（拍照/上传/切题/提取/直接提交批改）、批改回显（确认/申诉/分类）、错题本 + 详情（筛选/标签/错因）、复习（到期队列/答对答错/下一次到期）、讲解（auto/guide/full、提示 1–3 级、软闸门）。
- 数学统一 KaTeX 渲染；同源 `/api`：Vite dev 走 `WENGU_API_PROXY` 代理，容器内由 nginx 反代 `/api` 与 `/health`。
- 长任务加载态与重试：前端超时上传 60s、切题 120s、提取 300s、批改/讲解 180s；提取失败可单点重试；讲解重试复用同一 `request_id`。
- 确认/申诉答错时必须选择 seed 分类并作为 `category_id` 传入；分类不存在或学科无法确定 → 422 整体回滚。已有错题不覆盖确认标签。
- 纯查询 GET 零模型调用；软闸门未解除时前端不展示答案（API 仍保留"不硬拦"契约，页面记录动手后才展示）。

### 5.7 基础设施

- `learning_events` 只追加 + UNIQUE 幂等键 + UPDATE/DELETE 触发器。
- 掌握度/毕业/统计由事实确定性重算；同源改判只取最高版本。
- 提示词以 `llm_prompts/*.md` 为唯一真源，代码零 prompt 正文；当前 5 个 prompt 均 v1。
- 供应商按题型路由可配置，并支持有序列表故障转移（每家 1 次）与按 task 覆盖模型（VLM/OCR/文本）；密钥只走环境变量；日志/审计不落题目全文、答案、URL、PII。
- SQLite WAL + Alembic 迁移；迁移含备份/回退说明与迁移测试。

## 6. API 与数据现状

### 6.1 API 面

| 域 | 端点 |
|---|---|
| 健康 / seed | `GET /health`、`GET /api/seed/summary`、`GET /api/seed/topics` |
| 采集 | `POST /api/captures`、`GET /api/captures`、`GET /api/captures/{id}` |
| 切题 | `POST /api/captures/{id}/slice`、`GET /api/captures/{id}/items` |
| 提取 | `POST /api/captures/{id}/extract`、`GET /api/captures/{id}/extractions` |
| 导入 | `POST /api/imports`、`GET /api/imports/{id}`、`GET /api/imports/{id}/drafts` |
| 题库 | `POST /api/problem-bank/import`、`GET /api/problem-bank/items/{id}` |
| 批改 | `POST /api/gradings`、`GET /api/gradings/{id}`、`POST /api/gradings/{id}/confirm`、`POST /api/gradings/{id}/appeal`（确认/申诉可选 `category_id`） |
| 错题 / 标签 | `GET /api/mistakes`、`GET /api/mistakes/{id}`、`GET /api/mistakes/options`、`POST /api/mistakes/{id}/labels` |
| 概念 | `GET /api/concepts`、`POST /api/concepts`、`POST /api/concepts/merge` |
| 练习派生表 | `POST /api/practice-records`、`GET /api/practice-records`、`DELETE /api/practice-records` |
| 复习 | `GET /api/reviews/due`、`POST /api/reviews/{mistake_id}/complete` |
| 讲解 | `POST /api/explanations`、`POST /api/explanations/attempts` |

约束：

- 所有 GET 均为纯查询，零模型调用。
- 模型调用只发生在结构化提取、过程题初判、讲解；采集、导入、切题、标签、练习、复习等 POST 均零模型调用。
- 讲解无 GET，避免纯查询页触发模型；attempts 仅错题入口，拍照答疑返回 422 `attempt_not_required`。

### 6.2 数据库与文件

- Alembic head：`0009_review_schedules`（`0009` 只补 `review_schedules` 幂等索引，表结构 0002 已建）。
- 21 张业务表：事件/错题/复习/审计/seed/采集/提取/批改/练习等。
- `review_schedules` 已由用户确认 `wrong` 的建题路径写入首次排期；`source_event_id` 唯一 + 每题仅一条未完成排期。
- `attempts` 记录复习完成（`kind="review"`、`answer_text=NULL`），不存复习作答。
- seed：664 个知识点（数学 315 / 英语 257 / 物理 92）+ 1018 条先修边；全部 `unaudited`，仅初中数学 `blind_verified`。化学、语文为空格起步。
- 提示词：`extract_problem@1`、`transcribe_image@1`、`grade@1`、`explain_guide@1`、`explain_full@1`。

### 6.3 前端（P1-9）

- 路由：`/capture[/:captureId]`、`/grading/:gradingId`、`/mistakes[/:mistakeId]`、`/review`、`/explain`；未知路径回落采集页。
- 依赖：React 19.1.10 / Vite 7.3.7 / TypeScript 5.9.3 / Mantine 8.3.18 / KaTeX 0.16.47 / `react-router-dom` 7.18.4（精确锁版本）。
- 构建：`tsc`（strict，`noUnusedLocals`/`noUnusedParameters`）+ `vite build` 通过；容器由 nginx 托管并反代 API。

## 7. 验证与质量基线

### 7.1 工程门禁

- 全量测试 **323 passed**（2026-10-26，本机，61.07s）。
- `ruff check .` 全仓通过；前端 `tsc + build` 通过；CI 同时跑 pytest、compose config、前端构建。
- 迁移测试覆盖 up/down、append-only 触发器与 `0009` 幂等索引（含 downgrade 0008 后重建）。
- 最新 CI：`5121d1b` run `40278484172`，api / web 均 success。

### 7.2 真实模型评测（不进 CI）

| 能力 | 评测时间 / 版本 | 结果 |
|---|---|---|
| 结构化提取 | 2026-10-25，`extract_problem@1` | 豆包 lite 非探索题 **9/9**、解析 10/10、题目相似度 0.980、作答 1.000、p50 16.9s；Qwen `qwen3.8-max` **9/9**、p50 4.6s；`qwen3.5-ocr` **1/9**（不用于该任务） |
| 过程题初判 | 2026-10-25，`grade@1` | JSON 合规 **12/12**、有效结论 **4/4**、p50 8.3s、tokens in 5616 / out 8590 |
| 三段式讲解 | 2026-10-26，`explain_guide@1` + `explain_full@1` | 结构合规 **12/12**、引导零泄漏 **8/8**、完整讲解 ≥2 步 **4/4**、答案命中 **4/4**、p50 33.0s、tokens in 10633 / out 27005 |
| 切题对比 | 2026-10-25，`transcribe_image@1` | 清晰图 Δ +0.020；劣化图 **Δ +0.057**（整页 0.870 → 切题 0.927）；单题裁图 p50 3.1s vs 整页 15.4s；输入 token ≈10× |

评测均为**合成样本**，用于验证链路、提示词稳定性与闸门有效性，不代表真实手写学情。

### 7.3 容器实跑

每个已完成工单均有容器验收记录，覆盖：

- 迁移在既有卷上升级；Alembic 自动到 head。
- 拍照上传/重复去重；JSON 导入/坏项报告/重复批次。
- 双页切题 10 items、force 重切无孤儿文件、无锚点 422。
- 提取幂等/force 级联/整页兜底；模型审计无题目全文。
- 题库 verify 接受/拒绝；客观题确认/申诉；过程题采样不一致落待确认。
- 错题确认/标签部分更新/归并/检索/派生表清空；容器重启后数据一致。
- P1-8：导入 → 判错 → 确认入本 → 引导（answer=null、无泄漏）→ 记录动手 → 完整讲解（3 步、软闸门关闭）→ 3 条元数据事件；`alembic 0008` 不变。
- P1-7a：既有卷升至 `0009`，两个唯一索引就位；导入 → 判错 → 确认 → 错题 3、首排期 id 1（rung 0、1 天、due 2026-10-27）→ 按时完成 → 下一次排期 id 2（rung 1、10 天、due 2026-11-06）→ 重复完成返回同一 attempt/排期、无重复事件 → 到期队列清空；复习事件 payload 无题目/答案，`attempts.answer_text` 为 NULL。
- P1-9：重建 api/web 容器均 healthy；nginx `/api` 反代与 SPA fallback 生效；2MB 图片经 nginx 上传 201（无 413）；seed 664 节点加载正常。浏览器真实豆包 E2E 覆盖拍照 → 切题/提取 → 确认（选分类）→ 入本 + 首排期 → 复习完成 → 引导/完整讲解软闸门 → 错题列表/详情/概念/错因，全部走通。
- P1-2b/P1-2c：全量 **343 passed**、`ruff check .` 全绿；真实实跑（豆包密钥无效）→ `extract_problem` 自动转 `qwen_vl/qwen3.8-max` 并返回非空 `problem_text`，尝试链 attempt 0 doubao=account / attempt 1 qwen=ok；`dictation_extract` 解析为 `qwen3.5-ocr`。

## 8. 未完成、阻塞与缺口

| 项 | 状态 | 影响 | 解锁条件 / 下一步 |
|---|---|---|---|
| P0-1 边界表 | 进行中，闸门未解锁 | 全题型待确认；P1-7c 不能做 | 补错题样本、扩样本、优化识别链路、复核真值 |
| P0-2 黄金评测集 | 未开始 | prompt/供应商/模型变更无 CI 级回归门 | ≥30 条脱敏样本 + 代码阈值 + CI 调用 |
| 复习掌握度归因 | 缺口 | 现有事件无 `concept_id`，实际 mastery 恒 0.0，间隔只取基础档 | 后续工单把已确认 concept 归因写入事实，重算即自动生效 |
| 学科缺失 / 未配置 | 部分缓解 | API 未传 `category_id` 且题库无学科时仍 422 **整体回滚**；UI 确认答错已强制选 seed 分类 | API 侧补分类或题库挂载；P1-9 已覆盖主路径 |
| 毕业 / 复活复习周期 | 缺口 | 已毕业错题再次复活不会自动开启新复习周期 | 后续工单按产品口径决定是否重排首次复习 |
| P1-7b 前置回溯诊断 | 未开始 | 无法定位根因先修 | P1-7a 已完成；`prerequisite_edges` 就绪 |
| P1-7c 自动排复习 | 阻塞 | 无自动入库/自动排复习 | 边界表回填后按题型逐步开启 |
| P1-9b 前端错误呈现 | 未做 | 账户/额度类失败在 UI 仍显示笼统"提取失败"，用户易误判为识别能力差 | 复用 P1-2b 的 `kind/attempts`，按错误分类给文案与处置提示 |
| 默写提取入口 | 未接线 | `dictation_extract` 的 OCR 模型只在配置/工厂层验证，尚无 gateway/API 入口 | 默写功能落地时接 gateway 方法，复用 `task_models` |
| 豆包 JSON 导入 UI | 未做 | 导入通道只能走 API；主通道拍照已可用 | 按需补导入页，不阻塞闭环 |
| Phase 2–5 | 未开始 | 日队列、看板、导出、分发向导等缺失 | P0-1/P0-2 与 P1-7b 之后按 TICKETS 顺序 |
| 鉴权 / 本地 PIN 中间件 | 未做 | 仅适合本机/可信内网，不能公网暴露 | P5-3 可选 session 鉴权 + README 警告 |
| AI 错因预填 | 未做 | 标签候选仅字面匹配，可能漏配/误配 | 后续文本模型任务接入，仍需人工确认 |
| 化学 / 语文 seed | 未做 | 两科从空 seed 起步 | 家长按教材目录建章级粗粒度 seed |
| 真实手写复验 | 未做 | 真实拍照识别率未知 | 家长实拍样本跑 `eval_extraction` / `eval_slicing` |

## 9. 残留风险与技术债

1. **Phase 0 闸门是最大不确定性**：题目识别真实准确率未达标，边界表无法回填；当前"完成"仅指保守链路可用，不等于自动批改可信。
2. **延迟**：提取 p50 16.9s、讲解 p50 33.0s；10 题串行提取约 3 分钟。无流式输出，P1-9 已做分阶段加载态、等待秒数与重试，但长任务仍只能等待。
3. **上游抖动**：评测/容器实测出现过瞬时 `ConnectError` → 502；无自动重试，但幂等键保证客户端重试不产生重复事件；P1-9 讲解页提供手动重试。
4. **答案泄漏闸门是短语级**：单字符答案若未出现在"答案是…"句式中，可能漏过遮蔽；靠提示词约束 + 人工抽查。
5. **合成样本局限**：提取/切题/讲解评测均为合成题或印刷体，不能代表真实手写、真实作业分布。
6. **OCR 切题收益有代价**：清晰图提升有限（+0.020），劣化图提升明显（+0.057），但输入 token ≈10×；尚未用真实作业照片复验。
7. **标签候选仅字面匹配**：可能漏配/误配，且没有 AI 错因生成；全靠孩子/家长确认兜底。
8. **过程题采样不稳定**：真实模型 2 次采样即出现 `correct` / `uncertain` 分歧；因此保持默认待确认，是正确的保守行为。
9. **复习排期只完成用户触发部分**：首排/到期/完成/毕业已可用，但 mastery 实际恒 0.0（事实无 `concept_id`）、无自动补排、毕业复活不重开周期；P1-7c 仍被闸门阻塞。
10. **学科缺失会卡住确认**：API 未传 `category_id` 且题目未挂题库时，确认 422 整体回滚；这是有意的 fail-fast（不猜阶梯）。P1-9 的 UI 已强制选分类，主路径不再踩坑。
11. **Docker Desktop + SQLite WAL 运维坑**：容器运行期间从宿主机读写挂载库会破坏 WAL/SHM；查库走 `docker exec`，备份前先停 API。
12. **无鉴权 / 无本地 PIN**：已有最小 UI，但仍只适合本机/可信内网；公网暴露前必须先做鉴权与隔离或走 Tailscale。
13. **P1-9 UI 边界**：豆包 JSON 导入无 UI；切片序号 0-based 会出现"第 0 题"文案（整页提取为 1-based，历史遗留）；浏览器 E2E 为手工实跑，尚无自动化前端测试。
14. **故障转移不覆盖质量类**：模型返回但内容不合格时**不切备用**（避免白烧钱），这是设计选择；质量基线需 P0-2 黄金集量化后再评估。真实验证用 401 无效密钥复现账户类路径，未实跑 403 原文。
15. **模型选型样本小**：`qwen3.5-ocr` 提取 1/9、`qwen3.8-max` 9/9 来自单轮小样本；已用 `task_models` 把默认分档固化，但仍需扩样复测后再决定是否调整默认档。

## 10. 工程不变量（已落地，后续不得回退）

- `learning_events` 只追加，UNIQUE 幂等键，UPDATE/DELETE 触发器守卫。
- 客观题**模型只提、代码才判**；运行时不用 `eval()`，入库核验走 AST 白名单沙箱。
- AI 建议值与用户确认值分离；确认值优先，冲突不静默覆盖。
- 提示词以 `llm_prompts/*.md` 为唯一真源；改语义必须递增版本；代码不留 prompt 正文。
- 日志/审计/事件不落题目全文、答案、文件 URL、个人信息、密钥。
- 纯查询 GET 零模型调用。
- 变式/加练只进 `practice_records`，绝不进错题本、不排复习。
- 不引入通用 agent 编排框架、Redis、外部 MQ、向量库、K8s；不默认 Postgres。
- Phase 0 闸门：未经用户确认的自动入库/自动排复习不实现。

## 11. 下一步建议（按依赖与风险排序）

1. **P0-1 样本扩容 + P0-2 黄金评测集**（建议下一张）
   - 这是解锁 P1-7c 与提升真实可信度的长期主线，也是当前最大不确定性。
   - 至少先补"孩子做错"样本，验证漏判错率；再把现有合成评测迁入 `evals/` 统一跑分，
     接上 CI 可调用的回归门。
2. **P1-7b 前置回溯诊断**：依赖 P1-7a 已完成；固定种子 `replay(answers)` 必须可重建。
3. **复习掌握度归因**：把已确认 concept 写入事实（或等价归因），让 mastery 不再恒 0.0；
   这是间隔自适应的前提。
4. **P1-9b 前端错误呈现**（小步穿插）：后端已返回 `kind/attempts`，前端按分类给
   "账户异常 / 暂不可用 / 重拍人工" 的文案与处置，避免把账单问题误读成识别能力问题。
5. **Phase 2**：日队列 / 番茄钟 / 课表 / 两角色 / 家长看板 / 打卡 / PDF 导出。
6. **P1-9 后续增强（按需）**：豆包 JSON 导入 UI、浏览器端自动化测试、鉴权/本地 PIN
   分别并入对应工单（P2-4/P5-3），不单独占用 Phase 1。

> 说明：P1-7c 自动排复习仍被 Phase 0 边界表闸门阻塞，不得提前实现。

## 12. 后续阶段工单清单（均未开始）

> 这里只列目标，验收标准、依赖与禁止事项以 [`TICKETS.md`](../TICKETS.md) 为准。

### Phase 2 — 每日任务 + 收口看板

| 工单 | 目标 |
|---|---|
| P2-1 | 日队列自动生成：到期复习 + 固定背诵铺底、作业按 deadline 插入、硬事件抬权重 |
| P2-2 | 番茄钟执行：对下一项计时，完成打点写 `learning_events` |
| P2-3 | 课表/日历约束层：录入后喂 P2-1，不作为任务源主体 |
| P2-4 | 两角色 + 本地 PIN：孩子默认视图，家长 PIN 解锁；不做公网账号体系 |
| P2-5 | 家长看板（观察复盘型）：接 `learning_events` 与指标，孩子见同一份 |
| P2-6 | 极简打卡：streak + 掌握度曲线，从事实重算；不做积分/徽章 |
| P2-7 | 错题 PDF 四区块导出（原题 + 作答 + 解析 + 批注），按知识点/章节组卷 |

### Phase 3 — 内容与扩展（按 ROI）

| 工单 | 目标 |
|---|---|
| P3-1 | 真题库录入流水线：AI 帮录 → `problem_bank` → 家长审核队列 |
| P3-2 | 组卷/加练：按 category/错因/难度检索真题组卷；禁止 LLM 凭空编题 |
| P3-3 | 英语背诵：自评间隔重复（档③） |
| P3-4 | 听力 + 默写：默写复用批改；听力用教材音频 + TTS；不做口语 ASR |
| P3-5 | 语文客观题并入（字音/病句/默写）；作文/阅读理解只讲解不入本 |
| P3-6 | 信奥独立流：卡壳 → 引导 → 待重做清单；外部判题，不建判题 infra |
| P3-7 | 长期计划：覆盖型（图谱 + 掌握度）+ 积累型（streak），家长与 AI 共创 |

### Phase 4 — 基础设施演进（孩子真在用之后）

| 工单 | 目标 |
|---|---|
| P4-1 | Tailscale / CF Tunnel 稳定化，手机外网可用 |
| P4-2 | 可移植部署：镜像原样上云，SQLite 文件 + 挂载卷；Postgres 仅可选 |
| P4-3 | 可选本地 GPU 模型层：同一 Provider 接入 Qwen-VL / MiniCPM / PaddleOCR |

### Phase 5 — 开源分发与打包

| 工单 | 状态 | 目标 |
|---|---|---|
| P5-1 | 未开始 | 首次运行向导：孩子/年级 → 学科 → 教材 seed → API Key → 档位；热配置 |
| P5-2 | 未开始 | 一键备份/恢复（本地 zip；可选加密云备份）；清空级联清理 |
| P5-3 | 未开始 | 可选密码 session 鉴权（默认关）；README 醒目警告公网暴露风险 |
| P5-4 | 未开始 | 教材 seed 包机制：多教材可安装可切换（mappings 机制已有，安装 UI 未做） |
| P5-5 | 部分已有 | 开源基线：LICENSE / 中英 README / 安全合规声明 / CHANGELOG / `.env.example` 已就位；独立隐私声明与发布打包待补 |

## 13. 维护约定

- 每完成一张工单：更新 `CHANGELOG.md`（交付、实测、残留风险）+ `README.md` 当前进度 + 本文件的工单状态与验证数字。
- 本文件只保留**当前快照**，不逐提交追加历史；历史看 `CHANGELOG.md` 与 `git log`。
- 任何"自动入库/自动排复习"相关开工前，先核对 Phase 0 闸门与 `AGENTS.md` §2。
