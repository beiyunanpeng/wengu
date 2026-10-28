# Qoder 施工计划 · v2.5 核心闭环（8 批次合订版）

> **本文件是唯一有效的批次工单**——投喂 Qoder 时只从这里复制，不要翻聊天记录（聊天记录里含已作废的 `primary_concept_id` 旧写法）。
> 依据：`TICKETS.md`（v2.5）+ 设计文档 §16 + `AGENTS.md` 顶部 v2.5 横幅。三者与本文件冲突时，以**设计文档 §16** 为准。
> 生成：2026-10-28。

## 全局护栏（每一批都附带，别省）
- 每次给 Qoder 的上下文固定为：仓库根 `AGENTS.md` 全文 + 本批次卡的描述 + `docs/specs/architecture/StudyDesk-设计说明文档-v2.md` §16。绝不在聊天里重述需求。
- **本计划除批次⑧外，全部是"加法式"改动，禁止删/碰系统内旧视觉栈**（`preprocess/ocr.py`、`services/slicer.py`、`services/extraction.py`、`api/captures.py`、`api/extractions.py`、`providers/{doubao,qwen_vl,tencent,failover,http,openai_vision}.py`、`llm_prompts/`、`model_runs`）——新旧暂时并存，删除统一留到批次⑧，防闭环断档。
- 统一口径：主考点列 = **`primary_topic_id`**（FK `knowledge_seed.id`，形如 `cnm_042`）；作答来源 = **`attempts.source ∈ {student_self, system_quiz, manual}`**；闭环同类题考核**复用 `attempts`**，**不建 `quiz_attempts` 表**；主动加练变式走 `practice_records`；导入通道 `channel="agent_transcribe_v1"`（兼容旧 `doubao_json`）。
- 一条批次 = 一个可跑增量 = 一个 PR；跑完交回"运行态证据"（实跑输出/迁移升回退/端到端一遍），不接受"单测通过"一句话。

## 建议施工顺序
①→②→③→④→⑤→⑥→⑦→（家用一阵、确认闭环稳）→⑧

---

## 批次① 数据模型增量（TICKETS P1-1，迁移加在 0010 之后）

```
【上下文】读 AGENTS.md（v2.5 横幅 + §4/§5/§6）、设计文档 §16；先读现状别猜：
app/models/{ingestion,mistakes,grading,events,review}.py、services/ingestion.py、
migrations/versions/0010_model_run_attempts.py（照它的可重入写法）。

【现状·按此别按旧描述】
- Mistake.source_grading_id→grading_results 这条链（draft→GradingResult(source_kind='ingestion_draft')
  →确认 wrong→Mistake）已存在且合法，不要改 Mistake 来源结构。
- standard_answer 等是"进 normalized_json 的归一化字段"，不是数据库列；GradingResult/MistakeVersion
  已有 standard_answer，复用。

【精确改动】
A) 新增迁移 migrations/versions/0011_v25_intake_and_quiz.py
   revision="0011_v25_intake_and_quiz"，down_revision="0010_model_run_attempts"；
   SQLite 加列一律 op.batch_alter_table，升/回退前 inspect 列/索引、可重复执行。
   1. attempts：加 `source TEXT NOT NULL server_default 'manual'`
      （student_self=原题重做自评 / system_quiz=系统判同类题考核 / manual=历史与手录；既有行回填 manual）；
      加 `problem_bank_id INTEGER NULL` 外键→problem_bank.id ON DELETE SET NULL + 索引
      （system_quiz 溯源用的题库题，student_self 可空）。不新建 quiz_attempts 表——
      闭环考核记在 attempts（掌握度唯一事实源，另起表会让 recompute 双读、破坏确定性重算）。
   2. mistakes：加 `primary_topic_id TEXT NULL` 外键→knowledge_seed.id ON DELETE SET NULL + 索引
      （检索同类题的主考点；多对多仍走 mistake_versions.confirmed_concept_ids_json，不冲突）。

B) services/ingestion.py（非迁移）：FIELD_LIMITS 加 standard_answer(500)/verify(200)/
   error_cause_suggestion(50)/suggested_topic_id(40)；channel 接受 "agent_transcribe_v1"（兼容 doubao_json）；
   validate_and_normalize 把它们写进 normalized_json；standard_answer 空 或 student_answer 空→is_incomplete=True；
   含〔?〕→has_placeholder=True。仍不调模型、坏项进 errors、超长不截断。

C) app/models：Attempt 补 source/problem_bank_id、Mistake 补 primary_topic_id，与迁移一致；只加字段，
   不改"怎么用"的服务逻辑（那是批次②③④⑤⑥）。

【DoD（要运行态证据）】
1. alembic upgrade head 到 0011 成功；downgrade -1 回 0010 干净、可重复 upgrade。
2. 内存 SQLite 最小 pytest：建一条 attempts(source='system_quiz', problem_bank_id=…) +
   一条 mistakes(primary_topic_id='cnm_042') 能读回；旧数据回填 manual 不冲突。
3. 缺 standard_answer 的非法报文经 validate_and_normalize → is_incomplete=True 且进 normalized_json。
4. migrations/README.md 备份/回退段补一行（照 0010 风格）。
5. 全量测试不破（recompute/review 把新列当"读时忽略"）。

【禁止】不手改生产 db；不动 learning_events 的 UPDATE/DELETE 触发器守卫；不新建 quiz_attempts；
不改 Mistake 来源结构；不碰旧视觉栈；迁移含可回退 downgrade + 备份说明（AGENTS §8）。
```

