# Qoder 施工计划 · v2.5（MVP 8 批 + P2/P3 存档 + 待投卡与投单前言，每卡可直接复制）

> **本文件是唯一有效的批次工单**——每张卡都已内联"读哪些文件 + 全局护栏 + 验收口径"，**复制整段贴给 Qoder 即可，无需再补任何上下文**。（聊天记录里的旧版含已作废的 `primary_concept_id` 写法，别用。）
> 结构：**上半部 = MVP 八批**（批次①~⑧，已全部合并）；**中部 = P2 批次存档**（补票 B + P2-5/4/6/1/3/2/7，PR#9–#16 已全部合并）；**下部 = P3 批次存档**（P3-1a/1b/1c/8/2/2d + P5-2，PR#17–#24 已全部合并）+ 投单纪律附录。三段都只是**已交付工单的存档**，保留决策/边界/红线/DoD 供追溯与重建，不是待办。
> 依据：`TICKETS.md`（v2.5）+ 设计文档 §16 + `AGENTS.md` 顶部 v2.5 横幅 + 真实 `app/models/*` 读码校准。冲突以设计文档 §16 为准。
> 统一口径（全卡一致）：主考点列 = `primary_topic_id`（FK `knowledge_seed.id`，如 `cnm_042`）；作答来源 = `attempts.source ∈ {student_self, system_quiz, manual}`；闭环同类题考核复用 `attempts`、**不建 `quiz_attempts`**；主动加练变式走 `practice_records`；导入通道 `channel="agent_transcribe_v1"`（兼容旧 `doubao_json`）。
> 顺序：①→②→③→④→⑤→⑥→⑦→（家用跑顺）→⑧。每批一个 PR，人审"实际 diff 范围 + 运行态证据 + DoD"三件事，全绿再进下一批。

---

## 批次① —— 数据模型增量

```
你在 wengu 仓库工作。开工前先完整读三处并以其为准：仓库根 AGENTS.md（尤其顶部"v2.5 流程改向"横幅 + §2/§4/§5/§6）、
docs/specs/architecture/StudyDesk-设计说明文档-v2.md 的 §16、TICKETS.md 的 P1-1。
【全局纪律】一条 ticket = 一个可跑增量 = 一个 PR；交付附运行态证据（实跑输出/迁移升降/端到端），不接受"测试通过"空话。
本票是"加法式"schema 增量，禁止删除或改动旧视觉栈（preprocess/ocr.py、services/slicer.py、services/extraction.py、
api/captures.py、api/extractions.py、providers/{doubao,qwen_vl,tencent,failover,http,openai_vision}.py、llm_prompts/、
model_runs）——它们统一留到最后一票 P1-12 清理。禁止引入新依赖/框架。不改判分/复习业务逻辑。
【现状·按此别按旧描述】Mistake.source_grading_id→grading_results 的链（draft→GradingResult(source_kind='ingestion_draft')
→确认 wrong→Mistake）已存在且合法，不要改 Mistake 来源结构；standard_answer 等是"进 normalized_json 的归一化字段"、
不是数据库列；GradingResult/MistakeVersion 已有 standard_answer，复用勿重复造。

【任务：迁移加在 0010 之后 + 归一化契约 + 模型字段】
A) 新增迁移 migrations/versions/0011_v25_intake_and_quiz.py：
   revision="0011_v25_intake_and_quiz"，down_revision="0010_model_run_attempts"；SQLite 加列一律 op.batch_alter_table，
   升/回退前 inspect 列/索引是否存在、可重复执行（照 0010_model_run_attempts.py 写法）。
   1. 表 attempts：加 `source TEXT NOT NULL server_default 'manual'`（student_self=原题重做自评 /
      system_quiz=系统判同类题考核 / manual=历史与手录；既有行回填 manual）；加 `problem_bank_id INTEGER NULL`
      外键→problem_bank.id ON DELETE SET NULL + 索引（system_quiz 溯源题库题，student_self 可空）。
      不要新建 quiz_attempts 表——闭环考核记在 attempts（掌握度唯一事实源，另起表会让 recompute 双读、破坏确定性重算）。
   2. 表 mistakes：加 `primary_topic_id TEXT NULL` 外键→knowledge_seed.id ON DELETE SET NULL + 索引
      （检索同类题的主考点；多对多仍走 mistake_versions.confirmed_concept_ids_json，二者不冲突）。
B) services/ingestion.py（非迁移）：FIELD_LIMITS 加 standard_answer(500)/verify(200)/error_cause_suggestion(50)/
   suggested_topic_id(40)；channel 接受 "agent_transcribe_v1"（兼容旧 doubao_json）；validate_and_normalize 把它们写进
   normalized_json；standard_answer 为空 或 student_answer 为空 → is_incomplete=True；含〔?〕 → has_placeholder=True。
   仍不调模型、坏项逐条进 errors、超长不截断。
C) app/models：Attempt 补 source/problem_bank_id、Mistake 补 primary_topic_id，与迁移一致；只加字段，
   不改"怎么用"的服务逻辑（那是批次②③④⑤⑥）。

【DoD（要运行态证据）】1. alembic upgrade head 到 0011 成功；downgrade -1 回 0010 干净、可重复 upgrade 不报错。
2. 内存 SQLite 最小 pytest：建 attempts(source='system_quiz', problem_bank_id=…) + mistakes(primary_topic_id='cnm_042')
   能读回；旧数据回填 manual 不冲突。3. 缺 standard_answer 的非法报文经 validate_and_normalize → is_incomplete=True
   且进 normalized_json。4. migrations/README.md 备份/回退段补一行（照 0010 风格）。5. 全量测试不破
   （recompute/review 把新列当"读时忽略"）。
【禁止】不手改生产 db；不动 learning_events 的 UPDATE/DELETE 触发器守卫；不新建 quiz_attempts；不改 Mistake 来源结构；
不碰旧视觉栈；迁移含可回退 downgrade + 备份说明（AGENTS §8）。
```

---

## 批次② —— 监听目录导入引擎（主入本通道）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（顶部 v2.5 横幅 + §5）+ 设计文档 §16 + TICKETS.md 的 P1-3d。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据，不接受"测试通过"空话。禁止删除/改动旧视觉栈
（ocr/slicer/extraction/captures/extractions、providers/{doubao,qwen_vl,tencent,...}、llm_prompts、model_runs）——留到 P1-12。
禁止引入新依赖/框架。
【任务】wengu 后台扫描 data/inbox/ 目录的 *.json → 复用 services/ingestion.py 的 validate_envelope/validate_and_normalize
（standard_answer 缺失或含〔?〕 → 只进草稿、拒绝自动转正）→ 建 import_batches（sha256 对原始报文去重、重复导入返回
duplicate=true）→ 落 ingestion_drafts → 处理完的源文件归档到 data/inbox/.processed/。导入全程不调模型、不自动转正。
【DoD】放一份合法 JSON 进 inbox → 秒级生成草稿、返回 accepted_count/errors[]；同一文件再投命中去重（duplicate=true）；
坏项逐条报 index/field/reason、不静默截断超长；服务停机期间文件不丢、重启后补处理。
【禁止】导入时判分 / 建错题 / 自动转正。
```

---

## 批次③ —— 核对页确认 → 入本

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（顶部 v2.5 横幅 + §5/§6）+ 设计文档 §16 + TICKETS.md 的 P1-6。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
统一口径：主考点列 = primary_topic_id；闭环同类题考核复用 attempts、不建 quiz_attempts。
【任务】核对页把草稿的"题目 + 错答 + 正答"并排回显 → 家长/孩子一键确认 → 走唯一写入路径建错题（来源链
GradingResult(source_kind='ingestion_draft')→Mistake，不改结构）；standard_answer / 错因 / 知识点按"AI 建议值→确认值"
分来源存（冲突不静默覆盖）；尽量指定 primary_topic_id（主考点，可空）。知识点：粗 seed 挂载 + 细粒度受控生长
（优先复用、不覆盖确认值、归并需人工确认、alias）。主动加练变式 → practice_records。
转正闸门（v2.5 定稿）：standard_answer 必填、problem_text 必填；primary_topic_id 可空（缺则仍入本、存 NULL）；
student_answer 可空（整题没做也算错题）；但任一字段含〔?〕占位符一律拒绝转正（看不清须重拍，区别于"留空"）。
【DoD】一条转录错题确认 ≤1 点击入本；无 primary_topic_id 仍入本、只是不排同类题考核（复习退回原题重做自评
student_self）；缺 standard_answer 或含〔?〕 → 拒绝转正；practice_records / attempts 有可回看查询页。
【禁止】AI 自由生成标签泛滥；把变式/考核写进错题本；无用户确认静默入库。
```

---

## 批次④ —— 题库检索引擎（同类题地基，Phase 3 提前）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§2 反过度工程/§3 seed 数据形态/§5）+ 设计文档 §16 + TICKETS.md 的 P1-10。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
【任务】把 cn-math-taxonomy 的 questions.json 初中段（数学 1407 / 英语 1028 / 物理 368）载入内存索引
（不进 SQLite，守 §14 数据形态），建 topic_id → [题] 倒排；实现 services/bank.py：
find_same_type(primary_topic_id, seed) —— 同 topicId + mulberry32 固定种子、可 replay()；
覆盖不足（含语文/化学=0、物理薄）→ 返回空 + bank_gap=true；bank 每题 verify 在入库时过 AST 白名单沙箱核验（复用 P1-5）。
【DoD】给一个 cnm_* 主考点 + 固定种子 → 稳定返回同 topicId 题目、可重放；给无题知识点 → 明确"无同类题 + 缺口标记"；
题目内联 SVG 过 HTML 净化再渲染。
【禁止】LLM 编题；把题库塞进 SQLite。
```

---

## 批次⑤ —— 判分器作用域收缩 + 复习"考核优先 / 重做兜底"

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§5 判分/复习纪律）+ 设计文档 §16 + TICKETS.md 的 P1-5、P1-7a。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
统一口径：attempts.source ∈ {student_self, system_quiz, manual}；主考点 = primary_topic_id。
【任务】
- judgeAnswer 只做确定性归一化比对（NFKC 全/半角、多答案按 ,、；和/或 拆分、1/2≡0.5≡50% 有理数精确比较、
  坐标/单位别名/带分数、acceptableAnswers 别名），运行时不 eval；bank verify 仅入库时过 AST 白名单沙箱。
- 复习 due_queue() 对每道到期错题：先按 primary_topic_id 检索同类题（P1-10）→ 命中推"同类题考核"、
  未命中退回"原题重做（自评 student_self）"并标 bank_gap。
- 口径：只有 coverage="gap"（该知识点 0 题，如语文/化学）才触发"退回原题重做"；coverage="thin"
  （物理 368<500 的软提示）仍正常出同类题、只是给 UI 一个"覆盖偏薄"提示，**不得把 thin 当 gap**。
- recompute.mastery() 把 attempts 里 source ∈ {student_self, system_quiz} 两类都计入、MVP 各算 1 次仅打标签
  （暂不加权、可整体重算）；一道错题挂多 concept 取最小 mastery（不变）。
v2.5 关键：删除旧"对真实作业做客观/过程/开放分级 + 模型初判 + 多次采样一致性"整段——真实题不在系统内判。
【DoD】judgeAnswer 单测覆盖全规范化规则；verify 沙箱入库跑通；到期任务能按"考核优先/重做兜底"正确分流；replay 一致。
【禁止】让模型判分；运行时 eval verify；用 Python 内置 eval()（必须白名单 AST）。
```

---

## 批次⑥ —— 同类题考核闭环

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§5 判分/唯一写入路径）+ 设计文档 §16 + TICKETS.md 的 P1-11。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
统一口径：闭环考核记在 attempts（source=system_quiz）、不新建错题本条目、不建 quiz_attempts 表。
【任务】考核页取一道同类题 → 客观/短答题系统内作答、judgeAnswer 比对 bank 标准答案判分（记 attempts：
source=system_quiz，不新建错题）；数学解答大题（bank type 非客观 或 figure 依赖图）→ 降级"纸上做 → 拍已批改 →
自评"（source=student_self）。触发两者都要：复习到点自动推（P1-7a）+ 家长手动组卷入口（选知识点→出 1..N 题）。
考核结果计入该知识点掌握度、可整表清空。
【安全红线（最重要）】考核 API/响应体只下发 `题干 + 选项 + 题型`，**绝不下发 `answer`/`explanation`/`verify`**——
判分全在服务端 judgeAnswer 完成，前端拿不到答案（防 F12 偷看 = 又一支"更漂亮的红笔"）。
**system_quiz 的 `correct` 必须由服务端 judgeAnswer 得出后落库：新增"提交考核答案→服务端判→记录"端点，
绝不能信任客户端传入的 `correct`（否则孩子谎报即刷掌握度）；只有 student_self 原题重做自评端点
（P1-7a complete）才接受客户端 correct。**
对 verify_status=unverifiable 的题：判分仍以 bank `answer`+`accept` 走 judgeAnswer，但 UI 须透传质量标签
（unaudited / blind_verified=false / unverifiable），让家长看得到"此题未经二遍复核"。
【DoD】一道数学错题到期 → 推同 topicId 客观题 → 系统判对/错 → 掌握度变化可重放；大题 → 降级自评路径生效；
家长手动组卷可用；source=system_quiz 的 attempts 不新建错题；**响应体断言不含 answer/explanation/verify 字段；
system_quiz 完成端点拒绝客户端直接传 correct（必须服务端判）**。
【禁止】让模型判考核题；把考核结果建成错题本条目；把 answer/explanation/verify 序列化进任何前端响应；
对 unverifiable 题当作已核验静默加分；让 system_quiz 的 correct 由客户端决定。
```

---

## 批次⑦ —— 最小 Web UI（串起闭环）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§3 前端栈 / §4 零模型 / §6 回显总闸）+ 设计文档 §16 + TICKETS.md 的 P1-9。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
【任务】五页跑通：导入页（inbox 说明 + 家长手填最小表单）/ 核对页（题+错答+正答并排回显 + 错因确认 +
多知识点挂载 + 选主考点 primary_topic_id）/ 错题本 / 复习+考核页（到期任务、重做自评 or 同类题作答）/
讲解位（默认关）。技术栈 React + Mantine + KaTeX（数学渲染）。
【收批次③遗留】核对页确认入本后，"待确认 N 条"计数要自动刷新（确认成功即乐观更新或重拉列表），
不再需要用户手动点刷新。
【DoD】家长能"外部转录 → 核对确认入本 → 复习到期 →（能考就考 / 否则重做自评）"端到端走一遍；孩子见同一份；
核对页确认后待确认计数即时递减。
【禁止】提前做看板/规划/美化；在纯查询页触发任何模型调用（wengu 已零模型）。
```

---

## 批次⑧ —— 退役旧视觉栈与 Provider（一定放最后）

```
前置条件（不满足就停下、别做本票）：批次②④⑥⑦ 全部实跑通过、端到端闭环在家用场景跑顺之后才开工。
你在 wengu 仓库工作。开工前完整读：AGENTS.md（顶部 v2.5 横幅 / §4）+ 设计文档 §16 + TICKETS.md 的 P1-12。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。本票是"删除票"——把"模型在环"的整条旧链路连同其前后端一起退役。
【删除方法（先查引用再删，别照单硬删）】每个候选先 grep 全仓确认无存活 importer；删完必须三绿：
`python -c "import app.main"` 成功、全量 pytest 绿、`npm run build` 绿。任一不过=删漏或删多。

【后端删除清单（模型在环整链）】
- 视觉/提取：preprocess/ocr.py、services/slicer.py、services/extraction.py、api/captures.py、api/extractions.py、models/extraction.py
- 网关/审计/讲解端点：services/ai_gateway.py、services/model_audit.py、services/explanation.py、api/explanations.py、api/gradings.py
  （api/gradings.py 是 HTTP 模型判分端点，删；但 **services/grading.py 是 intake 唯一写入路径依赖的确认/版本服务，必须保留**）
- providers/ 整目录：doubao/qwen_vl/tencent/openai_vision/http/failover/registry/cache/text/base/mock ——
  删完网关后 grep 确认无任何模块再 import providers，则整目录删除（wengu 已零模型，不需要 provider 抽象）；
  若仍有测试引用某文件，只保留被引用者并在 PR 说明，否则不保留 mock。
- llm_prompts/（模板已迁 docs/templates/）；scripts/smoke_providers.py、make_extraction_fixtures.py、
  eval_slicing.py、eval_extraction.py、eval_grading.py、eval_explanation.py 等只服务旧链路的脚本及其测试。
- 迁移 0013（可逆）：DROP model_runs、ai_jobs 两张已无用表（down 重建空表）；learning_events/attempts 等事实/派生表不动。
- 可选清理：config.py 里失效的 provider/model/成本字段 + .env.example 模型 Key 必填项一并去掉。

【前端删除清单（依赖被删端点的旧页）】
- CapturePage.tsx、GradingPage.tsx、ExplainPage.tsx 及 App.tsx 中其路由、endpoints.ts/types.ts 里只服务这些页的条目、
  AppLayout 残留入口。删后 `npm run build` 必须绿（批次⑦只是移出导航，本票彻底移除）。

【必须保留（别删）】services/grading.py（intake 依赖）、judge/（judge_answer + verify_sandbox）、
seed/bank.py + services/bank.py、services/quiz.py、services/review.py + recompute.py、
api/imports.py + services/inbox.py + services/intake.py、api/reviews.py + api/quizzes.py + api/attempts.py；
迁移 0011/0012 不动，0013 只做 DROP。

【DoD】删后 `import app.main` 成功、/health 200、全量 pytest 绿、npm run build 绿、
端到端（导入→监听→核对入本→到期三态→手动组卷）不回归；单张可整体回滚（含 0013 down）。
【禁止】在新入口未跑通前删；删掉 intake 依赖的 services/grading.py 或 judge/bank/quiz/review/inbox/intake；
把删除扩到本清单外的活跃功能；留一堆 import 已死的空模块不清（要么删净要么在 PR 里说明为何留）。
```

---

# P2 批次存档（已合并：补票 B + PR#10–#16）

> 以下 8 张是 P2 阶段实际投给 Qoder 并已通过四重验证（静态审读 / 沙箱外实跑 / CI / 浏览器冒烟）
> squash 合并的工单存档，保留决策、边界、红线与 DoD 要点，供追溯与重建；**不是待办**。
> 交付节奏与 MVP 相同：一 ticket = 一 PR = 一个 squash 提交。

## 补票 B —— 错题作废/撤销入口（PR#9）

```
决策：primary_topic_id 与 student_answer 转正可选（B 定案）；错答留空（整题没做）也算错题。
【任务】services/mistakes.py 新增 void_mistake / unvoid_mistake：只翻 Mistake.status +
追加 mistake_voided / mistake_reactivated 事件（幂等键 mistake:{id}:void / :reactivate），
不建/不删 mistake_versions；作废不回溯洗掌握度（默认 a）。
新增 MistakeStateConflict 使"已作废改标签"从 422 细分为 409（catch 顺序先于 MistakeConflict）。
api/mistakes.py：POST /api/mistakes/{id}/void（actor、reason≤200）、/unvoid（actor）；404/409。
前端 MistakeDetailPage：作废（可选原因 Modal）/撤销作废，仅家长解锁后可见。
【DoD】作废→退出活跃列表与到期队列；重复作废幂等；撤销→到期恢复；voided 改标签 409；历史版本/事件留存。
```

## P2-5 —— 家长看板（PR#10）

```
【任务】纯只读确定性统计，全部从 learning_events/mistakes/review_schedules/grading_versions 现算，
掌握度/统计复用 recompute（勿重造）；掌握度曲线逐日回放事件前缀（默认 30 天、上限 90），
无已确认 concept 返回空曲线而非假 0；薄弱分布按 primary_topic_id；到期/逾期、本周复习/毕业、
bank_gap、申诉/作废计数。
api/dashboard.py：GET /api/dashboard?today=&curve_days=，事务只读、无写、无模型/网络调用。
前端 DashboardPage：导航首项"看板"；曲线用内联 SVG（不加图表依赖）；无推送/锁屏/问责、无积分、无写按钮。
【DoD】测试断言：patch socket 证不出网；请求前后五表行数不变；逐项 == recompute 重算；空库全零。
【禁止】实时催/锁屏/问责；积分徽章；看板页触发模型调用；新建写库路径。
```

## P2-4 —— 两角色 + 本地 PIN（PR#11）

