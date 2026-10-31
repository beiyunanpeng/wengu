# STATUS.md — 开发计划与完成情况

> 快照日期：2026-10-31（P3-2 主动加练变式交付后）
> 分支 / HEAD：`main` / `0d12f5f`（P3-2 加练改动尚未提交，工作区含本票变更）
> 全量测试：**386 passed**（本机 2026-10-31）；`ruff check .` 全绿；`npm run build` 绿
> Alembic head：`0017_bank_item_lifecycle`；业务表 22 张（0017 为 `problem_bank` 补 `status` + `updated_at`）

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
- **P1-1b 家长自建章级 seed 已交付**：语文/化学不再只能"空 seed 起步"——家长在
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
  （`config/app-config.json`，默认 10、改文件热生效）截断返回、只计数；响应新增
  `due_total / returned / today_completed / daily_limit`，排序“逾期 `due_date` 升序 → 今日、
  同组 `mistake_id`”；复习页显示今日进度与顺延提示，**顺延不惩罚、不加重做、不做焦虑 UI**。
  背诵铺底 / 作业 deadline / 硬事件抬权重 / 时间块排课**未做**（依赖 P2-3、P3）。
- **P2-4 两角色 + 本地家长 PIN 已交付**：孩子区免 PIN；作废/撤销错题、题库导入/审核、
  手动组卷需在导航"家长区"解锁（scrypt 哈希 + HMAC 签名 cookie，12h，连续 5 次错误锁 60s）。
  PIN **只防误入、不是安全边界**，不做登录/账号/多租户；公网暴露仍须鉴权隔离或 Tailscale。
- **Phase 1 剩余**：P1-7b 前置回溯诊断（未开始）；P1-7c 自动排复习仍受 Phase 0 闸门阻塞。
- **下一步**：P3-3 英语背诵；并行的长期项仍是 P0-1 样本扩容（v2.5 口径）+ P1-7b。

## 2. 总体路线图状态

| 阶段 | 目标 | 状态 | 说明 |
|---|---|---|---|
| Phase 0 | 摸底 + 回归基线 | 部分完成 | 首轮实测结论已在 `docs/methodology/phase0.md`；v2.5 后"识别瓶颈"由批改外移绕过，边界表不再是入本前置 |
| Phase 1 | 核心闭环 | 进行中 | P1-0～P1-12 完成（模型在环旧链路已退役）；仅剩 P1-7b，P1-7c 阻塞 |
| Phase 2 | 每日任务 + 家长看板 | 进行中 | P2-5 家长看板、P2-4 两角色 + 本地 PIN、P2-6 极简打卡、P2-1 日队列（本轮仅到期复习/考核）、P2-3 课表/日历约束层、P2-2 番茄钟执行、P2-7 打印导出已完成；日队列的背诵/作业/硬事件权重未开始 |
| Phase 3 | 内容与扩展 | 进行中 | P3-1 家长录题（真题入库审核流水线）+ P3-1b 家长题接入检索池 + P3-1c 题库修订/软作废 + P3-2 主动加练变式已完成；P3-5 前置（语文/化学家长自建章级 seed）已交付；英语背诵、听力默写、语文客观题、信奥、长期计划未开始 |
| Phase 4 | 基础设施演进 | 未开始 | Tailscale、可移植部署、可选本地 GPU |
| Phase 5 | 开源分发与打包 | 未启动（部分基线已有） | LICENSE / README / CHANGELOG / `.env.example` / 第三方署名已就位；首次运行向导、备份恢复、鉴权开关、教材包安装器未做 |

## 3. Phase 1 工单完成情况（v2.5 收口后）

