# Qoder 施工计划 · v2.5（MVP 8 批 + P2/P3 存档 + 5 张待投卡，每卡可直接复制）

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
> 投单顺序 = ~~P5-6~~（已合并 PR#27）→ ~~P0-3~~（已合并 PR#28）→ ~~P3-3a~~（已合并 PR#29）→ ~~P3-3b~~（已合并 PR#30）→ **P3-3c → P5-1（既有票）→ P1-3e → P1-13**。每张卡可整段复制给 Qoder。
> **2026-11-03 更新**：P5-6 孤儿表切片已交付（迁移 0019 一次退役 `problem_extractions` /
> `photo_capture_items` / `photo_captures` 三表；见 `TICKETS.md` 与 `docs/STATUS.md` §4.18），
> 本卡留作回溯；P0-3 亦已交付（PR#28），下一张待投 = **P3-3a**。

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
   lint 证据必须是 `ruff check --no-cache .`（不带 --no-cache 会因 .ruff_cache 给出假绿）。
5. 交付描述里给"你自己实跑"的数字（passed 数、关键断言结果、表数等），并单列一段
   「审核方需复核的点」；不要把计划说成已完成，也不要拿旧提交的绿凑数。
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

> **状态同步（2026-11-03）**：本卡已交付（`feat/p3-3b-recitation-import`）。
> 落地：`wengu-api/app/services/recitation_import.py`（stdlib `csv`、TSV 判定、表头/空行/注释、
> 限额与 U+FFFD 拒绝、物理行号）+ `POST /api/recitations/import`（`require_parent`）+
> `/recitations` 家长区「批量导入」；**无迁移、未改 0020 DDL、无新依赖**。
> 验证：新增单测 11 + 集成 11 + e2e 第 5 条；全量 **465 passed**（unit 304 / integration 156 /
> e2e 5）；`ruff check --no-cache .` 与 `npm run build` 全绿。下一张待投 = **P5-1**（P3-3c 排在期后）。