---

## 批次② 监听目录导入引擎（TICKETS P1-3d，主入本通道）

```
读 AGENTS + TICKETS P1-3d。做什么：wengu 后台扫 data/inbox/ 的 *.json →
复用 services/ingestion.py 的 validate_envelope/validate_and_normalize（standard_answer 缺失或含〔?〕
→ 只进草稿、拒绝自动转正）→ import_batches（sha256 对原始报文去重、重复返回 duplicate=true）
→ ingestion_drafts → 源文件归档到 data/inbox/.processed/。导入全程不调模型、不自动转正。
DoD：放一份合法 JSON 进 inbox → 秒级成草稿、报告 accepted_count/errors[]；同文件再投命中去重；
坏项逐条报 index/field/reason、不静默截断；服务停机时文件不丢、起来后补处理。
禁止：导入时判分/建错题/自动转正。
```

---

## 批次③ 核对页确认 → 入本（TICKETS P1-6）

```
读 AGENTS + TICKETS P1-6。做什么：核对页把"题+错答+正答"并排回显 → 家长/孩子一键确认 →
走唯一写入路径建错题；standard_answer/错因/知识点按"AI 建议值→确认值"分来源存（冲突不覆盖）；
确认时指定 primary_topic_id（主考点）。
v2.5：入本来源=核对页确认的外部转录错题（链走 GradingResult(source_kind='ingestion_draft')→Mistake，不改结构）。
DoD：一条转录错题确认 ≤1 点击入本；缺 standard_answer 或未确认 primary_topic_id → 不能转正、不排同类题考核
（只走原题重做自评 student_self）；practice_records 有可回看查询页。
禁止：AI 自由生成标签泛滥；把变式/考核写入错题本；无确认静默入库。
```

---

## 批次④ 题库检索引擎（TICKETS P1-10，"同类题"地基）

```
读 AGENTS + TICKETS P1-10。做什么：把 cn-math-taxonomy 的 questions.json 初中段（数学 1407/英语 1028/物理 368）
载入内存索引（不进 SQLite，守 §14 数据形态），建 topic_id→[题] 倒排；
services/bank.py: find_same_type(primary_topic_id, seed) —— 同 topicId + mulberry32 固定种子可 replay()；
无题→返回空 + bank_gap=true；bank 每题 verify 入库时过 AST 白名单沙箱核验（复用批次⑤判分器）。
DoD：给一个 cnm_* 主考点 + 固定种子 → 稳定返回同 topicId 题、可重放；无题知识点 → 明确"缺口"；内联 SVG 过 HTML 净化。
禁止：LLM 编题；把题库塞进 SQLite。
```

---

## 批次⑤ 判分器作用域收缩 + 复习"考核优先/重做兜底"（TICKETS P1-5 + P1-7a）

