# STATUS.md — 开发计划与完成情况

> 快照日期：2026-11-04（**P5-1b 首次运行向导：单页 `/setup` + 顶部横幅**；`setup_completed` 配置键 + 公开只读状态端点；无迁移）
> 基线：`main` = `f2514c0`（P5-1a / PR #32 已合并，P5-1b 卡已出）；本切片在 `feat/p5-1b-setup` 分支，合并前工作区状态
> 全量测试：**521 passed**（2026-11-04 本机实跑，unit 344 / integration 170 / **e2e 7**）；`pytest -m e2e` 收集 **7** 条全绿；`ruff check --no-cache .` 全绿；`npm run build` 绿
> Alembic head：`0020_recitation`；业务表 **21 张**（P5-1b 无迁移、未改表结构）

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
- **P3-1 家长录题已交付**：家长拍空白真题 → 外部 agent 按
  `docs/templates/doubao_bank_transcribe_v1.md` 转录 → `data/inbox/` 按 channel 分派进
  `bank_drafts` → 家长「题库审核」页逐条确认 → SQLite `problem_bank`（**不写 seed JSON**）；
  手填表单兜底。**红线：模型不得自行解题生成答案**，`answer` 只从卷面/答案册转录，
  否则留空由家长补填，缺答案拒入库。入库统一过长度/枚举/choice key/topic 存在性校验 +
  AST `verify` 沙箱（非法表达式、`__import__`、赋值、属性访问、纯数值矛盾全拒），
  固定标 `unaudited=true` / `blind_verified=false`。四个端点全挂 `require_parent`，
  孩子区导航不可见；迁移 `0016`（可逆）。
- **P3-1b 家长题接入检索池已交付**：审核入库的 `problem_bank` 题现在与 seed 题库合并为
  运行时题池，**参与到期考核与手动组卷**；seed 索引仍只读、家长题只存 SQLite。
  approve/手填提交后清缓存，下一条到期任务即见新题；统计从合并题集重算，
  `coverage`/`thin`/`bank_gap` 随池更新。`BankPick.pool_ids` 随池增长，旧记录在新池下
  `replay` 显式抛 `BankReplayError`（绝不静默换题），旧记录仍可用只读 seed 池复现。
- **P3-8 家长自建章级 seed 已交付**：语文/化学不再只能"空 seed 起步"——家长在
  `/local-seed`「学科 seed」页按教材目录建章级点（语文 `cnl_` / 化学 `cnc_`），
  **文件真源 = `<data_dir>/seeds_local/topics_<学科>.json`**，装载器按
  `仓库 seeds/data/topics.json → seeds/local/*.json → data/seeds_local/*.json` 多源合并、
  按 id upsert 幂等；本地行固定 `source='local'` / `unaudited=true` / `blind_verified=false`，
  id 冲突拒绝、坏文件只告警。语文/化学错题因此可挂主考点、题库可挂 `topic_id`，
  到期考核与手动组卷闭环打通；删除知识点会从文件与 `knowledge_seed` 移除并解绑
  错题/题目（置 NULL，历史不动），响应返回受影响计数。无迁移。
- **P3-1c 题库条目修订/软作废已交付**：`problem_bank` 增加 `status ∈ {active, voided}`
  + `updated_at`（迁移 `0017` 可逆，既有行回填 `active`）；运行时题池只合并 `active`，
  作废题**即刻退出检索池**，撤销作废后回池。家长 `/bank` 页新增「已入库题目（可修订）」区：
  列表/筛选、行内编辑（**合并后重跑同一套审核闸门**，稳定错误码）、作废/撤销（幂等）。
  **不做物理删除**；编辑不改 `external_id`，历史 attempts/事件/排期一律不改写，
  `replay`/`replay_paper` 按题 id/`pool_ids` 判定身份——内容修订不回溯，题离开池才重放失败。
- **P3-2 主动加练变式已交付**：错题详情新增「加练同类题」，按主考点从**运行时题池**
  用固定种子抽 1–10 题（可重放、答案不下发）；客观题服务端 `judge_answer` 判分、
  解答/依赖图题由孩子自评。结果**只写 `practice_records`（`kind='variant'`）**：
  **不写 attempts、不产生作答事件、不新建错题、不计入掌握度/排期/打卡**，可整表清空；
  无主考点或题池为空时入口置灰并提示「该知识点暂无同类题」，不报错、不硬凑。
  `/api/practice/*` 全部孩子区免 PIN。新增 4 条集成测试（不变量快照、防客户端谎报、
  自评/跳过、家长题 `problem_bank_id` 回填）。
- **P2-2 番茄钟执行已交付**：复习页每日队列第一项带**纯前端 25 分钟倒计时**，取消不打点，
  自然完成或手动“完成”才 `POST /api/pomodoros` 追加 `pomodoro_completed` 事件（幂等键按
  `started_at`，时长 5–120 钳制，错题可空）；看板与复习页头部显示今日番茄 / 本周专注，
  `GET /api/dashboard` 新增 `pomodoros_today`、`focus_minutes_this_week`。
  **不规划、不排程、不自动连跑、无后台计时/通知**；番茄**不计入掌握度、不计入打卡 streak、
  不进错题本、不完成复习任务**。无新表、无迁移（head 仍 `0015`）。
- **P2-7 打印导出已交付**：错题本“导出打印”与复习页组卷“导出练习卷”进入**无导航壳打印视图**，
  浏览器“打印 → 另存为 PDF”（零 PDF 库、零服务端文件）。错题按知识点页组输出四区块
  （原题 / 作答 / 正答 / 错因批注，KaTeX），支持知识点/错因/日期筛选；练习卷默认不含答案，
  家长答案页走 `require_parent` 单独分页、可不打印。唯一后端增量是家长答案钥匙端点；无迁移。
- **P2-5 家长看板已交付**：`GET /api/dashboard` + 前端 `/dashboard`，纯只读确定性统计
  （错题存量、薄弱分布、掌握度曲线、到期/完成/毕业、`bank_gap`、申诉/作废计数），
  全部从事实现算、与 `recompute` 一致；端点只读、无模型/网络调用，孩子与家长看同一份。
- **P2-6 极简打卡已交付**：看板新增“每日打卡”卡（今日状态、连续、最长、累计、近 30 天
  日历条）；当天有任一作答事件即打卡（答错也算），学习日取 `completed_on`、缺失回退
  `occurred_at`；今天缺席但昨天有 → 锚昨天不清零，连续两天缺席才归零。streak **绝不入库**、
  每请求现算，**不用于学习效果结论**；无手动签到按钮、无积分/徽章/等级。
- **P2-3 课表/日历约束层已交付**：导航第 7 项「课表/日历」录入每周课表（一节一科，周一=1、
  第 1–12 节，不做 A/B 周）与日历硬事件（考试/竞赛/请假/其它）；家长解锁可增删，孩子只读同见；
  日队列页与看板头部显示“今日课程 + 未来 7 天硬事件”。**唯一队列规则**：今天有 `kind='exam'`
  事件时复习上限 ×`exam_day_limit_factor`（默认 1.5、热生效、200 收口）并返回 `exam_today`；
  竞赛/请假/其它不放宽。**不自动排课、不做时间块、不做考试科目↔知识点重排序、不做冲突检测、
  不从课表生成任务**；迁移 `0015_timetable_calendar` 可逆。
- **P2-1 日队列（收窄口径）已交付**：到期队列仍纯查询，每日上限 `daily_review_limit`
  （`<data_dir>/app-config.json`，默认 10、改文件/调 `PUT /api/config` 热生效）截断返回、只计数；响应新增
  `due_total / returned / today_completed / daily_limit`，排序“逾期 `due_date` 升序 → 今日、
  同组 `mistake_id`”；复习页显示今日进度与顺延提示，**顺延不惩罚、不加重做、不做焦虑 UI**。
  背诵铺底 / 作业 deadline / 硬事件抬权重 / 时间块排课**未做**（依赖 P2-3、P3）。
- **P2-4 两角色 + 本地家长 PIN 已交付**：孩子区免 PIN；作废/撤销错题、题库导入/审核、
  手动组卷需在导航"家长区"解锁（scrypt 哈希 + HMAC 签名 cookie，12h，连续 5 次错误锁 60s）。
  PIN **只防误入、不是安全边界**，不做登录/账号/多租户；公网暴露仍须鉴权隔离或 Tailscale。
- **Phase 1 剩余**：P1-7b 前置回溯诊断（未开始）；P1-6 遗留的**知识点归并无 UI**（新票 P1-13）；
  P1-3e 移动端投递入口（新票）。~~P1-7c 自动排复习~~ **已于 v2.5 作废**（入本一律经核对页人工确认，
  "未确认自动入库"场景消失）——本行此前写"仍受 Phase 0 闸门阻塞"与 `TICKETS.md` 作废清单不一致，2026-11-02 修正。
- **P0-3 端到端回归已交付**：v2.6 审计发现 `e2e` marker 声明了却 0 条用例，端到端只在批次⑧
  手工验过一次。本票新增 `wengu-api/tests/e2e/test_closed_loop.py` 三条：①投递 2 题
  `agent_transcribe_v1` JSON → 草稿 → 核对页确认 → 到期队列出 `quiz` → 服务端判分写
  `attempts(source=system_quiz)` → 看板/streak 与手工推导逐项相等；②作废 → 退出活跃与到期队列
  → 撤销 → 回来；作废前历史事件与 `mistake_versions` 一行不改，只追加两条审计事件；③家长解锁
  → 导出备份 → 快照 `integrity_check=ok` → manifest 计数与快照库/业务库三方逐项相等。
  **全程真实 ASGI（`ASGITransport`）+ 临时 SQLite + 真迁移到 head**，不 mock 服务层、不调模型、
  无浏览器栈。同时强化 `test_migrations.py`：0018（`batch_alter_table` 重建，按去引号/默认值
  括号归一后逐项比列定义与约束）与 0019（**7 个 DDL 对象逐字节相等**）的可逆迁移 DDL
  before/after 对比，已用"改坏 0019 `server_default` → 用例变红 → 改回变绿"证明断言有效。
- **P3-3a 英语背诵（家长手填）已交付**：迁移 0020 新增 `recitation_items` /
  `recitation_reviews`（可逆，CHECK/UNIQUE/FK 齐备）；**背诵条目不是错题**，全链路不写
  `mistakes` / `mistake_versions` / `attempts` / `review_schedules`，不计掌握度。纯函数复用
  `MEMORY_LADDER=(1,3,7,14,30)`：`remembered` 进一档、`forgot` 保持当前档（不倒退）、到期日从
  实际自评日起算、最高档再记住即毕业；每次自评追加 `recitation_reviewed` 事件（幂等键
  `recitation:{item_id}:{reviewed_on}`，同日重复不产生第二条事实）。新增热配置
  `daily_recitation_limit`（默认 5、上限 20），到期队列按此截断、在复习页排在考核之后；
  看板加"今日背诵 x/N"。打卡口径**显式变更**为"有学习动作的日子"（含背诵）。
  `/recitations` 页孩子可自评、家长解锁后可增改退役；窄屏单列可用。
- **P3-3b 教材词表批量导入已交付**：家长在 `/recitations` 上传或粘贴 CSV/TSV，服务端
  `POST /api/recitations/import`（`require_parent`）解析入库；逐行报告成功 / 重复 /
  错误，坏行与重复行不阻断好行、不覆盖已有条目；限额（500 行 / 256KB / 字段长度）
  超限整批 422；UTF-8（含 BOM）唯一编码。无迁移、未改 0020 表结构、未引入新依赖。
- **P3-3c 从错题抽词已交付**：`/recitations` 家长区「从错题抽词（英语）」从 active 英语错题
  当前版本题面现算候选词（lowercase、去尾 `'s`、长度 ≥2），排除停用词与任何状态下的已有
  条目，按出现错题数降序取前 50；**候选只读，必须勾选才入库**，入库 `answer` 留空、不自动
  配释义；`GET /api/recitations/candidates` 与 `POST /api/recitations/candidates/batch`
  均挂 `require_parent`；撤销 = 前端逐条 `PATCH retired`。零迁移、零新依赖、未改错题链语义。
- **P5-1a Docker 热配置修复已交付**：旧解析以 `PROJECT_ROOT/config` 为准，Docker 里
  `PROJECT_ROOT=/` → 指向未打包也未挂载的 `/config/app-config.json`，三个运行时参数**静默走默认**。
  现改为 `WENGU_APP_CONFIG` → **`<data_dir>/app-config.json`**（随 data 卷持久、无需额外挂载）→
  仓库根 `config/app-config.json` **只读兼容回退**（`GET /api/config` 标 `legacy` + 迁移提示，
  不自动搬运/删除）；写入一律落 data_dir，同目录 tmp + fsync + `os.replace` + 进程内锁。
  新增 `GET/PUT /api/config`（均 `require_parent`，白名单三键 + 区间校验，非法 422 不写盘，
  未知键与布尔值一律拒绝）；备份包纳入 `<data>/app-config.json`（manifest 记 sha256），
  `restore.ps1` 恢复时替换、旧包无此文件则保留现状。无迁移、无新依赖；`/setup` UI 当时未做，
  已由 P5-1b 补齐。
