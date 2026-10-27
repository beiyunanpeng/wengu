# TICKETS.md — wengu 分 Phase 工单（v2.4）

每次给编码 agent **一条 ticket**，连同 `AGENTS.md` + `docs/specs/architecture/StudyDesk-设计说明文档-v2.md` 相关章节作为上下文。
**一条 ticket = 一个可跑增量 = 一次 PR，人审一次。** 每条含 目标·依赖·交付·DoD·禁止事项。
（DoD 一律含：服务能起 + 相应测试通过 + 涉模型跑 evals 回归 + 更新文档；见 AGENTS.md §8。）

> **路径说明**：以下出现的 `Phase0-实测/` 指代 wengu 仓库**外**的家长本地开发工作区（含 PII，不进仓库）；对应的仓库内方法论说明见 `docs/methodology/phase0.md`，首轮实测结论摘要在设计文档 §13。

---

## Phase 0 —— 摸底 + 回归基线（先做）
### P0-1 手写识别 + 分题型判分实测 → 《自动入库边界表》
- **状态（v2.1）**：首轮已跑（9 题 × 5 档 = 豆包 lite/pro/turbo + Qwen flash/max，45 次调用，工具在家长本地开发工作区）。**边界表本轮不能回填**——15 个 题型×供应商 组合全落"低置信/讲解"（题目识别 0.0–0.5 是主要瓶颈）。**Phase 1 全量按"待确认"保守起步**。方法论与设计映射见 `docs/methodology/phase0.md` 与设计文档 §13。
- 下一轮待办（回填边界表的前置）：①补"孩子做错"样本 ≥5 测漏判错率；②每题型样本 ≥20；③识别链路优化（`qwen3.5-ocr` 车道、豆包 `thinking.type=disabled`）；④复核其余 8 题真值。
- DoD：达成①–④后，"高置信自动"档首次出现且能回填 P1-5 配置。
- 禁止：未回填前放开自动入库 / 自动排复习。
### P0-2 evals 黄金集脚手架 + 首日填充
- 依赖：P0-1 样本。
- 交付：`evals/{import,analysis,generation,regressions}/` 结构 + 载入脚本 + **≥30 条脱敏黄金样本**（Phase 0 样本转入）+ **代码判定通过阈值** 的跑分脚本（比准确率/严重错误/延迟/费用）。
- DoD：改 prompt/换供应商/升 Schema 时可一键回归；CI 可调用。
- 禁止：只立结构不填样本（参考项目翻车点）；用 AI 自宣"通过"。

---

