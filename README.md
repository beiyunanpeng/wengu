# wengu · 温故

> 面向中国初中家庭的**自托管** AI 学习工作台：已批改错题转录归集 → 错因/知识点分类 → 跨科复习调度 → 每日任务 → 家长复盘。
> 不是又一个拍照答疑 App——那部分现成工具够好了。**wengu 做的是个性化错题闭环**，每个家庭部署自己的一份，数据不出家门。

**A self-hosted AI learning workbench for Chinese junior-high families**: confirmed mistake intake → knowledge tagging → cross-subject spaced review → same-type quizzes → parent dashboard. Every family runs their own instance; data stays home.

> 内部代号 StudyDesk。License = MIT（代码）；知识点树与题库 seed 数据来自 [`cn-math-taxonomy`](https://github.com/xiaoyang111222/cn-math-taxonomy)（CC BY-NC 4.0，**限个人非商用**），详见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)。

---

## ✨ 核心闭环

- 📥 **卷面批改外移**（孩子在纸上红笔批改 + 订正；外部 agent 整页拍 → 按版本化模板转录 → `data/inbox/` 监听导入）
- 📕 **错题归集**（核对页人工确认后才入本；错题表唯一写入路径，不设独立录入任务）
- 🏷️ **错因建议 + 孩子确认**（外部 agent 给建议，确认值与建议值分来源存储；知识点 = 粗粒度预置 seed + 细粒度受控生长）
- 🔁 **复习调度**（固定阶梯 + 掌握度自适应间隔 + 抗挫败三规则；FSRS 留接口）
- 📝 **同类题考核**（到期自动推题或家长手动组卷，答案钥匙来自题库，**代码判分**）
- 📖 **卷面订正回放**（系统不生成讲解、不调模型；拿不准的题在系统外问豆包/家长）
- 📅 **优先级日队列 + 番茄钟**（自动生成，课表/日历为约束层）
- 👀 **观察复盘型家长看板**（孩子见同一份；两角色 + 本地 PIN，非遥控监控）
- 🔥 **极简打卡**（当天做过任一题即点亮；答错也算，streak 从事实现算、不入库，无积分/徽章）

## 🚫 明确不做（反过度工程）

信奥判题 infra · AI 凭空编数理化题 · 口语 ASR · 时间块排课日程 · 实时监控/锁屏 · **公网 Hosting 多租户账号体系** · 云 GPU 跑模型 · 微服务/Redis/外部 MQ/向量库/K8s · 默认 Postgres · 积分徽章 · 产品内引入 LangGraph/CrewAI/AutoGen 等 agent 框架。

## 🛠 技术栈

| 领域 | 选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · async · 模块化单体 |
| 数据库 | SQLite + WAL · SQLAlchemy 2 · Alembic 迁移 |
| 前端 | React 19 · Vite · TypeScript · Mantine · KaTeX · PWA |
| 内核 | **零模型**：后端不调用任何云端 VLM/OCR/文本模型，无 provider 抽象、无模型审计表 |
| 判分 | 系统只判自造同类题：运行时 `judgeAnswer` 归一化比对；**AST 白名单沙箱跑 `verify`**（题库入库时） |
| 部署 | Docker Compose 一键起；远程访问 Tailscale / Cloudflare Tunnel |
| 分发 | 开源，**每个家长自托管自己的一份**（单用户实例） |

## 🚀 快速开始（面向"会装 Docker 不写代码"的家长）

**前置**：Docker Desktop（[官网](https://www.docker.com/products/docker-desktop/)）+ 至少 2 GB 空闲内存。

```bash
git clone https://github.com/<你>/wengu.git
cd wengu
cp wengu-api/.env.example wengu-api/.env   # 可选；v2.5 零模型通常无需任何 Key
docker compose up -d --build --wait
# 前端：http://localhost:5173
# 后端健康检查：http://localhost:8000/health
# 外部 agent 转录 JSON 投递目录：./data/inbox（宿主侧）
```

> 若 `8000` 被系统保留（Windows Hyper-V 常见），改用：
> `WENGU_API_PORT=8100 docker compose up -d --build --wait`（PowerShell: `$env:WENGU_API_PORT=8100; docker compose up -d --build --wait`）。

> 国内网络建议在 Docker Desktop → Settings → Docker Engine 配置 registry mirrors（如 `https://docker.m.daocloud.io`），否则拉取基础镜像会很慢或失败。API 镜像构建默认走清华 pip 源，可用 `--build-arg PIP_INDEX_URL=...` 覆盖。

> **查库/备份先停 API**：Docker Desktop 的共享挂载下，容器运行期间从宿主机用 SQLite 读写 `data/wengu.db` 会让容器侧 WAL/SHM 失效，可能丢失尚未 checkpoint 的写入（已实测）。备份前先 `docker compose stop api`；容器运行中查库请走 `docker exec wengu-api python -c "..."`。

### 本地开发（不用 Docker）

```bash
make install-api     # 创建 wengu-api/venv（Python 3.12）并装依赖
make upgrade         # 建/升级 SQLite 到最新迁移
make dev-api         # http://localhost:8000/health
# 另开终端
make install-web     # npm ci
make dev-web         # http://localhost:5173
```

`make test` / `make lint` / `make migration-test` 分别跑测试、ruff、迁移回退测试。
Windows 上若 `make` 不在 PATH，重开终端或安装 [GNU Make](https://winget.run/pkg/ezwinports/make)（`winget install ezwinports.make`）。

## 📦 当前进度

- ✅ **P1-0 Repo 骨架**（2026-10-24）：FastAPI `/health` + SQLite WAL + Alembic 基线 + React 空壳（Mantine + KaTeX）+ Docker/CI；`docker compose up` 双服务 healthy 已实测。
- ✅ **P1-1 数据模型 + 事件溯源/幂等 + seed 装载**：事实表、只追加 `learning_events`、确定性重算、`cn-math-taxonomy` 初中子集 seed 与教材包机制。
- ✅ **P1-5 判分纪律（v2.5 收口）**（2026-10-29）：真实作业不在系统内判分/讲解（外部红笔批改 + 转录导入）。系统只判**自造同类题**：`judgeAnswer` 确定性归一化（NFKC、有理数精确、多答案分隔、坐标/单位别名/带分数/acceptableAnswers），运行时不 `eval`；`verify` 仅在题库入库时过 AST 白名单沙箱。
- ✅ **P1-6 保守入本 + 两级标签 + 派生表**（2026-10-25）：只有孩子/家长确认或申诉 `wrong` 才建错题；`category` + `concept` 受控生长；`practice_records` 隔离；复习策略纯函数（不落库、不排期）。
- ✅ **P1-7a 复习排期（用户触发，v2.5 考核优先）**（2026-10-29）：确认错题自动排首次复习、完成排下一次、连续答对毕业；到期队列按主考点推**同类题考核**（附题目/seed，不下发答案），该知识点无题则退回**原题重做（自评）**并标 `bank_gap`；覆盖偏薄（物理）仍出题只给提示；完成自评记 `student_self`、到期考核由服务端判 `system_quiz`，双来源计入掌握度（P1-11 起考核提交走独立 `/quiz` 端点）；状态从事件重放推导，幂等键防重复。
- ✅ **P1-9 最小 Web UI（v2.5 五页）**（2026-10-29）：**导入**（inbox 路径/单批上限说明 + 家长手填最小表单）/ **核对**（题目·错答·正答三栏并排 + 错因确认 + 多知识点挂载 + 主考点 `primary_topic_id`；确认成功后"待确认 N 条"即时递减）/ **错题本** / **复习考核**（到期三态：同类题作答·服务端判分 / 纸上自评 / 原题重做，另有手动组卷）/ **讲解位**（默认收起，展开只回放卷面订正与标签，不调模型）。孩子与家长看同一份界面；数学 KaTeX 渲染。旧采集/批改/讲解页已在 P1-12 随视觉栈一并删除。
- ✅ **v2.5 批改外移 + 核对页入本（批次①②③）**（2026-10-29）：外部 agent 整页拍 → 按版本化模板转录已批改错题 → `data/inbox/` 监听导入 → **核对页三栏回显（题目/错答/正答）一键确认入本**；缺正答 / 占位符的草稿不能转正；主考点与错答可空（无主考点只做原题重做自评、不排同类题考核）；建议值与确认值分来源存储；新增"练习记录"页独立回看同类题考核与变式加练（不进错题本、不排复习）。
- ✅ **P1-10 题库检索引擎**（2026-10-29）：`cn-math-taxonomy` 初中段 **2803 题**（数学 1407 / 英语 1028 / 物理 368）以 JSON 随仓库分发、运行时载入内存倒排（不进 SQLite）；`find_same_type(primary_topic_id, seed)` 同知识点 + mulberry32 固定种子取 1 题、可 `replay()`；无题知识点返回空并标 `bank_gap`（语文/化学），物理按学科总量标 `thin`；每题 `verify` 装载时过 AST 沙箱，纯数值矛盾拒载；题干/选项内联 SVG 白名单净化。
- ✅ **P1-11 同类题考核闭环**（2026-10-29）：到期推考核 / 家长手动组卷（选知识点 → 出 1..N 题）；客观/短答在页面作答、**服务端 `judgeAnswer` 判分**后写 `attempts`（`source=system_quiz`），客户端 `correct` 一律忽略；解答大题/依赖题图降级"纸上做 → 自评"（`student_self`）；题面只下发题干/选项/题型/配图 + 质量标签，**绝不下发答案/解析/verify**；考核结果计入该知识点掌握度、可整表清空、**不新建错题本条目**。
- ✅ **P1-12 零模型收口（删除票）**（2026-10-30）：整条"模型在环"旧链路退役——系统内视觉栈（采集上传 / OCR 切题 / VLM 提取）、`ai_gateway`、provider 适配层与 mock、讲解服务、HTTP 模型判分端点、`model_runs` / `ai_jobs`（迁移 **0013** DROP，可逆）、`llm_prompts/` 与只服务旧链路的评测脚本；前端删除采集 / 批改 / 讲解三页及其 API 类型。保留 `services/grading.py`（intake 依赖）、`judge/`、题库/组卷/复习/inbox/intake 全链。三绿 + 端到端实跑（导入 → 监听 → 核对入本 → 到期三态 → 手动组卷）通过。
- ✅ **P1-6 作废 / 撤销作废入口**（2026-10-30）：`POST /api/mistakes/{id}/void|unvoid` 只翻 `status` + 追加 `mistake_voided` / `mistake_reactivated` 事件（幂等键防重复），不删版本/事件；作废退出活跃列表与到期队列，撤销后未完成排期自然回到队列，历史复习作答仍按现状计入掌握度；错题详情页提供"作废/撤销作废"按钮。
- ✅ **P2-2 番茄钟执行（计时器，不是规划器）**（2026-10-31）：复习页每日队列第一项可“开始专注”——**纯前端 25 分钟倒计时**，可取消（不打点），自然完成或手动“完成”才写一条 `pomodoro_completed` 事实事件（`POST /api/pomodoros`，幂等键按 `started_at`，时长钳制 5–120 分钟，错题可空）。看板与复习页头部显示“今日番茄 / 本周专注”（`GET /api/dashboard` 新增 `pomodoros_today`、`focus_minutes_this_week`，从事件现算）。**不规划、不排程、不自动连跑、不做后台计时或通知**；番茄**不计入掌握度、不计入打卡 streak、不进错题本、不完成复习任务**。无新表/无迁移（head 仍 0015）。
- ✅ **P2-3 课表/日历约束层**（2026-10-31）：导航第 7 项「课表/日历」——家长解锁后录**每周课表**（一节一科，`weekday` 1–7 + `period` 1–12，不做 A/B 周）与**日历硬事件**（考试 / 竞赛 / 请假 / 其它，默认显示今天起 30 天），孩子只读同见；日队列页与看板头部显示“今日课程 + 未来 7 天硬事件”。**唯一影响队列的规则**：日历上今天有 `kind='exam'` 事件时，复习上限按 `exam_day_limit_factor`（`config/app-config.json`，默认 1.5、热生效、200 收口）临时放大，复习页显示提示；竞赛/请假不放宽。**不自动排课、不做时间块、不做考试科目↔知识点重排序、不做冲突检测、不从课表生成任务**；写端点全部挂 `require_parent`（未解锁 403）。迁移 **0015**（可逆）新增 `timetable_slots` + `calendar_events`。
- ✅ **P2-1 日队列（收窄口径：只组织到期复习/考核）**（2026-10-31）：`GET /api/reviews/due` 仍是纯查询，新增每日上限 `daily_review_limit`（`config/app-config.json`，默认 10、改文件即热生效、缺失回退默认）与 `due_total / returned / today_completed / daily_limit` 字段；超限项不返回只计数，排序严格“逾期 `due_date` 升序 → 今日，同组 `mistake_id`”。前端复习页显示“今日任务 x/y 完成”与“其余 M 项顺延（明天还在，不会丢）”，顺延不惩罚、不加重做、不做漏打卡焦虑 UI。背诵铺底 / 作业 deadline / 硬事件抬权重 / 时间块排课本轮未做（依赖 P2-3 与 P3）。
- ✅ **P2-6 极简打卡**（2026-10-31）：看板新增“每日打卡”卡——今日已打卡 / 今天还没打卡、连续 N 天、最长 N 天、累计学习天数、近 30 天日历条，沿用已有掌握度曲线。当天有任一作答事件（复习或自造同类题考核）即打卡，**答错也算**；学习日优先 `completed_on`（本地日期），缺失回退 `occurred_at`；今天缺席但昨天有 → 锚昨天不清零，连续两天缺席才归零。streak **绝不入库**、每次现算，只做习惯展示、不用于学习效果结论；无手动签到按钮、无写库路径、无积分/徽章/等级，孩子与家长看同一份。
- ✅ **P2-5 家长看板（观察复盘型）**（2026-10-30）：`GET /api/dashboard` + 前端 **看板** 页（导航首项），纯只读确定性统计——错题存量（活跃/已作废/未挂考点）、按知识点与学科的薄弱分布、掌握度总览 + 逐 concept + 近 30 天曲线（可调 1–90）、今日/逾期/合计到期、本周完成复习、毕业总数与本周毕业、`bank_gap` 知识点清单、申诉与作废/撤销计数、事件统计。全部从事件与排期现算、与 `recompute` 一致；端点只有 `GET`、不出网、不调模型，孩子与家长看同一份；无推送/锁屏/问责、无积分徽章。
- ✅ **P2-4 两角色 + 本地家长 PIN**（2026-10-30）：孩子区免 PIN；导航右侧"家长区"入口首次引导设置 PIN（4–8 位数字或 6–20 位字符），以 scrypt 哈希存 `user_role.pin_hash`，解锁后签发 HMAC 签名 cookie（12h）。受保护操作：**作废/撤销错题、题库导入/审核/修订（编辑+软作废）、手动组卷**；导入、核对确认、到期复习、考核、错题本与看板只读不受影响。连续 5 次错误锁 60s。**PIN 只防误入，不是安全边界**；公网暴露仍须真鉴权与隔离或走 Tailscale。会话密钥取 `WENGU_SESSION_SECRET`，缺省首启生成到 `data/.session_secret`。
- ✅ **P2-7 错题四区块 / 练习卷打印导出**（2026-10-31）：错题本“导出打印”与复习页组卷“导出练习卷”打开**无导航壳的打印视图**，用浏览器“打印 → 另存为 PDF”（零 PDF 库、零服务端文件）。错题按知识点分组、每题四区块（①原题 ②孩子作答 ③订正正答 ④错因批注，公式走 KaTeX），支持知识点/错因/日期筛选，空结果显示提示；练习卷只含题干与选项，**默认不下发答案**，末页“家长答案页”需家长解锁、单独分页、可不打印。A4 分页（知识点组另起页、题卡不跨页），入口自动携带当前筛选与 `seed` 以保证重印同一张卷。
- ✅ **P3-1 家长录题（真题入库流水线）**（2026-10-31）：家长拍**空白真题 / 教师版** → 外部 agent 按新模板 `doubao_bank_transcribe_v1` 转录 → `data/inbox/` 监听导入到 `bank_drafts` → **家长「题库审核」页逐条确认** → 写入 SQLite `problem_bank`（**不写 seed JSON**）；家长手填表单兜底。**红线：模型不得自行解题生成答案**——模板只在照片明确含答案时转录 `answer`，否则留空由家长补填，缺答案一律拒绝入库。入库统一过 AST `verify` 白名单沙箱（拒绝 `__import__`/赋值/属性访问与纯数值矛盾）、choice 答案必须命中选项、`topic_id` 必须存在于知识点 seed，入库题固定标 `unaudited=true` / `blind_verified=false`。审核与手填端点全部挂 `require_parent`（未解锁 403），孩子区导航不可见。迁移 **0016**（可逆）新增 `bank_drafts` 并给 `problem_bank` 补 `topic_id/question_type/difficulty/choices_json/figure/hide_choice_text/percent`。**P3-1b**：入库题已合并进运行时检索池，参与到期考核与手动组卷；seed 文件仍只读，旧记录跨池 `replay` 显式失败、绝不静默换题。**P3-1c**：`/bank` 页新增「已入库题目（可修订）」区——可按状态/考点筛选、行内编辑（合并后重跑同一套审核闸门）、作废/撤销作废；作废按钮只把题移出检索池（`status=voided`），**不物理删除、不改写历史 attempts/事件/排期**；编辑不改 `external_id`，内容修订不回溯。迁移 **0017**（可逆）给 `problem_bank` 补 `status` + `updated_at`。
- ✅ **P1-1b 家长自建章级 seed（语文/化学空 seed 起步）**（2026-10-31）：家长解锁后导航新增「学科 seed」页，按语文/化学录教材章级知识点（语文 `cnl_` / 化学 `cnc_`，40–80 点即止，不做细粒度树）。**JSON 文件是唯一真源**（`<data_dir>/seeds_local/topics_<学科>.json`，同目录 tmp + `os.replace` 原子写、重启后按文件恢复），SQLite `knowledge_seed` 只是装载副本。装载器按 `仓库 seed → seeds/local → data/seeds_local` 多源合并、按 id upsert 幂等；id 冲突拒绝、坏文件只告警不阻塞服务，本地行固定 `source='local'` / `unaudited=true` / `blind_verified=false`。语文/化学错题从此可挂主考点、题库可挂 `topic_id`，到期考核与手动组卷闭环打通；删除知识点会同步移除文件与行、解绑错题/题目（置 NULL，历史不动）并在确认框显示受影响计数。导出脚本同步合并 local 源，转录模板的 `suggested_topic_id` 可选到语文/化学点。**无迁移**。
- ⏳ 下一张工单：**P3-2 主动加练变式**（`practice_records`，不影响掌握度）；P0-1 样本扩容 + P1-7b 前置回溯诊断仍待做；**P1-7c 自动排复习仍受 Phase 0 闸门阻塞**。

> 完整的工单状态、实测数字、阻塞项与下一步建议见 [`docs/STATUS.md`](./docs/STATUS.md)。

## 📖 文档地图

| 位置 | 内容 |
|---|---|
| [`AGENTS.md`](./AGENTS.md) | 给 AI 编码 agent 的**施工规约与缰绳**（硬约束/已砍清单/不可动设计决定/DoD） |
| [`TICKETS.md`](./TICKETS.md) | 分 Phase 工单（P0-1 到 P5-5），每条含 目标·依赖·交付·DoD·禁止事项 |
| [`docs/STATUS.md`](./docs/STATUS.md) | 开发计划与完成情况快照（工单状态、实测数字、阻塞与下一步） |
| [`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`](./docs/specs/architecture/StudyDesk-设计说明文档-v2.md) | **唯一事实来源**（v2.5，§16 为零模型改向定稿）——16 轮拷问敲定的完整设计树 |
| [`docs/methodology/phase0.md`](./docs/methodology/phase0.md) | Phase 0 实测方法论（手写识别 & 分题型判分，历史记录） |
| [`docs/templates/`](./docs/templates/) | 外部 agent 转录模板（frontmatter `id`+`version`，改语义必递增） |
| [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md) | 第三方数据源归属（`cn-math-taxonomy` CC BY-NC 4.0） |

## ⚠️ 安全与合规

- **公网暴露前必须先加鉴权与用户隔离**，或走 **Tailscale**；wengu 默认按"本机 / 可信内网"设计。
- **本地家长 PIN 只防误入，不是安全边界**：它只挡"家长区"（作废/组卷/题库审核），孩子区免 PIN，
  也不做登录/账号/多租户。会话 cookie 用 `WENGU_SESSION_SECRET` 签名；未设置时首启生成
  `data/.session_secret`（多实例/公网部署必须显式设置）。
- 密钥只走 `.env`（已在 `.gitignore` 里）；日志**不落题目全文、答案、文件 URL、个人信息**。
- 遵守《个人信息保护法》《未成年人网络保护条例》——所有数据留在你自己家里。
- 知识点树与题库 seed 数据（若你启用 `seeds/`）**限个人非商用**，见 `THIRD-PARTY-NOTICES.md`。

## 🤝 贡献与联系

本项目当前主要服务自家孩子，欢迎其他家长自托管使用与反馈。Issue / PR 提改进建议前请先读 `AGENTS.md`——**反过度工程是硬约束**，新特性请对应到 `TICKETS.md` 里的工单，别绕过 Phase 闸门。

## 📄 License

代码：[MIT](./LICENSE)。第三方数据源归属见 `THIRD-PARTY-NOTICES.md`。