- **P5-1b 首次运行向导已交付**：`/setup` 单页 + `AppLayout` 顶部横幅，**不采集年级、不做学科勾选**
  （seed 全量装载 7–9；一个孩子、全部学科），只做三件事：① 按数学/英语/物理/语文/化学展示
  `GET /api/seed/summary` 的 `topics`，**`group_by` 缺席学科按 0 展示**并引导 `/local-seed`；
  ② `GET/PUT /api/config` 回填与保存三个上限，成功提示“已生效，无需重启”；③ 完成/跳过都写
  `setup_completed=true`，不新增第二标记键。写配置复用 `ParentGate`（未解锁只读 seed 覆盖并提示解锁）；
  横幅仅在未完成时出现、**不劫持路由**，完成后消失。`setup_completed` 按字段独立校验：布尔键只认
  真布尔，数值键继续拒绝布尔；新增公开只读 `GET /api/setup/status`（只返回该布尔，供未解锁横幅）。
  无迁移、无新依赖。
- **下一步（v2.6 决策轮定的顺序）**：① ~~P5-6 口径清理~~、~~P0-3 端到端回归~~、
  ~~P3-3a 手填背诵~~、~~P3-3b 词表导入~~、~~P3-3c 从错题抽词~~、~~P5-1a 配置持久化修复~~、
  ~~P5-1b 首次运行向导 UI~~ 已完成 → ② 开源分发剩余项：英文 README + 独立隐私声明 + 发布打包
  （P5-5）→ ③ P1-3e 移动端投递 → ④ P1-13 归并 UI → ⑤ P3-4 听力默写。**PWA 已砍**
  （设计文档 §17-A / §12 反清单）。

## 2. 总体路线图状态

| 阶段 | 目标 | 状态 | 说明 |
|---|---|---|---|
| Phase 0 | 摸底 + 回归基线 | 部分完成 | 首轮实测结论已在 `docs/methodology/phase0.md`；v2.5 后"识别瓶颈"由批改外移绕过，边界表不再是入本前置；**P0-3 端到端回归已交付**（e2e 3 条 + 迁移 DDL 文对比），P0-1/P0-2 待按新口径重定义 |
| Phase 1 | 核心闭环 | 进行中 | P1-0～P1-12 完成（模型在环旧链路已退役）；仅剩 P1-7b，P1-7c 阻塞 |
| Phase 2 | 每日任务 + 家长看板 | 进行中 | P2-5 家长看板、P2-4 两角色 + 本地 PIN、P2-6 极简打卡、P2-1 日队列（本轮仅到期复习/考核）、P2-3 课表/日历约束层、P2-2 番茄钟执行、P2-7 打印导出已完成；背诵铺底已随 P3-3a 以独立到期端点 + 复习页入口交付；作业 deadline 与硬事件抬权重未开始 |
| Phase 3 | 内容与扩展 | 进行中 | P3-1 家长录题（真题入库审核流水线）+ P3-1b 家长题接入检索池 + P3-1c 题库修订/软作废 + P3-2 主动加练变式 + **P3-3a 家长手填英语背诵** + **P3-3b 词表批量导入** + **P3-3c 从错题抽词**已完成；P3-5 前置（语文/化学家长自建章级 seed）已交付；听力默写、语文客观题、信奥、长期计划未开始 |
| Phase 4 | 基础设施演进 | 未开始 | Tailscale、可移植部署、可选本地 GPU |
| Phase 5 | 开源分发与打包 | 部分完成 | LICENSE / README / CHANGELOG / `.env.example` / 第三方署名已就位；P5-2 备份 v1（导出一致性快照 + 停机恢复脚本）已交付；首次运行向导、在线恢复、云备份 / 清空级联、鉴权开关、教材包安装器未做 |

## 3. Phase 1 工单完成情况（v2.5 收口后）

| 工单 | 状态 | 说明 |
|---|---|---|
| P1-0 Repo 骨架 | 已完成 | FastAPI + `/health` + SQLite WAL + Alembic + React + Docker Compose + CI |
| P1-1 数据模型 + 事件溯源/幂等 | 已完成 | `learning_events` 只追加；确定性重算；幂等写入 |
| P1-1b 知识点 seed 装载 | 已完成 | 664 个初中知识点 + 1018 条先修边；`unaudited` / `blind_verified` 透传；多源装载 `仓库 seed → seeds/local → data/seeds_local`（**家长自建章级点已独立为 P3-8**：语文 `cnl_` / 化学 `cnc_`，文件真源、原子写、CRUD API + `/local-seed` 页） |
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

- 错题唯一写入路径；`correct` 只作废不删历史。作废 / 撤销作废已有 HTTP 入口
  （`POST /api/mistakes/{id}/void|unvoid`，**家长区解锁后可用**）：只翻 status + 追加
  `mistake_voided` / `mistake_reactivated` 事件，不删版本/事件；作废退出活跃列表与到期队列，
  撤销后未完成排期自然重回队列；历史复习作答仍按现状计入掌握度。
- 两级标签：`category` 挂 `knowledge_seed`；`concept` 受控生长、别名归一、人工归并。
- 标签建议值与确认值分离存储，冲突不静默覆盖。
- `practice_records` 派生表：变式/加练不进错题、不排复习、不影响掌握度、可整表清空。

### 4.3 复习与考核

- 首次排期由确认错题触发；间隔 = 基础档 ×（1 + mastery×4），`times_wrong>1` 折半；
  答对前进、答错不倒退；尾部连对 ≥3 毕业（FSRS 留接口）。
- 到期队列三态：`quiz`（可答题，服务端判分）/ `self_eval`（大题、依赖题图，纸上自评）/
  `redo`（题库缺口，原题重做自评 + `bank_gap`）。
- **日队列（P2-1 收窄口径）**：到期队列仍纯查询；每日上限 `daily_review_limit` 从
  `<data_dir>/app-config.json` 现读（默认 10、1–200、改文件/调 `PUT /api/config` 热生效），
  超限项不返回、只计入
  `due_total`；排序“逾期 `due_date` 升序 → 今日，同组 `mistake_id`”。响应新增
  `due_total / returned / today_completed / daily_limit`；`today_completed` 从
  `attempt_*` 事件（`payload.kind="review"` 且 `completed_on==today`）现算。
  复习页显示“今日任务 x/y 完成”，`y=min(due_total+today_completed, daily_limit)`；
  超限提示“其余 M 项顺延（明天还在，不会丢）”，**不惩罚、不加重做、不做焦虑 UI**。
  **考试日放宽（P2-3）**：今天有 `kind='exam'` 日历事件时上限
  `min(round(cap × exam_day_limit_factor), 200)`，响应 `exam_today=true`、`daily_limit`
  为放大后的值；竞赛/请假/其它不放宽，排序与任务类型不变。
  背诵铺底 / 作业 deadline / 硬事件抬权重 / 时间块排课未做（依赖 P3）。
- 手动组卷：按知识点出 1–20 题，固定 seed 可 `replay_paper`；客户端 `correct` 一律忽略。
- 题面只下发题干/选项/题型/配图 + 质量标签，**绝不下发答案/解析/verify**。

### 4.4 两角色与本地家长 PIN（P2-4）

- **孩子区免 PIN**：导入、核对确认、到期复习、考核作答/自评、错题本与看板只读全程可用。
- **家长区**（`require_parent`）才需解锁：作废/撤销错题、题库导入/审核（`problem-bank`
  import/items）、手动组卷（`GET /api/quizzes/paper`）。未解锁 / 无 cookie / 签名不符 → 403。
- **流程**：导航右侧"家长区"入口；未设 PIN 时引导设置（4–8 位数字或 6–20 位字符），
  已设则解锁；解锁后签发 HMAC-SHA256 签名 cookie（`wengu_parent`，TTL 12h，httponly/lax），
  刷新保持；"锁定家长区"清除。PIN 以 `hashlib.scrypt` + 随机盐存 `user_role.pin_hash`，不存明文。
- **限流**：同一来源连续解锁失败 ≥5 次锁 60s（进程内存计数，重启清零可接受），第 5 次即
  429 + `Retry-After: 60`。密钥 `WENGU_SESSION_SECRET`；缺省首启生成 `data/.session_secret`。
- **边界**：PIN 只防误入，不是安全边界；不做登录 / 账号 / 多租户；公网暴露仍须真鉴权与
  隔离（P5-3）或走 Tailscale。当前无"改配置"端点，新增时须挂 `require_parent`。

### 4.5 家长看板（P2-5，只读）

- `GET /api/dashboard`：错题存量（活跃 / 已作废 / 未挂考点）、按知识点与学科的薄弱分布、
  掌握度总览 + 逐 concept 明细 + 近 N 天（默认 30，上限 90）曲线、今日/逾期/合计到期数、
  本周（周一起算）完成复习数、已毕业总数与本周毕业数、`bank_gap` 知识点清单、
  申诉（`grading_versions.action="appealed"`）与作废/撤销计数、`recompute.stats` 事件统计、
  "今日背诵"（`recitations_today` / `recitation_limit`，P3-3a）。
- 全部从 `learning_events` / `attempts` / `review_schedules` / `grading_versions` 现算，
  复用 `recompute.stats/mastery/is_graduated`；端点只有 `GET`、事务只读，
  不写派生缓存、不调模型、不出网。孩子与家长看同一份。
- 掌握度曲线按日重放事件前缀；无已确认 concept 时曲线为空（不伪造 0 曲线）。
- 叙述性周报不在内核生成；如需，由外部 agent 产出、以"来源=ai"入库，绝不进判分/排期。

### 4.6 极简打卡（P2-6，只读现算）

- 看板“每日打卡”卡：今日已打卡 / 今天还没打卡、连续 N 天、最长 N 天、累计学习天数、
  近 30 天日历条（有学习动作的日期点亮）；沿用 P2-5 掌握度曲线，不新建页面/端点。
- **判定（P3-3a 显式变更）**：当天存在任一 `attempt_correct` / `attempt_wrong` /
  `recitation_reviewed` 事件即打卡——语义为"当天有学习动作"，**只背诵不做题也算**（含复习与
  自造同类题考核，答错也算）；学习日优先 `payload.completed_on`（本地日期），缺失或非法回退
  `occurred_at`。今天缺席但昨天有 → 从昨天倒数（不算断）；连续两天缺席才归零。
- **纪律**：streak 绝不入库，每次请求由 `services/streak.py` 纯函数现算；只做习惯展示，
  **不用于学习效果结论**；无手动签到按钮、无写库路径、无积分/徽章/等级/排行榜。

### 4.7 前端（十一页导航 + 错题详情，家长解锁另有题库审核、学科 seed、备份）

- `/dashboard` 看板；`/import` 导入说明 + 家长手填最小表单；`/intake` 核对入本；
  `/mistakes` + `/:id` 错题本；`/review` 到期三态 + 今日进度/顺延提示 + 手工组卷 +
  今日背诵入口；`/recitations` 英语背诵（孩子自评，家长解锁可增改退役、批量导入 CSV/TSV、
  从错题抽词）；
  `/schedule` 课表/日历（家长解锁可增删，未解锁只读）；`/records` 练习记录；
  `/bank` 题库审核（**仅家长解锁后出现在导航**，未解锁只显示家长专属提示；
  含草稿审核与「已入库题目（可修订）」列表/编辑/作废）；
  `/local-seed` 学科 seed（**仅家长解锁后可见**；语文/化学切换，列出家长自建章级点 +
  新增/编辑/删除，删除弹窗显示「将解绑错题 N 道、题库 N 道」）；
  `/backup` 备份（**仅家长解锁后可见**；立即导出 + 备份列表 + 下载，明示恢复需停机按文档操作）；
  `/print/mistakes`、`/print/paper` 打印视图（AppLayout 之外，无导航壳）；
  数学 KaTeX 渲染，同源 `/api` 代理。看板曲线为内联 SVG，不引入图表库。
- 导航右侧"家长区"入口：未设 PIN 首次引导设置，已设则解锁；解锁态存 cookie、刷新保持；
  错题详情的作废/撤销、复习页的手动组卷、课表/日历的增删仅在解锁后可见。
- 纯查询页零模型调用（内核已无模型可调）；看板页无推送/锁屏/问责，无积分/徽章。
- 复习页与看板头部共用只读摘要组件：今日课程（按 `period` 排序）+ 未来 7 天硬事件（排除请假）。

### 4.8 基础设施

- `learning_events` 只追加 + UNIQUE 幂等键 + UPDATE/DELETE 触发器。
- 掌握度 / 毕业 / 统计由事实确定性重算；同源改判只取最高版本。
- SQLite WAL + Alembic（head 0019）；迁移含备份/回退说明与迁移测试。
- 日志/事件 payload 不落题目全文、答案、文件 URL、PII；`attempts.answer_text` 恒 NULL。

### 4.9 课表 / 日历约束层（P2-3）

- **数据**：`timetable_slots`（`weekday` 1–7 周一=1、`period` 1–12、`subject`、`note`，
  `UNIQUE(weekday, period)` = 一节一科、无 A/B 周）；`calendar_events`（`date`、`title`、
  `kind ∈ {exam, competition, leave, other}`、`subject`、`note`、`INDEX(date)`）。