## Phase 1 —— 核心闭环
### P1-0 Repo 骨架
- 交付：FastAPI 应用 + **SQLite(WAL)** + `docker-compose.yml` + 目录 + 环境变量 + `/health` + 冒烟测试 + CI(lint/test) + React+Vite+TS+Mantine+KaTeX 前端空壳。
- DoD：`docker compose up` 起全栈、`/health` 200、CI 绿。
- 禁止：写业务；引入 Postgres/Redis/MinIO（默认本地卷/内嵌 SQLite）。
### P1-1 数据模型 + 事件溯源/幂等骨架
- 依赖：P1-0。
- 交付：Alembic 迁移建表——`knowledge_seed(category) / concepts + concept_aliases / mistake_versions / import_batches + ingestion_drafts / attempts / review_schedules / learning_events(append-only,UNIQUE) / ai_jobs(to_event_id水位,idempotency_key) / model_runs / user_role`；掌握度/毕业/统计的**确定性重算函数** + **幂等写入**骨架。
- DoD：迁移可 up/down + 备份说明 + **迁移测试**；重复导入/重试/重启不产生重复错题·事件·计数。
- 禁止：把易变状态存成字段（应由事实推导）；导入原文入 `model_runs` 日志。
### P1-1b 知识点 seed 装载（v2.2 改、v2.3 细化）
- 依赖：P1-1。交付：**导入外部 `cn-math-taxonomy` (CC BY-NC 4.0) 初中部分并转换 schema**——`data/topics.json` 里 `cnm_*`（数学 315）+ `cne_j_*`（英语 257）+ 初中物理 92 → `knowledge_seed.category`；`data/dependencies.json` → `prerequisite_edges`（含 hard/soft）。核心字段**直映**（camelCase→snake_case）：`id / name / domain / grade / semester / chapter / type / description / mastery_criteria / diagnostic_question / standards`（**没有** `evidence` / `assessmentPrompt`，那是 Marble 上游格式）。**高中 `grade 10–16` 语义为"册"非入学年**，需转换标注。
- **Seed 分档打标签**：`unaudited: true` 全部；**`blind_verified: true` 仅初中数学**（A/B 双轮盲解 1407 题、题库答案错 0）；**初中英语、初中物理 `blind_verified: false`**（verify 与答案同源、无二遍盲解，UI 明示"参考冷启动 + 家长复核"）。
- **化学、语文** = **复用同 JSON 契约（topics + dependencies 同款 schema），家长对课本目录录章级粗粒度 40–80 点**（`mastery_criteria` 可精简、无题、`unaudited: true`），不另找源、不自建细粒度题库。
- 教材包（`mappings/<版本id>.json` + `status: example|draft|reviewed`）：**注意 `edition-mappings.md` 里的 `mappings` 字段现网 0 条、示例文件是"不得引用"占位**——机制照抄、数据要家长自建。
- DoD：**License 署名 + 原项目 URL + NC 声明**写入 seed 包内嵌 `_source.json`；`unaudited` / `blind_verified` 透传到 UI；题目**内联 SVG 过 HTML 净化**再渲染。禁止：硬编码学科树；不署名分发；把 seed 数据塞进 SQLite（应作 JSON 文件形态随仓库分发 + 内存索引）。
### P1-2 Provider 适配层（含成本护栏）
- 依赖：P1-0。
- 交付：`VisionProvider`（`extract_problem/grade/solve_explain`）+ 豆包/Qwen-VL/（候选）腾讯 + OpenAI-compat 文本 + **mock provider**；`llm_prompts/*.md` **版本化真源**加载器（frontmatter + `{{TOKEN}}` + fail-fast）；`model_runs` 写入；**每日批量调用上限 + 内容哈希缓存 + `ai-raw/` 落盘**；性价比/旗舰分档。
- DoD：换 provider/加一家不改业务；每次运行记 provider/model/prompt_version/usage；密钥仅 env、日志无 PII/题目全文。
- 禁止：SDK 渗业务；无上限调用；把 prompt 写死在代码。
### P1-2b 供应商自动故障转移（互备落地，v2.4 补 §3 未做完的部分）
- 背景：§3 设计"至少两家、互备"，但当前 registry 是 `task → 单 provider`；实测中豆包 403 `AccountOverdueError` 直接让整条提取瘫掉，**没有自动切到 Qwen-VL**。这张把"互备"真正落地。
- 依赖：P1-2。
- 交付：
  - registry 支持 `task → 有序 provider 列表`（如 `extract_problem: [doubao, qwen_vl]`），**保留按题型路由**（题型可覆盖默认顺序，如字形默写 `[qwen_vl, doubao]`）。
  - `ai_gateway` 加**故障转移循环**：按序尝试，命中可用即返回；每次尝试都写 `model_runs`（记录尝试链：哪几家、各自结果、耗时）。
  - **错误分类**（决定要不要切备）：
    - **可转移**：403 账户/权限、402 欠费、429 限流、5xx、网络/超时 → 切下一个 provider；
    - **不可转移**：模型返回了内容但质量差 / 触发提取闸门 → **不切**（这是质量问题不是可用性问题，切了也没用、还费钱）。
  - 全部 provider 都失败才最终报错，且错误信息**区分"账户/额度/网络类"与"识别质量类"**（供 P1-9b 前端呈现）。
