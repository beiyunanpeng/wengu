# transcribe/ — 已批改错题转录 SOP（wengu 可选包）

> **这是什么**：把「整页已批改卷子 → 结构化错题 JSON → `data/inbox/`」这条**系统外第一公里**，做成随仓库分发的标准作业流程 + 契约 + Skill + 离线校验器。
> **这不是什么**：不是 wengu 运行时的一部分。**不进 `wengu-api/requirements.txt`、不进 API 镜像、不进 CI 主链依赖**。wengu 后端仍是零模型；本包只用 Python 标准库，不需要任何 API Key。
> **为什么单独放**：v2.5 把批改外移后，闭环的第一环落在系统外。做成独立可选包，既补上开源分发缺失的入口，又不把模型 SDK / 密钥 / 视觉依赖带回内核。

---

## 0. 先读这一段：合规 checklist（每次转录前逐条过）

外部转录会把卷面送进第三方 AI。教育部《中小学生成式人工智能使用指南》（2025 版）明确「严禁将个人信息、考试试题等敏感数据输入 AI 工具」。因此**以下不是建议，是流程前置条件**：

- [ ] **擦除**：姓名、学校、班级、学号、座位号、家长签名、教师评语、手写批注中的个人信息；照片 EXIF 定位一并去掉。只保留题目、作答、红笔批改与订正。
- [ ] **裁剪**：能只截题目区域就不传整页；页眉页脚、成绩栏、排名一律不进图。
- [ ] **告知**：首次使用由监护人知情并单独同意；孩子知道「卷子会送到哪个 AI 工具、送哪些内容」。
- [ ] **境内**：只用境内已备案模型服务；**禁止**把图片送到境外端点。
- [ ] **本地留存**：照片、转录 JSON、批次 manifest 只放在本机 `data/`，不进仓库、不进网盘同步目录、不进 issue / 群聊 / 反馈表单。
- [ ] **不联网替代路径**：若上面任一条做不到，改走 `/import` 页**手填**或本地粘贴 JSON（`POST /api/imports`），完全不调外部模型。

> 若你是替其他家庭部署/分发：请把本节原样保留，并让对方自行完成监护人告知。本仓库不代替下游承担合规义务。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 卷面 | **已经红笔批改 + 订正完毕**：原题、被划掉的错答、订正后的正答三者都在纸上 |
| 工具 | 一个能读图并输出 JSON 的 AI 工具（豆包网页/App、千问办公、WorkBuddy，或任意境内视觉模型） |
| 本地 | Python ≥ 3.11（仅标准库）、wengu 服务可起可不起 |
| 无需 | API Key、Docker 外的额外依赖、wengu 后端代码改动 |

> 卷子上没有订正正答的题，转录时 `standard_answer` 必须填 `〔?〕` 而不是让模型自己解题。缺正答的草稿**不能转正**，这是刻意设计，不是缺陷。

---

## 2. SOP 七步

| # | 步骤 | 产出 / 判据 |
|---|---|---|
| 1 | **过 §0 合规 checklist**，裁图、擦除 PII | 一张只含题目/作答/红笔痕迹的图 |
| 2 | **取模板**：读 `docs/templates/doubao_transcribe_v1.md` 中「===[ 发给模型的指令 ]===」到结束标记之间的整段；核对其 frontmatter `version` 与 `contract/ingestion_v1.json` 的 `template.version` 一致 | 指令正文（**不要改写、不要内嵌进 Skill**） |
| 3 | **转录**：把「指令 + 图」交给 AI 工具，拿到 `{channel, items}` JSON | 原始 JSON；只转录被红笔判错的题 |
| 4 | **自检**：`python transcribe/validate.py check <file.json> --source-tool <工具名> --template-version 1 --manifest <batch>.manifest.json` | `accepted / rejected / placeholder / incomplete / unknown_fields` 逐项报告 + 批次 manifest |
| 5 | **人工看回执**：`rejected > 0` 要回头补转录；`placeholder / incomplete` 高的批次要预期核对页工作量 | 你知道「这摞卷子丢了几道题」——**漏转录不再静默** |
| 6 | **投递**：把 JSON 放进 `./data/inbox/`（可用 `WENGU_INBOX_DIR` 覆盖）。服务没起也没关系，起来后会自动补扫；处理完归档到 `.processed/` | `ingestion_drafts` 草稿 |
| 7 | **核对页人工确认转正**：题目 / 错答 / 正答三栏并排，确认主考点与错因 | 唯一写入路径建错题 + 首排复习 |

> **只到草稿**是铁律：转录端绝不写 SQLite、绝不调转正端点、绝不自动入本。

### 命令速查

```bash
# 契约/模板/Skill/后端是否漂移（只读；改模板或升契约后必跑）
python transcribe/validate.py selfcheck
python transcribe/validate.py selfcheck --strict        # 供 CI，有 DRIFT 返回 1

# 脱敏合成样例回归（不调模型）
python transcribe/validate.py evals

# 校验一批转录产物
python transcribe/validate.py check data/inbox/transcribe-20261112-01.json \
  --source-tool doubao_web --template-version 1 \
  --manifest data/inbox/transcribe-20261112-01.manifest.json
```