```
决策（已拍板）：Q1-A PIN 只挡家长区；Q2-A PIN scrypt 哈希存 user_role(role='parent')，首次进家长区引导设置；
Q3 PIN 不是安全边界（公网须真鉴权/Tailscale，写进注释与 README）；Q4-A 签名 cookie，不引入登录/账号体系。
【任务】迁移 0014 确保 parent 行存在（downgrade 只删未设 PIN 行）。
services/session.py：PIN 4–8 位数字/6–20 位字符；hashlib.scrypt+随机盐（scrypt$N$r$p$salt$hash，
参数随哈希存）；hmac.compare_digest；HMAC-SHA256 签名 cookie（TTL 12h，httponly+samesite=lax）；
按来源内存限流（连续错 5 次锁 60s）；密钥 env → Settings → data/.session_secret（首启生成、0600）。
api/session.py：GET status / POST pin/set（已设须先解锁）/ unlock（409 未设、401 错、429 限流）/ lock；
require_parent 依赖 → 403。
门禁：mistakes void/unvoid、problem_bank import/items、GET /api/quizzes/paper；孩子区全程免 PIN。
前端：ParentSession 上下文 + ParentGate 导航入口；作废/组卷 UI 仅解锁后可见。
【DoD】未设 PIN→家长端点 403；pin_hash 非明文；错误 5 次→429+Retry-After；cookie 篡改→403；
孩子端点不受影响；lock 后重新 403。
```

## P2-6 —— 极简打卡（PR#12）

```
决策：打卡=从事实推导，不是手动按钮（完成作答即"当日已打卡"）；答错也续签（打卡只反映"来了"，
与掌握度解耦）；streak 绝不入库、每次现算；并入 P2-5 看板，不新建页/端点。
【任务】services/streak.py：summarize_streak(events, today) 纯函数——学习日取 payload.completed_on
（缺失/非法回退 occurred_at，不拿 UTC 拼本地日）；锚定=今天有→从今天倒数、今天没有但昨天有→从昨天倒数
（仍不算断）、连续两天没有才归零；输出 今日状态/连续/最长/累计/近30天 recent_days；set+sorted 顺序无关。
dashboard 快照增 streak 字段（复用已加载事件，不二次查库、不重造曲线）。
前端看板"每日打卡"卡：今日 ✓/未打卡、连续/最长/累计、30 天点亮条；无签到按钮。
【禁止】手动签到/写库；streak 入库；积分徽章；用 streak 下学习结论。
```

## P2-1 —— 最小日队列（PR#13）

```
边界（严格不做）：背诵铺底、作业 deadline、月考/硬事件抬权重——依赖 P2-3 与 P3，越界即退回。
本轮只做三件事：优先级排序、每日上限+顺延、今日完成进度。
【任务】core/runtime_config.py（新）：每次调用现读 config/app-config.json（gitignore），
daily_review_limit 缺失/非法回退 10、硬上限 200、WENGU_APP_CONFIG 供测试；app-config.example.json 样例。
due_queue 返回 DueQueue（items/due_total/today_completed/daily_limit/returned）：
排序=逾期(due_date 升序)→今日、同组 mistake_id→schedule id；超上限项不返回只计数；
today_completed 从事件现算（kind=review 且 completed_on==today）。
api/reviews/due 响应加四字段；前端"今日任务 x/y 完成"+ 顺延提示（"明天还在，不会丢"）。
【禁止】时间块排课；把顺延做成惩罚/消失；引入新依赖。
```

## P2-3 —— 课表/日历约束层（PR#14）

```
决策：Q1-A 两张表（timetable_slots 周循环 + calendar_events 单次）；Q2-A 写操作挂 require_parent；
Q3=(a)+(b)：仅展示 + 考试日当日放宽上限；明确不做 (c) 按考试科目↔知识点重排（防过度工程）。
【任务】迁移 0015：timetable_slots（weekday 1–7/period 1–12/UNIQUE(weekday,period)）+
calendar_events（kind CHECK exam/competition/leave/other + date 索引），DOWN 可回退。
api/schedule.py：课表/日历 CRUD——写挂 require_parent，读免 PIN；越界 422、重复节次 409。
唯一队列改动：due_queue 检测 date==today AND kind='exam' → cap=min(round(cap×exam_day_limit_factor),200)
（factor 默认 1.5、热改生效、非法回退），DueQueue 增 exam_today；排序/任务类型/thin/gap 不动。
前端：SchedulePage（家长解锁可增删、锁定只读）+ ScheduleBrief（复习页/看板头部：今日课程+未来7天硬事件，
排除请假）；复习页考试日显示"上限已临时放宽到 N"横幅。
【禁止】自动排课/时间块；科目↔知识点映射；冲突检测；把课表当任务源。
```

## P2-2 —— 番茄钟（PR#15）

```
定位：计时器不是规划器。纯前端倒计时 + 完成打点入 learning_events；不规划、不排程、不自动连跑。
口径：pomodoro_completed 是新事实事件，只用于看板展示专注时长——不计入掌握度、不计入 streak、不进错题本
（构造性保证：streak/mastery 只认 attempt_* 事件类型）。
【任务】services/pomodoro.py：record_pomodoro（幂等键 pomodoro:{started_at秒}、duration 服务端钳制 5–120、
mistake_id 可空、不写 attempts/不建表）+ summarize_pomodoros 纯函数。
api/pomodoro.py：POST /api/pomodoros→201；StrictInt 拒布尔/字符串；非法 422、错题不存在 404；无迁移。
dashboard 增 pomodoros_today / focus_minutes_this_week（从事件现算）。
前端 PomodoroTimer（25 分钟，取消不打点、不后台、不通知、不连跑）+ 队列首项挂计时器 + 看板两张卡。
【禁止】时间块排课；自动开始下一个；后台计时/通知；番茄计入掌握度或 streak。
```

## P2-7 —— 错题/练习卷导出打印（PR#16）

```
方案（已定勿改）：前端打印视图 + 浏览器"打印→另存为 PDF"——零新依赖、零 PDF 库、零服务端文件。
理由：错题含数学公式（前端已有 KaTeX）+ 中文（系统字体），reportlab/fpdf2 反而要另解 LaTeX 与打包字体。
【任务】/print/mistakes?category_id=&error_cause=&from=&to=：四区块（原题 KaTeX/孩子作答/订正正答/
错因批注），按知识点分组、未挂考点最后；空结果提示+打印禁用；入口在错题本带当前筛选。
/print/paper?topic_id=&count=&seed=：练习卷默认 DOM 无答案；无 seed 回写 URL 重印同卷；
末页"家长答案页"默认关、点击才加载、强制单独分页。print.css：@page A4、组 break-before:page、
题卡 break-inside:avoid。
唯一后端新增（工单例外条款内）：GET /api/quizzes/paper/answers 挂 require_parent，只回正答+可接受别名，
不含 explanation/verify（组卷题 id 是字符串，整型 problem-bank 端点取不到）。
【红线】练习卷默认视图绝不渲染答案；答案页仅家长解锁后可得。
【禁止】引入 PDF 生成库；服务端产文件；在既有端点里塞答案字段。
```

---

# P3 批次存档（已合并：PR#17–#24）

> 以下 7 张是 P3 阶段实际投给 Qoder 并已通过四重验证（静态审读 / 沙箱外实跑 / CI / 浏览器冒烟）
> squash 合并的工单存档，保留决策、边界、红线与 DoD 要点，供追溯与重建；**不是待办**。
> PR#22 已关闭（P3-2d 与 P5-2 混进同一提交），拆成 PR#23 / PR#24 重开——教训记在文末附录。

## P3-1a —— 家长录题与审核入库（PR#17）

```
决策（红线）：模型不得自行解题生成答案；answer 只能从卷面/答案册转录或家长手填；缺答案一律拒入库。
【任务】新模板 docs/templates/doubao_bank_transcribe_v1.md（frontmatter id+version，模板只引用不内嵌）。
迁移 0016（可逆）：建 bank_drafts（import_batch_id+seq+normalized_json+has_placeholder+status，
UNIQUE(import_batch_id,seq)）；给 problem_bank 补 topic_id/question_type/difficulty/choices_json/
figure/hide_choice_text/percent。
services/bank_import.py 两段闸门：normalize_bank_items → check_approvable → classify_verify
（AST 白名单沙箱跑 verify，仅四则/推导式/下标，禁 import/属性/赋值，2s 超时；纯数值矛盾也拒）。
inbox 按 channel 分派到 bank_drafts（草稿永不自动转正）。
api/bank.py：草稿列表/详情/approve/手填创建，**路由级 require_parent**；前端 /bank 审核页 + 手填表单。
【DoD】入库题固定 unaudited=true / blind_verified=false；choice 答案必须命中选项 key；
topic_id 必须存在于 knowledge_seed；沙箱拒绝 __import__ 等；家长题只进 SQLite、不写 seed JSON。
【禁止】LLM 生成题或答案；草稿自动转正；写 seed 文件；把审核面暴露给孩子区。
```

## P3-1b —— 运行时题池合并（PR#18）

```
【任务】services/bank.py 增 get_runtime_bank(session)：seed 只读索引 + problem_bank 已入库行
映射成 BankQuestion 合并进内存池。_dynamic_question 把 DB 行当不可信输入再校验一遍
（id/topic/type/prompt/answer 任一非法 → 计入 stats.dropped 并跳过，不抛异常）；
跨考点缺 meta 时回查 knowledge_seed 补 topics。approve / 手填提交后 reset_bank_cache() 失效。
mulberry32 必须是 JS 语义的位精确移植（uint32、>>>0），find_same_type / paper_picks 只用它。
replay / paper 重放按"题 id 序列 + pool_ids 身份"比较，池变了抛 BankReplayError，**绝不静默换题**。
【DoD】家长题参与到期考核与手动组卷；coverage / thin 统计随池重算；同 seed 重放得到同一张卷。
【禁止】回写 seed JSON；池变化后静默重选题；把 seed 题库塞进 SQLite（SQLite 只存动态数据 + external_id 溯源）。
```

## P3-1c —— 题库编辑与软作废（PR#19）

```
【任务】迁移 0017（可逆）：problem_bank 补 status TEXT NOT NULL default 'active'
（CHECK active|voided）+ updated_at NULL，既有行回填 active。
GET/PATCH /api/bank/items + void/unvoid，全挂 require_parent。
编辑 = 合并后**重跑同一套入库闸门**（缺答案/占位/沙箱/choice key/数值矛盾 → 422 稳定码），
不改 external_id；作废只把题退出检索池，**不物理删除、不改写历史 attempts/事件/排期**；
replay 按题 id / pool_ids 判定，内容修订不回溯。
前端 /bank 增「已入库题目（可修订）」区：状态/考点筛选、行内编辑、作废/撤销作废。
【禁止】物理删除题目；改写历史；因编辑变更 external_id 使旧组卷重放漂移。
```

## P3-8 —— 家长自建章级 seed（PR#20；幂等硬化见 P3-2d）

```
决策：JSON 文件是唯一真源，SQLite knowledge_seed 只是装载副本；章级 40–80 点即止、单科上限 200；
无迁移（knowledge_seed.source 已存在）。
【任务】seed/loader.py 多源装载顺序 seeds/data/topics.json（仓库只读）→ seeds/local/*.json（可选）
→ <data_dir>/seeds_local/*.json（家长运行时），按 id upsert 幂等；本地条目强制
source='local' / unaudited=true / blind_verified=false；id 与上游或先前本地冲突 → error 日志拒绝该条；
坏文件只 warning 跳过不阻塞其余源；**跳过下划线开头的簿记文件**。
services/local_seed.py：同目录 tmp + fsync + os.replace 原子写、进程内锁串行；
语文 cnl_ / 化学 cnc_ 前缀零填充三位递增；删除同步移除文件与行、解绑
mistakes.primary_topic_id 与 problem_bank.topic_id（SET NULL，历史不动）并返回受影响计数，
仍被 mistake_versions 标签引用则 409。
api/local_seed.py 全挂 require_parent；前端 /local-seed 页（仅家长解锁可见）带
「家长自建·未经教师审核」提示与解绑计数确认框。scripts/export_topics_junior.py 合并 local 源，
且不得改动仓库 seed 字节。
【禁止】写回 seeds/data；把细粒度知识点树做成家长手工录入（细粒度仍走错题受控生长）；用 DB 反向覆盖文件真源。
```

## P3-2 —— 主动加练变式（PR#21）

```
【任务】POST /api/practice/start（mistake_id 或 topic_id + count 1..10 + seed）：按
primary_topic_id 从 get_runtime_bank 固定种子取题（复用 paper_picks）；无主考点或池空
→ items=[] + message「该知识点暂无同类题」，200 不报错、不硬凑；题面走 quiz_view，
**绝不含 answer / accept / explanation / verify**。
POST /api/practice/submit 重建同卷并校验题目归属（重复/外来题 422）：mode=system 由服务端
judge_answer 判分（空白跳过、uncertain 不写行）、mode=self_eval 收孩子自评；
每题写一行 practice_records(kind='variant')，seed 题 problem_bank_id=NULL、
家长题按 external_id 反查回填。
GET /api/practice?mistake_id=&kind=&limit=&offset= 与 DELETE /api/practice（整表清空）。
服务层**不得 import record_event / Attempt**——从代码路径上保证零事件、零掌握度影响。
/api/practice/* 全部孩子区免 PIN。
前端 /practice 页复用 QuizQuestionCard；错题详情入口先探测 count=1，gap 时置灰 + 文案解释；
「练习记录」页加「变式/加练」tab 与带二次确认的清空按钮。
【DoD】加练前后 attempts / learning_events / review_schedules / mistakes 行数零变化；
清空后仅 practice_records 归零，看板与到期队列完全不变。
【禁止】与闭环考核混淆（变式不进错题本、不计掌握度/排期/streak）；LLM 编题或判分；写事件/attempts。
```

## P3-2d —— 幂等与身份硬化（PR#23）

```
【任务】① 迁移 0018（可逆）给 practice_records 补 topic_id / seed / dedup_key +
部分唯一索引 uq_practice_records_dedup_key（WHERE dedup_key IS NOT NULL，多 NULL 不冲突），
既有行三列保持 NULL 仍可回看；submit 每题先算 dedup_key = variant:{topic_id}:{seed}:{question_id}，
命中唯一冲突 → 不新增、回看已有行并返回 reused=true（**不覆盖原作答**，即使本次答案不同），
并发走 savepoint + 唯一索引兜底；GET /api/practice 支持 topic_id+seed 过滤，记录页按「这一组」展示。
② 本地 seed id 永不复用：<data_dir>/seeds_local/_id_counters.json 单调记录各学科已发放最大序号，
分配取 max(计数器, 文件与 DB 同前缀最大序号)+1，**先原子预留再落盘**，删除不回退，
计数器损坏 fail-closed 抛 LocalSeedError；装载器与导出脚本跳过下划线开头文件。
③ 工具链：仓库根一旦出现 scripts/ 目录，ruff 的 isort 会把 scripts 判成 first-party 并翻转
全仓 import 分组（连本次未改动的老测试文件一起 I001）；pyproject 钉 known-third-party = ["scripts"]。
【DoD】重复提交行数不增且 reused=true；换 seed 各自成行；删除后新建不回退号；
_id_counters 不被当 seed 读取有单测覆盖。
【禁止】覆盖历史作答；池或计数器变化后静默改判；本机 lint 不带 --no-cache 就当绿（.ruff_cache 假绿）。
```

## P5-2 —— 一键备份 v1（PR#24）

```
决策：**不做运行中热替换 SQLite 的在线恢复**（WAL/SHM + 活跃连接极易毁库）；
恢复 = 停服 → 全量安全副本 → 整库替换 → /health，走脚本 + 文档，不做 UI 恢复。
【任务】services/backup.py：VACUUM INTO 在 <data_dir>/backups_tmp 生成一致性快照
（mode=ro / PRAGMA query_only 会让 VACUUM INTO 报只读错，故用普通连接但**只执行这一条语句**、
不写业务表）；打包 wengu.db + uploads/ + seeds_local/（**必须含 _id_counters.json**，
否则恢复后"id 永不复用"失效）+ inbox/ 根目录未处理文件（.processed/ 不进包）+ manifest.json
（version / created_at / alembic_version / 各表计数 / 每文件 sha256+size_bytes）；
os.replace 原子落到 backups/wengu-backup-<UTC 时间戳>.zip；轮转只留 10 份、只删匹配规范名的 zip。
api/backup.py：export / list / download，**路由级 require_parent**；下载名四重校验
（规范名正则 fullmatch + / \ : NUL .. 黑名单 + Path(name).name == name + resolved.parent == backups/）。
scripts/restore.ps1：PowerShell 5.1 + **UTF-8 BOM**；zip 条目防遍历（绝对路径/盘符/.. 段）
→ manifest 核对 wengu.db sha256 → docker compose stop api → 现有数据全量安全副本
→ 先删 -wal/-shm 再替换 → up -d 并轮询 /health；失败时打印回滚路径，退出码非 0。
docs/deploy/backup-restore.md：包结构、导出下载、Docker 恢复、原生试用机恢复、Linux 手动、核对清单、回滚。
前端 /backup 页（导航 parentOnly，未解锁只显示家长专属提示）。
【DoD】导出前后全表逐行不变；快照 PRAGMA integrity_check=ok；并发写入下快照仍一致；
未解锁三端点 403；../ 与绝对路径下载 400/404；轮转不误删 backups/ 下其他文件。
【禁止】把 .env / data/.session_secret 打进包；日志记题目正文或 PII；在线热替换 DB；上传任何外部服务。
已知边界：config/app-config.json 不在 data_dir 内故不进包；backups/pre-restore-* 安全副本不参与轮转、
需手工清；backups_tmp/snapshot-* 崩溃残留需手工清；列表每次重算每份 zip 的 sha256。
```

---

## 附：P3 阶段新增的投单纪律（踩过才写下来的）

- **一票一分支，审核期冻结**：上一张票在审时不得在同一工作区继续写下一张票；开新票先
  `git switch -c feat/<新票> origin/main`。PR#22 就是 P3-2d 与 P5-2 并行开发挤进同一提交，
  只能事后拆分、关闭重开。
- **票号四处一致**：CHANGELOG / TICKETS / 分支名 / PR 标题用同一个号。曾出现提交叫 P3-9、
  CHANGELOG 叫 P3-2d；本地章级 seed 被误挂 `P1-1b`（与 2026-10-24 真正的 P1-1b 知识点 seed
  装载撞号）——现已统一为 P3-2d / P3-8。
- **lint 只认 `ruff check --no-cache`**：`.ruff_cache` 会给出与 CI 相反的假绿；代理自报"全绿"
  可能是工作区状态而非被推送的 HEAD，验收只认推上去的那个 commit。
- **部署只从合并后的 main 或标签取**：未合并的 PR 分支不算交付。
- **PowerShell 脚本必须 UTF-8 with BOM**：PS 5.1 无 BOM 会按 GBK 解码中文并截断字符串字面量，
  `Parser::ParseFile` 直接报语法错（run-trial.ps1 曾因此根本跑不起来）。

---

# 待投工单卡（v2.6 决策轮登记，**未开工**）

> 来源：`docs/audit/pr1-24-retrospective.md` 的交付回顾审计 + 用户拍板（砍 PWA、归并补 UI、按建议顺序推进）。
> 投单顺序 = ~~P5-6~~（PR#27）→ ~~P0-3~~（PR#28）→ ~~P3-3a~~（PR#29）→ ~~P3-3b~~（PR#30）→ ~~P3-3c~~（PR#31）→ ~~P5-1a~~（PR#32）→ ~~P5-1b~~（PR#33）→ ~~P0-4~~（PR#34）→ ~~P1-3e~~（PR#35）→ ~~P1-3f~~（PR#36）→ ~~P1-13~~（PR#37）→ ~~P1-13b~~（PR#38，随 `v0.5.0` 发布）→ ~~P4-1~~（PR#39，端口默认回环 + Tailscale 可达性）→ ~~P4-1b~~（PR#40，部署面命令体检）→ ~~P4-1c~~（PR#41，命令行备份入口，四问按定案执行）→ ~~P0-5~~（PR#42，两处 Windows 本地噪音）。
**当前无待投卡**；下一张候选：P4-2 可移植部署 / P5-5 英文 README + 独立隐私声明 / P3-4 听力默写，
以及**试用机上仍未验证的 P4-1 两条尾巴**（`tailscale serve` 的真实 CLI 形式、sidecar 路径 A 运行时）。
每张卡可整段复制给 Qoder。
> **2026-11-03 更新**：P5-6 孤儿表切片已交付（迁移 0019 一次退役 `problem_extractions` /
> `photo_capture_items` / `photo_captures` 三表；见 `TICKETS.md` 与 `docs/STATUS.md` §4.18），
> 本卡留作回溯；P0-3 亦已交付（PR#28），下一张待投 = **P3-3a**。
> **2026-11-04 更新**：P5-1a 已交付（`<data_dir>/app-config.json` + legacy 只读回退 +
> `GET/PUT /api/config` + 备份纳入；无迁移），本卡留作回溯；下一张待投 = **P5-1b**。

