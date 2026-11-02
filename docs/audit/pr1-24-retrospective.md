# wengu 交付回顾审计报告（PR#1–#24 / P0–P5）

> 审计日期：2026-11-02　审计对象：`main` = `e627b5f`（60 个提交、23 个已合并 PR、1 个关闭 PR#22）
> 审计人：审核方（千问办公），**不是**交付方自述的汇总
> 口径：红线逐票核 + 每票 DoD 抽查一条；提示词只给摘要与卡位（全文在 `docs/tooling/qoder-build-plan.md`）

## 0. 取证方法

三件套，缺一即标注：

1. **静态读码**：每条结论都指到 `文件:行号`，不看代理/文档怎么写。
2. **独立运行态**：审计当天自己跑，命令与结果见 §1。
3. **双向对差**：`TICKETS` 票号 ↔ `qoder-build-plan` 卡位 ↔ PR ↔ squash 提交 ↔ 盘上文件，任一环缺失即记入 §4 差异清单。

审计中修正了自己两处初判（都记下来，避免下轮重犯）：`.env.example` 不在仓库根而在 `wengu-api/.env.example`（存在，我第一遍找错位置）；`app/judge/verify_sandbox.py` 里的 `_eval` 是自定义 AST 遍历器的方法名、不是内置 `eval()`，且 `tests/unit/test_verify_sandbox.py::test_no_builtin_eval_or_exec` 把这条红线钉成了测试。

## 1. 运行态证据（审计方本机实跑，非代理自述）

| 命令 | 结果 |
| --- | --- |
| `ruff check --no-cache .`（wengu-api） | All checks passed |
| `pytest -q`（全量） | **397 passed** in 154s |
| `pytest --collect-only -q` 分层 | unit **266** + integration **131** + e2e **0** = 397 |
| `npm run build`（wengu-web） | ✓ built in 5.36s（仅既有 chunk 体积告警） |
| 文档自述对照 | STATUS.md 头部写 **397 passed** —— 与实跑一致 |

`e2e` marker 在 `pyproject.toml` 已声明但**零用例**，见 §4-A5。

## 2. 七条红线逐条核对

| # | 红线（出处） | 盘上证据 | 判定 |
| --- | --- | --- | --- |
| R1 | 内核零模型、系统内不调任何模型（AGENTS §4 / 设计 §16-B） | `app/providers/` 与 `llm_prompts/` 已不存在；全 `app/` 内 `model_runs`/`VisionProvider`/`solve_explain`/`openai`/`dashscope` 零命中；`app/` 内无 `httpx.`/`requests.`/`urllib` 出网点；迁移 `0013_drop_model_tables.py:35-38` DROP 两张表 | **通过** |
| R2 | 错题唯一写入路径 = 核对页确认（AGENTS §6） | `Mistake(` 全仓只出现在 `app/services/mistakes.py:230`；上游只有 `app/services/intake.py:346`（`persist_grading`）与 `:361`（`append_user_decision`）；`intake.py:8` 注释即"不另开建错题旁路"；`promote_draft` 的闸门在 `intake.py:302-305`（`standard_answer_missing`） | **通过** |
| R3 | 考核/组卷响应绝不下发 `answer/explanation/verify`（AGENTS §5 / 设计 §16-D） | `app/schemas/quiz.py:34-48` 的 `QuizQuestionView` 字段只有 `question_id/topic_id/subject/type/difficulty/prompt/choices/figure/mode/seed/pool_size/quality`；家长答案页单独端点 `app/api/quizzes.py:199-201` 挂 `require_parent`；前端 `answer` 出现处（`QuizQuestionCard.tsx:85,149`、`PracticePage.tsx:45,86`）都是**孩子自己的作答**，不是正答 | **通过** |
| R4 | 事实源 append-only + 幂等 + 确定性重算（AGENTS §5） | 触发器模板 `migrations/versions/0002_p1_1_core_schema.py:30`（`BEFORE {action} ON {table}`）+ `:280-281` 的 UPDATE/DELETE guard，`0007_grading.py:35`、`0008_mistakes_practice.py:33` 同构；`UNIQUE(idempotency_key)` 在 `0002:48` | **通过** |
| R5 | 两角色 + PIN 只挡家长区、且**不是安全边界**（AGENTS §2.4 / 设计 §16） | 已挂 `require_parent`：`backup/bank/local_seed/mistakes/problem_bank/quizzes/schedule/session`；未挂的 9 个（`attempts/concepts/dashboard/health/imports/pomodoro/practice/reviews/seed`）逐一核过均为设计上的孩子区或纯只读；PIN 实现 `app/services/session.py:75-79`（scrypt + 参数内嵌）、`hmac` 签名 cookie、`LOCK_SECONDS=60` | **通过**，一处语义待拍板（§4-A6） |
| R6 | 加练/变式不得影响掌握度·排期·streak（AGENTS §5 practice 细分） | `app/services/practice.py` 内 `record_event`/`Attempt`/`review`/`schedule`/`recompute` **零命中**；`app/services/streak.py` 只有纯函数 `summarize_streak(events, today)`（无 session、无 add） | **通过** |
| R7 | seed 与题库以 JSON 随仓库分发、SQLite 只存动态数据、绝不回写 seed 文件（AGENTS §3/§5） | `app/` 内无任何写 `seeds_dir`/`topics.json` 的路径；家长题只进 `problem_bank`（`services/bank.py` 运行时合并、`reset_bank_cache` 失效）；家长自建点写 `<data_dir>/seeds_local/`（`services/local_seed.py`），与仓库 seed 物理隔离 | **通过** |