```
读 AGENTS + TICKETS P1-5、P1-7a。做什么：
- judgeAnswer 只做确定性归一化比对（NFKC 全/半角、多答案按 ,、；和/或 拆分、1/2≡0.5≡50% 有理数精确比较、
  坐标/单位别名/带分数、acceptableAnswers 别名），运行时不 eval；bank verify 仅入库时过 AST 白名单沙箱。
- 复习 due_queue() 对每道到期错题：先按 primary_topic_id 检索同类题（批次④）→ 命中推"同类题考核"、
  未命中退"原题重做（自评 student_self）"并标 bank_gap。
- recompute.mastery() 把 attempts 里 source ∈ {student_self, system_quiz} 两类都计入、MVP 各算 1 次仅打标签
  （暂不加权，可整体重算）；一道错题挂多 concept 取最小 mastery（不变）。
v2.5 关键：删除旧"对真实作业做客观/过程/开放分级 + 模型初判 + 多次采样一致性"整段——真实题不判。
DoD：judgeAnswer 单测覆盖全规范化规则；verify 沙箱入库跑通；到期任务按"考核优先/重做兜底"正确分流；replay 一致。
禁止：让模型判分；运行时 eval verify；用 Python 内置 eval()。
```

---

## 批次⑥ 同类题考核闭环（TICKETS P1-11）

```
读 AGENTS + TICKETS P1-11。做什么：考核页取一道同类题 → 客观/短答题系统内作答、judgeAnswer 比对 bank 标准答案
判分（记 attempts：source=system_quiz，不新建错题）；数学解答大题（bank type 非客观 或 figure 依赖图）→
降级"纸上做 → 拍已批改 → 自评"（source=student_self）。触发两者都要：复习到点自动推（批次⑤）+ 家长手动组卷
入口（选知识点→出 1..N 题）。考核结果计入该知识点掌握度、可整表清空。
DoD：一道数学错题到期 → 推同 topicId 客观题 → 系统判对/错 → 掌握度变化可重放；大题走自评路径；手动组卷可用；
source=system_quiz 的 attempts 不新建错题。
禁止：让模型判考核题；把考核结果建成错题。
```

---

## 批次⑦ 最小 UI 串闭环（TICKETS P1-9）

```
读 AGENTS + TICKETS P1-9。做什么：五页跑通——导入页（inbox 说明 + 家长手填最小表单）/
核对页（题+错答+正答并排 + 错因确认 + 多知识点挂载 + 选主考点 primary_topic_id）/
错题本 / 复习+考核页（到期任务、重做自评 or 同类题作答）/ 讲解位（默认关）。React+Mantine+KaTeX（数学渲染）。
DoD：家长能"外部转录→核对确认入本→复习到期→(能考就考/否则重做自评)"端到端走一遍；孩子见同一份。
禁止：提前做看板/规划/美化；在纯查询页触发模型调用（wengu 已零模型）。
```

---

## 批次⑧ 退役旧视觉栈与 Provider（TICKETS P1-12，一定放最后）

```
前置：批次②④⑥⑦ 全部实跑通过、端到端闭环在家用场景跑顺之后才做（防断档）。
读 AGENTS + TICKETS P1-12。做什么：删除 preprocess/ocr.py、services/slicer.py、services/extraction.py、
api/captures.py、api/extractions.py、models/extraction.py；删 providers/{doubao,qwen_vl,tencent,failover,
http,openai_vision}.py、成本护栏、model_runs、llm_prompts/；清路由与 DI 引用；更新 CHANGELOG +
.env.example（去掉模型 Key 必填）。保留 providers/mock.py 供测试。
DoD：删后服务能起、/health 200、全测试绿、端到端不回归；单张可整体回滚。
禁止：在新入口未跑通前删；顺手删掉 mock.py。
```

---

## 交付节奏
- 每批 Qoder 交回后，人审三件事：**实际 diff 范围**（没越界改别的文件）、**运行态证据**（迁移升/回退、实跑一遍、非"测试通过"空话）、**DoD 对齐**。
- 全绿再进下一批；任一越界（改了无关文件、动了旧栈、加了新依赖）直接退回。
- 批次⑧做完 = v2.5 核心闭环稳定，可进 Phase 2（每日任务/看板）。