| 工单 | 状态 | 说明 |
|---|---|---|
| P1-0 Repo 骨架 | 已完成 | FastAPI + `/health` + SQLite WAL + Alembic + React + Docker Compose + CI |
| P1-1 数据模型 + 事件溯源/幂等 | 已完成 | `learning_events` 只追加；确定性重算；幂等写入 |
| P1-1b 知识点 seed 装载 | 已完成（含家长自建） | 664 个初中知识点 + 1018 条先修边；`unaudited` / `blind_verified` 透传；多源装载 `仓库 seed → seeds/local → data/seeds_local`，语文 `cnl_` / 化学 `cnc_` 家长自建章级点（文件真源、原子写、CRUD API + `/local-seed` 页） |
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
  `config/app-config.json` 现读（默认 10、1–200、改文件热生效），超限项不返回、只计入
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
  申诉（`grading_versions.action="appealed"`）与作废/撤销计数、`recompute.stats` 事件统计。
- 全部从 `learning_events` / `attempts` / `review_schedules` / `grading_versions` 现算，
  复用 `recompute.stats/mastery/is_graduated`；端点只有 `GET`、事务只读，
  不写派生缓存、不调模型、不出网。孩子与家长看同一份。
- 掌握度曲线按日重放事件前缀；无已确认 concept 时曲线为空（不伪造 0 曲线）。
- 叙述性周报不在内核生成；如需，由外部 agent 产出、以"来源=ai"入库，绝不进判分/排期。

### 4.6 极简打卡（P2-6，只读现算）

- 看板“每日打卡”卡：今日已打卡 / 今天还没打卡、连续 N 天、最长 N 天、累计学习天数、
  近 30 天日历条（有作答的日期点亮）；沿用 P2-5 掌握度曲线，不新建页面/端点。
- **判定**：当天存在任一 `attempt_correct` / `attempt_wrong` 事件即打卡（含复习与自造同类题
  考核，答错也算）；学习日优先 `payload.completed_on`（本地日期），缺失或非法回退
  `occurred_at`。今天缺席但昨天有 → 从昨天倒数（不算断）；连续两天缺席才归零。
- **纪律**：streak 绝不入库，每次请求由 `services/streak.py` 纯函数现算；只做习惯展示，
  **不用于学习效果结论**；无手动签到按钮、无写库路径、无积分/徽章/等级/排行榜。

### 4.7 前端（九页导航 + 错题详情，家长解锁另有题库审核、学科 seed）

- `/dashboard` 看板；`/import` 导入说明 + 家长手填最小表单；`/intake` 核对入本；
  `/mistakes` + `/:id` 错题本；`/review` 到期三态 + 今日进度/顺延提示 + 手工组卷；
  `/schedule` 课表/日历（家长解锁可增删，未解锁只读）；`/records` 练习记录；
  `/bank` 题库审核（**仅家长解锁后出现在导航**，未解锁只显示家长专属提示；
  含草稿审核与「已入库题目（可修订）」列表/编辑/作废）；
  `/local-seed` 学科 seed（**仅家长解锁后可见**；语文/化学切换，列出家长自建章级点 +
  新增/编辑/删除，删除弹窗显示「将解绑错题 N 道、题库 N 道」）；
  `/print/mistakes`、`/print/paper` 打印视图（AppLayout 之外，无导航壳）；
  数学 KaTeX 渲染，同源 `/api` 代理。看板曲线为内联 SVG，不引入图表库。
- 导航右侧"家长区"入口：未设 PIN 首次引导设置，已设则解锁；解锁态存 cookie、刷新保持；
  错题详情的作废/撤销、复习页的手动组卷、课表/日历的增删仅在解锁后可见。
- 纯查询页零模型调用（内核已无模型可调）；看板页无推送/锁屏/问责，无积分/徽章。
- 复习页与看板头部共用只读摘要组件：今日课程（按 `period` 排序）+ 未来 7 天硬事件（排除请假）。

### 4.8 基础设施

- `learning_events` 只追加 + UNIQUE 幂等键 + UPDATE/DELETE 触发器。
- 掌握度 / 毕业 / 统计由事实确定性重算；同源改判只取最高版本。
- SQLite WAL + Alembic（head 0017）；迁移含备份/回退说明与迁移测试。
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