作废票删净复核：`preprocess/ocr.py`、`services/slicer.py`、`services/extraction.py`、`api/captures.py`、`api/extractions.py`、`api/gradings.py` **六个文件全部不存在**；P1-8 讲解引擎已退役为前端默认关的"讲解位"（`components/ExplanationSlot.tsx:49,98-99` 明示"系统不生成讲解、不调用模型，只回放卷面订正"），无死代码残留。

## 3. 工单台账

### 3.1 v2.5 主链（批次①–⑧，PR#1–#8，有卡）

| 票 | 卡位（`qoder-build-plan.md`） | PR | squash 提交 | 抽查的 DoD 与盘上证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 批次① P1-1 增量 | :11 | #1 | `2dae796` | `migrations/versions/0011_*.py:33-37` 三列两索引（`attempts.source/problem_bank_id`、`mistakes.primary_topic_id`） | 通过 |
| 批次② P1-3d 监听导入 | :52 | #2 | `7f92de1` | `services/inbox.py:85` `ingest_raw_payload`、`:49` 5s 写稳窗口、`:51` `.processed/` 归档、`:297` 文件名排序保确定性 | 通过 |
| 批次③ P1-6 核对页入本 | :69 | #3 | `def01af` | `services/intake.py:273` `promote_draft`、`:302-305` 缺 `standard_answer` 拒转正；口径按 §16 放宽（`e166aef` 文档修正） | 通过 |
| 批次④ P1-10 检索引擎 | :88 | #4 | `bea5a85` | `services/bank.py:376` `mulberry32`、`:395` `find_same_type`、`:72/434` `pool_ids` 身份、`:54` `BankReplayError` | 通过 |
| 批次⑤ P1-5+P1-7a | :104 | #5 | `3d3e72f` | `judge/normalize.py:131` NFKC、`:379` `judge_answer`；`services/review.py:74-75` `student_self/system_quiz` 与 `quiz/self_eval/redo` 三态 | 通过 |
| 批次⑥ P1-11 考核闭环 | :126 | #6 | `576d73a` | `services/review.py:1059` 可答题"客户端只传作答、`correct` 由服务端判"、`:1095-1105` `judge_answer` → `judged_correct` | 通过 |
| 批次⑦ P1-9 五页 UI | :152 | #7 | `2948c66` | `wengu-web/src/pages/` 现有 14 页（含打印两页）；同源 `/api` 代理 | 通过 |
| 批次⑧ P1-12 退役删除票 | :169 | #8 | `ecc5cfc` | §2 末"六文件全部不存在" + `0013` DROP；删除范围与卡内清单一致 | 通过 |

