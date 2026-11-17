# seeds · 知识点树 seed 数据

本目录存放 wengu 的**知识点 seed 包**（JSON 文件形态 = 分发真源）与**家长自建数据**。
运行时装载器（`wengu-api/app/seed/loader.py`）把 `data/` 装载进 SQLite 作为装载副本 + FK 锚点，
并建内存索引供回溯诊断使用；**JSON 是唯一真源，装载幂等可重入**。

## 目录布局

```
seeds/
├─ data/                    # 随仓库分发：转换后的 cn-math-taxonomy 初中包（CC BY-NC 4.0）
│  ├─ topics.json           #   1821 个知识点（小学 450 + 初中 664 + 高中 707；数学 828 + 英语 724 + 物理 269）
│  ├─ dependencies.json     #   2917 条先修边（跨学段边全量保留；hard/soft）
│  ├─ questions.json        #   7431 题（小学 1800 + 初中 2803 + 高中 2828；数学 3459 + 英语 2896 + 物理 1076；P1-10）
│  ├─ _source.json          #   知识点/先修边署名：上游 URL / License / NC 声明 / 计数 / 快照 commit 与取证
│  └─ questions_source.json #   题库署名：同上 + 题目计数 / 配图 / verify 统计
├─ local/                   # 家长自建，不进 Git：化学/语文等同契约 seed 文件
├─ mappings/                # 家长自建，不进 Git：教材包对照（<版本id>.json）
└─ README.md
```

## 来源与许可：`cn-math-taxonomy`（data/ 目录）

- **上游**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **许可**：**CC BY-NC 4.0**（署名 + 非商用）；分发时必须保留 `_source.json` 与仓库根 `THIRD-PARTY-NOTICES.md`、`LICENSE-data.md`（数据许可分层全文见后者）
- **诚实标注**：上游自述"AI 生成的初稿、未经一线教师审核"（`unaudited: true`）；**仅初中数学做过二遍盲解**（`blind_verified: true`，mismatch=0），英语/物理的 `verify` 与答案**同源**、无二遍盲解（`blind_verified: false`）→ 英语/物理**仅作参考冷启动、家长复核后再用**，UI 必须透传这两枚标签。

## 重新生成 data/（开发者）

上游更新后重跑转换脚本（需要本地有上游 clone）：

```bash
# 在仓库根目录执行：把上游 clone 到仓库的父目录（与仓库同级）
git clone https://github.com/xiaoyang111222/cn-math-taxonomy.git ../cn-math-taxonomy-main  # 一次性
make seed-load   # 等价于 cd wengu-api && python -m scripts.import_seed --src ../../cn-math-taxonomy-main
```

**zip 来源必须显式传 `--upstream-commit <sha>`**：若上游来自 GitHub zip 解包（无 `.git`），
`git rev-parse HEAD` 探测不到 commit，脚本会写 `null` 并打印警告——**严禁按导入日期猜测 SHA**。
两个脚本（`import_seed.py` / `import_questions.py`）同规则：`--upstream-commit` 显式覆盖优先，
未提供才走 git 探测。当前分发快照的取证方法见设计文档 §19-F-1 与 `_source.json` 的 `commit_evidence`。

**重跑会重写 `_source.json` / `questions_source.json`**：脚本只发射基础署名键；P5-5 策展的
provenance 键（`upstream_commit_date` / `upstream_author` / `upstream_spdx` / `code_spdx` /
`modified` / `disclaimer` / `snapshot_source` / `commit_evidence`）是**当前快照的取证工件**，
换快照重跑后必须按 §19-F-1 重新取证、重新策展，不得沿用旧证据。

转换规则：学段过滤 `--grades` 参数驱动（默认 junior，可复现可回退）→ 12 核心字段直映
（camelCase→snake_case）→ 按 id 前缀显式化 `subject`（cnm_=数学、cne_=英语、cnp_=物理）→
打质量标签 → 先修边跨学段全量保留（收录范围与丢弃数记入 `_source.json`）。
全量收录 grade 1-16（grade 10-16 语义为"册"）。

## 题库（P1-10，同类题考核的数据源）

- `data/questions.json` 是**运行时内存索引的唯一真源**：`app/seed/bank.py` 读入后建
  `topic_id → [题]` 倒排，**不写 SQLite**（SQLite 只存动态数据，守设计 §14）。
- 每题在装载时过 P1-5 AST 白名单沙箱核验 `verify`：能算且与答案一致 → `verified`；
  无 `verify` / 表达式用了沙箱白名单外的 `Fraction`、`range`、数学函数 / 选择题选项带单位
  → `unverifiable`（保留，供考核使用）；**纯数值题算出矛盾 → 不装载**。
  当前 7431 题：verified 5996、unverifiable 1435、mismatch 0；
  reasons 分布见 `questions_source.json` 的 `counts.load_quality`（不在此手抄）。
- 同类题检索：`services/bank.py` 的 `find_same_type(primary_topic_id, seed)` 用
  mulberry32（与上游 JS 逐位一致）按固定种子取 1 题，`replay(pick)` 可重放；
  无题知识点返回空 + `bank_gap=true`（P1-7a 退回原题重做）。全量收录后各学科均不低于
  thin 阈值（学科级 500）；语文/化学无题 → 缺口。
- 配图安全：题干与选项的内联 SVG 在后端装载时过白名单净化（`app/seed/svg.py`，
  使用既有 `bleach` 依赖），前端只能渲染净化后的字符串。

重新生成题库（开发者，需上游 clone）：

```bash
make seed-questions
```

## 化学、语文（上游无数据）：local/ 起步

`cn-math-taxonomy` 不含化学、语文。这两科**空 seed 起步**，家长复用同款 topics 契约在 `local/`
放同结构 JSON（如 `local/topics.chemistry.json`），按课本目录录**章级粗粒度 40–80 点**
（`mastery_criteria` 可精简、无诊断题、`unaudited: true`），细粒度交给"错题驱动受控生长"。
装载器容忍缺文件/空数组。

## 多教材版本：mappings/ 机制照抄、数据自建

- 上游只对**人教版 2024 审定新版**做了目录核对；用其他版本教材（沪教/苏教…）需自建对照数据。
- 契约（结构照抄上游 `docs/edition-mappings.md`）：`{"edition", "label", "status": "example|draft|reviewed", "note", "entries": [{"topicId", "grade", "term", "unit", "chapter"}]}`
- **status 含义**：`example`=格式示例（占位、不得引用）、`draft`=草稿待核、`reviewed`=已核对。
- 装载器只校验 + 暴露进索引，供将来 UI 对照教材目录；**仓库不附带任何对照数据**。

## 运行时验证

启动后 `GET /api/seed/summary` 返回各学科点数、`unaudited`/`blind_verified` 计数与教材包列表。
