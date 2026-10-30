# STATUS.md — 开发计划与完成情况

> 快照日期：2026-10-30（v2.5 零模型收口 / P1-12 交付后）
> 分支 / HEAD：`main` / `e166aef`（P1-12 改动尚未提交，工作区含本票变更）
> 全量测试：**263 passed**（本机 2026-10-30，44.56s）；`ruff check .` 全绿；`npm run build` 绿
> Alembic head：`0013_drop_model_tables`；业务表 19 张

本文件是**状态快照**，不替代以下事实源；冲突时以它们为准：

- 计划与验收标准：[`TICKETS.md`](../TICKETS.md)
- 逐项交付记录与实测证据：[`CHANGELOG.md`](../CHANGELOG.md)
- 设计与硬约束：[`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`](./specs/architecture/StudyDesk-设计说明文档-v2.md)（v2.5，§16 为准）、[`AGENTS.md`](../AGENTS.md)
- 代码与提交：`git log`

---

## 1. 结论摘要

- **v2.5 零模型内核已完成**：wengu 后端不再调用任何云端 VLM/OCR/文本模型；真实作业的
  识别、批改、讲解全部移到系统外（卷面红笔 + 外部 agent 转录）。
- **入本链路**：外部 agent 整页拍 → 按 `docs/templates/` 版本化模板转录 → `data/inbox/`
  监听导入 → `ingestion_drafts` → **核对页人工确认** → 错题 + 首次复习排期。
  正答（`standard_answer`）必填，任一字段含 `〔?〕` 拒转正；主考点/错答可空。
- **系统内唯一判分场景 = 自造同类题考核**：`judgeAnswer` 确定性归一化 + 题库 `verify`
  AST 沙箱；到期三态 `quiz` / `self_eval` / `redo`；家长可手动组卷，固定 seed 可重放。
- **P1-12 删除票已交付**：视觉栈、gateway、provider 抽象、讲解服务、HTTP 模型判分端点、
  `model_runs` / `ai_jobs`（迁移 0013）、`llm_prompts/`、旧链路脚本与测试、前端旧三页
  全部退役；保留 intake / grading 确认服务 / judge / bank / quiz / review / inbox。
- **Phase 1 剩余**：P1-7b 前置回溯诊断（未开始）；P1-7c 自动排复习仍受 Phase 0 闸门阻塞。
- **下一步**：P0-1 样本扩容（重新定义 v2.5 口径）+ P1-7b；P0-2 黄金集需按"系统内无模型"
  重新界定价值（见 §6）。

## 2. 总体路线图状态

| 阶段 | 目标 | 状态 | 说明 |
|---|---|---|---|
| Phase 0 | 摸底 + 回归基线 | 部分完成 | 首轮实测结论已在 `docs/methodology/phase0.md`；v2.5 后"识别瓶颈"由批改外移绕过，边界表不再是入本前置 |
| Phase 1 | 核心闭环 | 进行中 | P1-0～P1-12 完成（模型在环旧链路已退役）；仅剩 P1-7b，P1-7c 阻塞 |
| Phase 2 | 每日任务 + 家长看板 | 未开始 | 日队列、番茄钟、课表、两角色、看板、打卡、PDF 导出 |
| Phase 3 | 内容与扩展 | 未开始 | 真题库流水线、组卷扩展、英语背诵、听力默写、语文、信奥、长期计划 |
| Phase 4 | 基础设施演进 | 未开始 | Tailscale、可移植部署、可选本地 GPU |
| Phase 5 | 开源分发与打包 | 未启动（部分基线已有） | LICENSE / README / CHANGELOG / `.env.example` / 第三方署名已就位；首次运行向导、备份恢复、鉴权开关、教材包安装器未做 |

## 3. Phase 1 工单完成情况（v2.5 收口后）