### 4.15 家长自建章级 seed（P1-1b / P3-5 前置）

- **定位**：语文/化学从**空 seed 起步**，家长按教材目录录章级粗粒度知识点（40–80 点即止，
  不做细粒度树）；有了本地点，语文/化学错题可挂主考点、题库可挂 `topic_id`，
  到期考核不再只能 `redo`。细粒度仍走错题受控生长，**不允许家长覆盖上游 seed 行**。
- **文件真源**：`<data_dir>/seeds_local/topics_<学科>.json`（Docker 内 `./seeds` 只读，
  `data/` 随备份走）；装载顺序 `seeds/data/topics.json`（仓库只读）→
  `seeds/local/*.json`（开发机分发，可选）→ `<data_dir>/seeds_local/*.json`（家长运行时）。
  按 id upsert 幂等，重启后本地点仍在；单文件坏 JSON 只告警跳过，不阻塞服务与其余源；
  id 与上游/先前本地冲突 → error 日志并拒绝该条。
- **契约**：与上游 topics.json 同 schema 子集；语文前缀 `cnl_`、化学 `cnc_`
  （与 `cnm_`/`cne_`/`cnp_` 隔离）；装载/API 统一强制 `source='local'`、`unaudited=true`、
  `blind_verified=false`；**无迁移**（`knowledge_seed.source` 已存在）。
- **写入**：原子写（同目录 tmp + fsync + `os.replace`，进程内锁串行），先写文件再
  upsert/改行；id 由服务端按前缀 + 递增序号生成（零填充 3 位）。
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
- **API（孩子区免 PIN，不挂 `require_parent`）**：`POST /api/practice/start`、
  `POST /api/practice/submit`（只回 `correct|wrong|uncertain|skipped` + mode + 记录 id，
  无答案钥匙）、`GET /api/practice?mistake_id=&kind=&limit=&offset=`、
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
- **测试**：`tests/integration/test_practice_api.py`（4 条，含全列快照不变量、
  dashboard/due 字节级不变、清空后不变量仍不变、自评/跳过/外来题、家长题主键回填）。

## 5. API 与数据现状

### 5.1 API 面

| 域 | 端点 |
|---|---|
| 健康 / seed | `GET /health`、`GET /api/seed/summary`、`GET /api/seed/topics` |
| 本地 seed（P1-1b） | `GET /api/local-seed/topics?subject=`、`POST /api/local-seed/topics`、`PATCH /api/local-seed/topics/{id}`、`DELETE /api/local-seed/topics/{id}`（全部 `require_parent`；仅语文/化学，文件真源 + `knowledge_seed` 副本同步） |
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
| 练习记录 | `GET /api/attempts`、`DELETE /api/attempts`、`GET/POST/DELETE /api/practice-records`（兼容旧前端） |
| 主动加练（P3-2） | `POST /api/practice/start`、`POST /api/practice/submit`、`GET /api/practice?mistake_id=&kind=&limit=&offset=`、`DELETE /api/practice`（全部孩子区免 PIN；只写 `practice_records`，提交响应不含答案钥匙） |
| 看板 | `GET /api/dashboard`（只读，可选 `today` / `curve_days` 1–90；响应含 `streak`、`pomodoros_today`、`focus_minutes_this_week`） |
| 会话 / 家长 PIN | `GET /api/session/status`、`POST /api/session/pin/set`、`POST /api/session/unlock`、`POST /api/session/lock` |

家长区（`require_parent`，未解锁 403）：`POST /api/mistakes/{id}/void|unvoid`、
`POST /api/problem-bank/import`、`GET /api/problem-bank/items/{id}`、`GET /api/quizzes/paper`、
`GET /api/quizzes/paper/answers`、`POST/DELETE /api/timetable/slots*`、
`POST/DELETE /api/calendar/events*`、`GET /api/bank/drafts`、
`POST /api/bank/drafts/{id}/approve|reject`、`POST /api/bank/items`、
`GET /api/bank/items`、`PATCH /api/bank/items/{id}`、`POST /api/bank/items/{id}/void|unvoid`、
`GET/POST /api/local-seed/topics`、`PATCH/DELETE /api/local-seed/topics/{id}`。
其余端点（导入、核对确认、到期、考核提交/自评、主动加练、错题/看板/课表/日历/seed 只读）
孩子区免 PIN。