---

## 3. 不同 AI 工具怎么接

| 工具 | 做法 |
|---|---|
| 豆包网页 / App | 手动复制模板指令 + 上传图 → 复制返回 JSON 存成 `.json` |
| 千问办公 | 用 `docs/tooling/wengu-transcribe.md` 的旧配方（注意：含开发者本机路径，见 §5） |
| WorkBuddy / Claude Code | 安装 `transcribe/skills/wengu-transcribe/`（通用版，无硬编码路径） |
| 任意 OpenAI 兼容视觉模型 | 把模板指令作 system prompt、图作 image 输入、要求 `response_format` 为 JSON；产出仍须过 `validate.py check` |

**共性要求**：感知/转录任务用**非深度思考档**。Phase 0 实测与 MME-CoT 等研究都表明，长 CoT 在 OCR / 定位 / 计数类感知任务上会引入「有害过度思考」，更贵、更慢、更差。别让模型「顺手讲讲这题为什么错」。

---

## 4. 版本纪律

1. 改模板语义 → `frontmatter.version + 1`；
2. 改字段契约 → `contract/ingestion_v1.json` 升版 + **同步后端 `wengu-api/app/services/ingestion.py` 的 `FIELD_LIMITS`**；
3. 跑 `selfcheck --strict`（必须 0 DRIFT）+ `evals`（13/13）；
4. 更新 Skill 的 `template_ref` / `contract_ref`；
5. CHANGELOG 留痕，一个 ticket 一个 PR。

> 后端常量是**运行时唯一权威**，`contract/*.json` 是给外部转录端用的镜像。`selfcheck` 的职责就是证明两者没有漂走 —— 这样不会制造「第二个真源」。

---

## 5. 当前已知漂移（P5-7 收口后 `selfcheck` 实跑结果）

```
12 OK / 5 DRIFT / 1 WARN
```

P5-7 起 `selfcheck` 除旧 Skill 外**也校验真正随包分发的 portable Skill**
（`skills/wengu-transcribe/SKILL.md` 的 `template_ref` / `contract_ref` 是否指向存在文件 / 本包契约，
以及经 `template_ref` 读到的模板 `id` / `version` / `channel` 是否与契约一致）；
入口已重配置 stdout/stderr 为 UTF-8 + replace，**Windows 默认 GBK cmd/PowerShell 不再抛
`UnicodeEncodeError`**（纯 GBK 代码页下中文显示为 UTF-8 字节、可能花屏，但汇总完整、退出码正确；
`chcp 65001` 后显示正常）。

| 状态 | 项 | 说明 |
|---|---|---|
| DRIFT | 字段集合 | 契约 9 项 / 后端 10 项：后端 `FIELD_LIMITS` 含 `correction_notes`（P1-17），契约镜像未含 → P5-8 收口 |
| DRIFT | 模板 `schema_fields` ↔ 契约字段 | 模板含 `correction_notes` 缺 `verify`；契约含 `verify` 缺 `correction_notes` → P5-8 二选一收口 |
| DRIFT | 模板 version | 模板 v2（P1-17 升）/ 契约 `template.version` 1 → P5-8 对齐 |
| DRIFT | portable Skill 模板 version | 经 `template_ref` 读到的模板 v2 / 契约 1，同上 → P5-8 对齐 |
| DRIFT | 版本纪律回归目录 | 模板 §「与 wengu 系统的契约」与旧 Skill 都要求跑 `evals/transcribe/`，但该目录随 P1-12 退役后**并不存在** → P5-8 改指 `transcribe/evals/` |
| WARN | 旧 Skill 硬编码个人路径 | `docs/tooling/wengu-transcribe.md` 写了 `D:\MyProducts\StudyDesk\...`，开源后其他家长不可直接用 → P5-8 改指新 Skill |

**本包不自动修这些** —— 按项目「一张 ticket = 一个可跑增量 = 一个 PR」的纪律，上述 drift 的修复属
**P5-8**（改现有文件），需人审；P5-7 只做纯新增 + 包内两处修复（编码 / portable 校验）+ UP038。

---

## 6. 目录

```
transcribe/
├─ README.md                       ← 本 SOP
├─ CONTRACT.md                     ← 契约语义与铁律
├─ validate.py                     ← 纯标准库校验器（check / selfcheck / evals）
├─ contract/ingestion_v1.json      ← 机器可读契约（后端常量的镜像）
├─ skills/wengu-transcribe/SKILL.md← 通用 Skill（多家 agent 可用）
└─ evals/fixtures/*.json           ← 脱敏合成样例（13 条断言，无真实作业内容）
```

## 7. License 与数据

- 本包代码与文档随 wengu 主仓库 MIT 分发。
- `evals/fixtures/` 全部为**合成样例**，不含任何真实学生作业、答案或个人信息的片段。
- 本包**不分发** `cn-math-taxonomy` 的题目或知识点数据；模板引用的 `topics_junior.tsv` 归属见 `THIRD-PARTY-NOTICES.md`（CC BY-NC 4.0，限个人非商用）。
- 不复制任何第三方 agent 的 Skill 源码或提示词资产，只定义本仓库自己的契约。