- **入口**：`/schedule` 页；家长解锁后可增删（改写 = 删除再添加，无 PATCH），孩子只读同见。
  写端点挂 `require_parent`；读端点孩子区免 PIN。weekday/period/kind/日期非法 → 422，
  同一节次重复 → 409，删除不存在 → 404。
- **约束规则（唯一）**：`due_queue` 查今天是否有 `exam` 事件，有则上限 ×
  `exam_day_limit_factor`（默认 1.5、非法/小于 1 回退默认、`min(..., 200)` 收口）。
  **不做**：自动排课 / 时间块 / 考试科目↔知识点重排序 / 冲突检测 / 从课表生成任务。
- **展示**：日队列页与看板头部“今日课程 + 未来 7 天硬事件”；复习页考试日提示
  “复习上限已临时放宽到 N 道”。事件默认窗口今天起 30 天，接口支持显式 `from`/`to`。

### 4.10 番茄钟（P2-2，计时器不是规划器）

- **定位**：对复习队列的下一项做一个 25 分钟**纯前端倒计时**；它不规划、不排程、不自动连跑。
- **打点**：取消 → 不打点；自然归零或手动“完成” → `POST /api/pomodoros`
  （`mistake_id` 可空、`duration_minutes`、`started_at`、`completed_on`）→ 追加
  `pomodoro_completed` 事件（幂等键 `pomodoro:{started_at 秒级}`），返回 `{id, duration_minutes}`。
  时长服务端钳制 5–120 分钟；`StrictInt` 拒绝布尔/字符串，缺字段、非法日期/枚举 → 422，
  不存在的 `mistake_id` → 404。**不建新表**。
- **展示**：看板卡片“今日番茄 / 本周专注”与复习页头部摘要，均读 `GET /api/dashboard` 的
  `pomodoros_today`、`focus_minutes_this_week`（周一起算，从事件现算，空库全零）。
- **边界**：番茄事件**不计入掌握度、不计入 P2-6 streak、不进错题本、不完成复习任务**；
  刷新/关页即弃，无后台计时、无通知推送、无自动开始下一个。

### 4.11 打印导出（P2-7）

- **路由（AppLayout 外，无导航壳）**：`/print/mistakes?category_id=&error_cause=&from=&to=`
  与 `/print/paper?topic_id=&count=&seed=`；屏显 A4 白纸预览 + “打印 / 另存为 PDF”/“返回”。
- **错题四区块**：调 `GET /api/mistakes`（`status=active`）分页拉全量，日期在**前端按本地自然日**
  过滤（既有接口无日期参数，本票未改后端）；按 `category_id` 聚合“知识点页组”，未挂知识点排最后；
  每题四区块：原题（KaTeX）/ 孩子作答 / 订正正答 / 错因批注（确认错因 + 知识点 + 细标签）。
  空结果显示“当前筛选下没有错题”并禁用打印。入口：错题本“导出打印”携带当前筛选。
- **练习卷**：调 `GET /api/quizzes/paper`，只渲染题干/选项/配图，**默认 DOM 无答案/解析/verify**；
  未带 seed 时把服务端返回的 seed 写回 URL，保证刷新/重印同卷。入口：复习页组卷成功区
  “导出练习卷”携带 `topic_id/count/seed`。
- **家长答案页**：默认关闭，点击后才调 `GET /api/quizzes/paper/answers`（`require_parent`，
  同 `topic_id/count/seed` 重建同卷，只回正答 + 可接受别名，不含 `explanation`/`verify`）；
  渲染在卷末并**强制另起一页**，家长可只打印卷面。该端点是本票唯一后端增量：练习卷接口按
  安全设计永不下发答案，且 seed 题 id 为字符串、无法用整型 `problem-bank/items/{id}` 取答，
  前端确实拿不到该字段。
- **打印样式**：`@page A4` + 14mm 边距；打印时隐藏工具栏；知识点页组 `break-before: page`、
  题卡 `break-inside: avoid`、答案页 `break-before: page`。实测：错题页 4 组 → 4 页；
  练习卷默认 1 页、开答案页 2 页；Chrome 阅读器打开正常。

### 4.12 家长录题 / 题库审核（P3-1）

- **链路**：家长拍**空白真题 / 教师版** → 外部 agent 按
  `docs/templates/doubao_bank_transcribe_v1.md` 转录（`channel=agent_bank_transcribe_v1`）→
  `data/inbox/` 监听导入 → `bank_drafts` → 家长 `/bank` 页逐条通过/驳回 → SQLite
  `problem_bank`；家长手填表单走同一闸门。**家长题不写 seed JSON**（seed 保持只读）。
- **红线**：**模型不得自行解题生成答案**。模板只在照片明确含答案时转录 `answer`，否则留空；
  审核页缺答案一律 422 拒绝入库，由家长补填后再通过。
- **导入校验**：字段长度（prompt 2000 / answer 500 / verify 2000 / source_ref 200）、
  `type ∈ {choice,numeric,short,self}`、choice 必须有选项且 key 唯一且 answer 命中 key、
  `topic_id` 必须存在于 `knowledge_seed`、内联 SVG 过白名单净化；坏项逐条
  `errors[{index,field,reason}]` 返回，不做整批静默截断；批次 sha256 去重。
- **审核闸门**：approve 时合并家长覆盖值 → 重新 normalize → `check_approvable`
  （缺 answer / 空题面 / 含 `〔?〕` / choice 不命中）→ `classify_verify`：
  无 verify → `unverifiable/no_verify`；非法表达式或 `__import__`/赋值/属性访问 →
  AST 沙箱拒；数值/短答表达式与答案矛盾 → 拒入库；choice 文本型 verify 无法数值核验 →
  `unverifiable/choice_text_mismatch`。入库固定 `unaudited=true`、`blind_verified=false`。
- **API（全挂 `require_parent`，未解锁 403）**：`GET /api/bank/drafts`（status 过滤 + 分页 +
  topic 名回显）、`POST /api/bank/drafts/{id}/approve`、`POST /api/bank/drafts/{id}/reject`、
  `POST /api/bank/items`（手填直录）。重复审核 / 已驳回转正 → 409。
- **前端**：导航「题库审核」仅家长解锁后出现；未解锁不发请求、只显示家长专属提示。
  草稿卡回显题面/配图/选项/建议考点/答案/verify，可改 `topic_id`、补答案、难度后通过；
  页面级提示显示 `problem_bank #id · verify_status`；手填表单复用同一校验。

### 4.13 家长题接入同类题检索池（P3-1b）

- **装载**：`services/bank.py` 的 seed 内存索引仍是**只读主体**；新增
  `get_runtime_bank(session)` 把 `problem_bank` 中 `topic_id` 非空的已入库行与 seed 合并：
  `external_id`→题 id，`problem_text/answer/acceptable_answers_json/choices_json/figure/
  hide_choice_text/percent/unaudited/blind_verified` 逐列映射，`choices_json` 与配图 SVG
  过 `sanitize_svg`。题型限 `QUESTION_TYPES`；非法行（id 冲突 / 未知 topic / 未知题型 /
  空题面 / 空答案 / choice 不命中）逐行丢弃并计入 `stats.dropped`（`db_invalid_*`）。
- **统计**：`_compute_stats` 从合并题集重建 `total/by_subject/by_type/topics_with_questions/
  verified/unverifiable/figures/dropped`；`coverage`/`thin` 与看板 `bank_gap` 随池更新。
  空 seed 学科补题后 topic 元数据回读 `knowledge_seed`（如化学补题即从 gap 转可考核）。
- **缓存**：`get_bank()`（同步、seed only）与 `get_runtime_bank()` 各持进程内快照；
  approve / 手填入库**提交成功后**调 `reset_bank_cache()`，下一条到期任务即用新题；
  pytest autouse fixture 每用例重置，避免临时库串味。
- **调用点**：练习记录、`/api/quizzes/topics|paper|paper/answers`、组卷
  `build_paper/submit_paper`、看板 `_bank_gap`、到期队列与 `POST /api/reviews/{id}/quiz`
  全部改读运行时池；`find_same_type`/`paper_picks` 未显式传 `bank` 时仍默认 seed 池。
- **确定性**：`BankPick.pool_ids` 随池增长，旧记录在新池下 `replay` **显式抛
  `BankReplayError`**（带 `recorded/replayed`），绝不静默换题；旧记录仍可用只读 seed 池复现。
- **实测**：物理到期题池 4 → 6（seed `2654435762` 不变，题目 `cnp_001_q2` →
  `bank_draft_2`），物理题数 368 → 370、合并总数 2806；化学补题前任务 `redo` +
  看板 gap 命中，补题后转 `quiz`、`coverage=thin`、gap 清空且 `weak_topics` 保留；
  旧 pick 在新池重放抛 `BankReplayError`；`seeds/data/questions.json` 字节未变。
- **测试**：新增 `tests/integration/test_bank_runtime.py`（池增长 + 重放失败 + 卷面不泄漏
  答案 + seed 文件不变；空 seed 学科补题后 gap 关闭、thin/weak_topics 口径不变）。
- **残留**：运行时池是**进程内快照**，绕开 API 直接改库需重启/清缓存；多实例不共享
  （单家庭单实例可接受）；家长题仍固定 `unaudited=true`；编辑/作废入口见 4.14（P3-1c）。

### 4.14 题库条目修订与软作废（P3-1c）

- **哲学**：题库修订 = **编辑 + 软作废**（`status ∈ {active, voided}`），**不做物理删除**，
  与错题本一致；作废题只退出检索池，**已发生的 attempts/事件/排期一律不改写**（append-only
  事实不受影响）。
- **数据**：迁移 `0017` 给 `problem_bank` 加 `status`（NOT NULL、server_default `active`、
  CHECK 只允许 `active|voided`）+ `updated_at`（可空）；既有行回填 `active`；
  up/down/up 可重入。
- **运行时池**：`_load_runtime_bank` 只合并 `status='active'`，作废题同 topic 立即抽不到。
- **编辑闸门**：`PATCH` 合并家长修改后**重跑同一套** `normalize_bank_item` →
  `check_approvable` → `classify_verify`，错误码稳定：`no_fields` / `missing_fields` /
  `normalize_failed` / `verify_error:*` / `verify_mismatch`；成功后重算 `verify_status`、
  写 `updated_at`、清缓存。**不修改 `external_id`**，历史判分与重放不受影响。
- **作废/撤销**：`POST /void`、`/unvoid` 幂等；仅状态实际变化时写 `updated_at` 并清缓存。
- **确定性重放**：`replay` 按 `topic/seed/question_id/pool_ids/index/coverage/mode` 比较，
  `replay_paper` 按题 id + mode + coverage + 池大小比较——**内容修订不回溯**；
  题被作废离开池后重放仍显式抛 `BankReplayError`。
- **前端**：`/bank` 新增「已入库题目（可修订）」区（状态/考点筛选、编辑弹窗、作废/撤销）；
  作废卡显示「已作废」徽章 + 红色「已退出考核出题」提示。仍仅家长解锁后可见。
- **API（`require_parent`）**：`GET /api/bank/items`、`PATCH /api/bank/items/{id}`、
  `POST /api/bank/items/{id}/void|unvoid`。

### 4.15 家长自建章级 seed（P3-8 / P3-5 前置）

- **定位**：语文/化学从**空 seed 起步**，家长按教材目录录章级粗粒度知识点（40–80 点即止，
  不做细粒度树）；有了本地点，语文/化学错题可挂主考点、题库可挂 `topic_id`，
  到期考核不再只能 `redo`。细粒度仍走错题受控生长，**不允许家长覆盖上游 seed 行**。
- **文件真源**：`<data_dir>/seeds_local/topics_<学科>.json`（Docker 内 `./seeds` 只读，
  `data/` 随备份走）；装载顺序 `seeds/data/topics.json`（仓库只读）→
  `seeds/local/*.json`（开发机分发，可选）→ `<data_dir>/seeds_local/*.json`（家长运行时）。
  按 id upsert 幂等，重启后本地点仍在；单文件坏 JSON 只告警跳过，不阻塞服务与其余源；
  id 与上游/先前本地冲突 → error 日志并拒绝该条。装载器跳过下划线开头的文件
  （`_id_counters.json` 是运行期簿记，不是 topics 数组）。
- **契约**：与上游 topics.json 同 schema 子集；语文前缀 `cnl_`、化学 `cnc_`
  （与 `cnm_`/`cne_`/`cnp_` 隔离）；装载/API 统一强制 `source='local'`、`unaudited=true`、
  `blind_verified=false`；**无迁移**（`knowledge_seed.source` 已存在）。
- **写入**：原子写（同目录 tmp + fsync + `os.replace`，进程内锁串行），先写文件再
  upsert/改行；id 由服务端按前缀 + 递增序号生成（零填充 3 位）。
- **id 永不复用**：`<data_dir>/seeds_local/_id_counters.json` 记录各学科「已发放过的最大
  序号」（如 `{"语文": 4}`），**只增不减**；`next_local_id` 取 `max(计数器, 文件与 DB 中
  同前缀最大序号) + 1`。创建时**先预留序号并原子写回计数器再落盘**——后续写失败只留空号，
  绝不回退复用；删除知识点不回退计数器。计数器文件损坏/格式非法 → fail-closed
  （`LocalSeedError`），不静默重置；`_id_counters.json` 不被装载器/导出脚本当作 seed 读取。