已删除（P1-12）：`/api/captures*`、`/api/extractions*`、`/api/gradings*`、`/api/explanations*`。

P3-1b 后题库相关端点（练习记录、组卷、到期考核、看板 gap）统一读**运行时题池**
（只读 seed + 已入库 `problem_bank`），API 面无变化；approve/手填提交后本进程缓存失效。

### 5.2 数据库与 seed

- Alembic head `0017_bank_item_lifecycle`；22 张业务表（0016 新增 `bank_drafts`，
  `problem_bank` 补 `topic_id` FK + `question_type/difficulty/choices_json/figure/hide_choice_text/percent`；
  0017 再补 `status TEXT NOT NULL server_default 'active'`（CHECK `active|voided`）+
  `updated_at DATETIME NULL`，既有行回填 `active`）。
- `bank_drafts`：`import_batch_id` FK + `seq` + `normalized_json` + `has_placeholder` +
  `status draft|approved|rejected` + `created_at`，`UNIQUE(import_batch_id, seq)`；
  草稿永不自动转正，只能由家长审核端点翻状态。
- `user_role` 由 `0014_parent_pin` 保证存在 `(role='parent', pin_hash=NULL)` 行；PIN 设置后存 scrypt 哈希。
- `model_runs` / `ai_jobs` 已 DROP（0013，down 可重建空表）。
- `photo_captures` / `photo_capture_items` / `problem_extractions` 表结构保留但**无写入方**
  （本票按清单只 DROP 两表；如需彻底清理另开工单）。
- seed：仓库 664 知识点（数学 315 / 英语 257 / 物理 92）+ 1018 先修边 + 2803 题
  （数学 1407 / 英语 1028 / 物理 368）；化学、语文从**空仓库 seed** 起步，由家长在
  `<data_dir>/seeds_local/topics_<学科>.json` 自建章级点（`source='local'`，装载副本进
  `knowledge_seed`；重启用文件恢复）。加载顺序 = 仓库 topics.json → `seeds/local/*.json` →
  `<data_dir>/seeds_local/*.json`。
  **P3-1 家长录题只进 SQLite `problem_bank`，不写 seed JSON**；P3-1b 在运行时把
  `problem_bank` 已入库行合并进检索池（seed 文件仍只读、随仓库分发）；P3-1c 后只合并
  `status='active'` 的行，作废题退出池但行与历史保留。
- 运行时非密钥参数：`config/app-config.json`（gitignore，本机配置；示例见
  `config/app-config.example.json`）当前含 `daily_review_limit`（默认 10）与
  `exam_day_limit_factor`（默认 1.5），每请求现读、改文件热生效；缺失/非法回退默认。
  密钥仍只走 `wengu-api/.env`。
- 掌握度 = 已确认 concept 的最小 mastery；`attempts.source ∈ {student_self, system_quiz}` 计入。

## 6. 未完成、阻塞与缺口