- DoD：把豆包设成不可用（欠费/错 key）时，提取**自动走 Qwen-VL 成功**；`model_runs` 能看到尝试链；两家都挂时报错信息能明确是"账户问题"而非"识别失败"；单测覆盖"主失败→切备成功""全失败→聚合错误""质量差不切备"。
- 禁止：引入熔断器/重试框架/agent 编排（就是有序列表 + 逐个 try）；无限重试（每家最多试 1 次、总尝试数有上限）；对内容质量做 failover；failover 逻辑渗进业务层（只在 gateway/registry）。
### P1-2c 按 task 配模型（VLM 与 OCR 分工，v2.4 试用暴露）
- 背景：现在每个 provider 只有一个 model（value/flagship 档），所有 task 共用。但 `extract_problem/grade/solve_explain` 需要**多模态 VLM**（结构化理解题目+作答），`dictation_extract`（字形默写）才是 **OCR** 的活。实测：`qwen3.5-ocr` 提取 **1/9**（不输出 problem_complete、漏手写作答）、`qwen3.8-max` **9/9**——模型类型用错就整链返回空。
- 依赖：P1-2b。
- 交付：把路由从 `task → [provider]` 扩到 **`task → [(provider, model)]`**（或 provider 默认 model + 按 task 覆盖），至少区分三类：**VLM 任务**（extract/grade/solve_explain）、**OCR 任务**（dictation_extract）、**纯文本任务**（text）。默认 extract/grade/solve_explain 走各 provider 的 VLM 档、dictation_extract 允许走 OCR 档。**全部配置驱动**（`app-config.json`/`.env`），不硬编码 if 分支。
- DoD：extract_problem 走 VLM 能返回非空 `problem_text`；dictation_extract 可走 OCR；换某 task 的模型只改配置不改代码；单测覆盖"同一 provider、不同 task 用不同 model"。
- 禁止：为每个 task 造复杂 DSL / 模型注册中心 / 框架；把 model 选择写死进业务层；给 VLM 任务配 OCR 模型（就是这次的坑）。
### P1-3 采集双通道
- 依赖：P1-0。
- 交付：**主**——手机拍照→HTTP 接收端→本地存储→`photo_capture`→触发；**兜底**——豆包 JSON 导入→确定性校验/归一→`import_batches`(sha256 去重)+`ingestion_drafts`（导入不调模型）。两条共用草稿结构。
- DoD：手机上传数秒落库；重复导入提醒。禁止：把网盘当主链路。
### P1-3b OCR 行聚类切题预处理（v2.4 新增）
- 依赖：P1-3。
- 交付：本地 OCR（PaddleOCR 或 RapidOCR，**不联网、不调 VLM**）检测整页文本行 → **按题号锚点（正则匹配"1. / 2. / 第X题"等）+ 垂直间隙聚类** → 裁切成单题子图存对象存储 → 每张子图作为一条 `photo_capture_item` 记录（关联到母 `photo_capture`）。
- DoD：双页平铺照片能切成清晰单题；**Phase 0 实测切题后再喂 VLM 的题目识别准确率显著高于整页直读**（Phase 0 主瓶颈的解药验证）。
- 禁止：把切题步骤交 VLM 做（成本 + 不稳）；无锚点情况下瞎切。

### P1-4 结构化提取（题目+作答）
- 依赖：P1-2、**P1-3b（首选输入=切好的单题子图）**；未切成功的整页走兜底 VLM 直读路径。
- 交付：`extract_problem()` 输出题目/作答/置信度；**回显用**"识别到的原文"；识别不清 `〔?〕` 占位；**`【依赖图形】` 关键词规则标记**（不调模型）。
- DoD：对边界表题型稳定产出；保留原文供回显；**提取质量前置闸门上线（v2.1 一等公民）**——题目残缺 / 含 `〔?〕` / 作答为空 → **直接路由人工，绝不进 P1-5 判分链路**。禁止：在此步判对错；对依赖图题判分。
### P1-5 批改分级闸 + 回显 + 建议/确认分离（v2.1 大改、v2.3 判分器细化）
- 依赖：P1-1、P1-4；**须依 P0-1 边界表**（本轮未回填 = **全走"待确认"保守起步**）。
- 交付：
  - **客观题（选择/填空/口算/默写）**：**模型只提取作答**，判分交给**确定性代码 `judgeAnswer`** → 匹配成功=自动入本，失败或含 `〔?〕`=转"待确认"。**运行时判卷走 `answer + accept + unordered + judgeAnswer` 规范化比对（NFKC 全/半角、多答案按 `,、；和/或` 拆分、`1/2≡0.5≡50%` 有理数精确比较、坐标、单位别名、带分数），不 eval verify；禁模型二次推理判分。**
  - **过程题（数理大解/化学方程式）**：模型给"逐步比对 + 偏保守初判"，**默认落"待确认"**，孩子核对才转正；判分波动大时可**多次采样一致性检查**。
  - **开放题**：走讲解，不进错题流。
  - **回显"识别题目+作答"** 必上；**AI 建议值 / 用户确认值分离存储 + 来源标记**（vlm/ai/student/parent）；申诉/自判改判（不重复计掌握度）；导入 JSON 提示注入防御。
  - **入库时核验**（三档核验第 2 档）：`problem_bank` 每题 `verify` Python 表达式**必须在 AST 白名单沙箱（仅四则/推导式/下标，禁 import/属性/赋值，2 s 超时）跑通 mismatch=0 才允许入库**。