| 工单 | 状态 | 说明 |
|---|---|---|
| P1-0 Repo 骨架 | 已完成 | FastAPI + `/health` + SQLite WAL + Alembic + React + Docker Compose + CI |
| P1-1 数据模型 + 事件溯源/幂等 | 已完成 | `learning_events` 只追加；确定性重算；幂等写入 |
| P1-1b 知识点 seed 装载 | 已完成 | 664 个初中知识点 + 1018 条先修边；`unaudited` / `blind_verified` 透传 |
| P1-2 / P1-2b / P1-2c Provider 与模型分档 | **已退役（P1-12）** | 依赖注入式 provider、故障转移、成本护栏、`model_runs` 全部删除 |
| P1-3 / P1-3b / P1-3c 采集与切片 | **已退役（P1-12）** | 上传、OCR 行聚类切题、配图切片几何全部删除；入本改走外部转录 |
| P1-4 结构化提取 + 质量闸门 | **已退役（P1-12）** | VLM 提取等删除；质量闸门语义由导入契约 + 核对页承接 |
| P1-5 判分纪律 | 已完成（v2.5 收口） | 真实题不判；系统只判自造同类题，`judgeAnswer` + AST `verify` |
| P1-6 保守入本 + 两级标签 + 派生表 | 已完成 | 唯一写入路径；category + concept 受控生长；`practice_records` 隔离 |
| P1-7a 复习排期（用户触发） | 已完成 | 首排期/完成/毕业；到期队列考核优先、重做兜底；状态由事件重放 |
| P1-7b 前置知识回溯诊断 | 未开始 | `prerequisite_edges` 已就绪 |
| P1-7c 自动排复习 | 阻塞 | 边界表回填前不实现 |
| P1-8 三段式讲解引擎 | **已退役（P1-12）** | 讲解移出系统；保留"卷面订正回放"只读视图 |
| P1-9 最小 Web UI | 已完成（v2.5 五页） | 导入 / 核对 / 错题本（+详情）/ 复习考核 / 练习记录；旧三页已删除 |
| P1-10 题库检索引擎 | 已完成 | 2803 题内存索引、mulberry32 固定种子、`verify` 沙箱、SVG 净化 |
| P1-11 同类题考核闭环 | 已完成 | 考核 `/quiz` 服务端判分、手动组卷、答案不下发、结果只进 attempts |
| P1-12 零模型收口（删除票） | 已完成 | 旧链路整链退役；迁移 0013；三绿 + 端到端实跑通过 |

## 4. 当前系统实际能做什么

### 4.1 导入与入本

- 外部 agent 转录 JSON（`channel=agent_transcribe_v1`）经 `POST /api/imports` 或
  `data/inbox/` 监听目录进入，生成 `ingestion_drafts`；同内容按批次 sha256 去重。
- 坏项逐条报 `index/field/reason`，不静默截断；非法 JSON 稳定窗口重试后按 invalid 归档。
- 核对页三栏回显（题目 / 错答 / 正答）+ 主考点 + 错因 + 细标签；确认后走唯一写入路径建错题、
  排首次复习；重复确认幂等（`already_promoted=true`）。
- 缺正答 / 含 `〔?〕` / 主考点不存在 / 细标签不属于主考点 → 422 拒绝转正；
  无主考点可入本（存 NULL，只做原题重做自评）；未知学科入本但不排期。

### 4.2 错题与标签

- 错题唯一写入路径；`correct` 只作废不删历史（v2.5 后无 HTTP 入口，仅服务层/历史数据语义）。
- 两级标签：`category` 挂 `knowledge_seed`；`concept` 受控生长、别名归一、人工归并。
- 标签建议值与确认值分离存储，冲突不静默覆盖。
- `practice_records` 派生表：变式/加练不进错题、不排复习、不影响掌握度、可整表清空。

### 4.3 复习与考核

- 首次排期由确认错题触发；间隔 = 基础档 ×（1 + mastery×4），`times_wrong>1` 折半；
  答对前进、答错不倒退；尾部连对 ≥3 毕业（FSRS 留接口）。
- 到期队列三态：`quiz`（可答题，服务端判分）/ `self_eval`（大题、依赖题图，纸上自评）/
  `redo`（题库缺口，原题重做自评 + `bank_gap`）。
- 手动组卷：按知识点出 1–20 题，固定 seed 可 `replay_paper`；客户端 `correct` 一律忽略。
- 题面只下发题干/选项/题型/配图 + 质量标签，**绝不下发答案/解析/verify**。

### 4.4 前端（五页导航 + 错题详情）