## 投单前言（每次连同卡一起复制，别单独发、也别塞进卡里）

```
【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：
   git fetch origin
   git switch -c feat/<本票号-英文名> origin/main
2. 本票期间该分支冻结：上一张票没审完，不要在这条分支上继续写下一张票的改动。
3. 提交前先跑 `git diff --cached --name-only` 核对暂存范围只含本票文件，把清单贴进交付描述；
   工作区里出现不属于本票的文件时停下来报告，不要顺手提交（并行开发时 CHANGELOG/STATUS 最容易串）。
4. 中文 commit message 一律 `git commit -F <UTF-8 文件>`，禁止 `git commit -m "中文"`（会被 GBK 编坏）；
   **消息临时文件写到仓库外的目录，禁止写进 `.git/` 里**（P1-13 返工时出现过 `.git/P1-13-rework-msg.txt`，
   虽未被提交，但往 git 内部目录写东西会让工具与人工排查都误判，属于必须避免的习惯）；
   lint 证据必须是 `ruff check --no-cache .`（不带 --no-cache 会因 .ruff_cache 给出假绿）。
5. 交付描述里给"你自己实跑"的数字（passed 数、关键断言结果、表数等），并单列一段
   「审核方需复核的点」；不要把计划说成已完成，也不要拿旧提交的绿凑数。
6. **指标类 DoD 只作用于用户面产物**（README*、Makefile、docs/** 里给家长照做的步骤、目录结构.md）。
   `docs/tooling/qoder-build-plan.md`（工单存档）与 `CHANGELOG.md`（历史）**不在指标范围内**：
   卡片正文与历史条目里出现的旧文件名、死路径、报错原文都是"当初哪里坏了"的证据，
   **不得为了让 grep/统计类指标归零而删改卡片正文或历史条目**。若某条指标确实无法在不碰存档的前提下
   满足，那是指标写错了——停下来在交付说明里指出，由审核方修订口径（P4-1b 就这么发生过一次）。
```

## P5-6 —— 交付口径与盘上一致性清理（含孤儿表退役）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§3 技术栈、§8 提交规约）+ TICKETS.md 的 P5-6
+ docs/audit/pr1-24-retrospective.md 的 §4-B3。
【全局纪律】一条 ticket = 一个 PR；DROP 表的迁移必须先出备份说明、必须可逆（up/down/up 实测）。
禁止引入新依赖。禁止顺手 DROP 任何仍被读的表——本票只动下面点名的三张。
【任务】problem_extractions / photo_capture_items / photo_captures 是 v2.5 视觉栈退役后的孤儿表
（迁移仍建表、但 app/ 业务代码零引用；problem_extractions 的两个 FK 还指向另两张表）。
出迁移 0019 按"先子后父"一次 DROP 这三张表（含其索引），downgrade 反向重建表结构
（不承诺找回数据）；同步删除两个 ORM 类与 models/__init__.py 的导出；
services/backup.py 的 COUNT_TABLES 去掉 photo_captures / photo_capture_items 两项。
再核对并修正文档口径：docs/STATUS.md 的"业务表 22 张"改为 19 张并在 §5.2 迁移说明里写清 0019；
CHANGELOG 记一条 Changed（含"为何现在才删"一句）。
【DoD】migrations 测试覆盖 0019 up/down/up 可重入；`alembic upgrade head` 后表清单与 STATUS 一致；
全测试绿（当前基线 397 passed，本票删表后允许因移除相关断言而小幅变动，必须在 PR 里逐条说明原因）；
`ruff check --no-cache .` 绿（本机不带 --no-cache 会假绿，不可用作证据）。
【禁止】手改生产 wengu.db；把迁移写成不可逆；DROP 点名的三张表之外的任何表；
为了"数字好看"删测试断言而不说明。
```

## P0-3 —— 端到端回归三条 + 迁移 DDL 原文对比（把空转的 e2e marker 用起来）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（事实源/幂等）+ §8 DoD + TICKETS.md 的 P0-3
+ 设计文档 §16-A（新闭环图）+ tests/integration/test_migrations.py 现有的 0018/0019 用例。
【全局纪律】一条 ticket = 一个 PR。禁止引入 Playwright/Selenium/任何浏览器栈或新依赖；
禁止 mock 服务层（e2e 的价值就在于走真实 ASGI + 真实 SQLite + 真实迁移）。
【任务】新建 tests/e2e/ 三条用例（marker 已在 pyproject 声明但目前 0 条）：
① 投递一段含 2 题的 agent_transcribe_v1 JSON → 落草稿 → 核对页端点确认入本 → 到期队列出 quiz →
   提交作答 → 服务端判分写 attempts(source=system_quiz) → 看板与 streak 数字与手工推导一致；
② 错题作废 → 退出活跃列表与到期队列 → 撤销 → 回到期队列。断言口径（勿照抄旧话"事件不增不改"）：
   **既有事件行与 `mistake_versions` 逐行、按序原样保留**，按设计**仅追加** `mistake_voided` /
   `mistake_reactivated` 两条审计事件（append-only = 只追加、不改不删，**不是"不追加"**）；
③ 家长解锁 → POST /api/backup/export → 解出快照 PRAGMA integrity_check=ok → manifest 表计数
   与库内实际计数逐项相等。
用真迁移到 head（含 0018/0019）+ 临时库 + ASGITransport，参照 tests/integration 现有 fixture 风格。
④ 强化 tests/integration/test_migrations.py：给可逆迁移加 **DDL 原文 before/after 对比**——
   先把库升到目标 revision 的前一版，从 `sqlite_master.sql` 取出涉及表与其索引的完整建表语句存档；
   再 upgrade 到 head、然后 downgrade 回该 revision，**逐字比对两侧 DDL**（列类型、NOT NULL、
   server_default、UNIQUE 与 FK 约束名、ON DELETE 行为、索引定义），差异必须为空。
   至少覆盖 0018 与 0019（0019 管三张孤儿表的重建，是最高危面）。
   理由：现有 inspector 断言只看列名/索引名集合，挡不住类型与默认值漂移；P5-6 审核时审核方用
   一次性脚本做过这件事并确认 7 个 DDL 对象零差异，现在要固化成常驻测试，别依赖人肉再跑。
【DoD】`pytest -m e2e` 收集数 = 3 且全绿；`pytest -q` 全量绿；CI 绿。①②③ 的断言必须落在
**跨引擎一致性**上（导入→确认→排期→判分→统计 五处数字互相咬合），不得只断"接口 200"。
④ 必须真断 DDL 文本相等（不得退化成"表存在"）；并在 PR 描述里给出**可证伪证据**：
临时把 0019 downgrade 里某一处 server_default 或约束名改坏 → 该用例变红 → 改回 → 变绿，
把两次运行输出贴进 PR。做不到这一条就说明断言是假的。
【禁止】把已有 integration 用例改名凑数；assert True；只断表名存在冒充结构比对；
引入模型/网络调用；修改业务代码来迁就测试（若发现业务真有 bug，停下来单独报告，不要顺手改）。
```

## P1-3e —— 移动端投递入口：粘贴整段转录 JSON（PWA 的替代票）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §2.4（可信网络默认）+ §5（导入即不可信输入）
+ TICKETS.md 的 P1-3e 与设计文档 §17-A（为何砍 PWA、本票补的是什么）。
【全局纪律】一条 ticket = 一个 PR。禁止新写任何绕过 services/inbox.py `ingest_raw_payload` 的入库路径；
禁止引入文件上传框架/对象存储；禁止引入 manifest/service worker（已进 §12 反清单）。
【任务】/import 页新增"粘贴转录 JSON"区：Textarea 贴整段（或选择本地 .json 文件读进同一个提交函数）
→ 调已存在的 POST /api/imports（前端封装见 api/endpoints.ts:252）→ 回显 accepted_count 与
errors[]（逐条 index/field/reason，复用 P1-9b 的错误呈现）→ 给"跳核对页"链接。
窄屏可用：按钮不溢出、错误清单可横向滚动、不依赖 hover。
【DoD】贴一段含 3 题（其中 1 题缺 standard_answer）的 JSON → 2 条成草稿、1 条逐字段报错、
**错题本行数不变**；同一段再贴一次 → 命中 sha256 去重 duplicate=true、不重复建批；
手机浏览器（窄视口）实测截图；全测试绿 + `npm run build` 绿。
【禁止】让这个入口自动转正/自动建错题；把原始报文写进日志（PII 纪律）；前端解析后再拼一遍字段
（应原样透传给后端，校验只有一套）。
```

> **状态：已完成（2026-11-04，分支 `feat/p1-3e-paste-import`，待评审）**——实跑 522 passed
> （unit 344 / integration 170 / e2e 8）、`pytest -m e2e` 8 条全绿、`ruff check --no-cache .`
> 全绿、`npm run build` 绿；无迁移、无新依赖、后端零改动。

## P1-13 —— 知识点归并 UI（补受控生长的另一半）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §6（知识点两级 + 受控生长：优先复用·不覆盖确认值·
归并需人工确认）+ §5（AI 建议值与用户确认值分离）+ TICKETS.md 的 P1-13。
【全局纪律】一条 ticket = 一个 PR。禁止物理删除 concept 行；禁止改写 append-only 的
mistake_versions 标签快照；禁止引入"相似度自动检测建议合并"这类猜测逻辑——归并必须是人工动作。
【任务】后端：把 POST /api/concepts/merge 挂上 require_parent（归并 = 家长专属；
POST /api/concepts 建点/复用仍留孩子区，别一并改掉）。
前端：错题详情的知识点区（或 /mistakes 页）新增"归并知识点"入口，仅家长解锁后可见 →
选源 concept + 目标 concept → 预览影响面（受影响错题数 / 别名数）→ 二次确认 → 调 merge。
【DoD】归并后列表只出目标点、源点带 merged_into_id 且不再出现；历史 mistake_versions 的
category_id/标签快照**一字未改**（用全表快照断言）；名称解析走合并家族（旧 id 仍能解析出目标名称）；
未解锁调用 403；对已归并的源再调一次幂等、不产生新行；全测试绿 + build 绿。
【禁止】把建点入口也锁上 PIN（会破坏孩子边做边长标签的路径）；顺手改 recompute/排期逻辑；
把归并做成"删除多余点"。
```

## P3-3a —— 英语背诵（家长手填条目 + 记忆阶梯自评闭环）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（事实源/幂等/确定性重算）+ §6（固定阶梯 + 抗挫败
三规则）+ TICKETS.md 的 P3-3a + 现有 app/services/review_policy.py（MEMORY_LADDER / MEMORY_SUBJECTS）
与 app/services/review.py（自评档 self_eval 与 source=student_self 的写法）。
【全局纪律】一条 ticket = 一个 PR；事实源纪律照旧（只追加 learning_events + 确定性重算，
不存易变字段）；禁止引入新依赖；禁止改动错题链路（mistakes / mistake_versions / review_schedules）
的既有语义。
【定位】P3-3 按 B → A → C 三期推进，**本票只做 B**（家长手填 + 自评闭环）；
教材词表导入（A，P3-3b）与从错题抽词（C，P3-3c）不在本票范围。
【任务】
1) 迁移 0020（可逆）新增两表：
   recitation_items(id PK, subject TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT NULL,
     unit TEXT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
     created_by TEXT NOT NULL, created_at DATETIME NOT NULL, UNIQUE(subject, prompt))
   recitation_reviews(id PK, item_id INTEGER NOT NULL REFERENCES recitation_items(id) ON DELETE CASCADE,
     verdict TEXT NOT NULL CHECK(verdict IN ('remembered','forgot')), rung INTEGER NOT NULL,
     reviewed_on DATE NOT NULL, scheduled_next DATE NULL,
     event_id INTEGER NOT NULL REFERENCES learning_events(id) ON DELETE RESTRICT,
     created_at DATETIME NOT NULL, UNIQUE(item_id, reviewed_on))
   背诵条目**不是错题**：绝不写 mistakes / mistake_versions；**也不写 attempts**
   （attempts 语义是"作答"，混入会脏掉练习记录页）。
2) 阶梯与排期写成纯函数（services/recitation.py）：复用 review_policy.MEMORY_LADDER=(1,3,7,14,30)；
   remembered → rung+1，forgot → **保持当前 rung**（抗挫败：不倒退）；下次到期一律从
   **实际完成日**起算（reviewed_on + ladder[rung]）；已到最高档且再次 remembered →
   scheduled_next=NULL（毕业，不再排，条目保留）。
3) 每次自评追加 learning_events(type='recitation_reviewed', mistake_id=NULL)，payload 含
   item_id / verdict / rung / scheduled_next / completed_on；幂等键
   `recitation:{item_id}:{reviewed_on}`——同一天重复自评**不产生**第二条 review/事件，返回既有结果。
   mastery 天然不受影响（recompute 按 mistake_id 归属，背诵事件无 mistake 归属）。
4) 打卡口径**显式变更**：把 recitation_reviewed 纳入 streak 的计入白名单，连续天数语义从
   "有作答的日子"改为"有学习动作的日子"；同步改 streak.py 注释与测试，**不得悄悄改**。
5) 日队列铺底：新增运行时配置 daily_recitation_limit（config/app-config.json 热加载，
   默认 5、上限 20）；每日到期队列在同类题考核**之后**追加最多 N 条到期背诵；无到期不塞、不硬凑；
   看板加"今日背诵 x/N"。
6) API：GET /api/recitations?subject=&status=&limit=；POST /api/recitations 与
   PATCH /api/recitations/{id} **挂 require_parent**（手填归家长）；
   GET /api/recitations/due?today=；POST /api/recitations/{id}/review（孩子区免 PIN）。
7) 前端 /recitations：孩子视图 = 今日卡片 + "记得 / 没记住"两个按钮 + 今日进度；
   家长解锁后可见"管理条目"（增/改/停用）；窄屏可用（手机是目标场景）。
【DoD】
- 迁移 0020 可逆，且 **DDL before/after 用例覆盖**（沿用 test_migrations.py 里 P0-3 新增的
  _master_ddl / _ddl_mismatches 写法；0020 用 op.create_table 显式建表 → 要求逐字一致）。
- **全表快照断言**：做一轮背诵自评后 mistakes / mistake_versions / attempts / review_schedules
  行数与内容零变化——这是"不污染掌握度"的唯一硬证据，必须真断。
- 阶梯：remembered 逐档推进到 30 天、forgot 保持当前档、到期日从 reviewed_on 起算，各有断言。
- 幂等：同一 item 同日提交两次 → 只有一条 review、一条事件，第二次返回既有结果。
- streak：当天只有背诵动作也计为一个学习日（新用例），且原有"只做题"用例不回归。
- 日队列：改 daily_recitation_limit 无需重启即生效；超过 20 收口到 20。
- `pytest -m e2e` 新增第 4 条：家长手填 3 条 → due 返回 3 条 → 逐条自评（记得/没记住混合）→
  阶梯与 scheduled_next 正确 → 看板"今日背诵"与 streak 一致。
- `pytest -q` 全绿、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】让模型生成背诵内容或判断"背得对不对"（本票 100% 确定性）；
把背诵条目塞进错题本或写 attempts；背诵计入 mastery；做"相似条目自动合并"的猜测；
把 daily_recitation_limit 硬编码；改错题链路的既有语义；顺手动 P3-3b/c 的范围。
```

## P3-3b —— 教材词表批量导入（CSV/TSV 粘贴或上传）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（导入即不可信输入）+ TICKETS.md 的 P3-3b
+ 现有 app/api/recitations.py、app/services/recitation.py、app/models/recitation.py
（0020 已建表，本票**不动表结构**）。
【全局纪律】一条 ticket = 一个 PR；禁止引入新依赖（Python stdlib `csv` 足够，禁 pandas）；
禁止改 0020 迁移与两张表的 DDL；禁止做导入前草稿暂存表。
【信任边界（写进代码注释）】词表来自家长本人 = 可信来源，直接入库 + 逐行报告即可，
**不需要**像外部 agent 转录那样过草稿/核对页；但"不可信输入"的体积与字段校验照抄（家长也会手滑）。
【任务】
1) 后端 `POST /api/recitations/import`（挂 require_parent），body = {subject, text}：
   - 解析：服务端做，前端只上传/粘贴原文。首行含 TAB → 按 TAB 切，否则按 CSV 切
     （stdlib csv，支持引号转义）；可选表头行（首行命中 prompt/answer/unit 关键字则跳过）。
   - 每行取 1–3 列：prompt（必填）、answer（可选）、unit（可选）；空行跳过、
     全注释行（# 开头）跳过。
   - 校验与限额：单次 ≤500 行、body ≤256KB、prompt ≤200 / answer ≤500 / unit ≤40 字符，
     超限整批 422 并指明行号与原因；编码只接受 UTF-8（带/不带 BOM 均可）。
   - 入库：逐行走既有 create 路径（复用 UNIQUE(subject, prompt)）；命中重复 → 该行报
     duplicate（不静默丢弃、**不更新已有行**）；其它校验失败 → 该行报 {line, field?, reason}，
     **坏行不阻断好行**。subject 只接受 MEMORY_SUBJECTS 内的学科（本票前端默认英语）。
   - 响应：{imported, duplicates: [{line, prompt}], errors: [{line, field?, reason}]}。
2) 前端 /recitations 家长区新增"批量导入"：文件选择 + 粘贴文本二选一（同一提交函数）、
   subject 固定英语下拉（默认英语，字段保留通用性）、报告渲染（成功 N / 重复 N（列前几条 prompt）/
   错误逐条）、UTF-8 提示（Excel 请用"CSV UTF-8"导出，否则 GBK 会乱码）。
3) 文档：CHANGELOG [Unreleased]、STATUS §4.20 续写、TICKETS P3-3b 打勾、施工卡同步。
【DoD】
- 集成测试：全成功 / 混合（坏行 + 重复 + 好行）/ 超 500 行 422 / 超长字段 422 / BOM 文件可读 /
  TSV 与 CSV 各一 / 未解锁 403 / subject 不在 MEMORY_SUBJECTS 422 / 同文本重复提交全部 duplicate
  且不产生第二条数据（天然幂等）。
- `pytest -m e2e` 第 5 条：家长导入 3 行（1 重复、1 坏）→ 报告正确、好行入库 →
  孩子端 /due 出现新条目 → 自评走阶梯（衔接 P3-3a 的既有 e2e 断言风格）。
- `pytest -q` 全绿（当前基线 442 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】静默丢弃坏行或重复行；静默更新已有条目；引入 pandas / 新依赖；做草稿暂存表；
让 LLM 生成或翻译词表；把解析放前端（服务端是唯一解析与校验真源）；动 0020 的表结构。
```

> **状态同步（2026-11-03）**：本卡已交付（`feat/p3-3b-recitation-import`）。
> 落地：`wengu-api/app/services/recitation_import.py`（stdlib `csv`、TSV 判定、表头/空行/注释、
> 限额与 U+FFFD 拒绝、物理行号）+ `POST /api/recitations/import`（`require_parent`）+
> `/recitations` 家长区「批量导入」；**无迁移、未改 0020 DDL、无新依赖**。
> 验证：新增单测 11 + 集成 11 + e2e 第 5 条；全量 **465 passed**（unit 304 / integration 156 /
> e2e 5）；`ruff check --no-cache .` 与 `npm run build` 全绿。

## P3-3c —— 从错题抽词（候选视图 + 家长勾选入库，零迁移）