- DoD：每题型行为符合边界表；孩子一键确认/纠错；申诉落库；`〔?〕` 一律走人工；`judgeAnswer` 单元测试覆盖全规范化规则；`verify` 沙箱跑通入库率 100%。
- 禁止：未回填前把任何题型当"高置信自动"入本；**让模型对客观题判分**（v2.1 Phase 0 第①类已证不可靠）；运行时 `eval verify`（沙箱仅用于离线入库核验）；**用 Python 内置 `eval()`**（必须走白名单 AST）。
### P1-6 错题本入库（唯一写入 + 两级标签 + 派生表）
- 依赖：P1-5。
- 交付：判错→自动建错题（唯一写入路径，**变式题绝不进本**）；错因候选预填+孩子确认；**粗粒度 category 挂载 + 细粒度 concept 受控生长**（优先复用已有分类、模型不覆盖确认值、归并需人工确认、alias）。**变式/加练作答写 `practice_records` 派生表**（v2.4，不进错题、不排复习、不影响掌握度、可整表清空）。
- DoD：零输入可入本；确认 ≤1 点击；可按 category/concept/错因检索；`practice_records` 有独立查询页可回看。禁止：AI 自由生成标签泛滥；设计成手录任务；把变式写入错题本。
### P1-7a 复习排期服务（用户触发，不阻塞）
- 依赖：P1-6；`review_policy.py` 纯函数（已交付）。
- 交付：
  - `0009_review_schedules.py` 迁移（表结构已在 `models/review.py`）
  - `services/review.py`：`schedule_initial()`（用户确认错题时建首次排期）、`complete_attempt()`（复习完成时写下一次排期，毕业则不生成新行）、`due_queue()`（今日到期队列）
  - `api/reviews.py`：`GET /reviews/due`、`POST /reviews/{mistake_id}/complete`
  - 集成测试：确认错题→首次排期→到期→完成→下一次排期→毕业 全链路