- `/import` 导入说明 + 家长手填最小表单；`/intake` 核对入本；`/mistakes` + `/:id` 错题本；
  `/review` 到期三态 + 手动组卷；`/records` 练习记录；数学 KaTeX 渲染，同源 `/api` 代理。
- 纯查询页零模型调用（内核已无模型可调）。

### 4.5 基础设施

- `learning_events` 只追加 + UNIQUE 幂等键 + UPDATE/DELETE 触发器。
- 掌握度 / 毕业 / 统计由事实确定性重算；同源改判只取最高版本。
- SQLite WAL + Alembic（head 0013）；迁移含备份/回退说明与迁移测试。
- 日志/事件 payload 不落题目全文、答案、文件 URL、PII；`attempts.answer_text` 恒 NULL。

## 5. API 与数据现状

### 5.1 API 面

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
| 练习记录 | `GET /api/attempts`、`DELETE /api/attempts`、`GET/POST/DELETE /api/practice-records` |

已删除（P1-12）：`/api/captures*`、`/api/extractions*`、`/api/gradings*`、`/api/explanations*`。

### 5.2 数据库与 seed

- Alembic head `0013_drop_model_tables`；19 张业务表。
- `model_runs` / `ai_jobs` 已 DROP（0013，down 可重建空表）。
- `photo_captures` / `photo_capture_items` / `problem_extractions` 表结构保留但**无写入方**
  （本票按清单只 DROP 两表；如需彻底清理另开工单）。
- seed：664 知识点（数学 315 / 英语 257 / 物理 92）+ 1018 先修边 + 2803 题
  （数学 1407 / 英语 1028 / 物理 368）；化学、语文空 seed 起步。
- 掌握度 = 已确认 concept 的最小 mastery；`attempts.source ∈ {student_self, system_quiz}` 计入。

## 6. 未完成、阻塞与缺口

| 项 | 状态 | 影响 | 解锁条件 / 下一步 |
|---|---|---|---|
| P0-1 样本扩容 | 待按 v2.5 重新定义 | 外部转录质量是新的主瓶颈 | 用真实"已批改卷"样本测转录模板 + 核对页漏/错项率 |
| P0-2 黄金评测集 | 未开始（需重新界定） | 系统内核已无模型，原 prompt/供应商回归失去对象 | 若做，只针对外部转录质量与题库/判分回归 |
| P1-7b 前置回溯诊断 | 未开始 | 无法定位根因先修 | `prerequisite_edges` 就绪 |
| P1-7c 自动排复习 | 阻塞 | 无自动入库/自动排复习 | 边界表回填后按题型逐步开启 |
| 复习掌握度归因 | 缺口 | 无 concept 时 mastery 恒 0.0，间隔只取基础档 | 后续工单把已确认 concept 写入事实 |
| 毕业 / 复活复习周期 | 缺口 | 已毕业错题再次复活不自动开新周期 | 按产品口径决定是否重排 |
| 主考点未确认 | 部分缓解 | 无主考点只做重做自评，不推同类题 | 核对页引导家长选主考点 |
| 历史作废/申诉入口 | 已移除 | 无 HTTP 入口修正已入本错题（v2.5 只到确认入本） | 如需恢复，另开"错题状态修订"工单，不复活模型链 |
| 鉴权 / 本地 PIN | 未做 | 仅适合本机/可信内网 | P5-3 可选 session 鉴权 + README 警告 |
| 化学 / 语文 seed | 未做 | 两科从空 seed 起步 | 家长按教材目录建章级粗粒度 seed |
| Phase 2–5 | 未开始 | 日队列、看板、导出、分发向导等缺失 | 按 TICKETS 顺序 |

## 7. 残留风险与技术债

1. **外部转录质量成为唯一入本来源**：模板遵从度、红笔痕迹识别、`〔?〕` 使用规范都靠外部 agent；
   系统侧只有契约校验 + 人工核对页兜底。
2. **核对页是人工闸门**：批量导入时确认工作量与家长时间成本需观察；当前无批量确认。
3. **题库覆盖不均**：数学/英语/物理有题；语文/化学 `bank_gap` 走原题重做；物理标 `thin`。
   英语/物理题无二遍盲解，UI 必须继续透传质量标签。