```
你在 wengu 仓库工作。开工前完整读：TICKETS.md 的 P3-3c + app/services/recitation.py
（create_item / due_items 的写法）+ app/models/mistakes.py 与 app/models/knowledge.py
（错题 → 主考点 → 学科的连接路径）。
【全局纪律】一条 ticket = 一个 PR；**本票零迁移**（候选是现算视图，不是新表）；
禁止引入新依赖；禁止改动错题链路语义与 recitation 两表结构。
【定位】P3-3 第三期（C）：把英语错题出现过的词补进背诵池，作为手填（A）与词表导入（B）
之后的增量来源。候选只读展示，**必须家长勾选确认才入库**。
【任务】
1) 候选抽取（纯函数放 services/recitation.py）：
   - 取数：active 英语错题（mistakes JOIN knowledge_seed ON mistakes.primary_topic_id =
     knowledge_seed.id，subject='英语'）当前版本（mistake_versions.version = mistakes.current_version）
     的 problem_text（NOT NULL，核对页确认过的题面）。
   - token：正则 [A-Za-z][A-Za-z'-]+，lowercase，去尾 's，长度 ≥2。
   - 排除：已在 recitation_items（任何状态，按 subject='英语' + prompt 匹配）的词；
     内置英文停用词起步集（~40 个功能词，硬编码常量 THE/OF/AND/IS/...，注释写明
     "按试用反馈增删，不做配置化"——没有它 the/is 会霸榜，抽词就废了）。
   - 排序与截断：按出现错题数降序（错得越多越该背），取前 50。
2) API（全部挂 require_parent——抽词与入库都是家长动作）：
   - GET /api/recitations/candidates?limit=50 → [{word, mistake_count}]
   - POST /api/recitations/candidates/batch（body {words: [...], unit?}）→
     复用 create_item（subject='英语'，UNIQUE 去重逐条报 duplicate），响应结构同 import 报告；
     answer 留空（**不给候选词自动配释义**，家长可后续手补，卡面只显示 prompt）。
   - 撤销本批 = 前端对本批 ids 逐条 PATCH status='retired'（不新增撤销端点）。
3) 前端 /recitations 家长区新增"从错题抽词"：候选列表（词 + 出现错题数）+ 勾选 +
   一键入库 + 成功后"撤销本批"；候选每次现算，无后台任务、无定时同步。
【DoD】
- 候选：去重 / 词频排序 / 停用词排除 / 排除已有条目（active 与 retired 都算"已有"）各有断言。
- 批量入库：走 UNIQUE 去重逐条报告；**四表快照断言**（mistakes / mistake_versions /
  attempts / review_schedules）零变化——抽词绝不改错题链路。
- 撤销：retired 后退出 /due；再抽词时该词重新出现在候选里（因为 retired 也算"已有"→
  不再出现在候选，此处以实测为准并在 PR 里写明行为）。
- `pytest -m e2e` 第 6 条：确认 2 条英语错题（题干含重复词与停用词）→ 候选排序/去重/停用词
  断言 → 勾选批量入库 → /due 出现 → 自评走阶梯。
- `pytest -q` 全绿（当前基线 465 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】LLM 抽词 / 翻译 / 选词；TF-IDF 等权重算法（只有"错题数降序"一把尺）；
中文词抽取（本票只做英文 token）；自动定期同步或后台任务；**未经家长勾选自动入库**；
给候选词自动配释义或例句；动 0020 两表结构；做新表或新迁移。
```

## P5-1a —— 配置持久化修复 + 家长配置端点（先修 Docker 下热配置失效）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（配置热加载那条承诺）+ §7（开源分发护栏）
+ TICKETS.md 的 P5-1a（含缺陷背景）+ app/core/runtime_config.py、app/core/config.py、
app/services/backup.py、app/services/local_seed.py（原子写参照）。
【全局纪律】一条 ticket = 一个 PR；禁止引入新依赖；禁止改任何迁移与表结构；
禁止把密钥写进 app-config（密钥仍只 `.env`）；本票不做 /setup 界面（那是 P5-1b）。
【缺陷背景（必读，别当成增强）】`PROJECT_ROOT = API_DIR.parent`：原生跑 =仓库根（正常），
Docker 跑 WORKDIR=/app → PROJECT_ROOT=/ → `app_config_path()` 指向容器根 `/config/app-config.json`，
而 Dockerfile 没 COPY config/、compose 只挂 ./data 与 ./seeds。结论：**Docker 形态下
daily_review_limit / daily_recitation_limit / exam_day_limit_factor 永远读不到、静默用默认值**，
AGENTS §5 的"UI 内改免重启"在主部署路径上是空的。
【任务】
1) `app_config_path()` 解析顺序改为：`WENGU_APP_CONFIG`（测试覆盖）→
   **`<settings.data_dir>/app-config.json`**（Docker 与原生都持久）→
   兼容回退仓库根 `config/app-config.json`（存在则读，并在 GET /api/config 的响应里
   标明来源与"建议迁移到 data 目录"提示）。**写入一律落 data_dir 那份**，
   绝不自动搬运、绝不删除或覆盖老路径文件（那是用户的文件）。
2) 原子写：同目录 tmp + fsync + `os.replace`，进程内锁串行（照抄 services/local_seed.py 的写法）。
3) API（全部挂 require_parent）：
   - `GET /api/config` → 生效值 + 每项来源（file / default）+ 当前落盘路径 + 兼容提示。
   - `PUT /api/config` → 只接受白名单键并校验区间：daily_review_limit 1..200、
     daily_recitation_limit 1..20、exam_day_limit_factor 1..3（浮点）；
     非法值 422 且**不写文件**；白名单外的键一律拒绝（不做"以后可能要"的预留）。
4) 备份纳入：services/backup.py 的打包清单加 `<data>/app-config.json`（文件存在才加、
   不存在不报错），manifest 的 files 记录其 sha256；顺带解决 P5-2 已知边界
   "换机恢复后热参数回默认"。恢复脚本 restore.ps1 与文档同步（该文件随 data 目录整库替换）。
5) 文档同步：config/README.md 与 app-config.example.json 写明新位置 + 兼容回退；
   docs/deploy/docker.md 增补"配置随 data 卷持久化，无需额外挂载"；AGENTS §5 的路径口径更新；
   CHANGELOG [Unreleased] 记 Fixed（写清"仅 Docker 形态受影响、原生一直正常"）。
【DoD】
- 路径解析回归测试：模拟 Docker 布局（API_DIR=/app）断言解析结果落在 data_dir 内；
  原生布局断言优先 data_dir、data_dir 无文件时回退仓库根 config/ 且**只读不写**。
- 热加载真实证据：PUT 改 daily_review_limit 后**不重启**，`GET /api/reviews/due` 的上限立即变化
  （断言响应里的 limit 字段），并断言非法值 422 后文件内容未变。
- 权限：未解锁 GET/PUT /api/config 均 403。
- 备份：导出包内含 app-config.json（存在时）；模拟恢复后配置值不丢；文件不存在时导出不报错。
- 原子写：并发 PUT 不产生半截 JSON（进程内锁 + os.replace 的测试）。
- `pytest -q` 全绿（当前基线 484 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】把密钥或任何凭据写进 app-config；自动搬运/删除老路径 config/ 文件；
接受白名单外的配置键；改表结构或加迁移；在本票顺手做 /setup 界面；
把 app_config_path 改成"只认 data_dir"从而弄坏原生老用户的现有配置（必须保留回退）。
```

> **状态同步（2026-11-03，本卡已交付）**：分支 `feat/p3-3c-candidates`。
> 落地：`wengu-api/app/services/recitation.py`（`english_word_tokens` / `extract_word_candidates`
> 纯函数 + `candidate_words` 现算查询）、`wengu-api/app/services/recitation_import.py`
> （`add_candidate_words` 复用 `create_item`）、`GET /api/recitations/candidates` 与
> `POST /api/recitations/candidates/batch`（均 `require_parent`）+ `/recitations` 家长区
> 「从错题抽词」候选表（勾选 / 全选 / 清空 / 可选 unit / 入库 / 撤销本批）。
> 候选口径：active 英语错题当前版本题面 → 正则 token → 小写去尾 `'s` → 长度 ≥2 →
> 去停用词（硬编码 80 词起步集，注释「按试用反馈增删，不做配置化」）→ 排除 `recitation_items`
> 任意状态同词（不区分大小写）→ 同题内去重 → 按出现错题数降序、同数按字母升序 → 取前 50。
> `answer` 留空，不自动配释义。撤销走前端逐条 PATCH `status='retired'`，无新端点。
> **零迁移**（alembic head 仍 0020）、零新依赖、未改错题链路与 recitation 两表结构。
> 验证：新增单测 11 + 集成 7 + e2e 第 6 条；全量 **484 passed**（unit 315 / integration 163 /
> e2e 6）；四表快照（`mistakes`/`mistake_versions`/`attempts`/`review_schedules`）在 GET 与批量
> 入库前后零变化。retired 行为实测：仍算「已有」→ 再抽词**不**重新出现，重新入库报 duplicate，
> 家长需手动把条目改回 active。下一张待投 = **P5-1**。
>
> **状态同步（2026-11-04）**：P5-1a 已交付（PR#32，配置落 `<data_dir>` + `GET/PUT /api/config`，
> 全量 **506 passed**）。下一张待投 = **P5-1b**（下方新卡）。

## P5-1b —— 首次运行向导（单页 /setup + 未完成横幅）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §7（开源分发护栏）+ §2.4（可信网络默认）
+ TICKETS.md 的 P5-1b（含"不采集年级/不做学科勾选"的口径修正与理由）+
app/api/config.py、app/core/runtime_config.py（P5-1a 刚落地的白名单与校验）、
app/api/seed.py 的 GET /api/seed/summary、wengu-web/src/components/{AppLayout,ParentGate}.tsx。
【全局纪律】一条 ticket = 一个 PR；禁止引入新依赖；禁止新增迁移或表结构；
禁止新增配置键（除 setup_completed 外）；向导是**单页**，不做多步向导机。
【口径修正（必读，覆盖 AGENTS §7 旧表述）】向导**不采集年级、不做"勾选学科"**：
v2.5 后 seed 全量装载初中 7–9、复习与考核都不以年级为输入，采集了没有逻辑消费它 =
装饰字段 + 多余 PII；家里就一个孩子，全部学科都是他的，勾选同样无作用。
本票只做三件**真有作用**的事：展示 seed 覆盖、设置运行上限、标记完成。
【任务】
1) 后端：把 `setup_completed: bool` 加进 runtime_config 白名单（_ALLOWED_KEYS / 校验体系）。
   ⚠️ 现有 `_reject_bool` 是挂在三个**数值键**上的 field_validator：加布尔键时必须按字段分别校验
   —— 布尔键只接受真正的 true/false，数值键继续拒绝布尔；
   **不得**为省事把"拒绝布尔"改成全局放开或全局禁止（那会让 `daily_review_limit: true` 复活）。
   非法值 422 且不写文件（沿用 P5-1a 的 save_config 语义）。
2) 前端 `/setup` 单页（家长解锁才让写，复用 ParentGate）：
   ① seed 覆盖：调既有 `GET /api/seed/summary`，按 数学/英语/物理/语文/化学 五行显示 topics 数。
      **陷阱：该接口按 group_by 聚合，零主题的学科不返回行**——前端必须把"缺席"当 0 处理，
      否则语文/化学会显示成空白而不是"0 个知识点"。为 0 的学科给一条引导：
      "先去「学科 seed」页建章级知识点" + 链接到 /local-seed（只引导，不自动建）。
   ② 运行上限：GET /api/config 回填，PUT /api/config 保存 daily_review_limit /
      daily_recitation_limit / exam_day_limit_factor；保存成功后显示"已生效，无需重启"。
   ③ 完成/跳过：PUT /api/config {setup_completed: true}。"跳过"与"完成"写同一个键
      （语义就是"不再提示"），**不要新增 setup_skipped 第二个标记**。
3) AppLayout 顶部横幅：`setup_completed` 为假时出现，含进入 /setup 的链接；完成后消失。
   **不劫持路由**（孩子一打开就被迫填表是错的），/setup 任何时候可从横幅再次进入。
4) 文档：CHANGELOG [Unreleased] 记 Added、STATUS 续写 P5-1 段、README 快速开始加一句
   "首次打开会有设置向导"、AGENTS §7 的"孩子/年级→勾选学科"按本票口径修正、
   TICKETS 与本卡状态同步。
【DoD】
- 后端：setup_completed 只接受布尔（传 "yes" / 1 / null → 422 且不写文件）；
  **数值键仍拒绝布尔**（回归断言，防"全局放开"）；未解锁 GET/PUT 403 不变。
- 向导写入的上限经 `GET /api/reviews/due` 的 **`daily_limit`** 字段立即生效（不重启）；
  注意 `limit` 是请求参数、`daily_limit` 才是运行时配置生效值，别断错字段。
- seed 覆盖：语文/化学在零主题时显示 0（不是空白）并出现 /local-seed 引导链接——有测试或截图证据。
- 横幅：未完成出现、完成后消失（组件测试或 e2e 断言）；不做路由劫持（断言未完成时
  直接访问 /review 仍正常渲染）。
- 窄屏可用（375px 宽不溢出）。
- `pytest -m e2e` 第 7 条：全新库 → GET /api/config 的 setup_completed 为假 →
  向导设 daily_review_limit=3 + 标记完成 → 横幅条件消失 → due 的 daily_limit 立即为 3。
- `pytest -q` 全绿（当前基线 506 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】采集姓名/生日/年级/照片；强制路由劫持；在向导里放模型 Key 或供应商选择
（v2.5 零模型，放了就是邀请回归）；新增 setup_skipped 之类第二个标记键；
新建"seed 覆盖"端点（GET /api/seed/summary 已够用）；把单页做成多步向导；
为"以后按年级过滤"预留 profile 结构。
```

## P0-4 —— 测试基线噪音清理：`Event loop is closed`

```
你在 wengu 仓库工作。开工前完整读：TICKETS.md 的 P0-4 + wengu-api/tests/conftest.py +
app/core/database.py（create_sqlite_engine）+ 任意两个"建引擎不 dispose"的测试文件
（如 tests/integration/test_config_api.py、tests/e2e/test_closed_loop.py）。
【现象与根因（已审计定位，别重新猜）】全量 `pytest -q` 间歇出现 1–3 条
`PytestUnhandledThreadExceptionWarning: ... RuntimeError: Event loop is closed`，用例全通过；
同一棵树多次跑出 3 / 2 / 1 / 0 条不等，单独跑 e2e+backup+config 三次 0 条 ——
**GC 时序依赖**。根因：**21 个测试文件**用 `create_sqlite_engine` / `create_engine` 建引擎后
**从不 `engine.dispose()`**，conftest 也没有兜底；aiosqlite 的连接工作线程在事件循环关闭之后
才被回收，收尾即抛该异常。
【全局纪律】一条 ticket = 一个 PR；**只改测试基建**：禁止改生产代码的池配置/引擎参数，
禁止逐文件补 dispose（会漏掉以后新增的文件），禁止用 warnings 过滤器把噪音"消音"。
【任务】在 `wengu-api/tests/conftest.py` 加**一个 autouse 异步 fixture**：
- 包装 `app.core.database.create_sqlite_engine` 与 `sqlalchemy.create_engine`，
  登记本次测试内创建的引擎；
- 在 **teardown 内（此时所属事件循环还活着）** 逐个释放：异步引擎 `await engine.dispose()`，
  同步引擎 `engine.dispose()`；异常吞掉不影响断言（但要打印，便于排查）。
一处改动覆盖全部 21 个文件与以后新增文件，测试文件本体一行不动。
【DoD】
- `pytest -q -W error::pytest.PytestUnhandledThreadExceptionWarning` **连续跑 5 遍全绿**
  （噪音一旦复现就等于失败）；把 5 遍的输出贴进 PR。
- 全量用例数不减少（当前基线 521 passed，只允许持平或增加）；
- `ruff check --no-cache .` 绿、`npm run build` 绿（本票不动前端，跑一遍证明无回归）；
- 5 遍全绿后把该 filter 固化进 `pyproject.toml` 的 `filterwarnings`，**锁住不回潮**；
  若固化后 CI 因第三方 warning 变红，回退为只保留 fixture 修复并在 PR 里说明原因与证据。
【禁止】改 `create_sqlite_engine` 的 pool/参数来"绕过"；`warnings.filterwarnings("ignore")`
之类的消音手法；顺手重构既有测试 fixture；新增依赖。
```

## P1-3e —— 移动端投递入口：粘贴整段转录 JSON（PWA 的替代票）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（导入即不可信输入）+ §17-A（为何砍 PWA、
本票补的是什么）+ TICKETS.md 的 P1-3e + wengu-api/app/api/imports.py（POST /api/imports 的
错误映射）+ wengu-web/src/api/{client,endpoints,types}.ts 与 pages/ImportPage.tsx 现状。
【全局纪律】一条 ticket = 一个 PR；禁止引入新依赖；禁止新写绕过 services/inbox.py
`ingest_raw_payload` 的入库路径；禁止给这个入口加自动转正；禁止引入文件上传/对象存储；
禁止重新引入 manifest/service worker（已进 §12 反清单）。
【背景】`POST /api/imports` 端点已存在且前端已在用（手填表单构建单条 items 后 POST），
但导入页**没有**"贴一段整份转录 JSON"的入口——外部 agent 在手机/平板上产出的整份 JSON
今天只能先进 inbox 文件。本票就是把这条路搬到页面上。
【任务】
1) 后端：**零改动预期**。POST /api/imports 接收原始字节、错误映射已齐全
   （400 JSON 错 / 413 超限 / 422 信封错 / 422 {message, errors[]} 无有效项）。
   若实现中发现缺口，停下来报告，不要顺手改语义。
2) 前端 /import 页新增"粘贴转录 JSON"区：
   - Textarea 粘贴 + 本地 .json 文件读取（file.text()，按 UTF-8）二选一，进同一个提交函数；
   - ⚠️ 新增 `importRawText(text)`：以**原文**为 body、Content-Type: application/json 直发。
     **绝不能**复用 `requestJson`（它会 JSON.stringify(body)，把原文二次序列化成
     "字符串套字符串"，后端 400）；走 client.ts 的底层 fetch/ApiError 通道即可；
   - 成功：渲染 batch_id / status / duplicate / draft_count / accepted_count /
     dropped_unknown_fields，duplicate=true 时显示"重复导入已跳过"（P1-9b 口径），
     并给"跳核对页"链接；
   - 失败：400/413/422 各按 detail 渲染；422 {message, errors[]} 时**逐行渲染**
     errors 的 index/field/reason（复用 P1-9b 的呈现，不得只吐 message）。
3) 移动端可用：375px 宽无横向溢出（含错误清单与 JSON 示例块）、按钮可点、Textarea 可滚动。
4) 文档：CHANGELOG [Unreleased] 记 Added、STATUS 续写、TICKETS P1-3e 打勾、施工卡状态同步。
【DoD】
- 贴一段含 3 题（含 1 坏项）的模板 JSON → 2 条成草稿、坏项逐条 {index, field, reason} 报错、
  **错题本行数零变化**（全表快照断言沿用既有集成测试的写法）；
- 同一段再贴一次 → duplicate=true、不重复建批；
- 非 JSON 文本 → 400 且错误信息可读（不含原始堆栈）；
- 375px 宽无横向溢出（截图或组件测试）；
- `pytest -q` 全绿（当前基线 521 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿；
- `pytest -m e2e` 第 8 条：走**原始文本路径**（不是构建 items 的对象路径）投递含坏项的 JSON →
  草稿与错误报告正确 → duplicate 重投 → 核对页确认一条入本。
【禁止】让模型或前端"修好"坏行再提交（坏行就该报错给家长）；自动转正；二次序列化；
引入文件上传/对象存储/manifest；把内部异常栈原样吐给用户；动 0020 与错题链路。
```

> **状态：已完成（2026-11-04，分支 `feat/p1-3e-paste-import`，待评审）**——`/import` 新增
> 原文粘贴 + 本地 `.json` 读取（`file.text()`）共用提交函数；`importRawText` 原文直发、
> 不复用 `requestJson`；422 逐行渲染 `index/field/reason`；e2e 第 8 条走原文路径
> （部分坏项 → 重投去重 → 核对页确认入本）。实跑 522 passed、e2e 8、ruff 绿、build 绿；
> 后端零改动、无迁移、无新依赖。
> **已合并：PR#35，`main` = `b600d4d`。**

## P1-3f —— 粘贴/文件导入显式剥离 BOM（P1-3e 后续小改）