- **mastery 取值（v2.4 定案）**：一道错题挂多 concept 时，取所有已确认 concept 中**最小的 mastery**（保守、不放过薄弱点，与抗挫败+前置回溯哲学一致）；无 concept 挂载时 mastery=0.0。
- DoD：错题确认后自动出现首次排期；到期队列正确；复习完成后排期更新；毕业判定生效。
- 禁止：MVP 强上 FSRS；LLM 现编题挡主链；`judgeAnswer` 之外的任意 eval；**未经用户确认就建错题或排复习（那是 P1-7c）**。
### P1-7b 前置知识回溯诊断（不阻塞）
- 依赖：P1-1b（`prerequisite_edges` 已装载）、P1-7a。
- 交付：`services/diagnose.py`（Python 重写 `cn-math-taxonomy` `diagnose/engine.js` 语义，~200 行：每知识点≤2 题；第 1 对=mastered 且推断祖先掌握；第 1 错补第 2；第 2 错=weak → 未判定先修（hard 先 soft 后 DFS）压栈回溯；第 2 对=shaky 不回溯；停止条件 16 题（筛查 40）或栈空；根因 = weak 且其先修无 weak；`mulberry32` 固定种子保证 `replay(answers)` 确定性重建）+ `api/diagnose.py` + 单测（环检测/栈溢出保护/replay 确定性）。
- **与排期联动**：诊断出的根因父节点 → 若已有错题记录，其排期优先级提升；若无，作为"待补前置"进入日队列（P2-1），**不自动建错题**。
- DoD：`replay(answers)` 可完整重建；根因判定与 engine.js 语义一致；栈有硬上限。
- 禁止：回溯不设停止条件（栈会炸）；诊断结果自动建错题。
### P1-7c 自动排复习（阻塞，待边界表回填）
- 依赖：P0-1 边界表回填 + P1-7a。
- 状态：**当前被 Phase 0 闸门阻塞**，回填后按题型逐步开启。
- 交付：对"高置信自动"档题型，模型判错即建错题 + 即排复习，跳过用户确认。
- DoD：仅对边界表标为"高置信自动"的题型生效；其余仍走"待确认"。
- 禁止：边界表回填前提前实现；把"自动"扩展到未测题型。
### P1-8 三段式讲解引擎
- 依赖：P1-2、P1-6。
- 交付：定位→（引导/讲解）→巩固；默认按错因预选；引导 ≤3 级、不直接甩答案；"看完整讲解"须先动手并写 `learning_events`；答疑入口复用；语气温暖、不上积分。
- DoD：一引擎服务"错题订正"与"拍照答疑"。禁止：硬拦看答案；讲解只报最终答案。
### P1-9 最小 Web UI
- 依赖：P1-3~P1-8。
- 交付：采集 / 批改结果+回显确认 / 错题本 / 复习 / 讲解 五页最小可用（React+Mantine+KaTeX，数学渲染）。
- DoD：孩子能"拍→看批改并确认→入本→复习→卡住看讲解"走通一遍。禁止：追求美观或提前做看板/规划。
### P1-9b 前端错误呈现（区分"账户/网络"与"识别质量"，v2.4 试用暴露）
- 背景：试用时豆包欠费，前端只显示笼统的"提取失败，未产生任何结果"，把后端已返回的 `errors[].reason`（`AccountOverdueError`）藏了，逼用户开 DevTools 才知道是账单问题、误判成"识别能力不行"。
- 依赖：P1-9、P1-2b（错误分类）。
- 交付：
  - 提取/批改失败时，前端**直接显示后端 `errors[].reason`**，并按 P1-2b 的错误分类给**不同文案 + 不同处置提示**：
    - **账户/额度/鉴权类**（402/403/无 key）→ "供应商账户异常（欠费/密钥），请检查额度或配置" + 引导去设置页；
    - **限流/网络/超时类**（429/5xx/timeout）→ "供应商暂时不可用，已尝试备用；可稍后重试"；
    - **识别质量类**（含 `〔?〕`/残缺/整页未切分）→ "这张没识别清楚，请重拍或改用人工/豆包导入"（对应回显闸门的措辞）。
  - 失败项**不静默**：每张失败图显示 seq + 原因，提供"重试提取"（只补缺失，不重复计费，复用 P1-4 幂等）。
- DoD：模拟豆包欠费 → UI 直接显示"账户异常"而非"未产生任何结果"；三家全挂 → 显示尝试链摘要；质量类失败 → 走"重拍/人工"提示而非"账户"提示。
- 禁止：把内部异常栈原样吐给用户（要分类成人话）；对质量类失败提示"去充值"（误导）。

---

## Phase 2 —— 每日任务 + 收口看板
- **P2-1 日队列自动生成**：到期复习+固定背诵铺底、作业按 deadline 插入、硬事件抬权重。禁：时间块排课。
- **P2-2 番茄钟执行**：对下一项计时、完成打点入 `learning_events`。
- **P2-3 课表/日历约束层**：录入生效喂 P2-1。禁：课表当任务源主体。
- **P2-4 两角色 + 本地 PIN**：孩子默认视图 / 家长 PIN 解锁。禁：公网账号体系/多租户。
- **P2-5 家长看板（观察复盘型）**：接走所有 `learning_events`/指标，孩子见同一份。禁：实时催/锁屏/问责。
- **P2-6 极简打卡**：streak + 掌握度曲线（从事实重算）。禁：积分/徽章。
- **P2-7 错题 PDF 四区块导出打印**（原题+作答+解析+批注；按知识点/章节聚合组卷导出）。