| 项 | 状态 | 影响 | 解锁条件 / 下一步 |
|---|---|---|---|
| 家长录题与组卷未打通 | 已关闭（P3-1b） | 审核入库题已合并进运行时题池，参与到期考核、手动组卷与 P3-2 主动加练；统计/coverage 随池重算 | 题目数量仍靠家长继续录题扩充 |
| 入库题无编辑/作废 | 已关闭（P3-1c） | 家长可在 `/bank` 列表内编辑（重跑同一套闸门）或软作废/撤销；作废题退出检索池，不物理删除、不改写历史 | 后续如需要"当时题面快照"，另开 attempts 展示层工单 |
| 主动加练污染闭环 | 已关闭（P3-2） | 加练只写 `practice_records(kind=variant)`，不写 attempts/事件/错题本，不影响掌握度/排期/打卡；可整表清空；gap 只提示不硬凑 | 提交幂等键、category/错因/难度筛选可另开增量工单 |
| 录题审核逐条 | 部分缓解 | 草稿只能逐条通过/驳回，批量录入时家长操作成本高 | 观察真实使用量后决定是否做批量确认；不得改为无人确认自动入库 |
| 空 seed 学科无法录题挂点 | 已关闭（P1-1b） | 家长可在 `/local-seed` 建语文/化学章级点（`cnl_`/`cnc_`），错题主考点与题库 `topic_id` 均可挂，到期考核闭环打通 | 教材包自动导入/多教材切换仍归 P5-4；细粒度仍走错题受控生长 |
| P0-1 样本扩容 | 待按 v2.5 重新定义 | 外部转录质量是新的主瓶颈 | 用真实"已批改卷"样本测转录模板 + 核对页漏/错项率 |
| P0-2 黄金评测集 | 未开始（需重新界定） | 系统内核已无模型，原 prompt/供应商回归失去对象 | 若做，只针对外部转录质量与题库/判分回归 |
| P1-7b 前置回溯诊断 | 未开始 | 无法定位根因先修 | `prerequisite_edges` 就绪 |
| P1-7c 自动排复习 | 阻塞 | 无自动入库/自动排复习 | 边界表回填后按题型逐步开启 |
| 复习掌握度归因 | 缺口 | 无 concept 时 mastery 恒 0.0，间隔只取基础档 | 后续工单把已确认 concept 写入事实 |
| 毕业 / 复活复习周期 | 缺口 | 已毕业错题再次复活不自动开新周期 | 按产品口径决定是否重排 |
| 主考点未确认 | 部分缓解 | 无主考点只做重做自评，不推同类题 | 核对页引导家长选主考点 |
| 历史作废/申诉入口 | 部分恢复 | 作废 / 撤销作废已有 HTTP 入口与事件留痕；申诉改判仍未开 | 如需申诉改判，另开"错题状态修订"工单，不复活模型链 |
| 鉴权 / 本地 PIN | 部分完成 | P2-4 本地家长 PIN 已做（只防误入，非安全边界）；公网鉴权/隔离仍未做 | 公网暴露前走 P5-3 真鉴权或 Tailscale |
| 化学 / 语文 seed | 已关闭（P1-1b；本地点为家长自建） | 家长按教材目录在 `/local-seed` 建章级点；仓库 seed 保持只读、不覆盖上游行 | 预置教材包（P5-4）可后续补充；章级 40–80 点、单科上限 200 |
| Phase 2 剩余 | 部分完成 | 打印导出已随 P2-7 补齐（前端打印视图，非服务端 PDF 文件）；课表/日历只做约束层（不排课、不生成任务）；日队列仅完成“到期复习/考核”组织，背诵铺底 / 作业 deadline / 硬事件抬权重未做（依赖 P3）；番茄钟已完成（纯前端计时 + 事件打点） | 按 TICKETS 顺序 |
| Phase 3–5 | 部分完成 | P3-1 录题流水线、P3-2 主动加练已交付；英语背诵、听力默写、语文、信奥、长期计划及 Phase 4/5 均未开始 | 按 TICKETS 顺序 |

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
9. **主动加练的派生表语义**：`practice_records` 无提交幂等键，同一张卷重复提交会重复写行
   （只影响可整表清空的派生表，不影响闭环事实）；组卷目前只按主考点检索，尚未提供
   category/错因/难度筛选；"再练一组"每次换随机种子，不保存上一组身份用于重放。
9. **P1-12 运行态证据为临时库**：E2E 使用 `.e2e-data` 临时库与 8123 端口，跑完即删；
   容器全栈重建验收待下次部署窗口。