4. **掌握度归因不足**：事实普遍无 `concept_id` 时 mastery 恒 0.0，自适应间隔退化为固定档。
5. **删除后语义缺口**：无 HTTP 作废/申诉；`photo_*` / `problem_extractions` 旧表未删；
   `services/grading.py` 名字保留但只做确认/版本追加。
6. **Docker Desktop + SQLite WAL 运维坑**：容器运行期间从宿主机读写挂载库会破坏 WAL/SHM；
   查库走 `docker exec`，备份前先停 API。
7. **无鉴权 / 无本地 PIN**：公网暴露前必须先做鉴权与隔离或走 Tailscale。
8. **前端无自动化 E2E**：浏览器走查为手工实跑；`npm run build` 只保证类型与打包。
9. **P1-12 运行态证据为临时库**：E2E 使用 `.e2e-data` 临时库与 8123 端口，跑完即删；
   容器全栈重建验收待下次部署窗口。

## 8. 工程不变量（已落地，后续不得回退）

- `learning_events` 只追加，UNIQUE 幂等键，UPDATE/DELETE 触发器守卫。
- **模型只提、代码才判**（作用域 = 自造同类题）；运行时不用 `eval()`，题库核验走 AST 白名单沙箱。
- 核对页确认是唯一转正入口；建议值与确认值分离；确认值优先、冲突不静默覆盖。
- 日志/事件不落题目全文、答案、文件 URL、个人信息、密钥。
- 纯查询 GET 零模型调用；内核零模型（无 provider / SDK / 模型审计表）。
- 变式/加练只进 `practice_records`，绝不进错题本、不排复习。
- 不引入通用 agent 编排框架、Redis、外部 MQ、向量库、K8s；不默认 Postgres。
- Phase 0 闸门：未经用户确认的自动入库/自动排复习不实现。

## 9. 下一步建议（按依赖与风险排序）

1. **P1-7b 前置回溯诊断**：`prerequisite_edges` 已装载，固定种子 `replay` 必须可重建。
2. **复习掌握度归因**：把已确认 concept 写入事实，让 mastery 不再恒 0.0。
3. **外部转录质量实测（P0-1 新口径）**：用真实已批改卷跑模板，统计 `〔?〕` 率、漏题率、
   核对页修改率；据此迭代 `docs/templates/doubao_transcribe_v1.md` 版本。
4. **Phase 2**：日队列 / 番茄钟 / 课表 / 两角色 / 家长看板 / 打卡 / PDF 导出。
5. **P5-3 鉴权/本地 PIN** 与桌面备份恢复，随分发需求穿插。

## 10. 后续阶段工单清单（均未开始）

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
| P3-1 | 真题库录入流水线：外部转录 → `problem_bank` → 家长审核队列 |
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
| P4-3 | 可选本地模型层：若回退模型决策，另行评审，不默认引入 |

### Phase 5 — 开源分发与打包

| 工单 | 状态 | 目标 |
|---|---|---|
| P5-1 | 未开始 | 首次运行向导：孩子/年级 → 学科 → 教材 seed → 可选外部 agent 配置；热配置 |
| P5-2 | 未开始 | 一键备份/恢复（本地 zip；可选加密云备份）；清空级联清理 |
| P5-3 | 未开始 | 可选密码 session 鉴权（默认关）；README 醒目警告公网暴露风险 |
| P5-4 | 未开始 | 教材 seed 包机制：多教材可安装可切换（mappings 机制已有，安装 UI 未做） |
| P5-5 | 部分已有 | 开源基线：LICENSE / 中英 README / 安全合规声明 / CHANGELOG / `.env.example` 已就位；独立隐私声明与发布打包待补 |

## 11. 维护约定

- 每完成一张工单：更新 `CHANGELOG.md`（交付、实测、残留风险）+ `README.md` 当前进度 + 本文件的工单状态与验证数字。
- 本文件只保留**当前快照**，不逐提交追加历史；历史看 `CHANGELOG.md` 与 `git log`。
- 任何"自动入库/自动排复习"相关开工前，先核对 Phase 0 闸门与 `AGENTS.md` §2。