---

## Phase 3 —— 内容与扩展（按 ROI）
- **P3-1 真题库录入流水线**：AI 帮录真题→`problem_bank`（题目/答案/知识点/难度/错因）+ 家长审核队列；入库题答案可信。
- **P3-2 组卷/加练/智能出题**：按 category/错因/难度**检索真题组卷**；回补 P1-7a 变式题源。禁：LLM 凭空编题（如开放生成需 Schema+答案唯一+学科规则+程序化复核四道校验，另立票）。
- **P3-3 英语背诵**：自评间隔重复（档③）。
- **P3-4 听力+默写**：默写复用批改；听力"教材音频+TTS"+组卷。禁：口语 ASR。
- **P3-5 语文客观并入**：字音/病句/默写并入；作文/阅读理解只走讲解不进本。
- **P3-6 信奥独立流**：卡壳→引导→"待重做清单"（复用采集）；需要时手动组卷；C++ 技能图谱 seed。禁：判题 infra、自动排复习。
- **P3-7 长期计划**：覆盖型（seed 图谱+掌握度自适应）+ 积累型（streak）；家长与 AI 共创、AI 生成后审核。

---

## Phase 4 —— 基础设施演进（孩子真在用之后）
- **P4-1 Tailscale/CF Tunnel 稳定化**（手机外网可用）。
- **P4-2 可移植部署**：Docker 镜像原样上云（搬 SQLite 文件 + 挂载卷）；Postgres 迁移为**可选**路径。
- **P4-3（可选）本地 GPU 模型层**：若购置带 N 卡主机，Qwen-VL/MiniCPM/PaddleOCR 经同一 Provider 接入做隐私/高频识别。禁：为省 API 去租云 GPU。

---

## Phase 5 —— 开源分发与打包（v2 新增）
- **P5-1 首次运行向导 + 热配置（v2.4）**：孩子/年级→勾选学科→选教材 seed→填各家 API Key→选默认档位；产出配置，不逼手改 .env。**运行时可改参数走 `config/app-config.json` 热加载、优先级高于 .env、UI 内改免重启**（wrong-notebook 模式）；密钥仍只 .env。
- **P5-2 一键备份/恢复（UI 内，v2.4 加云备份）**：**本地**导出 SQLite + 图片目录 zip / 导入恢复；**可选云备份**（KuroTutor `services/cloud_backup.py` 模式）：**AESGCM + scrypt 逐文件加密 → 每日独立 git commit 推到家长私有仓库（Gitee/GitHub）→ `git checkout <commit>` 一键回滚**；数据清空级联清理原文/派生/证据/摘要/`practice_records`。
- **P5-3 可选密码 session 鉴权开关**（默认关，供想远程暴露的家长）；README/首页**醒目警告公网须先加鉴权与隔离或走 Tailscale**。禁：做用户体系/多租户。
- **P5-4 教材 seed 包机制**：多教材 JSON/YAML 可安装可切换。
- **P5-5 开源基线**：LICENSE + 中英 README（一行安装）+ 隐私声明（数据不出户）+ CHANGELOG + `.env.example`；合规点名《个人信息保护法》《未成年人网络保护条例》。

---

## 依赖总览
P0-1 →（P1-5 档位来源；P1-7c 自动排复习的解锁条件）；P0-1 样本 → P0-2 黄金集 →（P1-2/P1-5/P3-2 的回归门）
P1-0 → 全部 P1；P1-1(+P1-1b) → P1-2 → **P1-2b（供应商自动故障转移）→ P1-2c（按 task 配 VLM/OCR 模型）** → P1-3 → **P1-3b（OCR 切题预处理）** → P1-4 → P1-5 → P1-6 → **P1-7a（用户触发排期）→ P1-7b（前置回溯诊断）** / P1-8 → P1-9 → **P1-9b（前端错误呈现，依赖 P1-2b 错误分类）** → Phase2 → Phase3 → Phase5（Phase4 任意时点，孩子用起来后；**P1-7c 自动排复习阻塞至 P0-1 边界表回填后**）
P3-1 → P3-2 →（回补 P1-7a 变式题源）