- **API（全挂 `require_parent`）**：`GET /api/local-seed/topics?subject=`、
  `POST /api/local-seed/topics`、`PATCH/DELETE /api/local-seed/topics/{id}`。
  subject 仅语文/化学（其它 422）、name 非空 ≤40、grade 7–9、单科 ≤200 点；
  非 local 行（含上游）PATCH/DELETE → 404。
- **删除联动**：从文件移除 + 删行；`mistakes.primary_topic_id` / `problem_bank.topic_id`
  显式置 NULL 并返回 `mistakes_unbound` / `problems_unbound`；错题保留（退回原题重做）、
  历史 attempts/事件/排期不动；仍被 `concepts` 引用 → 409（先归并/移除）。
- **导出**：`scripts/export_topics_junior.py` 合并仓库 + `seeds/local` +
  `<data_dir>/seeds_local` 后导出 `docs/templates/topics_junior.tsv`（664 + local 行，
  UTF-8 无 BOM），转录模板的 `suggested_topic_id` 可选到语文/化学点。
- **前端**：导航「学科 seed」仅家长解锁后出现；按语文/化学列出 id/名称/年级/学期/章/类型/
  引用计数与「家长自建 · 未经教师审核」，新增/编辑弹窗、删除确认显示受影响计数。
- **本地点不作历史改写**：删除点不会回写 `mistake_versions` 的标签快照；快照里的旧
  `category_id` 仍在，但名称解析为 None（只影响展示，不影响事实与排期）。
- **P3-2d 运行态证据（2026-10-31）**：临时库 + uvicorn `127.0.0.1:8111`。连续创建语文点
  得 `cnl_001..003`，计数器 `{"语文": 3}`；删除 `cnl_003` 后计数器仍为 3；再创建得
  **`cnl_004`**（非 003），计数器 4。重启服务后装载器仍见 `cnl_001/002/004`，
  `_id_counters.json` 未被当作 seed；重启后再创建得 `cnl_005`，计数器 5。
  `_id_counters.json` 不被 loader 当 seed 读取另有单测覆盖（两个 local 源均跳过下划线文件）。

### 4.16 主动加练变式（P3-2）

- **定位**：孩子可从错题详情主动加练同类题；这是**派生练习**，不是闭环复习/考核。
  加练结果只进 `practice_records`（`kind='variant'`），**绝不写 `attempts`、不产生
  `attempt_*` 事件、不新建错题、不计入掌握度/复习排期/打卡 streak**，可整表清空。
- **练点解析**：`start_practice(mistake_id | topic_id, count=1..10, seed?)`；`mistake_id`
  取其 `primary_topic_id`。无主考点或该点题池为空 → 返回 `items=[]`、`coverage='gap'`、
  `message='该知识点暂无同类题'`（HTTP 200，不报错、不硬凑）。组卷复用
  `get_runtime_bank` + `paper_picks`：同 topic、mulberry32 固定种子、可重放；
  题面只走 `quiz_view`（题干/选项/题型/配图/质量标签，**无 answer/accept/explanation/verify**）。
- **判分与落库**：`submit_practice(topic_id, seed, count, answers, mistake_id?)` 重建同卷，
  外来/重复题 422；`mode=system` 服务端 `judge_answer`（客户端 `correct` 一律忽略；
  空白 `skipped`、`uncertain` 不写行），`mode=self_eval` 收孩子自评；每题一行
  `PracticeRecord`（`source_mistake_id`、`problem_bank_id`、`student_answer`、`is_correct`）。
  seed 题 `problem_bank_id=NULL`；家长题按 `external_id` 反查 `problem_bank.id` 回填。
  服务层**不 import `record_event`/`Attempt`**，从代码路径上保证零事件、零尝试。
- **提交幂等（迁移 0018）**：`practice_records` 增 `topic_id` / `seed` / `dedup_key`
  与部分唯一索引 `uq_practice_records_dedup_key`（`WHERE dedup_key IS NOT NULL`，多 NULL
  不冲突）。每题写行前计算 `dedup_key = variant:{topic_id}:{seed}:{question_id}`：
  已存在 → 不新增、回看已有行并返回 `reused=true`（同题重复提交不覆盖原作答）；
  并发重复走 savepoint + 唯一索引兜底，再次回看。不同 seed 视为另一组练习，各自成行。
  既有行（三列 NULL）不受影响、仍可回看；`GET /api/practice` 支持 `topic_id` + `seed`
  过滤，练习记录页按组展示「这一组」。
- **API（孩子区免 PIN，不挂 `require_parent`）**：`POST /api/practice/start`、
  `POST /api/practice/submit`（只回 `correct|wrong|uncertain|skipped` + mode + 记录 id，
  无答案钥匙）、`GET /api/practice?mistake_id=&kind=&topic_id=&seed=&limit=&offset=`、
  `DELETE /api/practice`（整表清空，返回 `deleted`）。旧 `/api/practice-records` 保留兼容。
- **前端**：错题详情「加练同类题」入口先探测 count=1，gap/无主考点时**置灰 + 文案解释**；
  `/practice` 页复用 `QuizQuestionCard`，系统题页面作答、自评题「做对了/没做对」，
  提交后逐题状态 + 本轮计数，可「再练一组」或回看记录；「练习记录 → 变式 / 加练」tab
  接 `GET /api/practice`，清空按钮带二次确认（写明不影响错题本/掌握度/排期/打卡）。
- **实测**：临时库 + uvicorn 8790 + Vite 5186。错题 #1（`cnm_001`）3 题：数值答对、
  选择 B 答对、第 3 题留空跳过 → `2 对 / 0 错`；固定 seed 42 两次启动响应字节一致；
  客户端对错答谎报 `correct=true` 仍判 `wrong`；提交响应无答案字段。
  清空前 `attempts=0/events=2/schedules=1/mistakes=1/practice_records=2`，
  清空后仅 `practice_records=0`，其余表内容与 dashboard、到期队列**完全不变**；
  无主考点错题 #2 入口置灰并显示 gap 文案。
- **测试**：`tests/integration/test_practice_api.py`（6 条，含全列快照不变量、
  dashboard/due 字节级不变、清空后不变量仍不变、自评/跳过/外来题、家长题主键回填；
  另含提交幂等（重复提交行数不增 + `reused=true`、换 seed 各自成行）与旧行 NULL 分组可读）。
- **P3-2d 运行态证据（2026-10-31）**：临时库 head `0018` + uvicorn `127.0.0.1:8111`。
  同 `cnm_001` + seed 7 连提两次：第一次 `rows=2`、`reused=false`；第二次 `rows=2`、
  `reused=true` 且记录 id 不变；换 seed 8 再提 → `rows=4`、各自 `reused=false`。
  `GET /api/practice?topic_id=cnm_001&seed=7|8` 各 2 条并带 `topic_id/seed`。
  加练前后 `attempts/learning_events/review_schedules/mistakes` 均 0 → 0，
  `practice_records` 0 → 4；`/api/dashboard` 与 `/api/reviews/due` 响应完全一致。

### 4.17 备份与恢复（P5-2 v1）

- **定位**：只做**导出一致性快照 + 停机整库替换**；**不做运行中热替换 SQLite 的 UI 恢复**
  （WAL/SHM 与活跃连接极易把库弄坏），也不上传任何外部服务。
- **快照**：`app/services/backup.py` 用 SQLite `VACUUM INTO` 在
  `<data_dir>/backups_tmp/` 生成快照（不拷 `-wal/-shm`，已含全部已提交数据）；
  临时目录 `finally` 清理。快照只执行 `VACUUM INTO`，**不写业务表**；测试用全列快照断言
  导出前后各表零变化。
- **包内容**：`wengu.db` + `uploads/` 全量 + `seeds_local/`（含 `_id_counters.json`）+
  `inbox/` 根目录未处理文件（`.processed/` 不进包）+ `manifest.json`（`version` /
  `created_at` / `alembic_version` / 各表计数 / 每个文件 `sha256` + `size_bytes`）。
  成品 `os.replace` 原子落到 `<data_dir>/backups/wengu-backup-<UTC 时间戳>.zip`；
  只保留最近 **10** 份，轮转只删 `backups/` 下匹配命名的 zip，日志只记文件名。