### 3.2 P2（PR#9–#16，有卡）

| 票 | 卡位 | PR | 提交 | 抽查证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 补票 B 作废/撤销 | :213 | #9 | `b6ff167` | `services/mistakes.py:230` 唯一构造点未被旁路；作废走事件追加 | 通过 |
| P2-5 家长看板 | :226 | #10 | `355cbcc` | `api/dashboard.py` 无 `require_parent`（只读、孩子见同一份）；测试含 patch socket 证不出网 | 通过 |
| P2-4 两角色 + PIN | :239 | #11 | `72b2a69` | `services/session.py:75-79` scrypt、`:17` hmac、`:39` 60s 锁 | 通过 |
| P2-6 极简打卡 | :256 | #12 | `a2b3ec4` | `services/streak.py:82` 纯函数、无写路径 | 通过 |
| P2-1 最小日队列 | :269 | #13 | `cc5c0bd` | `services/review.py:184-188` `coverage/bank_gap/quiz/coverage_hint` | 通过（范围按卡收窄：只做到期复习） |
| P2-3 课表/日历 | :283 | #14 | `fbe7116` | `services/review.py:920-936` 考试日 `round(cap × factor)` 且仍受 200 收口 | 通过 |
| P2-2 番茄钟 | :298 | #15 | `8d41dac` | `services/pomodoro.py:45` clamp、`:90` 幂等键 `pomodoro:{秒}` | 通过 |
| P2-7 导出打印 | :312 | #16 | `2d7c3f8` | `package.json`/`requirements.txt` 零 PDF 依赖；`api/quizzes.py:199-212` 答案页单独挂 PIN | 通过 |

### 3.3 P3 + P5（PR#17–#24，有卡）

| 票 | 卡位 | PR | 提交 | 抽查证据 | 判定 |
| --- | --- | --- | --- | --- | --- |
| P3-1a 家长录题 | :336 | #17 | `981b2f0` | `judge/verify_sandbox.py` AST 白名单（无内置 eval，且有 `test_no_builtin_eval_or_exec` 钉住）；`bank_drafts` 迁移 0016 | 通过 |
| P3-1b 运行时题池 | :353 | #18 | `ad68371` | `services/bank.py` `get_runtime_bank` + `pool_ids` 身份比较 | 通过 |
| P3-1c 编辑/软作废 | :366 | #19 | `cc48999` | 迁移 0017 `status`；`api/bank.py` 路由级 `require_parent` | 通过 |
| P3-8 家长自建 seed | :379 | #20 | `0d12f5f` | `seed/loader.py` 多源装载 + 跳过下划线文件；`services/local_seed.py` 原子写与解绑 | 通过 |
| P3-2 主动加练 | :398 | #21 | `539bac3` | R6 全项 | 通过 |
| （混票事故） | — | **#22 已关闭** | `aa861b7` | P3-2d 与 P5-2 挤进同一提交；已拆分重开，`refs/pull/22/head` 保留 | 不适用 |
| P3-2d 幂等硬化 | :419 | #23 | `e866fc7` | 迁移 0018 部分唯一索引；`_id_counters.json` fail-closed；`pyproject` isort pin | 通过 |
| P5-2 备份 v1 | :437 | #24 | `ad67f30` | `services/backup.py:299-317` 四重路径校验；`api/backup.py:32` 路由级 PIN；6 条集成测试含并发快照 | 通过（三项剩余见 §5） |

### 3.4 v2.5 之前的直推提交（**无卡、无 PR**，多数已被作废或重做）

