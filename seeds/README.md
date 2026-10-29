# seeds · 知识点树 seed 数据

本目录存放 wengu 的**知识点 seed 包**（JSON 文件形态 = 分发真源）与**家长自建数据**。
运行时装载器（`wengu-api/app/seed/loader.py`）把 `data/` 装载进 SQLite 作为装载副本 + FK 锚点，
并建内存索引供回溯诊断使用；**JSON 是唯一真源，装载幂等可重入**。

## 目录布局

```
seeds/
├─ data/                    # 随仓库分发：转换后的 cn-math-taxonomy 初中包（CC BY-NC 4.0）
│  ├─ topics.json           #   664 个初中知识点（数学 315 + 英语 257 + 物理 92）
│  ├─ dependencies.json     #   1018 条先修边（两端点均在初中集内；hard/soft）
│  ├─ questions.json        #   2803 道初中题（数学 1407 + 英语 1028 + 物理 368；P1-10）
│  ├─ _source.json          #   知识点/先修边署名：上游 URL / License / NC 声明 / 计数
│  └─ questions_source.json #   题库署名：同上 + 题目计数 / 配图 / verify 统计
├─ local/                   # 家长自建，不进 Git：化学/语文等同契约 seed 文件
├─ mappings/                # 家长自建，不进 Git：教材包对照（<版本id>.json）
└─ README.md
```

## 来源与许可：`cn-math-taxonomy`（data/ 目录）

- **上游**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **许可**：**CC BY-NC 4.0**（署名 + 非商用）；分发时必须保留 `_source.json` 与仓库根 `THIRD-PARTY-NOTICES.md`
- **诚实标注**：上游自述"AI 生成的初稿、未经一线教师审核"（`unaudited: true`）；**仅初中数学做过二遍盲解**（`blind_verified: true`，mismatch=0），英语/物理的 `verify` 与答案**同源**、无二遍盲解（`blind_verified: false`）→ 英语/物理**仅作参考冷启动、家长复核后再用**，UI 必须透传这两枚标签。

## 重新生成 data/（开发者）

上游更新后重跑转换脚本（需要本地有上游 clone）：

```bash
git clone https://github.com/xiaoyang111222/cn-math-taxonomy.git ../cn-math-taxonomy-main  # 一次性
make seed-load   # python -m scripts.import_seed --src ../cn-math-taxonomy-main
```

转换规则：过滤初中（grade 7–9）→ 12 核心字段直映（camelCase→snake_case）→ 按 id 前缀显式化
`subject`（cnm_=数学、cne_=英语、cnp_=物理）→ 打质量标签 → 先修边仅保留两端点均在初中集内的
（跨小学/高中的 74 条丢弃，小学阶段成为回溯天然停止点；丢弃数记入 `_source.json`）。
注意：上游 `grade 10–16` 语义为"册"（高中），本次未导入。

## 题库（P1-10，同类题考核的数据源）

- `data/questions.json` 是**运行时内存索引的唯一真源**：`app/seed/bank.py` 读入后建
  `topic_id → [题]` 倒排，**不写 SQLite**（SQLite 只存动态数据，守设计 §14）。
- 每题在装载时过 P1-5 AST 白名单沙箱核验 `verify`：能算且与答案一致 → `verified`；
  无 `verify` / 表达式用了沙箱白名单外的 `Fraction`、`range`、数学函数 / 选择题选项带单位
  → `unverifiable`（保留，供考核使用）；**纯数值题算出矛盾 → 不装载**。
  当前 2803 题：verified 1738、unverifiable 1065（no_verify 532、sandbox 498、选项带单位 35）、
  mismatch 0。
- 同类题检索：`services/bank.py` 的 `find_same_type(primary_topic_id, seed)` 用
  mulberry32（与上游 JS 逐位一致）按固定种子取 1 题，`replay(pick)` 可重放；
  无题知识点返回空 + `bank_gap=true`（P1-7a 退回原题重做）。物理 368 题按学科总量标
  `thin`，语文/化学无题 → 缺口。
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