- **API（路由级 `require_parent`）**：`POST /api/backup/export`、
  `GET /api/backup/list`、`GET /api/backup/download/{name}`。未解锁一律 403；
  下载名只接受 `wengu-backup-YYYYMMDDTHHMMSSffffffZ.zip`，含 `/`、`\`、`:`、NUL、`..`
  或解析后不在 `backups/` → 400/404。
- **恢复**：`scripts/restore.ps1`（PowerShell 5.1 + UTF-8 BOM；默认要求输入 `RESTORE`
  确认，支持 `-Force` / `-SkipServiceControl` / `-SkipHealthCheck` 做离线演练）：
  zip 条目防路径遍历 + manifest 核对 `wengu.db` sha256 → `docker compose stop api` →
  现有数据拷到 `backups/pre-restore-<时间戳>/` → 解包覆盖 → 起服务轮询 `/health`。
  Linux/macOS 手动步骤与回滚见 `docs/deploy/backup-restore.md`。
- **边界**：`seeds/data`（随代码分发）与 `.session_secret`（本机密钥）不进包；
  `inbox/.processed/` 已处理归档不备份；恢复是整库替换，备份包里没有的可选目录会被置空；
  备份 zip 含全部错题与家长 PIN 哈希，禁止上传网盘/群聊/公网。
- **实测**：导出 `wengu-backup-20261031T131049098216Z.zip`（122557 字节，
  sha256 `8dc1196f5bb43fed8b59298a24f0af9bd323c53a225ee1a02f6616a8304e27eb`，
  `knowledge_seed=664` / `learning_events=3`）；包内快照 `PRAGMA integrity_check=ok`，
  manifest sha256 与实际文件一致；未解锁 export/list/download 全 403，`../` 与绝对路径
  下载被拒；导出前后业务库零变化。恢复演练在临时副本上替换成功、旧数据进入安全副本、
  第二次运行 exit 0（幂等）。并发写事件时快照仍一致（集成测试覆盖）。
- **测试**：`tests/integration/test_backup_api.py` 6 条（只读且内容完整、并发写入、
  轮转保留 10 份、文件名/路径遍历、403、导出→列表→下载闭环）。
- **审核发现（v1 未做，留后续）**：
  ① ~~`config/app-config.json` 不在 `data_dir` 内、不进备份包~~ —— **P5-1a 已关闭**：
  配置真源改为 `<data_dir>/app-config.json` 并纳入备份（manifest 记 sha256），
  换机恢复后热参数不再回默认；仓库根旧文件仅作只读兼容回退、不进包（需手工迁移）。
  ② 恢复文档原本只覆盖 Docker 路径；**本机原生试用（无 Docker）必须带
  `-SkipServiceControl -SkipHealthCheck`** 并自行停起 uvicorn / vite，已在
  `docs/deploy/backup-restore.md` 补一节。
  ③ `backups/pre-restore-<时间戳>/` 安全副本**不参与轮转**，全量数据副本会无上限堆积
  （`backups/` 已在 `.gitignore`，不会误提交，但要手工清）。
  ④ `data/backups_tmp/snapshot-*` 只清本次运行目录，崩溃残留需下次导出前手工清理。
  ⑤ 列表接口每次重算每份 zip 的 sha256，备份多时偏慢（自用规模可接受）。
  ⑥ 并发写入快照那条测试偶发 pytest warning（397 全量跑三次出现一次，无失败断言），暂观察。

### 4.18 孤儿表退役（P5-6 切片）

- **背景**：`photo_captures` / `photo_capture_items` / `problem_extractions` 是 P1-3/P1-3b/P1-4
  拍照、切片与提取通道的表；v2.5 视觉栈整体退役后，`app/` 已无任何读写方，只剩迁移
  0004/0005/0006 当"活化石"。前两张被删后，`problem_extractions` 的两个 FK 会永久悬空，
  故三张一并退役，**不留悬空外键**。
- **本切片**：迁移 `0019_drop_orphan_photo_tables` 先删 `problem_extractions`（含其两个索引），
  再删 `photo_capture_items`（含 `ix_photo_capture_items_capture_id`），最后删父表
  `photo_captures`（含 `ix_photo_captures_status`）；`downgrade` 反向重建三张空表
  （`problem_extractions` 18 列、UNIQUE `uq_problem_extractions_capture_source_seq`、两个
  `ON DELETE CASCADE` FK；`photo_captures` / `photo_capture_items` 按 0004/0005 原定义），
  不回填数据。同步删除 `models/ingestion.py` 的两个 ORM 类与 `models/__init__.py` 导出；
  `services/backup.py` 的 `COUNT_TABLES` 去掉两项（manifest 表计数从 13 项变 11 项）；
  `problem_extractions` 本无 ORM 类、也从未进 `COUNT_TABLES`，无需代码改动。
- **备份前置**：升级前先跑家长区「备份」导出（`POST /api/backup/export`），或按
  `wengu-api/migrations/README.md` 复制 `wengu.db` 到仓库外；迁移文档已写明。
- **实测**：临时库 `alembic upgrade head` → `0019_drop_orphan_photo_tables`，业务表 **19 张**，
  三表全部缺席、`PRAGMA foreign_key_check` 返回空；`downgrade -1` 后三表按原结构重建（0 行），
  再 `upgrade head` 再次缺席。
- **测试**：新增 `test_p5_6_drops_orphan_photo_tables_up_down_up`（三表列/索引/唯一约束/FK/
  级联/数据不回填/up-down-up/`foreign_key_check` 空）；`EXPECTED_TABLES` 移除三项。全量 398 passed
  （unit 272 / integration 126 / e2e 0），`ruff check --no-cache .` 全绿。
- **残留**：无。三张视觉栈遗留表已一次删净，仓库内不再有指向缺失表的 FK。

### 4.19 端到端回归与迁移 DDL 对比（P0-3）

- **背景**：`pyproject.toml` 早已声明 `e2e` marker，但 `pytest -m e2e` 收集 **0 条**；AGENTS §8
  写了 E2E，实际端到端只有批次⑧手工走过一次、不可重放。P5-6 审核还发现迁移测试只断
  列名/索引名集合，挡不住类型与默认值漂移。
- **三条 e2e**（`wengu-api/tests/e2e/test_closed_loop.py`，真实 `ASGITransport` + 临时库 +
  `alembic upgrade head`）：
  ① 导入 2 题 `agent_transcribe_v1` → 落 2 条草稿 → 逐条确认入本 → 同日到期队列 2 个 `quiz`
  （题面无 `answer/accept/explanation/verify`）→ 一真答一错答（客户端故意谎报 `correct`）
  → 服务端判 `["correct","wrong"]` 并写 `attempts(source=system_quiz)` → 看板断言
  `inventory`/`weak_topics`/`weak_subjects`/`mastery=0.5`/`due=0`/`reviews_this_week=2`/
  `event_stats`（6 事件、准确率 0.25）与 streak 逐项相等。
  ② 作废 → 活跃 2→1、到期 2→1、详情 `voided`；幂等重复作废不叠加；撤销 → 恢复 2/2；全程
  旧事件行与 `mistake_versions` 一字不改，只追加 `mistake_voided` + `mistake_reactivated`
  两条审计事件（**与工单原文"不增"的差异见下文"口径"**）。
  ③ 设 PIN → 上锁 → 导出 403 → 解锁 → 导出 200；下载字节的 size/sha256 与响应一致；zip 含
  `wengu.db` + `manifest.json`；快照 `PRAGMA integrity_check=ok`；manifest 的 `counts`、
  快照库实算、业务库实算三方逐表相等（11 张计数表 + `alembic_version`）。
- **DDL 原文对比**（`tests/integration/test_migrations.py`）：
  `test_p3_2d_reversible_ddl_matches_pre_migration` 覆盖 0018：升到 0017 存
  `practice_records` 及其索引的 `sqlite_master.sql`，升 head 再降 0017 后对比；因
  `batch_alter_table(recreate="always")` 会改变引号/默认值括号/约束顺序，先做**仅表现层归一**
  （去标识符引号、`DEFAULT (X)`→`DEFAULT X`、列保序、约束排序），列类型/NOT NULL/默认值/
  唯一与 FK 约束名仍逐字比对，索引定义精确比对。
  `test_p5_6_reversible_ddl_is_byte_identical` 覆盖 0019：**7 个对象**（3 表 + 4 索引）零归一
  **逐字节相等**——与 P5-6 审核方一次性脚本的结论一致，现在常驻为测试。
- **可证伪证据**：临时把 0019 `downgrade` 里 `photo_captures.source` 的
  `server_default="phone"` 改坏为 `"phone_tampered"` → 用例红，差异精确落到
  `table:photo_captures` 的 `source TEXT DEFAULT ...` 一行；改回 → `2 passed`。
- **口径（需审核注意）**：工单原文②写"全程历史事件与 versions 不增不改"，但按设计
  `mistake_voided` / `mistake_reactivated` 本就是**只追加的审计事件**——业务上必须留痕。
  用例按设计事实断言：**既有行零改动 + 恰好追加 2 条审计事件 + versions 零改动**。
  未改业务代码迁就工单措辞。
- **实测**：`pytest -m e2e` 收集 **3** 条全绿；全量 **403 passed**（unit 266 / integration 134 /
  e2e 3，另 2 条为本次新增迁移用例）；`ruff check --no-cache .` 全绿。

### 4.20 英语背诵：家长手填 + 记忆阶梯自评（P3-3a）

- **定位**：v2.6 的档③"自评间隔重复"。内容来源按 B → A → C 推进，本票只做 **A 家长手填**：
  零模型、不做相似条目猜测；**背诵条目不是错题**，也不进 `attempts`（作答语义）。
- **数据（迁移 0020，可逆）**：`recitation_items`（`subject / prompt / answer? / unit? /
  status(active|retired) / created_by / created_at`，`UNIQUE(subject,prompt)` +
  `CHECK status`）与 `recitation_reviews`（`verdict(remembered|forgot) / rung /
  reviewed_on / scheduled_next? / event_id / created_at`，`UNIQUE(item_id, reviewed_on)` +
  `CHECK verdict`；条目 FK `ON DELETE CASCADE`、事件 FK `ON DELETE RESTRICT`）。
  备份 `COUNT_TABLES` 加入两表（manifest 计数 11 → 13 项），业务表 19 → **21**。
- **阶梯（纯函数 `services/recitation.py`）**：复用 `review_policy.MEMORY_LADDER =
  (1,3,7,14,30)`；`remembered` 进一档、`forgot` **保持当前档不倒退**；下次到期日一律
  `reviewed_on + ladder[rung]`；最高档 rung=4 仍 `remembered` → `scheduled_next=NULL`
  毕业（条目保留，可退役但不删除）。状态可由事件历史确定性重算，未知 verdict / 越界 rung 拒绝。
- **事实与幂等**：每次自评追加 `learning_events(type='recitation_reviewed',
  mistake_id=NULL)`，payload `item_id / verdict / rung / scheduled_next / completed_on`，
  幂等键 `recitation:{item_id}:{reviewed_on}`；同日重复提交返回既有结果，不新增自评/事件。
  **全链路不写 `mistakes` / `mistake_versions` / `attempts` / `review_schedules`，不计掌握度**。
- **调度**：热配置 `daily_recitation_limit`（默认 5、上限 20，非法回退默认）；
  `GET /api/recitations/due` 按此截断，复习页在考核任务之后显示"今日背诵 N 条"入口卡片，
  无到期条目则不显示、不硬凑。看板新增 `recitations_today` / `recitation_limit` 与
  "今日背诵 x/N" 卡片。
- **打卡口径（显式变更）**：`streak` 白名单从作答事件扩为
  `attempt_correct / attempt_wrong / recitation_reviewed`，语义改为"有学习动作的日子"；
  仅背诵也打卡。原有作答用例不改，新增背诵用例；e2e 的独立推导函数同步纳入。
- **前端**：`/recitations` 页孩子区免 PIN（今日卡片 + 记得/没记住 + 今日进度），
  家长解锁后显示新增/编辑/退役/恢复；导航"英语背诵"位于"复习考核"之后，窄屏单列可用。
- **禁止项落实**：无 LLM 生成/判分、无相似度去重（手填重复由 `UNIQUE(subject,prompt)` 409 兜底）；
  未改错题链语义；未触碰 P3-3b/c。
- **实测**：全量 **442 passed**（unit 293 / integration 145 / e2e 4）；`pytest -m e2e` **4** 条
  全绿；迁移 0020 up/down/up + DDL 逐字对比（回退再升级 / ORM 一致）；`ruff check --no-cache .`
  全绿；`npm run build` 绿。
- **运行态证据**：临时库迁到 `0020` + uvicorn/Vite 实走——家长设 PIN 解锁 → 手填
  `abandon / 放弃；抛弃 / Unit 1` → 卡片出现 → 点「记得」→ 进度 1/5、`下次复习 2026-11-06
  （第 2 档）`（11-03 + 3 天）→ 看板「今日背诵 1/5」、仅背诵即点亮打卡、掌握度仍 0%、
  活跃错题 0 → 复习页在到期任务之后显示「今日背诵 1 条」。

### 4.21 教材词表批量导入：CSV / TSV + 逐行报告（P3-3b）

- **定位**：P3-3a 内容来源 A 的批量入口；词表来自家长本人 = **可信来源**，直接入库 +
  逐行报告，**不走**外部 agent 转录的草稿/核对页（与「导入即不可信输入」是两种信任级）；
  但体积、字段长度、编码校验照抄该纪律（家长也会手滑）。无迁移、不动 0020 DDL。
- **解析（服务端唯一真源，`services/recitation_import.py`，stdlib `csv`）**：首个非空/
  非注释行含 TAB → TSV，否则 CSV；`csv.reader(strict=True)` 支持引号转义与引号内换行，
  错误行号按**物理行**（`reader.line_num` 累计 + 换行归一）回报；可选表头仅当首行 ≥2 个
  非空单元格且全部命中 `prompt/answer/unit` 才跳过；空行与 `#` 注释整行跳过；
  1–3 列依次为 `prompt`（必填）/ `answer` / `unit`，>3 列按坏行报告。
- **限额**：单次 ≤500 行、body ≤256KB、`prompt ≤200 / answer ≤500 / unit ≤40` 字符；
  超限**整批 422**，detail 带 `line / field / reason`。编码只收 UTF-8（BOM 可带），
  含 U+FFFD 即拒并提示 Excel「CSV UTF-8」导出。`subject` 必须属于 `MEMORY_SUBJECTS`。
- **逐行语义**：命中 `UNIQUE(subject,prompt)` → 该行 `duplicate`（**不静默丢弃、不更新
  已有行**）；结构坏行 → `{line, field?, reason}`；两者都不阻断好行。写库复用
  `create_item`（内含 SAVEPOINT），单行失败只回滚本行。同文本重复提交 → 全部 duplicate，
  不新增数据（天然幂等）。
- **API**：`POST /api/recitations/import`（`require_parent`），body `{subject, text}`，
  响应 `{imported, duplicates:[{line,prompt}], errors:[{line,field?,reason}]}`；
  未解锁 403（校验先于解析，零写入）。
- **前端**：`/recitations` 家长区「批量导入（CSV / TSV）」——文件选择与粘贴文本二选一、
  共用 `runImport()`；学科下拉默认英语（字段保留通用）；报告成功 N / 重复 N（前 5 条
  prompt + 行号）/ 错误逐条；显示文件名与 UTF-8 导出提示（选文件会替换文本框内容）。
- **实测**：全量 **465 passed**（unit 304 / integration 156 / e2e 5）；`pytest -m e2e`
  **5** 条全绿；`ruff check --no-cache .` 全绿；`npm run build` 绿。
- **运行态证据**：浏览器实走——粘贴 4 行（1 行已存在、1 行空 prompt）→ 报告
  「成功 2 条 / 重复 0 条 / 第 4 行（prompt）：prompt 不能为空」，今日到期 2 条；
  同文本再提交 → 「成功 0 条 / 重复 2 条（abandon 第 2 行、ability 第 3 行）」，列表仍 2 条；
  点「记得」→ `下次复习 2026-11-06（第 2 档）`、进度 1/5；看板「今日背诵 1/5」、连续 1 天。

### 4.22 从错题抽词：候选现算视图 + 家长勾选入库（P3-3c）

- **定位**：P3-3 内容来源 C，接在 A 手填（P3-3a）与 B 词表导入（P3-3b）之后。**候选是现算
  视图，不是新表**：无迁移、无新依赖、未改 0020 两表结构，也未改错题链路语义。
- **取数**：`mistakes.status='active'` JOIN `knowledge_seed.subject='英语'`，只取
  `mistake_versions.version = mistakes.current_version` 且 `problem_text` 非空的题面。
- **token（纯函数 `english_word_tokens`）**：正则 `[A-Za-z][A-Za-z'-]+` → lowercase、
  去尾 `'s`、长度 ≥2；中文/数字自然跳过（本票只做英文 token）。
- **候选（纯函数 `extract_word_candidates`）**：同一题面内重复词只计一次；排除内置英文
  停用词起步集（**80 个功能词**，硬编码常量并注明「按试用反馈增删，不做配置化」）与
  背诵池已有词（`subject='英语'`，**active / retired 都算已有**，大小写不敏感）；
  按**出现错题数降序**、同数按字母序稳定排序，取前 50。只有「错题数」一把尺，无 TF-IDF/权重。
- **API（均 `require_parent`）**：
  - `GET /api/recitations/candidates?limit=50` → `[{word, mistake_count}]`；只读，不写任何表。
  - `POST /api/recitations/candidates/batch` body `{words, unit?}` → 复用 `create_item`
    （subject='英语'，`UNIQUE(subject,prompt)` 去重逐条报 duplicate），响应同 import 报告并
    多带 `created:[{id,prompt}]`；`answer` 留空（**不自动配释义**）；单词至少 2 个字母、
    可含 `-`/`'`，单次 ≤50 个，超限 422。
  - 撤销本批 = 前端对本批 ids 逐条 `PATCH status='retired'`，不新增撤销端点。