| 票 | 提交 | 命运 |
| --- | --- | --- |
| P1-0 repo 骨架 | `ce496e0` | 存活 |
| P1-1 数据模型 + 事件溯源 | `45d4e3b` | 存活（批次① 在其上加列） |
| P1-1b 知识点 seed 装载 | `25c9370` | 存活（批次① 后由 P3-8 扩多源） |
| P1-2 provider 适配 + 成本护栏 | `fb8c3ec` | **已废**（P1-12 删除） |
| P1-3 / P1-3b 采集双通道 + OCR 切片 | `9f9ae93` | **已废** |
| P1-4 系统内结构化提取 | `7853f78` | **已废**（能力移到 `docs/templates/`） |
| P1-5 批改分级闸 + P1-6 保守入本 | `dbee72c` | **改造**（批次③⑤ 重做） |
| P1-7a 复习排期 + P1-9 最小 UI | `5121d1b` | **改造**（批次⑥⑦ 重做） |
| P1-8 三段式讲解 | `a9a84db` | **退役**为默认关的讲解位 |
| P1-2b / P1-2c 供应商互备 + 按 task 配模型 | `5e9e38f` | **已废**（TICKETS 作废清单在册） |
| P1-3b 锚点切片修复 | `2384f43` | **已废** |
| P1-3c 配图切片 | `a249c8d` | **已废** |

这一段是审计中最容易被误读的地方：**同一票号在 v2.5 前后各交付过一次**（P1-5 / P1-6 / P1-7a / P1-9 / P1-1b）。按票号回溯会一眼以为"这票做了两遍"，实际是第一遍被架构改向作废或改造。台账因此按"票号 × 版本代次"分列，见 §4-C2。

## 4. 与设计的差异清单

### A 类：设计有、盘上没有（真缺口）

| # | 缺口 | 设计/规约出处 | 盘上事实 | 影响 |
| --- | --- | --- | --- | --- |
| A1 | **PWA 未做** | AGENTS §3 技术栈明列"React + Vite + TS + Mantine + KaTeX + **PWA**" | `wengu-web/public/` 不存在；`index.html`/`vite.config.ts` 无 manifest；无 `vite-plugin-pwa`/`workbox`/`registerSW` | 手机"添加到主屏幕 + 离线壳"没有；当前只是普通网页，家用场景可接受但与设计不符 |
| A2 | **英文 README 缺** | AGENTS §7"LICENSE + **中英 README** + 隐私声明 + CHANGELOG + `.env.example`" | 只有 `README.md`（全中文，13 个二级标题无英文段） | 开源分发受众受限；STATUS 自述过实（见 B1） |
| A3 | **独立隐私声明文档缺** | AGENTS §7 同上；设计 §6 | 无 privacy 文档；`README.md:116-123` 有"安全与合规"一节并点名两法 | 半满足——内容在、载体不在 |
| A4 | **P0-2 evals 黄金集空** | AGENTS §5"三档核验模式…改 prompt/换供应商/升 Schema/导入外部数据**必跑**"；TICKETS P0-2 DoD"≥30 条脱敏黄金样本 + 跑分脚本" | `evals/` 目录零文件 | 转录模板 `doubao_transcribe_v1` 后续被扩展（语文/化学点、`topics_junior.tsv` 重生成 665 行）**没跑过任何回归**；改模板等于裸改 |
| A5 | **e2e 零用例** | AGENTS §8 DoD"单测/集成/**E2E**"；`pyproject.toml` 声明了 `e2e` marker | `pytest -m e2e` → 0 collected（397 deselected） | 端到端只在批次⑧当时手工验过一次，不可重放 |
| A6 | **知识点"归并"没有 UI** | AGENTS §6"细粒度受控生长（优先复用·不覆盖确认值·**归并需人工确认**）" | `POST /api/concepts/merge` 后端存在（`api/concepts.py:123`），前端 `endpoints.ts` 只调 `GET /api/concepts`(:161) 与 `POST /api/concepts`(:170)，**merge 零调用** | 受控生长只交付了"新建/复用"半条腿；归并能力悬空。另：这两个 concepts 写端点未挂 `require_parent`，孩子区可直接建点——按"PIN 不是安全边界"不算漏洞，但"谁能建/并知识点"是产品语义，需你拍板 |
| A7 | **P5-1 首次运行向导未做** | AGENTS §7"受众是能装 Docker 的半技术家长…不逼手改 .env" | 无向导；`README.md:47` 仍让人 `cp .env.example .env`；原生跑要自建 venv | 开源分发路径的真瓶颈 |
| A8 | P1-7b 前置回溯诊断未做 | TICKETS P1-7b（明标"不阻塞"） | 未实现 | 计划内，不算债 |
| A9 | **`wengu-web/README.md` 整篇是脚手架时代的假文案** | 该文件自称前端权威说明 | 页面清单只列 6 页（实际 14）；"规划中（未实现）：`/dashboard` 看板（P2-5）"——**P2-5 早已交付**；目录约定列了 `public/`（PWA manifest + sw.js）、`src/hooks`、`src/stores`、`src/router`、`src/assets` **五个不存在的目录** | 误导程度最高的一份文档：新 agent 读它会以为 PWA 已做、看板未做。已于 2026-11-02 按盘上事实重写 |