```
你在 wengu 仓库工作。开工前完整读：TICKETS.md 的 P1-3f + wengu-web/src/pages/ImportPage.tsx
的 submitRaw / handleRawFile + wengu-api/app/services/inbox.py 的 ingest_raw_payload（sha256 去重）。
【背景（审核方实测，别当成增强）】现在 BOM 是被 `text.trim()` **顺带**去掉的——
ECMAScript 把 U+FEFF 列为 WhiteSpace，所以 trim 会去掉它；而 Python `json.loads` 拒绝 BOM 开头
（实测 JSONDecodeError）。也就是说 Windows 记事本/Excel 导出的"UTF-8（带 BOM）.json"今天能导入，
**但这是巧合不是设计**：没注释、没测试、DoD 也没要求。任何人把 trim 换成别的空白处理
（例如只 `replace(/\s+$/,'')` 或改 slice），BOM 就会留在报文里。
⚠️ **后果更正（交付实测，审核方复验）**：本卡原写"BOM 报文立刻变 400"是错的——后端
`ingest_raw_payload(raw: bytes)` 收 bytes，CPython 按 `utf-8-sig` 吃掉 BOM（只有对 `str` 才抛
`Unexpected UTF-8 BOM`），**不会 400**。真后果是带/不带 BOM 的同一报文产生**不同 sha256**，
让 `import_batches` 批次去重失效。修法不变（投递侧显式归一），理由以此为准。
【全局纪律】一条 ticket = 一个 PR；只动前端投递侧清洗，**后端契约不动**
（不许让 `ingest_raw_payload` 去容忍 BOM——清洗应在投递侧）；禁止引入编码检测库；
禁止顺手重构 ImportPage 其它逻辑。
【任务】在 submitRaw 的前置加**显式** BOM 剥离：`text.replace(/^\uFEFF+/, "")` 之后再 trim，
并写一行注释说明"为何必须显式处理：Python json.loads 拒绝 BOM"。
文件路径（`file.text()`）与粘贴路径共用同一处理，确保同一内容（带或不带 BOM）
得到**同一 sha256**、命中同一批次去重。
【DoD】
- 新增断言：带 BOM 的合法报文（`\uFEFF{...}`）走前端提交路径返回 **201**、草稿数正确；
- 同内容去 BOM 与带 BOM 两次提交 → 第二次 `duplicate=true`（证明归一到同一 sha256）；
- 非 JSON 文本 → 400 且错误可读；空文本 / 全 BOM 文本 → 不发请求（按钮禁用或提前返回）；
- `pytest -q` 全绿（当前基线 522 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】改后端 `ingest_raw_payload`/`imports.py` 去容忍 BOM；引入 jschardet 之类检测库；
顺手重构 ImportPage；把 trim 删掉（BOM 剥离要在它之前或独立生效，两者都要保留）。
```

> **状态：已完成（2026-11-04，分支 `feat/p1-3f-bom`，待评审）**——`submitRaw` 先显式剥离
> `^\uFEFF+` 再 `trim()`，粘贴/文件共用；e2e 第 9 条证明带/不带 BOM 命中同一批次。
> 实跑 523 passed（e2e 9）、`ruff check --no-cache .` 绿、`npm run build` 绿；
> 无迁移、无新依赖、后端零改动。**已记：后端 bytes 路径 CPython 会按 utf-8-sig 识别 BOM，
> 未剥离的后果是去重 sha256 分叉，而非工单所述必然 400。**

## P1-13 —— 知识点归并 UI（补受控生长的另一半，零迁移）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §6（知识点两级 + 受控生长：优先复用·不覆盖确认值·
归并需人工确认）+ §5（AI 建议值与用户确认值分离；append-only）+ TICKETS.md 的 P1-13
（含"盘上现状"一节，已逐行核实）+ wengu-api/app/api/concepts.py +
app/services/concepts.py（merge_concepts / resolve_concepts / concept_family_ids / list_concepts）+
wengu-web/src/pages/MistakeDetailPage.tsx（已管 concepts 的标签区）与 LocalSeedPage.tsx
（:496 的"确认框带受影响计数"范式，照抄它）。
【总则】现有代码与本卡描述不一致时**以实际代码为准**：先读再改，发现不一致写进交付描述，
不要硬凑成卡里写的样子。（本合集里审核方的卡已被交付实测纠正过 5 次，这条是硬要求。）
【全局纪律】一条 ticket = 一个 PR；**零迁移**（不改 Concept 表结构、不新建归并历史表）；
禁止引入新依赖；禁止物理删除 concept 行；禁止改写 mistake_versions 的 append-only 历史标签。
【盘上事实（已核实，直接依赖）】
- 三个 concepts 端点当前**都没有 require_parent**；
- `POST /api/concepts/merge` 请求体 `{source_id:int≥1, target_id:int≥1, actor:"student"|"parent"}`，
  默认 actor="student"；响应 `{source, target, aliases_moved}`；
- 异常继承 `ConceptMerged ⊂ ConceptConflict ⊂ ValueError`，API 已 catch：
  ConceptNotFound→404、ConceptConflict→409（**已归并的源再调是 409，不是幂等成功**）；
- `merge_concepts` 只写 `source.merged_into_id` + 把源名称/别名并入目标 `ConceptAlias`，
  并校验：自归并 / 跨 category / 别名与第三方概念冲突 都抛 409；
- `list_concepts` 已过滤 `merged_into_id.is_(None)` → 归并后源点自动从列表消失，无需额外改动；
- 前端 `endpoints.ts` 只有 listConcepts / createConcept，**没有 merge**。
【任务】
1) 后端：给 `POST /api/concepts/merge` 挂 `require_parent`。
   ⚠️ **只挂这一个**：`GET /api/concepts` 与 `POST /api/concepts`（建点/复用）必须保持孩子区可用，
   锁了会断掉"孩子边做边长标签"的主路径。
2) 后端：新增只读 `GET /api/concepts/merge-preview?source_id=&target_id=`
   → `{source, target, source_aliases: string[], affected_mistakes: int, same_category: bool}`。
   `affected_mistakes` = 当前版本 `mistake_versions.confirmed_concept_ids_json` 含源点 id 的
   **active** 错题数（扫描写法参照 `services/dashboard.py:228`，不新建表、不加索引）；
   也挂 `require_parent`。非法 id / 概念不存在 → 404；跨 category → 返回 same_category=false
   （不报错，让 UI 提示"只能在同一知识点下归并"）。
3) 前端：`MistakeDetailPage` 的知识点区新增"归并知识点"入口，**仅家长解锁可见**；
   源与目标两个选择器都限定在**同一 category**内（后端跨 category 会 409）；
   打开时调 merge-preview，确认框显示"源名称 → 目标名称 · 将并入 N 个别名 · 影响 M 道错题"，
   文案与交互照抄 LocalSeedPage 删除确认（:496）；提交时 `actor:"parent"`；
   成功后刷新 concepts 列表并提示"历史错题标签与事件未改动，仅名称解析指向最终概念"。
4) 文档：CHANGELOG [Unreleased] 记 Added、STATUS、TICKETS P1-13 打勾、施工卡状态同步。
【DoD】
- 归并后：`merged_into_id` 与别名生效、`GET /api/concepts` 只出目标点、
  **`mistake_versions` 全表快照逐行一字不改**（这条是 append-only 的硬证据，必须真断）；
- 名称解析走合并家族：`resolve_concepts([源id])` 返回目标；`concept_family_ids(目标id)` 含源 id；
- 权限：未解锁调 merge / merge-preview → 403；**未解锁调 GET /api/concepts 与 POST /api/concepts
  仍 2xx**（防"一并锁死"的回归断言，必须有）；
- 错误分支各有断言：自归并 409、跨 category 409、别名与第三方冲突 409（消息含"请先归并那个概念"）、
  源/目标已归并 **409**（不是幂等）、概念不存在 404；
- `affected_mistakes` 与实扫一致：测试造 2 道挂源点的 active 错题 + 1 道 voided 错题 → 断言 = 2；
- 窄屏可用（375px 不溢出）；
- `pytest -q` 全绿（当前基线 523 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】物理删除 concept 行；改写历史标签/事件；把建点入口也锁上 PIN；
做"相似度自动建议合并"（归并必须是人工动作）；新建归并历史表或改 Concept 表结构；
顺手改 recompute / 排期逻辑；引入新依赖。
```

> **状态：已完成（2026-11-04，分支 `feat/p1-13-merge-ui`，待评审）**——merge 与只读
> `merge-preview` 挂 `require_parent`，建点/列表仍留孩子区；预览实扫 active 错题数、跨
> category 只返回 `same_category=false`；错题详情家长可见归并入口（同 category、预览
> "源 → 目标 · N 个别名 · M 道错题"）；`mistake_versions` 全表快照逐行不变。实跑
> 526 passed（unit 344 / integration 173 / e2e 9）、`ruff check --no-cache .` 绿、
> `npm run build` 绿；临时库浏览器实测归并与未解锁 403、375px 无溢出。无迁移、无新依赖。
> **与卡偏差：预览在两个选择器都选好后请求（非打开即调）。**
> **PR#37 返工：预览改用 `projected_aliases_moved`（含源名称，与 `aliases_moved` 同源计算），
> 响应在 `session.begin()` 块内构造、不依赖 `expire_on_commit=False`。**

## P1-13b —— 归并弹窗取消预选（产品决定，一行级小改）

```
你在 wengu 仓库工作。开工前完整读：TICKETS.md 的 P1-13b + wengu-web/src/pages/MistakeDetailPage.tsx
里归并弹窗的初始化逻辑（现在会在"当前错题只有 1 个 concept"时把它预选为源）。
【决定与理由】归并弹窗**一律不预选**源或目标。源是"会被并掉、从列表消失的那个"，
方向性后果不该由默认值替家长决定；错题只有 1 个 concept 时预选为源，恰好是最容易一次点错的场景。
【全局纪律】一条 ticket = 一个 PR；**零迁移**；只改弹窗初始状态，
不动归并语义 / 权限 / 预览契约 / 事务边界；禁止引入新依赖。
【任务】
1) 删除预选逻辑：打开弹窗时 sourceId 与 targetId 都为空（含"错题只有 1 个 concept"的场景）。
2) 未同时选好源与目标时：确认按钮禁用，且**不发 merge-preview 请求**（保持现有"选齐才预览"的行为）。
3) 文案上把方向讲清楚（源=将被并入消失；目标=保留的最终概念），避免家长理解反。
【DoD】
- 断言"打开弹窗时源与目标均为空"，覆盖错题有 1 个 concept 与有多个 concept 两种场景；
- 断言未选齐时不发 preview、确认按钮不可用；
- 选齐后 preview 与 merge 的既有断言（projected_aliases_moved == aliases_moved、
  mistake_versions 全表快照不变、未解锁 403 而 GET/POST /api/concepts 仍 200）**一字不改仍全绿**；
- `pytest -q` 全绿（当前基线 526 passed）、CI 绿、`ruff check --no-cache .` 绿、`npm run build` 绿。
【禁止】改归并语义或权限；加"智能推荐目标/相似度建议"；改 Concept 表结构或加迁移；
顺手重构 MistakeDetailPage 其它部分；把提交信息临时文件写进 `.git/`（写到仓库外目录）。
```

> **状态：已合并（2026-11-04，PR#38 squash → main `18f81b9`，随 `v0.5.0` 发布）**——归并弹窗一律
> 不预选；未选齐不发 preview、确认禁用；文案明示归并方向。前端抽 `mergeSelection.ts` 纯函数，
> 新增 Node 内置 test runner 单测 5 条（`npm test`）并在 CI web job 增加该步骤；后端、权限、
> 预览契约与既有归并断言未动。实跑 526 passed、`ruff check --no-cache .` 绿、`npm test`
> 5 passed、`npm run build` 绿；零迁移、无新依赖。

## P4-1 —— Tailscale 可达性 + 把"局域网裸奔"的口子默认关掉

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §2.4（可信网络默认）+ §7（开源分发护栏）
+ §8（一票一 PR / DoD）+ TICKETS.md 的 P4-1 + docs/deploy/docker.md + docs/deploy/backup-restore.md
+ docs/deploy/upgrade-v0.5.0.md（第 2 节讲清了"起服务即自动迁移"，本票不要动它）。

【全局纪律】一条 ticket = 一个 PR。禁止引入新依赖（Python 与 npm 都不许加）；禁止引入
Caddy / Nginx basic auth / OAuth / Cloudflare Tunnel 等公网鉴权栈；零迁移；不改任何业务 API
的语义与权限。孩子区全程免登录、家长 PIN 只防误入——这是 AGENTS §2.4 的有意设计，本票只改
"哪些网络能碰到这台机器"，不改"碰到之后能干什么"。

【事实（审核方 2026-11-04 读盘核实，与本卡不一致时以实际代码为准，不要硬凑）】
1. 前端所有请求都是相对路径：wengu-web/src/api/client.ts 用 `fetch(path, …)`，endpoints.ts 里
   全是 "/api/…"；wengu-web/nginx.conf 把 `location /api/` 反代到 `http://api:8000`、`/health`
   单独代理。**结论：远程访问只需要打通 web 这一个入口，api 端口不需要对外发布。**
2. docker-compose.yml 现状：api `ports: "${WENGU_API_PORT:-8000}:8000"`、
   web `ports: "${WENGU_WEB_PORT:-5173}:80"` —— 两个都发布到所有网卡（Docker 绑 0.0.0.0），
   同网段任何设备都能读写错题本、看板、备份列表（备份路由虽 require_parent，但孩子区免登录）。
3. compose 第 47–64 行那段被注释的 tailscale 服务**今天起不来**：它挂载
   `./deploy/tailscale/serve.json`，而仓库里**连 `deploy/` 目录都不存在**；且它用
   `network_mode: service:api` + `devices: [/dev/net/tun]` + `cap_add: [NET_ADMIN]`，这套在
   **Docker Desktop for Windows 上不成立**。所以注释里"取消注释即启用"这句话是假的，要改。
   ⚠️ 平台结论必须由你在机器上实测得出，不许照抄本卡措辞：实测不通就改文档并在 PR 里报告。
4. 原生形态 run-trial.ps1 后端 `--host 127.0.0.1`（只本机），但 wengu-web/vite.config.ts 的
   `server.host = true` 让 5173 绑所有网卡，而 vite 自己又代理 `/api` 到 127.0.0.1:8000 ——
   于是**局域网设备经 5173 就能用到整个系统含写操作**。这条要么收紧、要么写明是有意为之，
   不要让它"偶然成立"。
5. 家长会话 cookie（app/api/session.py 的 `_set_cookie`）：`httponly=True`、`samesite="lax"`、
   12h，**没有 `secure`**。走 Tailscale Serve 的 HTTPS 同源访问不受影响；本票**不要**顺手加
   `secure=True`（会把现有 http://127.0.0.1:5173 打挂）。
6. `.env.example` 已有注释项 `# TS_AUTHKEY=`，compose 里是 `TS_AUTHKEY=${TS_AUTHKEY}`。
   保持"只在环境里注入、仓库内任何文件都不出现真实 key（含示例值）"。

【任务】
1. compose 端口收紧：给 api/web 的 `ports:` 加可配置绑定地址，**默认只绑回环**，例如
   `"${WENGU_BIND_ADDR:-127.0.0.1}:${WENGU_API_PORT:-8000}:8000"`（web 同理）。
   README 与 docs/deploy/docker.md 写清：默认仅本机；要让同网段设备直连须显式
   `WENGU_BIND_ADDR=0.0.0.0` 并自担风险；手机/平板远程用走第 2 条，不要靠开 0.0.0.0。
2. 按第 3 条事实把 tailscale 段落修成**真能照做**的样子：
   - 建出 `deploy/tailscale/serve.json`（路径与 compose 注释里的挂载路径一致），内容用
     `tailscale serve` 的配置格式；格式不确定就查官方文档，**不要凭记忆编字段**；
   - 注释块拆成两条路径并各自标平台：A) Linux / 群晖 = sidecar 容器；
     B) **Windows / macOS 试用机 = 宿主机安装 Tailscale 客户端 + `tailscale serve` 转发本机
     web 端口，compose 完全不参与**（试用机是 Windows 11 + Docker Desktop，默认教这条）；
   - TS_AUTHKEY 保持从环境读，文档里写"去 Tailscale 管理后台自建，别提交进仓库"。
3. 新增**只读**自检脚本 `scripts/remote-check.ps1`（与 restore.ps1 同目录同风格；PowerShell 5.1
   必须 UTF-8 **带 BOM** + **LF** 行尾，否则 PS5.1 直接解析失败——这是本仓踩过的坑）。打印：
   实际监听地址与端口、是否只绑回环、`docker compose port` 映射结果、`tailscale status` /
   `tailscale serve status`（未安装就打印"未安装"并继续）、本机访问 `http://127.0.0.1:<web>/health`
   的状态码。末尾给一句明确判定：仅本机可达 / 局域网可达 / tailnet 已转发。
   **严禁**脚本改配置、重启服务、写库、打印 cookie 或 key。
4. 第 4 条事实二选一并说明取舍：把 vite `server.host` 改为默认回环（需要 LAN 时显式 `npm run dev -- --host`），
   或在文档里明确写"原生形态 5173 局域网可达是已知事实 + 如何收紧"。
5. 口径统一：把"Cloudflare Tunnel 与 Tailscale 并列"的表述改掉——`TICKETS.md` 已改为只认 tailnet，
   你还要检查 README（技术栈表与"公网暴露"注意块）、`docs/deploy/docker.md`、
   `docs/specs/architecture/StudyDesk-设计说明文档-v2.md` §17-A 里是否还有同类并列，
   统一成"远程访问 = Tailscale（tailnet 私有网）；CF Tunnel / 公网反代必须先做真鉴权与用户隔离，未支持"。
6. 文档新增一节"手机/平板怎么连回家里那台机器"（三步：设备装客户端登录同一 tailnet → 家用机
   确认默认绑定并按平台做第 2 条 → 跑 `scripts/remote-check.ps1` 自检），放 `docs/deploy/`，
   并在 README 的远程访问处给链接。

【DoD】
- `docker compose config -q` 通过（CI 已有这一步，必须仍然绿）；`docker compose config` 的渲染
  输出里默认 ports 绑定确实是 `127.0.0.1` —— **把输出贴进 PR**，不要口头保证。
- `scripts/remote-check.ps1` 在本机跑通，**脱敏输出**贴进 PR（tailscale 输出里的设备名/邮箱打码）。
- 若动了 vite `server.host`：`npm run lint` 与 `npm run build` 绿，`run-trial.ps1` 仍能起前后端
  （贴关键日志行）。
- `pytest -q` 全绿（当前基线 **526 passed**）、`ruff check --no-cache .` 绿、CI 绿。
- 证伪证据：把绑定地址临时改回 `0.0.0.0` 跑一次 `remote-check.ps1` → 判定必须变成"局域网可达"
  → 改回 → 变绿。贴两次输出。**没有这一步就说明脚本是摆设。**
- CHANGELOG 记一条 Changed（默认只绑回环是**行为变更**，属 breaking-ish，必须写明家长怎么恢复
  LAN 直连），写在 `## [Unreleased]` 下。
【禁止】引入任何公网鉴权栈或新依赖；在仓库文件里出现真实 TS_AUTHKEY/示例 key；把 CF Tunnel 写成
等价选项；动 `data/`、`backups/`、生产 `wengu.db`；顺手重构 nginx.conf 或 compose 里与本票无关的
服务定义；把自检脚本写成"顺手修一下"的变更脚本；放宽 `require_parent` 或 PIN 逻辑来方便测试。