- **前端**：`/recitations` 家长区「从错题抽词（英语）」——候选表（词 + 出现错题数）+ 勾选 +
  全选/清空 + 可选 unit + 「入库选中的 N 个词」；成功后显示报告与「撤销本批（N 条）」。
  候选每次现算，无后台任务、无定时同步、绝不未经勾选自动入库。
- **实测行为**：入库后把条目 `retired`，它退出 `/due`；由于 retired 也算「已有」，
  **该词不会重新出现在候选里**，再次提交同名词报 duplicate——恢复背诵需家长手动启用条目。
- **测试与实测**：新增单测 11 + 集成 7 + e2e 第 6 条；单测覆盖 token 归一/题内去重/排序/
  停用词/已有条目/limit；集成覆盖 active+当前版本+英语三边界、active/retired 排除、
  403 零写入、混合批次逐条报告、重复幂等、**四表快照零变化**、retired 退出 `/due` 且
  不再出现于候选；e2e 走真实导入确认 → 抽词 → 勾选入库 → 自评阶梯。全量 **484 passed**
  （unit 315 / integration 163 / e2e 6）；`ruff check --no-cache .` 与 `npm run build` 全绿。
- **残留边界**：不做词形还原（`practice` / `practiced` 视为两个词）；停用词为硬编码起步集，
  按试用反馈增删；题面全中文时无英文候选（本票不抽中文词）。

## 5. API 与数据现状

### 5.1 API 面

| 域 | 端点 |
|---|---|
| 健康 / seed | `GET /health`、`GET /api/seed/summary`、`GET /api/seed/topics` |
| 本地 seed（P3-8） | `GET /api/local-seed/topics?subject=`、`POST /api/local-seed/topics`、`PATCH /api/local-seed/topics/{id}`、`DELETE /api/local-seed/topics/{id}`（全部 `require_parent`；仅语文/化学，文件真源 + `knowledge_seed` 副本同步） |
| 导入 | `POST /api/imports`、`GET /api/imports/{batch_id}`、`GET /api/imports/inbox` |
| 核对入本 | `GET /api/imports/drafts`、`GET /api/imports/{batch_id}/drafts`、`POST /api/imports/drafts/{draft_id}/confirm` |
| 错题 / 标签 | `GET /api/mistakes`、`GET /api/mistakes/{id}`、`GET /api/mistakes/options`、`POST /api/mistakes/{id}/labels`、`POST /api/mistakes/{id}/void`、`POST /api/mistakes/{id}/unvoid` |
| 概念 | `GET /api/concepts`、`POST /api/concepts`、`POST /api/concepts/merge` |
| 题库 | `POST /api/problem-bank/import`、`GET /api/problem-bank/items/{id}` |
| 题库审核（P3-1） | `GET /api/bank/drafts`、`POST /api/bank/drafts/{id}/approve`、`POST /api/bank/drafts/{id}/reject`、`POST /api/bank/items`（全部 `require_parent`） |
| 题库修订（P3-1c） | `GET /api/bank/items?status=&topic_id=&subject=&limit=&offset=`、`PATCH /api/bank/items/{id}`、`POST /api/bank/items/{id}/void`、`POST /api/bank/items/{id}/unvoid`（全部 `require_parent`；编辑重跑同一套闸门，作废/撤销幂等） |
| 复习 | `GET /api/reviews/due`（纯查询；按 `daily_review_limit` 截断，响应含 `due_total` / `returned` / `today_completed` / `daily_limit` / `exam_today`）、`POST /api/reviews/{mistake_id}/quiz`、`POST /api/reviews/{mistake_id}/complete` |
| 课表 | `GET /api/timetable`、`POST /api/timetable/slots`、`DELETE /api/timetable/slots/{id}` |
| 日历 | `GET /api/calendar/events?from=&to=`（缺省今天起 30 天）、`POST /api/calendar/events`、`DELETE /api/calendar/events/{id}` |
| 番茄 | `POST /api/pomodoros`（追加 `pomodoro_completed`，201 `{id, duration_minutes}`；孩子区免 PIN） |
| 组卷 | `GET /api/quizzes/topics`、`GET /api/quizzes/paper`、`GET /api/quizzes/paper/answers`（家长答案钥匙：同卷只回正答 + 可接受别名，不含解析/verify）、`POST /api/quizzes/paper/submit` |
| 背诵（P3-3a / P3-3b / P3-3c） | `GET /api/recitations?subject=&status=&limit=&offset=`、`GET /api/recitations/due?today=`（孩子区免 PIN；到期按 `daily_recitation_limit` 截断）、`POST /api/recitations`、`PATCH /api/recitations/{id}`、`POST /api/recitations/import`（`require_parent`；CSV/TSV body `{subject,text}`，逐行报告 duplicate/error，限额超限整批 422）、`GET /api/recitations/candidates?limit=`（`require_parent`；active 英语错题现算候选 `[{word,mistake_count}]`）、`POST /api/recitations/candidates/batch`（`require_parent`；body `{words,unit?}`，复用 create_item 去重逐条报告并回 `created` ids）、`POST /api/recitations/{id}/review`（孩子区免 PIN，幂等键 `recitation:{item_id}:{reviewed_on}`） |
| 练习记录 | `GET /api/attempts`、`DELETE /api/attempts`、`GET/POST/DELETE /api/practice-records`（兼容旧前端） |
| 主动加练（P3-2） | `POST /api/practice/start`、`POST /api/practice/submit`（幂等：重复提交回 `reused=true`）、`GET /api/practice?mistake_id=&kind=&topic_id=&seed=&limit=&offset=`、`DELETE /api/practice`（全部孩子区免 PIN；只写 `practice_records`，提交响应不含答案钥匙） |
| 看板 | `GET /api/dashboard`（只读，可选 `today` / `curve_days` 1–90；响应含 `streak`、`pomodoros_today`、`focus_minutes_this_week`） |
| 备份（P5-2） | `POST /api/backup/export`、`GET /api/backup/list`、`GET /api/backup/download/{name}`（全部 `require_parent`；下载名做路径遍历防护） |
| 会话 / 家长 PIN | `GET /api/session/status`、`POST /api/session/pin/set`、`POST /api/session/unlock`、`POST /api/session/lock` |

家长区（`require_parent`，未解锁 403）：`POST /api/mistakes/{id}/void|unvoid`、
`POST /api/problem-bank/import`、`GET /api/problem-bank/items/{id}`、`GET /api/quizzes/paper`、
`GET /api/quizzes/paper/answers`、`POST/DELETE /api/timetable/slots*`、
`POST/DELETE /api/calendar/events*`、`GET /api/bank/drafts`、
`POST /api/bank/drafts/{id}/approve|reject`、`POST /api/bank/items`、
`GET /api/bank/items`、`PATCH /api/bank/items/{id}`、`POST /api/bank/items/{id}/void|unvoid`、
`GET/POST /api/local-seed/topics`、`PATCH/DELETE /api/local-seed/topics/{id}`、
`POST /api/recitations`、`PATCH /api/recitations/{id}`、`POST /api/recitations/import`、
`GET /api/recitations/candidates`、`POST /api/recitations/candidates/batch`、
`POST /api/backup/export`、`GET /api/backup/list`、`GET /api/backup/download/{name}`。
其余端点（导入、核对确认、到期、考核提交/自评、主动加练、背诵列表/到期/自评、
错题/看板/课表/日历/seed 只读）孩子区免 PIN。

已删除（P1-12）：`/api/captures*`、`/api/extractions*`、`/api/gradings*`、`/api/explanations*`。

P3-1b 后题库相关端点（练习记录、组卷、到期考核、看板 gap）统一读**运行时题池**
（只读 seed + 已入库 `problem_bank`），API 面无变化；approve/手填提交后本进程缓存失效。

### 5.2 数据库与 seed

- Alembic head `0020_recitation`；**21 张业务表**（0020 新增 `recitation_items` /
  `recitation_reviews`，可逆迁移；0016 新增 `bank_drafts`，
  `problem_bank` 补 `topic_id` FK + `question_type/difficulty/choices_json/figure/hide_choice_text/percent`；
  0017 再补 `status TEXT NOT NULL server_default 'active'`（CHECK `active|voided`）+
  `updated_at DATETIME NULL`，既有行回填 `active`；0018 给 `practice_records` 补
  `topic_id TEXT NULL` / `seed INTEGER NULL` / `dedup_key TEXT NULL` + 部分唯一索引
  `uq_practice_records_dedup_key ... WHERE dedup_key IS NOT NULL`，既有行三列保持 NULL；
  0019 DROP `problem_extractions` / `photo_capture_items` / `photo_captures` 及其显式索引）。
- 迁移 `0019_drop_orphan_photo_tables`：v2.5 后三表在 `app/` 零读写，本票一次删净、不留悬空 FK；
  `downgrade` 按 0004/0005/0006 原定义重建三张空表（列/UNIQUE/FK/级联/索引齐全），
  **不回填历史数据**。**升级前先跑家长区导出备份**（或复制 `wengu.db` 到仓库外）；backup 的
  `COUNT_TABLES` 已同步去掉 `photo_captures` / `photo_capture_items` 两项。up/down/up 可重入见
  `tests/integration/test_migrations.py`。
- 历史口径：`problem_extractions` 曾是 P1-4 提取通道的表，v2.5 后无读写方并已于 0019 一并退役
  （本行原记"另开工单"，范围扩充后不再适用）。
- `bank_drafts`：`import_batch_id` FK + `seq` + `normalized_json` + `has_placeholder` +
  `status draft|approved|rejected` + `created_at`，`UNIQUE(import_batch_id, seq)`；
  草稿永不自动转正，只能由家长审核端点翻状态。
- `user_role` 由 `0014_parent_pin` 保证存在 `(role='parent', pin_hash=NULL)` 行；PIN 设置后存 scrypt 哈希。
- `model_runs` / `ai_jobs` 已 DROP（0013，down 可重建空表）。
- `photo_captures` / `photo_capture_items` 已 DROP（0019，down 可重建空表结构）。
- seed：仓库 664 知识点（数学 315 / 英语 257 / 物理 92）+ 1018 先修边 + 2803 题
  （数学 1407 / 英语 1028 / 物理 368）；化学、语文从**空仓库 seed** 起步，由家长在
  `<data_dir>/seeds_local/topics_<学科>.json` 自建章级点（`source='local'`，装载副本进
  `knowledge_seed`；重启用文件恢复）。加载顺序 = 仓库 topics.json → `seeds/local/*.json` →
  `<data_dir>/seeds_local/*.json`；下划线开头的簿记文件（`_id_counters.json`）跳过。
  `_id_counters.json` 记录各学科已发放最大序号、只增不减，删除点也不回退——本地 id 永不复用。
  **P3-1 家长录题只进 SQLite `problem_bank`，不写 seed JSON**；P3-1b 在运行时把
  `problem_bank` 已入库行合并进检索池（seed 文件仍只读、随仓库分发）；P3-1c 后只合并
  `status='active'` 的行，作废题退出池但行与历史保留。
- 运行时非密钥参数（P5-1a 路径修订）：真源 **`<data_dir>/app-config.json`**（Docker 即
  `<仓库>/data/app-config.json`，随 data 卷持久；原生即 `wengu-api/data/app-config.json`），
  示例见 `config/app-config.example.json`；解析顺序 `WENGU_APP_CONFIG` → data_dir →
  仓库根 `config/app-config.json`（**只读兼容回退**，`GET /api/config` 返回 `legacy` 与迁移提示，
  不自动搬运/删除）；**写入一律落 data_dir**。当前含 `daily_review_limit`（默认 10、上限 200）、
  `exam_day_limit_factor`（默认 1.5）、`daily_recitation_limit`（默认 5、上限 20）与
  `setup_completed`（默认 false，只认真布尔；P5-1b），每请求现读、改文件或调 `PUT /api/config`
  热生效（家长 PIN）；缺失/非法回退默认。未解锁页面横幅读公开只读
  `GET /api/setup/status`（仅返回该布尔）。密钥仍只走 `wengu-api/.env`。
- 备份包含 `<data>/app-config.json`（存在才加，manifest 记 sha256）；仓库根 legacy 配置不进包。
- 掌握度 = 已确认 concept 的最小 mastery；`attempts.source ∈ {student_self, system_quiz}` 计入。

## 6. 未完成、阻塞与缺口