### B 类：文档自述与盘上不符（过实/过期）

| # | 位置 | 说法 | 事实 | 处置建议 |
| --- | --- | --- | --- | --- |
| B1 | `docs/STATUS.md:759` | "开源基线：LICENSE / **中英 README** / 安全合规声明 / CHANGELOG / `.env.example` 已就位" | 英文 README 不存在；隐私是 README 一节而非独立文档 | 改成"中文 README 已就位（英文待补）"，别写"中英" |
| B2 | `docs/STATUS.md:106` | Phase 5"部分完成…`.env.example` 已就位" | **说法成立**（在 `wengu-api/.env.example`），但路径易被误读为仓库根 | 补一句路径 |
| B3 | 表清单 | — | `photo_captures` / `photo_capture_items` 两张表仍在（`models/ingestion.py:21,40`），业务代码**零引用**——v2.5 视觉栈退役后的孤儿表 | 出一张可逆迁移删表（或明确保留理由），并记进 STATUS |
| B4 | CHANGELOG P3-8 条目 | "被删序号会被 `next_local_id` 复用"列为残留风险 | 已被 P3-2d 的 `_id_counters.json` 关闭 | **本轮已修**（`e627b5f`） |

### C 类：治理瑕疵（不影响功能，影响可回溯性）

1. `TICKETS.md:49` 与 `:51` **重复的 `### P1-2` 标题**（前一个是空节）。
2. 同一票号跨 v2.5 两代交付，台账未区分代次（§3.4 已补，建议 STATUS 也补）。
3. 票号漂移（提交叫 P3-9 / CHANGELOG 叫 P3-2d；本地章级 seed 误挂 P1-1b）——**本轮已统一**（`e627b5f`）。
4. `gh pr merge --delete-branch` 多次未真删远端分支，一度攒 20 个（已 prune）；每张 PR 合完须确认远端。
5. PR#22 混票事故 → 已立"一票一分支 + 审核期冻结"纪律并写进工单合集附录。

## 5. 未开工 / 剩余项（对照 TICKETS 全量）

- **P5-2 剩余**：在线导入 UI、可选加密云备份与回滚、清空级联清理。
- **P3-2 残留**：组卷按错因/难度/category 筛选；「再练一组」不保存上一组身份用于重放。
- **未启动**：P0-1（新口径：外部转录质量实测）、P0-2、P1-7b、P3-3 英语背诵、P3-4 听力+默写、P3-5（仅剩题库内容接入，前置已交付）、P3-6 信奥流、P3-7 长期计划、P4-1 Tailscale、P4-2 可移植部署、P4-3 本地模型（可选）、P5-1、P5-3 鉴权开关、P5-4 教材包、P5-5 剩余（英文 README、独立隐私声明、发布打包）。
- **作废不实现**：P1-2b、P1-2c、P1-3b、P1-3c、P1-4、P1-7c（TICKETS 作废清单在册，盘上已核实删净）。

## 6. 建议的处理顺序