10. **打卡回退口径的边界**：批量入库确认会写一条无 `completed_on` 的 `attempt_wrong`
    （代表既往错题），按 P2-6 规则回退 `occurred_at` 计入当天，因此家长“确认导入”也可能
    点亮当日打卡；streak 仅做习惯展示，**不得据此推断学习效果**（与掌握度解耦）。
11. **日队列配置与统计成本**：`config/app-config.json` 被 gitignore（本机配置），默认值兜底；
    当前无“改配置”端点/UI，需手改文件（UI 热配置归 P5-1）。`today_completed` 每次 GET 扫描
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
    端点或重建库才同步）；id 冲突只跳过冲突条目并记 error 日志；被删序号会被
    `next_local_id` 复用。删除知识点不会改写 `mistake_versions` 历史标签快照
    （快照 `category_id` 仍在、名称解析为 None，只影响展示）。本地点固定
    `unaudited=true` / `blind_verified=false`，UI 必须继续透传"家长自建 · 未经教师审核"。
    本地文件位于 `data/` 随备份走、**不进 git**；`seeds/local` 只用于开发机分发。

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
- 课表/日历只做约束层：不参与选题、排序、冲突检测，不从课表生成任务；写端点挂
  `require_parent`；唯一队列影响是考试日按热配置系数放大上限。
- 番茄钟只是计时器：不规划/不排程/不自动连跑、无后台计时与通知；`pomodoro_completed`
  事件**不计入掌握度、不计入打卡 streak、不进错题本、不完成复习任务**。

## 9. 下一步建议（按依赖与风险排序）

1. **P3-3 英语背诵**（P3-2 主动加练已完成）：自评间隔重复（档③），只做习惯与自评，
   不引入语音/ASR；P3-2 的派生表与免 PIN 加练模式可复用。
2. **P1-7b 前置回溯诊断**：`prerequisite_edges` 已装载，固定种子 `replay` 必须可重建。
3. **复习掌握度归因**：把已确认 concept 写入事实，让 mastery 不再恒 0.0。
4. **外部转录质量实测（P0-1 新口径）**：用真实已批改卷 / 空白真题跑两个模板，统计 `〔?〕` 率、
   漏题率、核对页修改率；据此迭代 `docs/templates/` 下模板版本。
5. **Phase 2 剩余**：日队列的背诵铺底、作业 deadline、硬事件抬权重待 P3；
   P2-1 收窄口径、P2-2 番茄钟、P2-3 课表/日历、P2-4 两角色、P2-5 看板、P2-6 打卡、
   P2-7 打印已完成。
6. **P5-3 公网鉴权**（本地 PIN 已做，但非安全边界）与桌面备份恢复，随分发需求穿插。
7. **P3-5 语文客观题并入**：前置已就位（P1-1b：家长自建语文章级点 → 题库挂点 → 语文错题
   到期 `quiz` 闭环已实跑），可按模板接入字音/病句/默写；作文/阅读理解仍只走外部讲解、
   不进本。

## 10. 后续阶段工单清单（均未开始）

> 这里只列目标，验收标准、依赖与禁止事项以 [`TICKETS.md`](../TICKETS.md) 为准。

### Phase 2 — 每日任务 + 收口看板

| 工单 | 目标 |
|---|---|
| P2-1 | 部分完成（本轮收窄口径）：到期复习/考核组织、每日上限（热配置）、今日进度与顺延提示已交付；固定背诵铺底、作业 deadline 插入、硬事件抬权重待 P2-3/P3 |
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
| P3-3 | 英语背诵：自评间隔重复（档③） |
| P3-4 | 听力 + 默写：默写复用批改；听力用教材音频 + TTS；不做口语 ASR |
| P3-5 | 语文客观题并入（字音/病句/默写）；作文/阅读理解只讲解不入本。**前置已交付（P1-1b）**：家长自建语文/化学章级 seed，语文错题可挂主考点、题库可挂 `topic_id` |
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