| 项 | 状态 | 影响 | 解锁条件 / 下一步 |
|---|---|---|---|
| 家长录题与组卷未打通 | 已关闭（P3-1b） | 审核入库题已合并进运行时题池，参与到期考核、手动组卷与 P3-2 主动加练；统计/coverage 随池重算 | 题目数量仍靠家长继续录题扩充 |
| 入库题无编辑/作废 | 已关闭（P3-1c） | 家长可在 `/bank` 列表内编辑（重跑同一套闸门）或软作废/撤销；作废题退出检索池，不物理删除、不改写历史 | 后续如需要"当时题面快照"，另开 attempts 展示层工单 |
| 主动加练污染闭环 | 已关闭（P3-2 / P3-2d） | 加练只写 `practice_records(kind=variant)`，不写 attempts/事件/错题本，不影响掌握度/排期/打卡；可整表清空；gap 只提示不硬凑；提交按 `(topic_id, seed, question_id)` 幂等，重复提交不增行并回 `reused=true` | category/错因/难度筛选、「上一组」身份重放可另开增量工单 |
| 录题审核逐条 | 部分缓解 | 草稿只能逐条通过/驳回，批量录入时家长操作成本高 | 观察真实使用量后决定是否做批量确认；不得改为无人确认自动入库 |
| 空 seed 学科无法录题挂点 | 已关闭（P3-8） | 家长可在 `/local-seed` 建语文/化学章级点（`cnl_`/`cnc_`），错题主考点与题库 `topic_id` 均可挂，到期考核闭环打通 | 教材包自动导入/多教材切换仍归 P5-4；细粒度仍走错题受控生长 |
| P0-1 样本扩容 | 待按 v2.5 重新定义 | 外部转录质量是新的主瓶颈 | 用真实"已批改卷"样本测转录模板 + 核对页漏/错项率 |
| P0-2 黄金评测集 | 未开始（需重新界定） | 系统内核已无模型，原 prompt/供应商回归失去对象 | 若做，只针对外部转录质量与题库/判分回归 |
| P1-7b 前置回溯诊断 | 未开始 | 无法定位根因先修 | `prerequisite_edges` 就绪 |
| P1-7c 自动排复习 | 阻塞 | 无自动入库/自动排复习 | 边界表回填后按题型逐步开启 |
| 复习掌握度归因 | 缺口 | 无 concept 时 mastery 恒 0.0，间隔只取基础档 | 后续工单把已确认 concept 写入事实 |
| 毕业 / 复活复习周期 | 缺口 | 已毕业错题再次复活不自动开新周期 | 按产品口径决定是否重排 |
| 主考点未确认 | 部分缓解 | 无主考点只做重做自评，不推同类题 | 核对页引导家长选主考点 |
| 历史作废/申诉入口 | 部分恢复 | 作废 / 撤销作废已有 HTTP 入口与事件留痕；申诉改判仍未开 | 如需申诉改判，另开"错题状态修订"工单，不复活模型链 |
| 鉴权 / 本地 PIN | 部分完成 | P2-4 本地家长 PIN 已做（只防误入，非安全边界）；公网鉴权/隔离仍未做 | 公网暴露前走 P5-3 真鉴权或 Tailscale |
| 化学 / 语文 seed | 已关闭（P3-8；本地点为家长自建） | 家长按教材目录在 `/local-seed` 建章级点；仓库 seed 保持只读、不覆盖上游行；id 由 `_id_counters.json` 单调发放，删除不复用 | 预置教材包（P5-4）可后续补充；章级 40–80 点、单科上限 200 |
| Phase 2 剩余 | 部分完成 | 打印导出已随 P2-7 补齐（前端打印视图，非服务端 PDF 文件）；课表/日历只做约束层（不排课、不生成任务）；日队列仅完成“到期复习/考核”组织，背诵铺底已随 P3-3a 以独立到期端点交付，作业 deadline / 硬事件抬权重未做（依赖 P3）；番茄钟已完成（纯前端计时 + 事件打点） | 按 TICKETS 顺序 |
| Phase 3–5 | 部分完成 | P3-1 录题流水线、P3-2 主动加练、**P3-3a 手填背诵**、**P3-3b 词表批量导入**、**P3-3c 从错题抽词**、P5-2 备份 v1、**P5-1a 配置持久化修复 + 家长配置端点**、**P5-1b 首次运行向导** 已交付；听力默写、语文、信奥、长期计划及 Phase 4 均未开始 | 按 TICKETS 顺序 |

## 7. 残留风险与技术债

1. **外部转录质量成为唯一入本来源**：模板遵从度、红笔痕迹识别、`〔?〕` 使用规范都靠外部 agent；
   系统侧只有契约校验 + 人工核对页兜底。
2. **核对页是人工闸门**：批量导入时确认工作量与家长时间成本需观察；当前无批量确认。
3. **题库覆盖不均**：数学/英语/物理有题；语文/化学 `bank_gap` 走原题重做；物理标 `thin`。
   英语/物理题无二遍盲解，UI 必须继续透传质量标签。
4. **掌握度归因不足**：事实普遍无 `concept_id` 时 mastery 恒 0.0，自适应间隔退化为固定档。
5. **删除后语义缺口**：申诉改判仍无 HTTP 入口（作废/撤销作废已补齐）；`photo_*` /
   `problem_extractions` 旧表未删；`services/grading.py` 名字保留但只做确认/版本追加。
6. **Docker Desktop + SQLite WAL 运维坑**：容器运行期间从宿主机读写挂载库会破坏 WAL/SHM；
   查库走 `docker exec`，备份前先停 API。
7. **本地 PIN 不是安全边界**：只防误入，公网暴露前必须先做真鉴权与隔离或走 Tailscale；
   限流为进程内存计数（重启清零、多实例不共享），会话密钥缺省自动生成到 `data/.session_secret`
   （多实例部署必须显式设置 `WENGU_SESSION_SECRET`）。
8. **前端无自动化 E2E**：浏览器走查为手工实跑；`npm run build` 只保证类型与打包。
9. **主动加练的派生表语义**：`practice_records` 已按 `(topic_id, seed, question_id)` 幂等
   （迁移 0018 部分唯一索引；重复提交回 `reused=true`、不覆盖原作答），只影响可整表清空的
   派生表、不影响闭环事实；旧行三列为 NULL、不参与幂等也不与新建行冲突。组卷目前只按主考点
   检索，尚未提供 category/错因/难度筛选；「再练一组」每次换随机种子，不保存上一组身份用于重放；
   降级到 0017 会丢掉 `topic_id/seed/dedup_key`（升回后为 NULL），需保留幂等数据时先备份。
9. **P1-12 运行态证据为临时库**：E2E 使用 `.e2e-data` 临时库与 8123 端口，跑完即删；
   容器全栈重建验收待下次部署窗口。
10. **打卡回退口径的边界**：批量入库确认会写一条无 `completed_on` 的 `attempt_wrong`
    （代表既往错题），按 P2-6 规则回退 `occurred_at` 计入当天，因此家长“确认导入”也可能
    点亮当日打卡；P3-3a 起 `recitation_reviewed` 也计入（只背诵也算打卡）。streak 仅做习惯
    展示，**不得据此推断学习效果**（与掌握度解耦）。
11. **背诵无内容质量校验**：条目内容完全由家长手填、从其词表导入或从错题抽词（P3-3b/3c
    只做格式/体积/长度/重复校验），系统不判断释义正确性；`answer` 可空、不参与任何判分。
    P3-3c 抽词不做词形还原（`practice`/`practiced` 视为两个词）、停用词是硬编码起步集、
    题面全中文时无候选；候选只按「出现错题数」排序，不做任何权重/语义筛选。
11. **日队列配置与统计成本**：P5-1a 起配置真源是 `<data_dir>/app-config.json`（随 data 卷走），
    `GET/PUT /api/config` 家长端点 + **P5-1b `/setup` 向导**已交付，改上限无需手改文件；
    读取侧保留原宽松口径（复习上限超 200 钳到 200、系数 ≥1 即接受），
    PUT 校验更严（系数 ≤3）——手改文件写超范围值仍按宽松口径生效。`today_completed` 每次 GET 扫描
    `attempt_*` 事件并解析 payload，家庭规模可接受，事件量大时需改为按 `completed_on` 建索引列
    （不得把该计数落成易变列）。
12. **日队列上限不是任务欠账**：顺延项只截断展示，不写库、不惩罚、不加重做；次日仍按原
    `due_date` 出现在队列中，“实际完成日起算”保证不丢。
13. **课表/日历只是约束层**：`timetable_slots` 不参与选题、排序或冲突检测，也没有 A/B 周；
    `calendar_events` 只有 `kind='exam'` 影响上限，且按服务器本地日期判断“今天”。
    事件列表默认窗口 30 天，更远的考试需在查询中显式给 `from`/`to`；无时区存储，
    跨时区/跨零点使用需自行确认日期口径。课表/日历写端点无 UI 以外入口，均走 `require_parent`。
14. **番茄钟是客户端计时**：刷新/关页即丢、无后台计时；`started_at` 与手动完成的已用时长
    均由客户端上报（可信家庭场景，非防作弊），服务端只钳制 5–120 分钟；不足 5 分钟的手动
    完成会记为 5 分钟。看板按 payload `completed_on` 归日，缺失回退 `occurred_at`（UTC）日期；
    番茄只展示专注时长，**不得用于学习效果结论**。
15. **家长录题已接入检索池，修订走编辑/软作废**：P3-1c 后家长可在 `/bank` 编辑或作废
    入库题；编辑不改 `external_id`、不回溯历史，作废只退出检索池（不物理删除）。
    题池增长或作废会使旧 quiz 记录在重放时按 `pool_ids`/题 id 判定——题仍在池则视为同题，
    离开池则 `replay` 抛 `BankReplayError`（设计如此，绝不静默换题）；运行时池是
    **进程内快照**，绕开 API 直接改库需重启/清缓存，多实例不共享（单家庭单实例可接受）。
    **编辑后 `GET /api/attempts` 的 `problem_text` 会随当前题面变化**（该视图 join 当前
    `problem_bank`，不是尝试行快照）；attempts 行/事件/排期均未被改写，判分与统计不受影响；
    如需"当时题面快照"应另开工单。审核页逐条确认、无批量通过；`verify` 只验证"答案自洽"，
    **无法发现题目文本抄错**，仍需家长人工把关。`answer` 只能来自卷面/答案册或家长手填，
    **绝不由模型生成**；choice 的文本型 verify 无法数值核验，只能标 `unverifiable`。
    `topic_id` 必须命中既有 seed，语文/化学空 seed 学科暂不能挂点。审核/修订面全部挂
    `require_parent`，但 PIN 仍只防误入、不是安全边界。
16. **打印导出依赖浏览器**：PDF 由“打印 → 另存为 PDF”生成，分页/页边距由 Chrome/Edge 打印
    引擎决定（已实测 A4），Firefox/移动端可能有差异；不产出服务端 PDF 文件（邮件附件等场景
    留待真需求）。错题日期筛选在**前端**分页拉全量后过滤，家庭规模可接受，量大时应下推到后端
    索引。答案页仅靠 `require_parent` 与“默认不渲染”防误入，**不是安全边界**；家长若在打印
    时同时勾选答案页，需自行确认不在孩子卷面里。筛选项仅覆盖知识点/错因/日期，未做章节级
    或跨学科聚合。
17. **家长自建 seed 以 API 为准**：`knowledge_seed` 只是本地 JSON 的装载副本，
    **手工从 `seeds_local/*.json` 删条目不会自动清理旧行**（只有经 `DELETE`
    端点或重建库才同步）；id 冲突只跳过冲突条目并记 error 日志。id 由
    `_id_counters.json` 单调发放（取 `max(计数器, 文件/DB 最大序号)+1`，先写计数器再落盘，
    **删除不回退、永不复用**）；计数器文件损坏会 fail-closed 拒绝新建，需人工修复。
    装载器/导出脚本跳过下划线开头的文件，`_id_counters.json` 不会被当作 topics 读取。
    删除知识点不会改写 `mistake_versions` 历史标签快照（快照 `category_id` 仍在、
    名称解析为 None，只影响展示）。本地点固定 `unaudited=true` / `blind_verified=false`，
    UI 必须继续透传"家长自建 · 未经教师审核"。本地文件位于 `data/` 随备份走、**不进 git**；
    `seeds/local` 只用于开发机分发。
18. **备份只能停机恢复，且是整库替换**：P5-2 v1 只提供导出一致性快照 + `scripts/restore.ps1`，
    **不做运行中热替换 SQLite 的在线恢复**；恢复时备份包里没有的可选目录（如 `inbox/`）
    会被置空而非合并。`inbox/.processed/`（已处理归档）、`seeds/data`（随代码）与
    `.session_secret`（本机密钥）**不进包**；换机需同时拷贝仓库。备份 zip 含全部错题与
    家长 PIN 哈希，**禁止上传网盘/群聊/外部服务**；`GET /api/backup/list` 每次现算每份 zip
    的 sha256，备份很多时略慢。云备份、加密与清空级联清理仍属 P5-2 后续，未实现。

## 8. 工程不变量（已落地，后续不得回退）

- `learning_events` 只追加，UNIQUE 幂等键，UPDATE/DELETE 触发器守卫。
- **模型只提、代码才判**（作用域 = 自造同类题）；运行时不用 `eval()`，题库核验走 AST 白名单沙箱。
- 核对页确认是唯一转正入口；建议值与确认值分离；确认值优先、冲突不静默覆盖。
- **家长录题红线**：`answer` 只能来自卷面/答案册或家长手填，**模型不得解题生成答案**；
  缺答案拒入库；`verify` 必须过 AST 白名单沙箱（禁 `__import__`/赋值/属性访问）；
  `bank_drafts` 永不自动转正；入库固定 `unaudited=true`、`blind_verified=false`；
  家长题只进 SQLite `problem_bank`，**绝不写 seed JSON**；审核/手填端点挂 `require_parent`。