1. **先清 B/C 类**（一张 doc-only 票 + 一张小迁移票）：改 STATUS 的"中英 README"过实说法、删 `TICKETS.md` 重复标题、孤儿表出迁移 0019（可逆、含备份说明）。成本半天，收益是回溯不再骗人。
2. **A5 e2e 三条**（导入→核对入本→到期考核→打卡→看板；作废→撤销；备份导出→快照一致）。内核零模型后，回归面就是**流程本身**，比补 evals 更值钱，且能把空转的 `e2e` marker 用起来。
3. **A7 P5-1 首次运行向导**：决定这项目是"我自己家用"还是"别的家长也能装"。要开源分发，这是第一块短板。
4. **A2/A3 英文 README + 独立隐私声明**：跟 P5-1 同一张分发票做掉最省。
5. **A1 PWA**：建议**降级为明确不做或写进 §12 反清单**——单家庭内网部署，PWA 的离线收益接近零，留着只会一直欠债。这是设计自我矛盾的地方，值得你拍板删。
6. **A6 concepts 归并**：要么补 UI（并在设计上明确"归并 = 家长动作"），要么在 TICKETS 里把这条承诺改成"归并只由维护者经后端 API 手工执行"。别让它悬在设计文档里当已交付。
7. 之后回到功能线：P3-3/P3-4（自家孩子价值最高）。

## 7. 本审计的局限（别把这份报告当全量验收）

- DoD 是**抽查**（每票一条），不是逐条；抽查未覆盖的票包括 P1-9b（导入校验错误呈现）、批次②③的字段长度与提示注入防御细节、P2-5 的曲线逐日回放算法。
- 运行态证据来自本机实跑 + 各 PR 的 GitHub CI；**本轮未做浏览器冒烟**（历次单票验收时做过，报告不重复引用其结论）。
- 未审 seed/题库 JSON 的**内容质量**（`unaudited` / `blind_verified` 标签已确认透传到 UI，数据本身按设计"家长复核"）。
- 路径遍历只做静态审 + 现有测试面，未做穷举式 fuzz。
- 结论有效期到 `main = e627b5f`。

## 8. 裁决记录（报告交付同日，用户拍板 + 审计方判断）

| 项 | 裁决 | 落点 |
| --- | --- | --- |
| **A1 PWA** | **砍掉**。原动机（安卓/iPad 拍题）已被 v2.5 架构改向消解——拍照与转录都在系统外，手机对 wengu 只剩"看题/答题/核对/手填"，普通浏览器全覆盖；数据只在服务端，离线壳无价值；"添加到主屏幕"不依赖 manifest。真需求换名重登记为 **P4-1（可达性）** 与 **P1-3e（投递入口）** | 设计文档 §17-A + §12 反清单 + AGENTS §3 + README 技术栈表 + `wengu-web/README.md` |
| **A6 concepts 归并** | **补 UI**，并定语义：归并 = 家长动作（挂 `require_parent`），建点/复用仍留孩子区 | 新票 **P1-13**（TICKETS + 施工卡） |
| **A2/A3 英文 README、独立隐私声明** | 归入 **P5-5** 未完结部分，与 P5-1 分发票一起做 | STATUS §10 的 P5-5 行已改为"部分完成 + 仍缺什么" |
| **处理顺序** | P5-6 口径清理 → P0-3 端到端回归 → P5-1 分发（含英文 README/隐私声明）→ P1-3e 移动端投递 → P1-13 归并 UI → 回功能线 P3-3/P3-4 | STATUS §1"下一步" + 工单合集"待投工单卡"段 |

四张新票（P0-3 / P1-3e / P1-13 / P5-6）已在 `TICKETS.md` 登记、并在
`docs/tooling/qoder-build-plan.md` 末尾配好可直接复制的施工卡；本轮只落文档，未动任何代码。

审计方在裁决 A1 前额外核过两条事实，避免把"该砍"建立在感觉上：`POST /api/imports` 端点确实已存在且
前端已在用（`api/imports.py:144`、`endpoints.ts:252`），所以移动端投递缺的只是入口 UI 而不是整条链路；
`index.html` 有 viewport meta、Mantine 自带响应式栅格，所以窄屏不是 PWA 才能解决的问题。
