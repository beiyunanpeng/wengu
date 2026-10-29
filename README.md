# wengu · 温故

> 面向中国初中家庭的**自托管** AI 学习工作台：错题自动归集 → 错因/知识点分类 → 跨科复习调度 → 每日任务 → 家长复盘。
> 不是又一个拍照答疑 App——那部分现成工具够好了。**wengu 做的是个性化错题闭环**，每个家庭部署自己的一份，数据不出家门。

**A self-hosted AI learning workbench for Chinese junior-high families**: auto mistake capture → knowledge tagging → cross-subject spaced review → daily task queue → parent dashboard. Every family runs their own instance; data stays home.

> 内部代号 StudyDesk。License = MIT（代码）；知识点树与题库 seed 数据来自 [`cn-math-taxonomy`](https://github.com/xiaoyang111222/cn-math-taxonomy)（CC BY-NC 4.0，**限个人非商用**），详见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)。

---

## ✨ 核心闭环

- 📸 **拍照答疑 & 作业批改**（双通道：手机拍照 → HTTP 秒传；豆包 JSON 导入兜底）
- 📕 **错题自动归集**（批改判错的自动副产品，不设独立录入任务；错题表唯一写入路径）
- 🏷️ **错因 AI 预填 + 孩子一键确认**（知识点 = 粗粒度预置 seed + 细粒度受控生长）
- 🔁 **复习调度**（固定阶梯 + 掌握度自适应间隔 + 抗挫败三规则；FSRS 留接口）
- 📖 **三段式讲解**（定位 → 引导 or 讲解 → 巩固；要答案须先动手，留痕不硬拦）
- 📅 **优先级日队列 + 番茄钟**（自动生成，课表/日历为约束层）
- 👀 **观察复盘型家长看板**（孩子见同一份；两角色 + 本地 PIN，非遥控监控）

## 🚫 明确不做（反过度工程）

信奥判题 infra · AI 凭空编数理化题 · 口语 ASR · 时间块排课日程 · 实时监控/锁屏 · **公网 Hosting 多租户账号体系** · 云 GPU 跑模型 · 微服务/Redis/外部 MQ/向量库/K8s · 默认 Postgres · 积分徽章 · 产品内引入 LangGraph/CrewAI/AutoGen 等 agent 框架。

## 🛠 技术栈

| 领域 | 选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · async · 模块化单体 |
| 数据库 | SQLite + WAL · SQLAlchemy 2 · Alembic 迁移 |
| 前端 | React 19 · Vite · TypeScript · Mantine · KaTeX · PWA |
| 任务队列 | SQLite `ai_jobs` 表 + 进程内并发 1–2 循环（**不用 Redis/Celery**） |
| 模型层 | 云多模态双供应商（**火山豆包为主 + 阿里 Qwen-VL 对照**），经 `VisionProvider` 适配层；按题型路由 |
| 判分 | 客观题 = **模型只提取 + 代码 `judgeAnswer` 归一化比对**（运行时）；**AST 白名单沙箱跑 `verify`**（入库时） |
| 部署 | Docker Compose 一键起；远程访问 Tailscale / Cloudflare Tunnel |
| 分发 | 开源，**每个家长自托管自己的一份**（单用户实例） |

## 🚀 快速开始（面向"会装 Docker 不写代码"的家长）

**前置**：Docker Desktop（[官网](https://www.docker.com/products/docker-desktop/)）+ 至少 2 GB 空闲内存。

```bash
git clone https://github.com/<你>/wengu.git
cd wengu
cp wengu-api/.env.example wengu-api/.env
# 编辑 .env，填入你的豆包/阿里百炼 API Key（P1-0 空跑可先不填）
docker compose up -d --build --wait
# 前端：http://localhost:5173
# 后端健康检查：http://localhost:8000/health
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
- ✅ **P1-2 Provider 适配层 + 成本护栏**：豆包/Qwen/DeepSeek/mock、按题型路由、预算上限、三级缓存、`model_runs` 记账；四档真实模型连通实测。
- ✅ **P1-3 / P1-3b 采集与切题**：拍照上传、豆包 JSON 兜底导入（sha256 去重）、本地 OCR 行聚类切单题；零锚点拒绝切分。
- ✅ **P1-4 结构化提取 + 质量闸门**：VLM 提取题目/作答/完整性/置信度，确定性闸门拦 `〔?〕`/残题/空作答；整页兜底恒人工复核。
- ✅ **P1-5 判分纪律（v2.5 收口）**（2026-10-29）：真实作业不在系统内判分/讲解（外部红笔批改 + 转录导入）；批改端点只回显题面并固定 `uncertain`，永不调模型。系统只判**自造同类题**：`judgeAnswer` 确定性归一化（NFKC、有理数精确、多答案分隔、坐标/单位别名/带分数/acceptableAnswers），运行时不 `eval`；`verify` 仅在题库入库时过 AST 白名单沙箱。
- ✅ **P1-6 保守入本 + 两级标签 + 派生表**（2026-10-25）：只有孩子/家长确认或申诉 `wrong` 才建错题；`category` + `concept` 受控生长；`practice_records` 隔离；复习策略纯函数（不落库、不排期）。
- ✅ **P1-7a 复习排期（用户触发，v2.5 考核优先）**（2026-10-29）：确认错题自动排首次复习、完成排下一次、连续答对毕业；到期队列按主考点推**同类题考核**（附题目/seed，不下发答案），该知识点无题则退回**原题重做（自评）**并标 `bank_gap`；覆盖偏薄（物理）仍出题只给提示；完成自评记 `student_self`、到期考核由服务端判 `system_quiz`，双来源计入掌握度（P1-11 起考核提交走独立 `/quiz` 端点）；状态从事件重放推导，幂等键防重复。
- ✅ **P1-8 三段式讲解引擎**（2026-10-26）：定位 → 引导/讲解 → 巩固；按错因预选模式，引导 1–3 级不揭晓答案；"看完整讲解"不硬拦但留痕，答疑入口复用同一引擎；质量/答案泄漏闸门 + 元数据事件。
- ✅ **P1-9 最小 Web UI（v2.5 五页）**（2026-10-29）：**导入**（inbox 路径/单批上限说明 + 家长手填最小表单）/ **核对**（题目·错答·正答三栏并排 + 错因确认 + 多知识点挂载 + 主考点 `primary_topic_id`；确认成功后"待确认 N 条"即时递减）/ **错题本** / **复习考核**（到期三态：同类题作答·服务端判分 / 纸上自评 / 原题重做，另有手动组卷）/ **讲解位**（默认收起，展开只回放卷面订正与标签，不调模型）。孩子与家长看同一份界面；数学 KaTeX 渲染。旧采集/批改/讲解页仍保留但不在导航，待 P1-12 随视觉栈一并退役。
- ✅ **v2.5 批改外移 + 核对页入本（批次①②③）**（2026-10-29）：外部 agent 整页拍 → 按版本化模板转录已批改错题 → `data/inbox/` 监听导入 → **核对页三栏回显（题目/错答/正答）一键确认入本**；缺正答 / 占位符的草稿不能转正；主考点与错答可空（无主考点只做原题重做自评、不排同类题考核）；建议值与确认值分来源存储；新增"练习记录"页独立回看同类题考核与变式加练（不进错题本、不排复习）。
- ✅ **P1-10 题库检索引擎**（2026-10-29）：`cn-math-taxonomy` 初中段 **2803 题**（数学 1407 / 英语 1028 / 物理 368）以 JSON 随仓库分发、运行时载入内存倒排（不进 SQLite）；`find_same_type(primary_topic_id, seed)` 同知识点 + mulberry32 固定种子取 1 题、可 `replay()`；无题知识点返回空并标 `bank_gap`（语文/化学），物理按学科总量标 `thin`；每题 `verify` 装载时过 AST 沙箱，纯数值矛盾拒载；题干/选项内联 SVG 白名单净化。
- ✅ **P1-11 同类题考核闭环**（2026-10-29）：到期推考核 / 家长手动组卷（选知识点 → 出 1..N 题）；客观/短答在页面作答、**服务端 `judgeAnswer` 判分**后写 `attempts`（`source=system_quiz`），客户端 `correct` 一律忽略；解答大题/依赖题图降级"纸上做 → 自评"（`student_self`）；题面只下发题干/选项/题型/配图 + 质量标签，**绝不下发答案/解析/verify**；考核结果计入该知识点掌握度、可整表清空、**不新建错题本条目**。
- ⏳ 下一张工单：**P0-1 样本扩容 + P0-2 黄金评测集**；随后 P1-7b 前置回溯诊断；**P1-7c 自动排复习仍受 Phase 0 闸门阻塞**。

> 完整的工单状态、实测数字、阻塞项与下一步建议见 [`docs/STATUS.md`](./docs/STATUS.md)。

## 📖 文档地图

| 位置 | 内容 |
|---|---|
| [`AGENTS.md`](./AGENTS.md) | 给 AI 编码 agent 的**施工规约与缰绳**（硬约束/已砍清单/不可动设计决定/DoD） |
| [`TICKETS.md`](./TICKETS.md) | 分 Phase 工单（P0-1 到 P5-5），每条含 目标·依赖·交付·DoD·禁止事项 |
| [`docs/STATUS.md`](./docs/STATUS.md) | 开发计划与完成情况快照（工单状态、实测数字、阻塞与下一步） |
| [`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`](./docs/specs/architecture/StudyDesk-设计说明文档-v2.md) | **唯一事实来源**（v2.4）——16 轮拷问敲定的完整设计树 |
| [`docs/methodology/phase0.md`](./docs/methodology/phase0.md) | Phase 0 实测方法论（手写识别 & 分题型判分） |
| [`docs/methodology/evals.md`](./docs/methodology/evals.md) | evals 黄金集与持续回归方法论 |
| [`llm_prompts/`](./llm_prompts/) | 提示词**版本化真源**（frontmatter `id`+`version`，改语义必递增） |
| [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md) | 第三方数据源归属（`cn-math-taxonomy` CC BY-NC 4.0） |

## ⚠️ 安全与合规

- **公网暴露前必须先加鉴权与用户隔离**，或走 **Tailscale**；wengu 默认按"本机 / 可信内网"设计。
- 密钥只走 `.env`（已在 `.gitignore` 里）；日志**不落题目全文、答案、文件 URL、个人信息**。
- 遵守《个人信息保护法》《未成年人网络保护条例》——所有数据留在你自己家里。
- 知识点树与题库 seed 数据（若你启用 `seeds/`）**限个人非商用**，见 `THIRD-PARTY-NOTICES.md`。

## 🤝 贡献与联系

本项目当前主要服务自家孩子，欢迎其他家长自托管使用与反馈。Issue / PR 提改进建议前请先读 `AGENTS.md`——**反过度工程是硬约束**，新特性请对应到 `TICKETS.md` 里的工单，别绕过 Phase 闸门。

## 📄 License

代码：[MIT](./LICENSE)。第三方数据源归属见 `THIRD-PARTY-NOTICES.md`。
