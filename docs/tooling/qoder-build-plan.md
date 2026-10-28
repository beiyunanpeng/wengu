# Qoder 施工计划 · v2.5 核心闭环（8 批次合订版，每卡可直接复制）

> **本文件是唯一有效的批次工单**——每张卡都已内联"读哪些文件 + 全局护栏 + 验收口径"，**复制整段贴给 Qoder 即可，无需再补任何上下文**。（聊天记录里的旧版含已作废的 `primary_concept_id` 写法，别用。）
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
分来源存（冲突不静默覆盖）；确认时指定 primary_topic_id（主考点）。知识点：粗 seed 挂载 + 细粒度受控生长
（优先复用、不覆盖确认值、归并需人工确认、alias）。主动加练变式 → practice_records。
【DoD】一条转录错题确认 ≤1 点击入本；缺 standard_answer 或未确认 primary_topic_id → 不能转正、不排同类题考核
（只走原题重做自评 student_self）；practice_records 有独立可回看查询页。
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
【DoD】一道数学错题到期 → 推同 topicId 客观题 → 系统判对/错 → 掌握度变化可重放；大题 → 降级自评路径生效；
家长手动组卷可用；source=system_quiz 的 attempts 不新建错题。
【禁止】让模型判考核题；把考核结果建成错题本条目。
```

---

## 批次⑦ —— 最小 Web UI（串起闭环）

```
你在 wengu 仓库工作。开工前完整读：AGENTS.md（§3 前端栈 / §4 零模型 / §6 回显总闸）+ 设计文档 §16 + TICKETS.md 的 P1-9。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。禁止删除/改动旧视觉栈（留到 P1-12）。禁止新依赖/框架。
【任务】五页跑通：导入页（inbox 说明 + 家长手填最小表单）/ 核对页（题+错答+正答并排回显 + 错因确认 +
多知识点挂载 + 选主考点 primary_topic_id）/ 错题本 / 复习+考核页（到期任务、重做自评 or 同类题作答）/
讲解位（默认关）。技术栈 React + Mantine + KaTeX（数学渲染）。
【DoD】家长能"外部转录 → 核对确认入本 → 复习到期 →（能考就考 / 否则重做自评）"端到端走一遍；孩子见同一份。
【禁止】提前做看板/规划/美化；在纯查询页触发任何模型调用（wengu 已零模型）。
```

---

## 批次⑧ —— 退役旧视觉栈与 Provider（一定放最后）

```
前置条件（不满足就停下、别做本票）：批次②④⑥⑦ 全部实跑通过、端到端闭环在家用场景跑顺之后才开工。
你在 wengu 仓库工作。开工前完整读：AGENTS.md（顶部 v2.5 横幅 / §4）+ 设计文档 §16 + TICKETS.md 的 P1-12。
【全局纪律】一条 ticket = 一个 PR；交付附运行态证据。**本票是"删除票"，与前面各卡的"勿删旧栈"护栏相反——本票的活就是删。**
【任务】删除：preprocess/ocr.py、services/slicer.py、services/extraction.py、api/captures.py、api/extractions.py、
models/extraction.py；providers/{doubao,qwen_vl,tencent,failover,http,openai_vision}.py、成本护栏、model_runs、llm_prompts/；
清路由与 DI 引用；更新 CHANGELOG + .env.example（去掉模型 Key 必填）。**保留 providers/mock.py 供测试。**
【DoD】删后服务能起、/health 200、全测试绿、端到端不回归；单张可整体回滚。
【禁止】在新入口（批次②④⑥⑦）未跑通前删；顺手删掉 mock.py；把删除范围扩到本票清单之外。
```