【另开一票，本票不做】P4-1b：`make backup` 是死目标（Makefile:138 调 `python -m scripts.local_backup`，
全仓无该模块，实跑 `No module named scripts.local_backup`），注释还指向不存在的
`docs/manuals/ops/backup.md`；现行唯一备份路径是家长区 `POST /api/backup/export`。
本票不要顺手改 Makefile 那一行以外的东西。
```

> **状态：已合并（2026-11-05，PR#39 squash → main `170b5da`）**。实际改动：
> compose 端口默认 `127.0.0.1`、vite 默认回环、`deploy/tailscale/serve.json`、
> 分平台注释块、只读 `scripts/remote-check.ps1`、`docs/deploy/mobile-access.md`；
> 与卡片的偏差以交付说明为准（Qoder 修正了本卡"事实 3"里 `network_mode: service:api` 与
> "反代到 web 容器 nginx:80"互相矛盾的缺陷，改为 `service:web`，并把单文件挂载改成目录挂载）。
>
> **合并后仍需在试用机验证的两件事**（静态审核证不了，别当已完成）：
> ① `tailscale serve --bg http://127.0.0.1:5173` 的 CLI 形式——官方 serve 文档只给裸端口
> `tailscale serve 3000` 且注明"CLI 在 1.52 版变更过"，须以试用机 `tailscale serve --help`
> 打印的形式为准，不符就改 `mobile-access.md` 与 compose 注释块 B（文档返工，不另开票）；
> ② sidecar 路径 A 从未在 Linux/群晖起过，`serve.json` 只做了格式同构比对、无运行时验证。
> 已知小瑕疵（留后续小票）：`remote-check.ps1` 在两个端口都没监听时仍判"仅本机可达"，
> 更准确的判定应是"服务未运行"。

## P4-1b —— 部署面命令体检（写给家长/开发者敲的每条命令都必须真能跑）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §7（开源分发护栏，受众是"能装 Docker 的半技术家长"）
+ §8（一票一 PR / DoD）+ TICKETS.md 的 P4-1b 与 P4-1c + Makefile 全文 + README.md 快速开始段
+ wengu-api/README.md + wengu-web/README.md + seeds/README.md + docs/deploy/ 全部四篇。

【全局纪律】一条 ticket = 一个 PR。禁止引入新依赖；零迁移；不改任何业务 API、权限与备份实现。
本票的产出物主要是"一张命令 → 实测结果"的对照表，不是新功能。
现有代码与本卡不一致时以实际代码为准，不要硬凑；本卡事实由审核方 2026-11-05 读盘核实。

【事实（逐条可复核）】
1. Makefile:135-138 `backup:` 调 `$(VENV_PY) -m scripts.local_backup`。`wengu-api/scripts/` 实际只有
   `__init__.py` / `export_topics_junior.py` / `import_questions.py` / `import_seed.py`，**全仓没有
   `local_backup.py`**。审核方只读实跑：`No module named scripts.local_backup`。
2. Makefile:134 注释指向 `docs/manuals/ops/backup.md`——**这个文件不存在**。`docs/manuals/` 本身在
   （只有 `guide/.gitkeep` 与 `ops/.gitkeep` 两个空骨架，见 CHANGELOG:1761 的建仓记录与 `目录结构.md:38`），
   但里面没有任何文档；实际部署文档在 `docs/deploy/`：backup-restore.md / docker.md / mobile-access.md /
   upgrade-v0.5.0.md。
3. Makefile:39 的 `.PHONY` 声明了 `restore`，但文件里**没有 `restore:` 规则**（Makefile 正文到 138 行
   为止，最后一条规则就是 `backup:`）→ `make restore` 只会报 "No rule to make target"；`help:` 也没列它。
4. Makefile:82 `dev-api` 是 `$(VENV_UVICORN) app.main:app --reload --host 0.0.0.0` —— **P4-1 收紧后
   仓库里最后一处"默认全网卡"**，而 README:73 与 wengu-api/README.md:36 都叫家长敲 `make dev-api`。
   原生 `run-trial.ps1` 用的是 `--host 127.0.0.1`，两条路径口径不一致。
5. Makefile:119 `lint:` 是 `$(VENV_RUFF) check .`，**不带 `--no-cache`**——本仓已多次被 `.ruff_cache`
   骗出与 CI 相反的假绿（投单前言也明写了"lint 证据必须 --no-cache"）。CI 是全新 checkout，绿是真的；
   本地这条给的是假证据。
6. `seeds/README.md:34` 行内注释写 `--src ../cn-math-taxonomy-main`，Makefile:96 写
   `--src ../../cn-math-taxonomy-main`。上游 clone 实际在**仓库根的上一级**（本机
   `D:\MyProducts\StudyDesk\cn-math-taxonomy-main`），`cd wengu-api` 之后只有 `../../` 对，README 少一级
   （CHANGELOG:1177 当年只修了 Makefile 侧，漏了这行注释）。
7. Makefile:53 的 `help` 说 `make seed-load` 是"从 seeds/ 装载 knowledge_seed + prerequisite_edges"，
   而 recipe（96）做的是**从上游 clone 转换生成 `seeds/data/`**（一次性开发者动作）。措辞会让家长
   以为这是日常步骤。
8. Makefile:137 `@mkdir -p backups` 在 Windows 分支由 `SHELL := cmd.exe`（10–11 行）执行，`-p` 是
   POSIX 写法，cmd.exe 下行为不可靠。**必须在 Windows 实测后再决定怎么写，不许照抄本卡措辞。**
9. 现行唯一备份路径：家长区 `POST /api/backup/export`（`app/api/backup.py` + `app/services/backup.py`，
   `VACUUM INTO` 一致性快照 → `<data_dir>/backups/wengu-backup-*.zip`，`KEEP_BACKUPS=10` 轮转）；
   恢复 = 停机整库替换 `scripts/restore.ps1` + `docs/deploy/backup-restore.md`。

【任务】
1. 删除死的 `backup:` 目标，并删掉 `.PHONY` 里不存在的 `restore`。**不要**新写一个 CLI 备份脚本
   冒充它（见【另开一票】）。`help` 的"备份"段改成指向家长区导出 + `docs/deploy/backup-restore.md`，
   并保留"每次升级/迁移前必须先备份"的提醒（P4-1 之后升级会自动迁移，见 upgrade-v0.5.0.md §2）。
2. `dev-api` 的 `--host 0.0.0.0` → 默认 `127.0.0.1`，与 P4-1 口径一致；确需局域网调试用变量覆盖
   （建议 `HOST ?= 127.0.0.1`），并在 README / wengu-api/README 写清怎么覆盖与风险。
3. `lint:` 加 `--no-cache`（`format:` 保持原样，不要顺手改无关目标）。
4. 修 `seeds/README.md` 那行 `--src` 层级；把 `help` 里 seed-load 的描述改成与 recipe 一致
   （"从上游 clone 转换生成 seeds/data/，一次性、开发者跑；需要本地有上游 clone"）。
5. **Windows 实测**（试用机就是 Windows 11 + PS 5.1）：`make help`、`make upgrade`、`make lint`、
   `make dev-api`、以及改动前的 `make backup` 各跑一次，把真实输出/报错原文贴进 PR。若 cmd.exe 下
   POSIX 写法确实有问题，改成跨平台安全的写法并说明依据。