- **题库 = 只读 seed + 动态合并**：运行时题池由 seed（只读）与 `problem_bank` 中
  `status='active'` 的行合并；选题仍走 mulberry32 固定种子，`pool_ids`/题 id 变化后旧 pick
  重放必须显式失败（`BankReplayError`），不得静默换题；答案钥匙永不下发孩子区。
- **题库修订 = 编辑 + 软作废**：不物理删除、不改写历史 attempts/事件/排期；编辑不改
  `external_id` 并重跑同一套闸门；作废只翻 `status` 退出检索池；`replay` 按身份判定，
  内容修订不回溯（题仍在池视为同题）。修订/作废端点全部挂 `require_parent`。
- **家长自建 seed = 文件真源 + 装载副本**：语文/化学章级点只写
  `<data_dir>/seeds_local/topics_<学科>.json`（原子写），`knowledge_seed` 只是副本；
  固定 `source='local'` / `unaudited=true` / `blind_verified=false`；id 冲突拒绝、
  **不得覆盖上游 seed 行**；删除必须同步文件与行并解绑 `mistakes.primary_topic_id` /
  `problem_bank.topic_id`（返回计数），不改写历史 attempts/事件/排期；
  本地 seed 写端点全部挂 `require_parent`。
- **本地 seed id 永不复用**：`_id_counters.json` 记录已发放最大序号、只增不减；
  分配取 `max(计数器, 文件/DB 最大序号)+1`，先原子写计数器再落盘；删除不回退，
  计数器损坏 fail-closed；装载器/导出脚本跳过下划线开头文件。
- **加练提交幂等**：`practice_records.dedup_key = variant:{topic_id}:{seed}:{question_id}`
  + 部分唯一索引（`WHERE dedup_key IS NOT NULL`）；重复提交不新增、回看已有行并
  返回 `reused=true`，不覆盖原作答；不同 seed 视为另一组。既有 NULL 行不受影响。
- 日志/事件不落题目全文、答案、文件 URL、个人信息、密钥。
- 纯查询 GET 零模型调用；内核零模型（无 provider / SDK / 模型审计表）。
- 变式/加练只进 `practice_records`，绝不进错题本、不排复习；`/api/practice/*` 孩子区免 PIN，
  gap/无主考点只返回空提示（HTTP 200），不报错、不硬凑题。
- 不引入通用 agent 编排框架、Redis、外部 MQ、向量库、K8s；不默认 Postgres。
- Phase 0 闸门：未经用户确认的自动入库/自动排复习不实现。
- 两角色边界：孩子区免 PIN；家长区端点挂 `require_parent`；PIN 只防误入，不替代公网鉴权。
- 打卡 streak 由事实现算、**绝不入库**；不做手动签到/写库路径、积分/徽章/等级/排行榜，
  也不得用 streak 下“学习效果”结论。
- 到期队列纯查询：每日上限只截断返回并计数，**不写库、不惩罚顺延、不自动加重做**；
  `today_completed` 从事件现算，不新增易变计数列；排序（逾期 `due_date` 升序 → 今日，
  同组 `mistake_id`）稳定、同输入必同输出。
- 运行时配置只写 `<data_dir>/app-config.json`（原子写 + 进程内锁），**仓库根 `config/` 只读、
  绝不自动搬运/删除**；`app-config` 只放非密钥参数，密钥唯一入口仍是 `.env`；
  `PUT /api/config` 只收白名单三键并校验区间，非法 422 且不落盘，保存时保留在盘未知键。
- 课表/日历只做约束层：不参与选题、排序、冲突检测，不从课表生成任务；写端点挂
  `require_parent`；唯一队列影响是考试日按热配置系数放大上限。
- 番茄钟只是计时器：不规划/不排程/不自动连跑、无后台计时与通知；`pomodoro_completed`
  事件**不计入掌握度、不计入打卡 streak、不进错题本、不完成复习任务**。
- 背诵条目独立于错题链：只写 `recitation_items` / `recitation_reviews` +
  `recitation_reviewed` 事件，**绝不写 `mistakes` / `mistake_versions` / `attempts` /
  `review_schedules`、不计掌握度**；阶梯确定性（`forgot` 不倒退、从实际自评日起算），
  同日自评幂等；手填重复由 `UNIQUE(subject,prompt)` 拒绝，不做相似度猜测。

## 9. 下一步建议（按依赖与风险排序）

1. ~~**P3-3a 英语背诵（家长手填）**~~、~~**P3-3b 教材词表导入**~~、~~**P3-3c 从错题抽词**~~
   已完成（2026-11-03）：自评间隔重复（档③），零模型、不进错题本；词表 CSV/TSV 由服务端
   解析、逐行报告，不依赖 P5-4 教材包；候选从 active 英语错题现算、家长勾选才入库、
   可整批撤销。~~**P5-1a 配置持久化修复 + 家长配置端点**~~ 已完成（2026-11-04）：
   配置真源迁 `<data_dir>/app-config.json`、legacy 只读回退、`GET/PUT /api/config` + 备份纳入。
   ~~**P5-1b 首次运行向导 UI**~~ 已完成（2026-11-04）：单页 `/setup` + 未完成横幅，不采集年级、
   不做学科勾选，seed 缺席学科按 0 + `/local-seed` 引导；`setup_completed` 布尔键按字段校验。
   **下一步开源分发剩余项：英文 README + 独立隐私声明 + 发布打包（P5-5）**；不引入语音/ASR。
2. **P1-7b 前置回溯诊断**：`prerequisite_edges` 已装载，固定种子 `replay` 必须可重建。
3. **复习掌握度归因**：把已确认 concept 写入事实，让 mastery 不再恒 0.0。
4. **外部转录质量实测（P0-1 新口径）**：用真实已批改卷 / 空白真题跑两个模板，统计 `〔?〕` 率、
   漏题率、核对页修改率；据此迭代 `docs/templates/` 下模板版本。
5. **Phase 2 剩余**：背诵铺底已随 P3-3a 交付（独立到期端点 + 复习页入口）；作业 deadline、
   硬事件抬权重待 P3。P2-1 收窄口径、P2-2 番茄钟、P2-3 课表/日历、P2-4 两角色、P2-5 看板、
   P2-6 打卡、P2-7 打印已完成。
6. **P5-3 公网鉴权**（本地 PIN 已做，但非安全边界）；P5-2 备份 v1（导出 + 停机恢复）
   已交付，云备份/加密与清空级联仍待做，随分发需求穿插。
7. **P3-5 语文客观题并入**：前置已就位（P3-8：家长自建语文章级点 → 题库挂点 → 语文错题
   到期 `quiz` 闭环已实跑），可按模板接入字音/病句/默写；作文/阅读理解仍只走外部讲解、
   不进本。

## 10. 后续阶段工单清单（目标与当前状态）

> 这里只列目标，验收标准、依赖与禁止事项以 [`TICKETS.md`](../TICKETS.md) 为准。

### Phase 2 — 每日任务 + 收口看板

| 工单 | 目标 |
|---|---|
| P2-1 | 部分完成：到期复习/考核组织、每日上限（热配置）、今日进度与顺延提示已交付；背诵铺底随 P3-3a 以独立到期端点 + 复习页入口交付（按 `daily_recitation_limit` 截断、排在考核之后）；作业 deadline 插入、硬事件抬权重待 P3 |
| P2-2 | 已完成：番茄钟执行。复习页对下一项做纯前端 25 分钟倒计时，取消不打点；完成写 `pomodoro_completed`（幂等、5–120 钳制），看板展示今日番茄/本周专注；不计入掌握度/streak/错题本，不规划/排程/自动连跑 |
| P2-3 | 已完成：课表/日历约束层。家长录入每周课表 + 日历硬事件、孩子只读同见；唯一队列规则 = 考试日放宽上限（热配置系数）；不自动排课/时间块/冲突检测/从课表生成任务 |
| P2-4 | 已完成：两角色 + 本地 PIN。孩子区免 PIN；家长区（作废/组卷/题库审核）scrypt 哈希 + 签名 cookie 解锁；不做公网账号体系 |
| P2-5 | 已完成：家长看板（观察复盘型），`GET /api/dashboard` 只读确定性统计，孩子见同一份；无模型/写路径 |
| P2-6 | 已完成：极简打卡。看板打卡卡（今日/连续/最长/累计/近 30 天日历条）；streak 从事实现算、不入库，答错也续签；无手动签到、无积分徽章，不用于学习结论 |
| P2-7 | 错题 PDF 四区块导出（原题 + 作答 + 解析 + 批注），按知识点/章节组卷 |

### Phase 3 — 内容与扩展（按 ROI）

| 工单 | 目标 |
|---|---|
| P3-1 | 已完成：家长录题（真题入库审核流水线）。外部转录 `agent_bank_transcribe_v1` → `bank_drafts` → 家长 `/bank` 逐条确认 → SQLite `problem_bank`；手填兜底；缺答案/choice 不命中/未知 topic/AST 沙箱拒/数值矛盾一律拒绝；固定 `unaudited`/`blind_verified`；迁移 0016。**模型不得生成答案**；P3-1b 已把入库题合并进运行时检索池（到期考核/手动组卷），旧记录跨池 `replay` 显式抛 `BankReplayError`；**P3-1c（已完成 2026-10-31）**：题库列表/编辑/软作废/撤销（迁移 0017），编辑重跑同一套闸门、作废只退出检索池、不物理删除且不改写历史 |
| P3-2 | 已完成：主动加练变式。错题详情按主考点从运行时题池固定种子抽题，系统题服务端判分、自评题收孩子结论；结果只写 `practice_records(kind=variant)`，不进 attempts/事件/错题本、不影响掌握度/排期/打卡，可整表清空；无题知识点只提示不硬凑；端点孩子区免 PIN。LLM 不参与出题/判分。category/错因/难度筛选未做 |
| P3-3 | 英语背诵：自评间隔重复（档③）。**P3-3a 已完成（2026-11-03）**：家长手填条目 + 记忆阶梯自评（迁移 0020），100% 确定性、不进错题本/attempts、不计掌握度；**P3-3b 已完成（2026-11-03）**：CSV/TSV 批量导入（`POST /api/recitations/import`，逐行 duplicate/error 报告，不覆盖已有行，无迁移）；**P3-3c 已完成（2026-11-03）**：从 active 英语错题现算候选词（停用词/已有条目排除、错题数降序、前 50），家长勾选后批量入库、`answer` 留空、可整批撤销；零迁移、零新依赖 |
| P3-4 | 听力 + 默写：默写复用批改；听力用教材音频 + TTS；不做口语 ASR |
| P3-5 | 语文客观题并入（字音/病句/默写）；作文/阅读理解只讲解不入本。**前置已交付（P3-8）**：家长自建语文/化学章级 seed，语文错题可挂主考点、题库可挂 `topic_id` |
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
| P5-1 | 已完成 | **P5-1a（2026-11-04）**：配置真源迁 `<data_dir>/app-config.json` + 仓库根只读回退 + `GET/PUT /api/config`（require_parent、白名单区间、422 不写盘）+ 备份纳入；**P5-1b（2026-11-04，待评审）**：单页 `/setup` + 未完成横幅，**不采集年级、不做学科勾选**，只展示 seed 覆盖（缺席按 0 + `/local-seed`）、设置复习/背诵上限、完成/跳过写同一 `setup_completed` 键；调 P5-1a 端点、不重启、不劫持路由 |
| P5-2 | 部分完成 | 已完成：家长区导出 `VACUUM INTO` 一致性快照 + `uploads`/`seeds_local`/未处理 `inbox` + **`app-config.json`（P5-1a 起）** 打包 + manifest（sha256/表计数/迁移版本），保留最近 10 份；`scripts/restore.ps1` 停机整库替换 + 恢复文档。未做：在线热恢复、可选加密云备份、清空级联清理 |
| P5-3 | 未开始 | 可选密码 session 鉴权（默认关）；README 醒目警告公网暴露风险 |
| P5-4 | 未开始 | 教材 seed 包机制：多教材可安装可切换（mappings 机制已有，安装 UI 未做） |
| P5-5 | 部分完成 | **已在盘上**：LICENSE / 中文 README / CHANGELOG / `wengu-api/.env.example` / 第三方署名（`THIRD-PARTY-NOTICES.md`）/ 两法点名（README §安全与合规）。**仍缺**：**英文 README**（此前本行写"中英 README 已就位"属过实，2026-11-02 审计修正）、**独立隐私声明文档**、发布打包 |
| P5-6 | 部分完成 | 交付口径与盘上一致性清理（v2.6 审计新增）。**已完成孤儿表切片**：迁移 0019 DROP `problem_extractions`/`photo_capture_items`/`photo_captures`（可逆、含备份说明、不留悬空 FK）、删 ORM 类与备份表计数，业务表 22 → 19，见 §4.18。**剩余**：Phase 5 行与 §7 表格的进一步口径复核；见 `docs/audit/pr1-24-retrospective.md` |

## 11. 维护约定

- 每完成一张工单：更新 `CHANGELOG.md`（交付、实测、残留风险）+ `README.md` 当前进度 + 本文件的工单状态与验证数字。
- 本文件只保留**当前快照**，不逐提交追加历史；历史看 `CHANGELOG.md` 与 `git log`。
- 任何"自动入库/自动排复习"相关开工前，先核对 Phase 0 闸门与 `AGENTS.md` §2。