6. 全仓再扫一遍"写给用户敲的命令/文件路径"是否还有死引用：README.md、wengu-api/README.md、
   wengu-web/README.md、seeds/README.md、`目录结构.md`（整篇都在声明路径，逐个对磁盘核一遍）、docs/**。
   每条要么实测通过，要么改掉/删掉；PR 里给一张 `命令 → 实测结果` 对照表，覆盖你扫到的每一条。

【DoD】
- `grep -rn "local_backup" .`（排除 node_modules/venv）**零命中**；`grep -rn "docs/manuals/ops/backup.md" .`
  也**零命中**——要么把那行注释改指 `docs/deploy/backup-restore.md`，要么把 `docs/manuals/` 这个空骨架
  一并清掉（`guide/.gitkeep` 与 `ops/.gitkeep` 里没有任何文档），二选一并在 PR 里说明为什么。
  CHANGELOG 里的历史条目**不要改**（那是发生过的事实，允许保留对旧名的记述）。
- `make help` 列出的每个 target 都真实存在；不存在的要么实现要么从 help 删除。
- `make lint` 与 CI 结论一致：同一份代码在干净 checkout 与本机都绿（证明假绿口子堵上了）。
- `make dev-api` 起来后跑 `.\scripts\remote-check.ps1`，判定必须是"仅本机可达"（api 只绑 127.0.0.1:8000），
  且 `http://127.0.0.1:8000/health` 返回 200；贴两次输出作为**证伪证据**（改回 0.0.0.0 时判定应变
  "局域网可达"）。
- `pytest -q` 全绿（当前基线 **526 passed**）、`ruff check --no-cache .` 绿、`npm run lint` 与
  `npm run build` 绿、CI 绿。零迁移、零新依赖、业务 API 与权限未改。
- CHANGELOG 在 `## [Unreleased]` 下记 Fixed（`make backup` 死目标）+ Changed（`make dev-api` 默认回环，
  属行为变更，要写怎么覆盖）。
【禁止】新写 `local_backup.py` 或任何 CLI 备份实现来"让 make backup 复活"；改 `app/services/backup.py`
的快照/轮转/manifest 逻辑；把 `dev-api` 留在 0.0.0.0 只靠文档提醒；为了数字好看删改 CHANGELOG 历史
条目；顺手重构 Makefile 里与本票无关的目标（install-*、seed-*、migrate、up/down/logs 等）。

【另开一票，本票不做】P4-1c：是否给家长一个"不停服务、命令行即可导出备份"的入口。技术上可行
（`VACUUM INTO` 对运行中的 WAL 库是安全的一致性快照，P5-2 就是这么实现的），但要一并决定：产物是否
同落 `<data_dir>/backups/` 并共用 `KEEP_BACKUPS` 轮转、CLI 侧的权限模型（绕过 PIN 意味着什么）、
Windows 计划任务怎么调、失败怎么告警。想清楚再开工，不要为了补 make 目标顺手造一半。
```

> **状态：已合并（2026-11-05，PR#40 squash → main `6f6c4cf`；原分支
> `feat/p4-1b-deploy-command-audit` 已删）**——交付内容与偏差见下。
>
> 【交付】
> 1. 删死目标：`backup:` 规则（调一个全仓不存在的备份模块）与 `.PHONY` 里没有规则的 `restore`
>    一并删除，**不新造任何 CLI 备份实现**；`help` 的备份段改为指向家长区「备份」页
>    （`POST /api/backup/export`，`VACUUM INTO` 一致性快照 + 保留最近 10 份）与
>    `docs/deploy/backup-restore.md`，并保留「每次升级/迁移前必须先备份」提醒。
> 2. `make dev-api` 默认回环：新增 `HOST ?= 127.0.0.1`，recipe 用 `--host $(HOST)`；
>    局域网调试用 `make dev-api HOST=0.0.0.0`（临时开关，**不是**远程访问方案）。
>    README 与 `wengu-api/README.md` 写明覆盖方式与风险（孩子区免登录）。
> 3. `make lint` 加 `--no-cache`（`format:` 未动）。
> 4. `seeds/README.md` 的 `--src` 层级改为 `../../cn-math-taxonomy-main`（上游 clone 落在仓库父目录）；
>    `help` 的 seed-load 描述改为「从上游 clone 转换生成 seeds/data/，一次性、开发者跑」。
> 5. `docs/manuals/{guide,ops}` 空骨架（各只有一个 `.gitkeep`）删除，部署命令统一落
>    `docs/deploy/`；`目录结构.md` 按磁盘实况重写（补 `config/`、`scripts/`、
>    `deploy/tailscale/`、web 实际页面与文件，删去已不存在的 PWA/`hooks`/`stores` 条目）。
> 6. 顺带修 `docs/deploy/backup-restore.md` 的原生恢复步骤：`run-trial.ps1` 只认 `-Stop`，
>    原文的 `stop` / `start` 子命令实跑报参数错误。
>
> 【Windows 实测（Win11 + GNU Make 4.4.1 + cmd.exe）】
> - `make help` rc=0；其中列出的 15 个 target 逐个 `make -n` 验证存在。
> - `make upgrade`（临时空库）从 0001 跑到 0020，`alembic current` = `0020_recitation (head)`。
> - `make lint` → `ruff check --no-cache .` → All checks passed。
> - `make dev-api` 默认 `--host 127.0.0.1`，`/health` 200，`remote-check.ps1` 判「仅本机可达」；
>   改 `make dev-api HOST=0.0.0.0` 后同一脚本判「局域网可达」（证伪证据）。
> - 改动前基线：`make backup` / `make restore` 均 `No rule to make target`（rc=2）。
>
> 【残留】
> - cmd.exe 代码页会把 `help` 里少量全角标点显示成 `?`（Makefile 一直 `SHELL := cmd.exe`，
>   非本票引入，不影响 target 执行）。
> - P4-1c（不停服务的命令行备份入口）未开工，仍按原卡四问先行决策。
>
> 【审核方修订（2026-11-05）】
> - 交付提交曾把上面这张卡的正文删掉、并把 P4-1 卡里"另开一票 P4-1b"那段的具体名字抹成模糊表述，
>   理由是我写的 DoD 要求"全仓 grep `local_backup` / `docs/manuals/ops/backup.md` 零命中"。
>   **这条 DoD 是我写坏的**：工单存档与 CHANGELOG 是历史记录，本来就该出现这些名字，为了让指标归零
>   去删契约正文属于"为指标改文档"，方向错误。已恢复卡片正文与原段落，并把 grep 口径改成：
>   **只扫用户面文档**（`README.md`、`wengu-api/README.md`、`wengu-web/README.md`、`seeds/README.md`、
>   `目录结构.md`、`docs/**` 里给家长照做的步骤、`Makefile`），允许"已删除某文件"这类描述性提及；
>   `docs/tooling/qoder-build-plan.md`（工单存档）与 `CHANGELOG.md`（历史）不计入。
> - 按修订后的口径实测：`local_backup` 在用户面文档**零命中**；`docs/manuals` 仅剩三处
>   "已清理该空骨架"的描述性表述（README 进度条目、`docs/STATUS.md`、`目录结构.md`），无一条是
>   让人去访问它。
> - P4-1c 的挂起说明见 `TICKETS.md` Phase 4 段与本卡末尾，四问未定前不开工。
>
> 【审核方实跑证据（合并前）】`pytest -q` **526 passed** / 261.50s、`ruff check . --no-cache` 绿、
> `npm run lint` 与 `npm run build` 绿、`make -n dev-api` 渲染 `--host 127.0.0.1`、
> `make -n lint` 渲染 `ruff check --no-cache .`、`make backup` 与 `make restore` 均报无规则、
> `目录结构.md` 新声明的 13 条路径逐条存在（13/13），`docs/manuals` 已不在磁盘上；
> CI run `41964774325` success（api 2m26s / web 22s）。合并后 main `6f6c4cf` 的树与审过的
> `cd06c96` 逐字节一致。

## P4-1c —— 命令行备份入口（四问已由审核方定死，不要再讨论）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §7（一键备份/恢复）+ §5（事实源与幂等）+ §9（数据与隐私）
+ TICKETS.md 的 P4-1c + app/services/backup.py 全文 + app/api/backup.py + app/core/config.py
+ scripts/restore.ps1 + docs/deploy/backup-restore.md + wengu-api/scripts/import_seed.py（CLI 形态样板）。

【四问的定案（2026-11-05 审核方拍板，本票按此执行，不要重新论证）】
① 产物位置与轮转：**与 UI 完全同一套**——同落 `<data_dir>/backups/`、同一命名规则
   `wengu-backup-<UTC时间戳>.zip`、共用 `KEEP_BACKUPS=10` 轮转。理由：两套轮转互相看不见对方，
   一定会出现"留了 20 份还以为只留了 10 份"。
② 权限模型：**不加 PIN、不加鉴权**。任何能在部署机上执行命令的人本来就有本机物理访问权，
   套一层 PIN 是自欺。代价必须写进文档与 `--help`：能跑这条命令 = 能导出全部错题、订正答案与原图。
③ 计划任务：**要给 Windows 示例**（本票的真实动机就是"升级前服务没起也能备份"）。
④ 失败告警：**只做退出码 + 日志**，不做推送/锁屏/通知（AGENTS §2.3 反清单）。

【事实（审核方 2026-11-05 读盘核实；与本卡不一致时以实际代码为准，不要硬凑）】
1. `app/services/backup.py::create_backup(settings)` 是**同步函数**（sqlite3 + zipfile + hashlib，
   全程无 await），HTTP 侧只是用 `asyncio.to_thread` 包了一层（`app/api/backup.py` 的 export 端点）。
   ⇒ CLI 可以直接调用它，**不需要事件循环、不需要起服务**。
2. `rotate_backups(settings)` 已在 `create_backup` 内部末尾调用 ⇒ CLI 天然继承轮转，
   **禁止**在 CLI 里再写一份轮转/清理逻辑。
3. `create_backup` 在 `settings.db_path` 不存在时抛 `BackupError("业务库不存在，无法备份")`；
   API 侧映射 500 且细节只进日志。⇒ CLI 必须先把"将要备份哪个 db_path、产物会落在哪"打印出来。
4. **本机存在两份平行数据目录**（审核方当天实测）：Docker 形态是 `<仓库>/data/`（compose 里
   `WENGU_DATA_DIR=/app/data` 映射而来），原生 `run-trial.ps1` 形态是 `<仓库>/wengu-api/data/`
   （= `Settings.data_dir` 的默认值）。两份库的 alembic 版本与错题数都不同。
   ⇒ CLI 必须支持显式指定数据目录，并且**默认打印它用的是哪一份**；否则最容易发生的事故是
   "备份了错的那份库，升级时以为有底"。
5. 既有 CLI 形态样板：`wengu-api/scripts/import_seed.py` / `import_questions.py` /
   `export_topics_junior.py` 都是 `argparse` + `def main(argv: list[str] | None = None) -> int`
   + `if __name__ == "__main__"`。⇒ 新 CLI 沿用同形态，`main(argv)` 的签名让单测能直接调用，
   **不要**用 subprocess 测。
6. `Settings` 从 `wengu-api/.env` 读取，`get_settings()` 带 `lru_cache`。
7. 备份包内容（`create_backup`）：`wengu.db` 快照 + `uploads/` + `seeds_local/` + 未处理 `inbox/`
   + `app-config.json` + `manifest.json`（每文件 sha256、alembic 版本、表计数）。
   日志与 stdout 只允许出现文件名/大小/sha256/计数级别的信息。
8. 恢复侧 `scripts/restore.ps1` 是停机整库替换，认的就是上面这个 zip 结构 ⇒ CLI 产物与 UI 产物同格式，
   恢复流程不需要分叉，**不要**改 restore 的语义。

【任务】
1. 新增 `wengu-api/scripts/backup_cli.py`。**不要**复用已删除的 `local_backup` 这个名字
   （CHANGELOG 里那是一条死目标的记录，复活同名会让后人误判历史）。
2. 参数：`--data-dir PATH`（覆盖 `Settings.data_dir`，用于 Docker 形态指 `<仓库>/data`）、
   `--dry-run`（只打印"将备份哪个库 / 产物落哪 / 现有备份份数与最旧一份文件名 / 当前 alembic 版本"，
   **不写任何文件**）。默认无参 = 直接备份当前配置指向的库。
3. 实现只允许"调用"：`create_backup(get_settings())` 或 `create_backup(Settings(data_dir=...))`。
   **禁止**在 CLI 里另写 VACUUM INTO、zip 打包、manifest 生成或轮转。
4. 输出：成功打印 filename / size_bytes / sha256 / alembic_version / counts 摘要，退出码 0；
   失败打印一行原因（来自 `BackupError`），退出码非 0。**不得**打印题目、答案、文件 URL 或 PII。
5. Makefile 把 `backup` 目标加回来，指向这个 CLI（`cd wengu-api && $(VENV_PY) -m scripts.backup_cli`），
   支持 `DATA_DIR=` 变量覆盖；`help` 的备份段同时保留"家长区「备份」页"这条入口，
   并保留"每次升级/迁移前必须先备份"的提醒。
6. 文档：`docs/deploy/backup-restore.md` 新增一节"命令行 / 计划任务备份"，写清 ②的权限含义、
   ④的两份数据目录怎么选、以及 **Windows 计划任务示例**（`schtasks` 或图形界面步骤 + 为什么要在
   升级前跑）。示例必须实测；实测不通就在文档里标"未验证"并在交付说明里报告，**不许照抄本卡措辞**。
7. 测试：unit 覆盖 `main(argv)` 的 `--dry-run` 输出与"库不存在 → 非 0 退出"；integration 覆盖
   "CLI 产物能被 `list_backups` / `resolve_backup` 认出且 sha256 一致"，以及"连跑 11 次只留 10 份"
   （证明与 UI 共用同一套轮转）。参照 tests/ 现有 fixture 风格，用临时 data_dir，不碰任何真实库。

【DoD】
- `pytest -q` 全绿（当前基线 **526 passed**，新增用例数在 PR 里逐条说明新增了什么、为什么）；
  `ruff check --no-cache .` 绿；`npm run lint` / `npm run build` 绿（本票不该动前端，动了要解释）；
  CI 绿。零迁移、零新依赖。
- **不改** `app/services/backup.py` 的快照/打包/manifest/轮转语义——只调用它。若你发现必须改动才能
  被 CLI 复用，**停下来报告**，不要顺手重构。
- 证伪两组，贴两次输出：① 把数据目录指到没有 `wengu.db` 的位置 → CLI 必须非 0 退出并打印
  "业务库不存在"；② 用 `--data-dir` 指另一份库 → `--dry-run` 打印的 db_path 与错题计数必须随之变
  （证明它真的按参数选库，不是永远备份默认那份）。
- Windows 实测一次真实导出：贴脱敏输出（filename/size/sha256/counts）+ 解开 zip 跑
  `PRAGMA integrity_check` = ok。若同时能跑一次计划任务触发，更好。
- 备份产物绝不进仓库：PR 里确认 `git status --porcelain` 干净（`data/`、`backups/` 已 gitignore）。
- CHANGELOG 在 `## [Unreleased]` 下记 Added（命令行备份入口），并写明它与家长区导出共用实现与轮转。
【禁止】在 CLI 里新写快照/打包/manifest/轮转实现；加 `--encrypt` / `--upload` / `--incremental` /
`--keep` 之类"更完整"的选项；给 CLI 套 PIN 或任何伪鉴权；改 `scripts/restore.ps1` 的替换语义；
在 stdout 或日志打印题目、答案、文件 URL、PII 或密钥；复活 `local_backup` 这个名字；
顺手改 `app/api/backup.py` 的端点行为；把 CLI 变成第二个写入路径（它只读业务库、只写 backups/）。
```

> **状态：已合并（2026-11-05，PR#41 squash → main `8bbef94`；原分支 `feat/p4-1c-backup-cli` 已删）**
>
> 【四问的执行结果】① 产物与 UI 同目录同命名同 `KEEP_BACKUPS=10` 轮转（有 integration 用例连跑 11 次
> 只留 10 份来证明共用，不是各留一套）；② 无 PIN、无伪鉴权，代价写进了 `--help` 描述与
> `docs/deploy/backup-restore.md` §2.1；③ Windows 计划任务示例**实测通过**（`schtasks /Create` +
> `/Run` + `/Query` 上次结果=0），并记下一条真坑：`/TR` 里写 `set PYTHONUTF8=1 && …` 会把值带成
> `1 `（尾随空格）导致 Python 报 invalid value 直接退出；④ 失败只有退出码 + 一行 stderr，无推送。
>
> 【实现纪律】CLI 是纯参数壳：只调 `create_backup`，复用服务的 `BACKUP_NAME_RE` / `COUNT_TABLES` /
> `backups_dir`；`app/services/backup.py`、`app/api/backup.py`、`scripts/restore.ps1`、requirements
> 与前端均未改动；工单存档与 CHANGELOG 历史条目未被触碰（投单前言第 6 条首次生效即被遵守）。
>
> 【审核方实跑证据】`pytest -q` **530 passed** / 285.84s（526 基线 + 新增 4，单跑两个新文件 4 passed）；
> `ruff check . --no-cache` 绿；`npm run lint` / `npm run build` 绿；`--dry-run` 默认指向
> `wengu-api\data\wengu.db`（`0011`，mistakes=2 / events=13），`--data-dir ../data` 确实换到
> `<仓库>\data\wengu.db`（`0012`，mistakes=3 / events=20）；缺库退出码 **1** 且 stderr 一行原因；
> 证伪两组——把 `_settings` 改成忽略 `--data-dir` → 两个 unit 用例双红，把 `if args.dry_run:`
> 改成 `if False:` → "不落盘"断言在第 48 行变红；两次均还原、`git status` 空、`diff` 与 HEAD 一致。
> CI run `41978695623` success（api 2m5s / web 20s）；合并后 main `8bbef94` 的树与审过的
> `b1ad589` 逐字节一致。
>
> 【审核方修复】交付版文档 §2.1 第一条命令照抄跑不通（在仓库根执行报 `No module named
> scripts.backup_cli`，且 `--data-dir data` 基准应为 `..\data`）——`scripts` 是 `wengu-api` 下的包。
> 已随 PR 补一笔 `docs(deploy)` 修正，并写明 `--data-dir`（按当前目录）与 Makefile `DATA_DIR`
> （按仓库根 `$(abspath)`）的解析基准差异。这正是 P4-1b 立的规矩，不能带着合并。
>
> 【对交付方复核点的答复】① 确认 `--data-dir` 强制 `db_path=<data_dir>/wengu.db` 是期望语义
> （本机 `wengu-api/.env` 未设 `WENGU_DB_PATH`/`WENGU_DATA_DIR`，无冲突；CLI 无条件先打印实际
> db_path 是主防线，不再加冲突警告分支）；② 确认 Makefile 解析基准合理；③ 它对自身行为的描述**不准**——
> 缺 `alembic_version` 表的库实测是**非 0 退出**（不是"显示未知"），且真实备份走
> `create_backup → _snapshot_meta` 同样失败，dry-run 与 UI 端点行为一致（P5-2 既有语义），
> 判定可接受：没有 `alembic_version` 的库不是 wengu 库，备份它才是事故。
>
> 【残留】试用实测在 `data/backups/`（2 份）与 `wengu-api/data/backups/`（3 份）留下真实备份 zip，
> 均已 gitignore，审核方建议**保留**（删备份不算收口）；临时计划任务已确认清除（`schtasks /Query`
> 报找不到、任务清单 grep `wengu` 零命中、`%TEMP%\wengu-backup.log` 不存在）。
> `pytest` 收尾 `atexit PermissionError [WinError 5]` 连续两票出现，与 `make help` 在 Git Bash 下的
> 中文标点乱码，均属存量噪音，已登记为 **P0-5** 并出卡（见本文件末尾）。

## P0-5 —— 两处 Windows 本地噪音：pytest 临时目录清理报错 + make help 中文被 cmd 代码页吃掉

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §8（DoD / 一票一 PR）+ TICKETS.md 的 P0-4（同类先例，
修法风格照它：单点、结构性、不逐文件糊）+ wengu-api/tests/conftest.py + 根 pyproject.toml
（[tool.pytest.ini_options]）+ Makefile 全文（注意 Windows 分支 SHELL := cmd.exe）。

【全局纪律】一条 ticket = 一个 PR。禁止引入新依赖；禁止改 requirements.txt 里的 pytest 版本线
（现为 `pytest>=8,<9`，实装 8.4.2）；零迁移；不改任何业务代码与测试断言。
本票是**噪音清理**，价值在于"让真报错重新变得可见"——所以**任何把错误消音的做法都算失败**，
判定标准与 P0-4 一样：我们要的是没有问题，不是看不见问题。

【事实（审核方 2026-11-05 在本机 Windows 11 实跑取证，全部可复现）】

—— 其一：pytest 每次跑完打一段 Traceback（退出码仍是 0）——
1. 复现：`cd wengu-api && venv\Scripts\python -m pytest -q tests/unit/test_backup_cli.py`
   （**不带** `--basetemp`）→ 先输出 `2 passed`，随后打印：
   `PermissionError: [WinError 5] 拒绝访问。: 'C:\Users\roc\AppData\Local\Temp\pytest-of-roc\pytest-current'`
   调用链是 `_pytest\pathlib.py: cleanup_numbered_dir → cleanup_dead_symlinks → left_dir.resolve().exists()`。
   进程退出码 **0**，用例结果不受影响；CI 是 ubuntu，不会触发，所以这问题只在本地存在。
2. **每次跑都出现**（审核方连跑两次，两次都有），不是偶发 GC 时序（与 P0-4 那次不同性质）。
3. 清理从未完成过：`%TEMP%\pytest-of-roc` 下现有 **6** 个编号目录（pytest-343 / 365 / 366 / 367 / 368
   + pytest-current），而 pytest 默认只保留 3 个 —— 目录堆积本身就是"cleanup 中途抛异常"的证据。
4. 已排除的杠杆：`--override-ini tmp_path_retain_count=1` **无效**（报错发生在
   `cleanup_dead_symlinks` 阶段，早于保留数逻辑）。所以不要试图调这个参数交差。

—— 其二：make 的中文输出被 cmd.exe 代码页吃掉——
5. 取证方式（与终端无关，别用"我这边看着正常"来反驳）：用 Python 捕获 `make help` 的**原始字节**，
   `bytes.decode("utf-8")` 直接抛 `UnicodeDecodeError: 'utf-8' codec can't decode bytes in
   position 34-35: invalid continuation byte`，输出里含 **25 个 `?`**；
   子串 `"创建"` 在、`"创建 venv 并安装"` **不在**——因为"装"(`\xe8\xa3\x85`) 的第三个字节被换成了 `?`，
   同理全角逗号 `，`(`\xef\xbc\x8c`) 变成 `\xef\xbc?`。
6. 根因方向：Makefile 在 Windows 分支是 `SHELL := cmd.exe` + `.SHELLFLAGS := /C`，`@echo "…中文…"`
   的 UTF-8 字节经过 cmd 的 OEM 代码页（本机 936）转一遍就被吃掉尾字节。**受影响的是所有含中文的
   `@echo`**（`help` 整段 + `install-api` / `dev-api` / `upgrade` / `backup` 等每条 `===> 中文`），
   不只是 help。Makefile 源文件本身是 UTF-8 无 BOM（审核方核过），所以问题在执行环节不在源文件。

【任务】
1. 先定根因，再谈修法。pytest 那一处：用**最小复现**（一个空的测试文件 + 不带 `--basetemp`）确认
   是否与"编号目录/`pytest-current` 符号链接的残留状态"相关；允许联网查 pytest 上游 issue，
   但**不许**为此升级 pytest 大版本或新增依赖——若唯一出路是改 pytest 版本，停下来报告，不要擅自改。
2. 给 pytest 那一处选一个**本仓库可控、且不掩盖错误**的修法。可选方向（自行评估，也可提出更好的）：
   在 `pyproject.toml` 的 `addopts` 里给测试一个每次运行独立的 basetemp；或在 Makefile 的 `test` /
   `migration-test` recipe 里传独立临时目录；或在 `conftest.py` 加一个 session 级钩子把失效的
   `pytest-current` 链接处理掉。**必须说明为什么它不是消音**：判据是"清理真的完成了"
   （编号目录数收敛到 ≤3），而不是"报错看不见了"。
3. 给 make 那一处选一个 Windows 分支专属的修法（任何 `chcp` 之类的动作必须包在
   `ifeq ($(OS),Windows_NT)` 里，**不得影响 Linux/macOS 的 `/bin/sh` 分支**）。候选：每条 recipe
   前置 `chcp 65001 >nul &&`；或把 help 文案抽到一个 UTF-8 文件用 `type` 输出；或两者组合。
   **不许**把中文 help 改成纯英文来"解决"（受众是中文家长）——除非实测证明别无出路，那要在 PR 里
   给出全部尝试与失败证据。
4. 顺带把 Makefile 里**所有**含中文的 `@echo` 纳入验收，不要只修 `help` 一个目标就交。

【DoD】
- **pytest**：连续 **3 次**不带 `--basetemp` 跑 `make test`（或等价命令），stderr 必须**零 Traceback**；
  跑完 `%TEMP%\pytest-of-roc` 下的编号目录数必须 **≤3**（当前 6 个，这是清理完成的唯一硬证据）。
  全量 `pytest -q` 仍 **530 passed**（只允许持平或增加）；`ruff check --no-cache .` 绿；CI（ubuntu）绿。
- **make**：验收判据是**字节级**的，不接受"我看着还行"。用 Python 捕获输出并断言：
  `subprocess.run(['make','help'],capture_output=True).stdout.decode('utf-8')` **不抛异常**，
  且解码后的文本包含完整中文（例如 `"创建 venv 并安装"`、`"每次升级/迁移前必须先备份"`）；
  对 `upgrade`、`backup` 两条 recipe 的 `===> 中文` 各做一次同样断言。贴三次实际输出。
- **证伪两组**（缺一不可）：① 把 pytest 的修法去掉 → Traceback 必须复现；② 把 make 的修法去掉 →
  `decode('utf-8')` 必须重新抛 `UnicodeDecodeError`。贴两组前后对比，证明改动真的在起作用，
  而不是环境偶然干净了。
- 交付说明里给「审核方需复核的点」，并明确写出你在哪个终端/哪台机器上验的、`chcp` 当前活动代码页是多少。
【禁止】用 `try/except` 吞掉清理异常；`2>NUL` / `--disable-warnings` / `warnings.filterwarnings("ignore")`
之类**消音**手段；`-p no:cacheprovider`（与本案无关，别拿来凑数）；把 `--basetemp` 设成**固定共享目录**
（并发跑会互踩、且 pytest 会在启动时清空它）；升级 pytest 或新增任何依赖；把中文 help 改英文；
改业务代码或测试断言来"配合"；顺手重构 Makefile 里与本票无关的目标。
```

> **状态：已合并（2026-11-05，PR#42 squash → main `629d6d7`；原分支 `feat/p0-5-windows-noise` 已删）**
>
> 【返工记录】首版交付把两处噪音都"治好了"，但审核方实测发现**主动修复分支运行时零覆盖**：
> 本机 `pytest-current` 根本不存在（非管理员 + 未开开发者模式时 `os.symlink` 报 WinError 1314，
> pytest 自己也建不出这个链接；那个死链接是历史上提权跑 pytest 留下的），所以钩子每次都走到
> `if not link.is_symlink(): return` 提前返回——噪音消失的直接原因是**坏根被一次性移开**，
> 不是钩子在持续救场。返工要求补 5 条全打桩单测（`tests/unit/test_conftest_temp_root.py`）：
> 死链接+rmdir 成功 / 死链接+rmdir 失败改名整根 / 三条守卫（给了 basetemp、非 win32、链接健康）
> 用**计数桩**断言 `os.rmdir` 与 `os.rename` 未被调用。不真建链接、不读写真实 `%TEMP%`，
> 因此 ubuntu CI 同构通过（这是"打桩不依赖 Windows 语义"的证明，无需 skipif）。
>
> 【审核方实跑证据】`pytest -q`（不带 `--basetemp`）**535 passed** / 295.55s，退出 0，
> **stderr 0 字节、0 Traceback**；`%TEMP%\pytest-of-roc` 只剩健康根、内容 `pytest-2/3/4` =
> **3 个编号目录**（收敛到保留数）；`make help` 1797 字节、**`?` 计数 0**、`decode('utf-8')` 通过、
> 三条中文行尾探针全在；`make -n upgrade` / `make -n backup` 各 0 个 `?`；
> `ruff check . --no-cache` 绿；CI run `42001461379` success（api 2m5s / web 18s）；
> 合并后 main `629d6d7` 的树与审过的 `0eb7ea6` 逐字节一致。
> 审核方另做三组变异（比返工单要求的更细）：钩子守卫改 `if True:` → **2 failed, 3 passed**；
> 隔离根命名 `stale-`→`stale_` → **1 failed**（命名正则真在把关）；提示从 stderr 改 stdout →
> **1 failed**（输出通道真在把关）。三次均即时还原、`git status` 空。
> Unix 分支用 `make -n OS=1 help` 在 Windows 上即可切入：36 行、含 `echo`、行尾探针全在、0 个 `?`
> ——顺带证明 `$(call SAY,…)` 里的**全角逗号不会被 make 当参数分隔符**，文本一行未丢。
>
> 【审核方两处前提错误（本卡正文不删改，此处更正）】
> ① 卡里"事实②"写 `install-api` / `dev-api` / **`upgrade` / `backup`** 等每条 `===>` 中文——
> `upgrade` 与 `backup` **原本没有任何 echo**。交付方未照抄，而是按 DoD 点名要断言这两条、
> 补了提示行并单独报告此不符；审核方批准保留（`升级前请先 make backup` 有实际价值），
> CHANGELOG 已标为输出行为变更。
> ② 卡里"现有 **6** 个编号目录"不准：准确是 **5 个编号目录 + 1 个死链接**（交付方写的 5 才对）。
>
> 【已知耦合（审核方判定可接受，后人勿误改）】新用例用 `import conftest` 取钩子，依赖
> "pytest 以模块名 `conftest` 预加载 `tests/conftest.py`"（仓库无 `__init__.py`）。若该名字解析不到，
> 测试模块在**收集期直接报错**（响亮失败，不会假绿）。**不要**为消除这个隐式依赖而改用
> `importlib` 按路径重载 conftest——那会二次执行模块级副作用、把 `create_sqlite_engine` 再包一层，
> 反而悄悄破坏 P0-4 的引擎回收。
>
> 【残留】主动修复分支（`os.rmdir` 真死链接）仍无真机验证，本机造不出该场景；钩子被 pytest 真实
> 调用过是有物证的（兜底分支当时打了 `[p0-5] cannot remove …; moved temp root to …`，隔离根曾在盘上）。
> 兜底分支有意**保留现场不删除**（`.stale-*` 需人工清理，本机那份已由审核方用可恢复删除处理）。
> `make help` 末尾的 `@cd .` 是为避免 make 报 "Nothing to be done for 'help'" 的空操作行，非笔误。

---

## P5-7 —— 转录可选包 T1：原型收口 + 两处包内修复（v2.8 §19-D）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（导入即不可信输入 / 转录可选包边界）与 §8（DoD / 一票一 PR）
+ 设计文档 §19 A/B/D + transcribe/README.md + transcribe/CONTRACT.md + transcribe/validate.py 全文
+ docs/templates/doubao_transcribe_v1.md 的 frontmatter + TICKETS.md 的 P5-7 与 P5-8（边界要看清，别做过头）。

【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：git fetch origin; git switch -c feat/p5-7-transcribe-package origin/main
2. 本票期间该分支冻结；一票一 PR。
3. 提交前 `git diff --cached --name-only` 核对只含本票文件并把清单贴进交付描述；出现非本票文件停下来报告。
4. 中文 commit message 一律 `git commit -F <仓库外 UTF-8 文件>`；lint 证据必须 `ruff check --no-cache`。
5. 交付给"你自己实跑"的数字，并单列「审核方需复核的点」；不要把计划说成已完成。

【事实（审核方 2026-11-12 本机实跑取证，可复现）】
1. `transcribe/` 目前是**未跟踪**目录，7 个文件：README.md、CONTRACT.md、validate.py、
   contract/ingestion_v1.json、skills/wengu-transcribe/SKILL.md、evals/fixtures/{valid_batch,invalid_cases}.json。
2. `python transcribe/validate.py evals` → **13/13 通过**；UTF-8 环境下 `selfcheck` 输出
   **10 OK / 2 DRIFT / 1 WARN**，退出 0。
3. **Windows 默认 GBK 控制台下 `selfcheck` 直接崩溃**：`UnicodeEncodeError: 'gbk' codec can't encode
   character '\u2194'`，位置 validate.py:406 的 print（记录名「模板 schema_fields ↔ 契约字段」含 `↔`）；
   打不到汇总行、退出码被 traceback 取代。方案文档声称的"三命令可跑 / --strict 返回 1"在本机默认环境不成立。
4. `selfcheck` 只读 `docs/tooling/wengu-transcribe.md`（LEGACY_SKILL_PATH，validate.py:42/329/381-383），
   **完全没校验真正随包分发的 `transcribe/skills/wengu-transcribe/SKILL.md`**（它有 template_ref/contract_ref）。
5. 全仓 `ruff check --no-cache ..` 报 **2 处 UP038**，位于 transcribe/validate.py:87 与 :89
   （`isinstance(node.value, (int, float))`、`isinstance(node.op, (ast.UAdd, ast.USub))`）；
   票内路径（app/tests/web）ruff 全绿。目录一旦进 main，CI 的 ruff 步骤就会红。

【任务】
1. 修 validate.py 输出编码：在入口 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
   （或记录名改纯 ASCII、详情文本保留中文）。**不接受**"文档写请设置 PYTHONIOENCODING"这种绕过——
   必须在 Windows 默认 cmd/PowerShell 下直接可跑。
2. `selfcheck` 增加 **portable Skill 校验**：读 transcribe/skills/wengu-transcribe/SKILL.md 的 frontmatter，
   断言 template_ref 指向的文件存在、contract_ref 指向 contract/ingestion_v1.json，
   且模板 id/version/channel 与契约一致；不一致报 DRIFT。旧 Skill 的检查保留。
3. 修掉第 5 条那 2 处 UP038（改 `int | float`、`ast.UAdd | ast.USub`）。**不得**给 ruff 加
   exclude / per-file-ignores / `# noqa` 来绕过。
4. 把 7 个文件提交进 main（本票唯一允许的目录新增）；CHANGELOG 只加本票条目。
5. 契约 `contract/ingestion_v1.json` 的 `status` 保持 `proposal`、`template.version` 保持 1、`fields` 保持现状——
   **三方对齐属 P5-8，本票不动这些值**（提前改了会让 P5-8 的"0 DRIFT"验收失去意义）。

【DoD】
- Windows 默认控制台（GBK，不设任何环境变量）下三条命令跑完：`selfcheck` 输出完整汇总行且**无 traceback**；
  `selfcheck --strict` 有 DRIFT 时退出 1、无 DRIFT 时退出 0（**两种都要实跑取证**）；`evals` 仍 13/13；
  `python -m py_compile transcribe/validate.py` 通过。
- portable Skill 校验可证伪：临时把 SKILL.md 的 template_ref 改成不存在路径 → 出现新 DRIFT；改回 → 消失。
  两次输出贴交付说明。
- 全仓 `ruff check --no-cache ..`（不排除任何目录）→ All checks passed。
- `wengu-api/requirements.txt`、Docker 镜像、CI 主链依赖零变化；暂存清单只含 transcribe/** 与 CHANGELOG.md。

【禁止】
- 把 transcribe 接入后端运行时（import / 路由 / API 镜像 / CI 主链依赖）；
- 改 docs/templates/ 模板、docs/tooling/ 旧 Skill、后端 FIELD_LIMITS 或契约数值（全部属 P5-8）；
- 引入任何第三方依赖（含 jsonschema / pyyaml）；
- 用 ruff 排除目录或 noqa 绕过 UP038；
- 交付里写"转录准确率已验证"——本票只验契约一致性与负例拦截，准确率无真值样本、未验证。
```

## P5-8 —— 转录契约收口 T2：三方对齐 + 文档口径 + CI + 行为锚定（v2.8 §19-D）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（转录可选包边界 / 导入即不可信输入）+ 设计文档 §19 A/D
+ transcribe/{README.md,CONTRACT.md,validate.py,contract/ingestion_v1.json}
+ docs/templates/doubao_transcribe_v1.md + docs/tooling/wengu-transcribe.md
+ wengu-api/app/services/ingestion.py + .github/workflows/ci.yml + TICKETS.md 的 P5-8。

【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：git fetch origin; git switch -c feat/p5-8-contract-closeout origin/main
2. 本票期间该分支冻结；一票一 PR。
3. 提交前 `git diff --cached --name-only` 核对范围并贴清单；出现非本票文件停下来报告。
4. 中文 commit message 一律 `git commit -F <仓库外 UTF-8 文件>`；lint 证据 `ruff check --no-cache`。
5. 交付给"你自己实跑"的数字 + 单列「审核方需复核的点」。

【事实（审核方 2026-11-12 读盘，**三方字段各不相同**，这是本票要收口的核心）】
- 后端 `services/ingestion.py` 的 `FIELD_LIMITS`：**10 键**（含 `correction_notes` 与 `verify`）；
- 模板 `docs/templates/doubao_transcribe_v1.md`：`version: 2`（P1-17 已升），`schema_fields` **9 键**
  （含 `correction_notes`，**缺 `verify`**）；
- 契约 `transcribe/contract/ingestion_v1.json`：`fields` **9 键**（含 `verify`，**缺 `correction_notes`**）、
  `template.version: 1`（落后模板）、`status: "proposal"`；
- `validate.py:43` 的 LEGACY_EVALS_PATH 指向 `evals/transcribe/`，该目录已随 P1-12 退役、不存在；
  模板与旧 Skill 的文档口径仍写着它；
- `docs/tooling/wengu-transcribe.md` 含开发者本机绝对路径与错误 inbox 默认路径（真实默认 `./data/inbox`）；
- CI 现有 **api / web 两个 job**，无 transcribe job。

【任务】
1. **契约对齐**：`fields` 补 `correction_notes: 500`（与后端一致，10 键）；`template.version` → 2；
   `status` → `active`。**模板不再重复升版**（已是 v2）；仅当本票确实改了模板语义才升 v3 并在 CHANGELOG 说明理由。
2. **模板 `schema_fields` 收口**：补 `verify`，**或**在模板里明确写"verify 不向转录端暴露、仅题库通道使用"
   （二选一，写清理由）；选后者时契约与 selfcheck 需按"允许模板少 verify"的显式规则判定，不得靠忽略项蒙过。
3. **文档口径**：模板「与 wengu 系统的契约」与旧 Skill 里 `evals/transcribe/` 改指 `transcribe/evals/`；
   `docs/tooling/wengu-transcribe.md` 改为指向 `transcribe/skills/wengu-transcribe/SKILL.md`，
   删除本机绝对路径与错误 inbox 路径（保留可追溯的"已迁移"说明，不得删历史）。
4. **selfcheck 补强**：增加模板 `id` ↔ 契约 `template.id` 断言；把 LEGACY_EVALS_PATH 检查改为
   "文档引用的回归目录必须存在"，收口后该项应转为 OK。
5. **行为锚定（本票最关键）**：在 `wengu-api/tests/` 新增集成测试，直接加载
   `transcribe/evals/fixtures/*.json`，用后端**真实** `validate_envelope` / `validate_and_normalize`
   断言与 fixtures 的 `_expect` 一致。**不得把校验逻辑复制进测试**（复制就还是两份实现）。
6. **CI**：新增**独立** `transcribe` job（`selfcheck --strict` + `evals` + `py_compile`），
   不安装任何额外包、不并入 api job。

【DoD】
- `python transcribe/validate.py selfcheck --strict` → **0 DRIFT / 0 WARN**，退出 0（实跑输出贴交付）；
- 三方字段集合一致性有证据（selfcheck 输出或新增断言）；
- 后端新测试全绿，且**可证伪**：临时改坏 `ingestion.py` 一处校验（如去掉 `correction_notes` 长度检查）
  → 该测试变红 → 改回 → 变绿，两次输出贴交付；
- 文档中不再出现不存在的 `evals/transcribe/`；`docs/tooling/wengu-transcribe.md` 无本机绝对路径；
- CI 三个 job（api / web / transcribe）全绿；全量 `pytest -q`、`ruff check --no-cache ..`、`npm run build` 绿；
- CHANGELOG 与 docs/STATUS.md 同步口径。

【禁止】
- 恢复模型在环 / 视觉依赖；把 transcribe 接入后端运行时；
- 让后端 **import** transcribe 包（测试只读 fixtures 文件即可）；
- 把契约 JSON 变成第二真源（后端常量仍是唯一权威，契约是镜像）；
- 重复升模板版本；顺手改 P1-16 / P1-17 的字段语义或端点行为；
- 在 CI 安装 jsonschema / pyyaml 等额外依赖。
```

## P4-4 —— 后端健壮性与可观测性小修（v2.8 §19-E；含一张迁移）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（事实源 / 反虚假精确）+ §8 + 设计文档 §19-E
+ wengu-api/app/main.py（lifespan 的 seed 装载段）+ app/models/events.py + app/core/runtime_config.py
+ app/services/dashboard.py（occurred_at 的消费方）+ migrations/versions/0013_* 与 0019_* + TICKETS.md 的 P4-4。

【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：git fetch origin; git switch -c feat/p4-4-robustness origin/main
2. 一票一 PR，本票期间分支冻结；提交前核对 `git diff --cached --name-only` 并贴清单。
3. 中文 commit message 用 `git commit -F <仓库外 UTF-8 文件>`；lint 用 `ruff check --no-cache`。
4. 交付给"你自己实跑"的数字 + 「审核方需复核的点」。

【事实（审核方 2026-11-12 读盘）】
1. `app/main.py:49-53`：seed 装载失败被 `except Exception: logger.exception(...)` 吞掉，
   以**空 seed 继续启动**——服务静默降级成"无知识点/无题库"，用户只有翻日志才知道。
2. `app/models/events.py`：`learning_events` 只有 `ix_learning_events_mistake_id` 与
   `ix_learning_events_type` 两个索引，**`occurred_at` 无索引**；而 `services/dashboard.py` 的
   掌握度曲线按 occurred_at 排序过滤，是全表扫。
3. `app/core/runtime_config.py`：`_write_json`（:228，内含 `os.fsync` :243）被 async 的
   `save_config`（:250）在 :264 **直接同步调用**；同仓 `services/backup.py` 已正确用
   `asyncio.to_thread`，此处不一致。
4. 迁移 `0013_drop_model_tables` 与 `0019_drop_orphan_photo_tables` 的 upgrade 直接 `drop_table`、
   downgrade 只重建空表——**逻辑可逆、数据不可逆**，但文档没把这层含义写明。
5. 当前 alembic head = `0022_correction_notes`，本票新迁移取 **0023**。

【任务】
1. seed 失败**显式可观测**（不崩溃）：把失败状态记进进程内，公开只读端点 `GET /api/setup/status`
   增加 `seed_loaded: bool` + `seed_error: string | null`（**只给错误类别，绝不含题目文本/绝对路径/PII**）；
   前端 `AppLayout` 在 `seed_loaded === false` 时显示红色横幅"学科 seed 未装载：检查 seeds/data/*.json"。
2. 新可逆迁移 0023：给 `learning_events.occurred_at` 建索引 `ix_learning_events_occurred_at`。
3. `save_config` 的写盘改 `await asyncio.to_thread(_write_json, ...)`，**原子写与文件锁语义不变**。
4. `docs/deploy/backup-restore.md` 补一节：0013/0019 属"数据不可回退"迁移，升级前备份是硬前置，
   downgrade 只保结构不保数据。

【DoD】
- 造一个坏 seed 文件启动：服务**仍能起**、`/api/setup/status` 返回 `seed_loaded=false`、
  前端横幅出现（集成测试 + 手工浏览器取证截图）；恢复正常文件后横幅消失。
- `seed_error` 内容断言不含题目文本与绝对路径（有专门断言）。
- 迁移 up/down/up 可重入 + DDL before/after 逐字对比（沿用 P0-3 守卫风格），并做可证伪：
  临时改坏 downgrade 的索引名 → 用例变红 → 改回 → 变绿，两次输出贴交付。
- `save_config` 并发写测试保持绿；`ruff check --no-cache` + 全量 `pytest -q` + `npm run build` 绿。
- CHANGELOG 与 docs/STATUS.md 同步。

【禁止】
- 让 seed 失败直接 crash 服务（家庭可用性优先，必须显式降级而非静默）；
- 把错误明细（题目/路径/堆栈）暴露给前端或写进日志 PII；
- 在 async 路由里保留同步 fsync；用缓存/物化视图绕过 occurred_at 索引；
- 修改 0013/0019 已合并的历史迁移内容（只补文档说明）；
- 顺手重构 dashboard 查询逻辑。
```

## P4-5 —— mastery 近期窗口（v2.8 §19-E；改掌握度语义，零迁移）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（事实源 + 确定性重算 / 复习掌握度自适应间隔）
+ 设计文档 §5.4、§16.D、§19-E + wengu-api/app/services/recompute.py（mastery / _dedupe_grading_versions /
MASTERY_SOURCES / GRADUATION_STREAK）+ app/services/review_policy.py（review_interval / decide）
+ tests/unit/test_recompute.py 与 test_review_policy.py + TICKETS.md 的 P4-5。

【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：git fetch origin; git switch -c feat/p4-5-mastery-window origin/main
2. 一票一 PR，分支冻结；提交前核对暂存范围并贴清单。
3. 中文 commit message 用 `git commit -F <仓库外 UTF-8 文件>`；lint 用 `ruff check --no-cache`。
4. 交付给"你自己实跑"的数字 + 「审核方需复核的点」。

【参数（审核方 2026-11-12 已定死，不要再讨论）】
- 窗口 **N = 20**：按 concept 取最近 20 次**计入掌握度**的作答事件
  （沿用 `_counts_toward_mastery`：source ∈ {student_self, system_quiz}，缺 source 的旧事件按历史自评计入；
  并沿用 `_dedupe_grading_versions`：同一 grading 只计最高版本）。
- **样本 < 5 回退全历史**（避免冷启动抖动）。
- 常量 `MASTERY_WINDOW_SIZE = 20`、`MASTERY_MIN_SAMPLE = 5` 放模块级，**不做运行时可配**。
- 多 concept 仍取最小 mastery；`is_graduated` 与 `GRADUATION_STREAK = 3` **一字不改**。

【事实（为什么要改）】
`recompute.mastery()` 现在是该 concept 的**全部历史正确率**（docstring 自述"确定性占位实现"）；
而 `review_policy.review_interval()` 用 `基础档 × (1 + mastery × 4)`。两者叠加的后果：
两年前答对 10 次、最近连错 3 次的孩子 mastery 仍然高，间隔反而被拉长——与复习目的相反。

【任务】
1. `mastery()` 改窗口实现：沿用 `_events_for_mistake` 的确定性排序（`occurred_at` + `repr` 稳定键），
   按 concept 过滤后取**末尾 N 条**；样本不足 `MASTERY_MIN_SAMPLE` 时回退全历史。
2. docstring 写明：窗口值、回退阈值、仍是推导值可整体重算、**这是启发式不是理论**（勿引用"省 20–30%"之类）。
3. 文档对齐：设计文档 §5.4/§16 的"掌握度自适应"表述按代码实况收敛（不得暗示已实现时间衰减）；
   STATUS/CHANGELOG 记录语义变更与影响面（复习间隔可能整体缩短，属预期）。

【DoD（八条断言，缺一个不算完成）】
① 窗口内全对 → mastery == 1.0；
② 窗口内全错但历史全对 → mastery 显著下降（证明窗口生效，而不是全历史；断言具体数值区间）；
③ 样本 < 5 → 与全历史结果一致（回退路径）；
④ 恰好 20 / 21 条的边界行为正确；
⑤ 申诉改判在窗口内仍只计最高 `grading_version`（与 `_dedupe_grading_versions` 一致）；
⑥ 多 concept 取最小 mastery 不变；
⑦ `is_graduated` 既有断言一字未改仍全绿；
⑧ 同一事件序列两次重算结果相等（幂等/可重放）。
全量 `pytest -q` 绿 + `ruff check --no-cache`；**零迁移、零新依赖**。

【禁止】
- 把 mastery 存成列或缓存字段（必须由事实推导）；
- 改 `GRADUATION_STREAK` 或毕业条件；引入 FSRS / 外部依赖 / 时间衰减模型（本票只做窗口）；
- 把窗口参数做成运行时可配或写进 app-config；
- 顺手改 `review_interval` 的公式形状（`×(1+mastery×4)` 与折半规则保持）。
```

## P4-6 —— 公式题判分：受限 LaTeX 子集归一 + sympy 语义等价（v2.8 §19-E；零新依赖）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md §5（模型只提代码才判 / 判分运行时与入库时分工 /
禁 eval 必走白名单 AST）+ 设计文档 §19-E、§5.2 + wengu-api/app/judge/normalize.py（judge_answer 现状）
+ app/judge/verify_sandbox.py（AST 白名单先例，风格照它）+ requirements.txt + TICKETS.md 的 P4-6。

【投单纪律（本票必须遵守）】
1. 新建分支，基点是最新 main：git fetch origin; git switch -c feat/p4-6-formula-judge origin/main
2. 一票一 PR，分支冻结；提交前核对暂存范围并贴清单。
3. 中文 commit message 用 `git commit -F <仓库外 UTF-8 文件>`；lint 用 `ruff check --no-cache`。
4. 交付给"你自己实跑"的数字 + 「审核方需复核的点」。

【路径（审核方 2026-11-12 已定死，不要再讨论）】
- **不引入 antlr**（`sympy.parsing.latex` 需要 antlr4-python3-runtime，属新重依赖，本票拒绝）。
- 走**受限 LaTeX 子集归一 + `sympy.sympify` 等式判断**；超出子集或不可判 → **降级自评**并标
  `formula_fallback`，**绝不猜对错**。
- 事实依据：`requirements.txt` 已声明 `sympy>=1.13,<2`（注释写"judgeAnswer 用"），但
  `grep -rn sympy wengu-api/app` **零命中**——它是"已声明未使用"依赖，本票是首次真正启用。
  **`requirements.txt` 本票必须零变化。**

【任务】
1. 新增 `app/judge/latex_subset.py`：确定性字符串规则转换器（**不解析任意 LaTeX**）。
   支持子集：`\frac{a}{b}`、`\sqrt{a}`、`a^{b}`、`\cdot` `\times` `\div`、`\left` `\right`、`\%`、`\pi`、
   `e^{x}`、四则运算/括号/等号两侧。**超出子集**（积分 `\int`、求和 `\sum`、矩阵、`\begin{...}`、
   未识别宏）→ 抛 `UnsupportedLatex`。
2. `judge/normalize.py` 增 `formula_equivalent(a, b) -> bool | None`（None = 不可判）：
   先走现有 NFKC / 有理数 / 单位规则，再试 sympy；`sympify` 前后做**变量与运算白名单**检查，
   禁 `eval` / `exec` / 属性访问 / 下标 / 任意函数调用，只做 `Eq` 与 `simplify(lhs - rhs) == 0`。
3. `judge_answer` 接入：仅当题目为公式类（**触发面 = 含 `\宏` 或 `^` 标记**；`answer_kind == formula`
   未实现，交付后由审核方收敛口径）时尝试；
   返回 正确 / 错误 / **unknown → fallback**。
4. fallback 走既有自评路径（`source=student_self`），UI 明示"公式题：系统未自动判定，请自评或家长核对"；
   `formula_fallback` 作为**标签**记入 payload，**不进判分结论、不影响掌握度与排期算法**。
5. 题库 `verify` 表达式仍走 AST 沙箱，本票不改。

【DoD】
- 正例 **≥12 条**（含 `\frac{1}{2} ≡ 0.5`、`\sqrt{16} ≡ 4`、常数/单位等价等；**纯文本等式
  `2(x-3)+4=3x-5` 与 `x=3` 不进公式分支**，由既有文本/有理数规范化比对处理，等价性只在
  `formula_equivalent` 函数层断言——原卡把它列为端到端正例是审核方措辞错误，已改）；
- 负例不误判为对（有断言）；
- `UnsupportedLatex` 用例（积分 / 矩阵 / 未知宏）→ 返回 None、走自评、不抛给调用方；
- **白名单必须是承重墙**：用"语法合法但结构被禁"的输入直接打 `_parse_formula_side`，断言精确拒绝码
  （属性访问 `x.y`→`forbidden_node`、下标 `sqrt[2]`→`forbidden_node`、多参 `sqrt(1,2)`→`bad_call`、
  关键字 `sqrt(x=1)`→`bad_call`、白名单外名 `foo+1`/`_x+1`→`forbidden_name`、字符串常量→`forbidden_constant`、
  裸 `lambda: 1`→`forbidden_node`、超大常数→`const_too_large`）；
  **注意 `ast.walk` 是 BFS**：外层 `Call` 先于内层 `Lambda` 被访问，故 `(lambda: 1)(x)` 的真实拒绝码是
  `forbidden_call` 而非 `forbidden_node`——按真实码断言，另补裸 lambda 用例覆盖节点路径；
  变异要求：临时把 `_validate_formula_ast` 的 `nodes` 置空，这批用例必须**全部变红**；
- 标签惰性必须有集成反证：剥掉 `formula_fallback` 后 mastery 与下次到期日一字不变，
  **且 `mastery=0` 时到期日必须不同**（证明 mastery 真进入间隔计算，等式非恒真）；
- 同输入重放一致（确定性）；
- 全量 `pytest -q` 绿 + `ruff check --no-cache` + `npm run build`；**`requirements.txt` 零变化**（用
  `git diff` 证明）。

【禁止】
- 引入 antlr4-python3-runtime 或任何新依赖；
- `eval` / `exec` / unrestricted `sympify`（白名单外的名字一律拒绝）；
- 把 fallback 伪装成"判对"或默认通过；
- 对依赖图形的题（`figure` / `【依赖图形】`）启用公式判分；
- 改动 `judgeAnswer` 既有非公式路径的行为与既有断言；把公式判分接进真实作业链路（真实题不在系统内判）。
```
