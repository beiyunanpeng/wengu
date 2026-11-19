# seeds · 知识点树 seed 数据

本目录存放 wengu 的**知识点 seed 包**（JSON 文件形态 = 分发真源）与**家长自建数据**。
运行时装载器（`wengu-api/app/seed/loader.py`）把 `data/` 装载进 SQLite 作为装载副本 + FK 锚点，
并建内存索引供回溯诊断使用；**JSON 是唯一真源，装载幂等可重入**。

## 目录布局

```
seeds/
├─ data/                    # 随仓库分发：转换后的 cn-math-taxonomy 全量包（小学+初中+高中，10 学科）（CC BY-NC 4.0）
│  ├─ topics.json           #   3557 个知识点（小学 1481 + 初中 1267 + 高中 809；数学 870 + 英语 791 + 语文 683 + 物理 269 + 科学 269 + 道德与法治 269 + 化学 147 + 历史 134 + 生物 66 + 地理 59）
│  ├─ dependencies.json     #   5132 条先修边（跨学段边全量保留；hard/soft）
│  ├─ questions.json        #   14375 题（小学 5924 + 初中 5215 + 高中 3236；数学 3627 + 英语 3164 + 语文 2732 + 物理 1076 + 科学 1076 + 道德与法治 1076 + 化学 588 + 历史 536 + 生物 264 + 地理 236；P1-10）
│  ├─ figures_sha256.json   #   640 段配图 sha256 清单（P5-16 路线 B：构建期净化、装载期验哈希）
│  ├─ _source.json          #   知识点/先修边署名：上游 URL / License / NC 声明 / 计数 / 快照 commit 与取证
│  └─ questions_source.json #   题库署名：同上 + 题目计数 / 配图 / verify 统计
├─ local/                   # 家长自建，不进 Git：语文/化学同契约 seed 文件（统一 loc_ 前缀，P5-15）
├─ mappings/                # 家长自建，不进 Git：教材包对照（<版本id>.json）
└─ README.md
```

## 来源与许可：`cn-math-taxonomy`（data/ 目录）

- **上游**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **许可**：**CC BY-NC 4.0**（署名 + 非商用）；分发时必须保留 `_source.json` 与仓库根 `THIRD-PARTY-NOTICES.md`、`LICENSE-data.md`（数据许可分层全文见后者）
- **诚实标注**：上游自述"AI 生成的初稿、未经一线教师审核"（`unaudited: true`）；**仅初中数学做过二遍盲解**（`blind_verified: true`，mismatch=0），其余 9 学科的 `verify` 与答案**同源**、无二遍盲解（`blind_verified: false`）→ 其余学科**仅作参考冷启动、家长复核后再用**，UI 必须透传这两枚标签。

## 重新生成 data/（开发者）

上游更新后重跑转换脚本（需要本地有上游 clone）：

```bash
# 在仓库根目录执行：把上游 clone 到仓库的父目录（与仓库同级）
# P5-16 起实际取证 clone 在 ../cn-math-taxonomy（带 .git，detached 到钉死快照）；
# 旧 zip 解包目录 ../cn-math-taxonomy-main 保留为 d58785ce 取证现场，不再用作转换源。
git clone https://github.com/xiaoyang111222/cn-math-taxonomy.git ../cn-math-taxonomy  # 一次性
cd ../cn-math-taxonomy && git checkout <钉死快照 sha> && cd -   # 必须 detached 到钉死快照，不是最新 main
# make seed-load / seed-questions 的 --src 仍指向旧 zip 路径（Makefile 不在本票白名单，另票更新）；
# 重跑请显式传 --src：
cd wengu-api && python -m scripts.import_seed --src ../../cn-math-taxonomy --grades primary,junior,senior
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
（camelCase→snake_case）→ 按 id 前缀显式化 `subject`（cnm_=数学、cne_=英语、cnp_=物理、cnc_=语文、
cnk_=化学、cnb_=生物、cns_=科学、cnd_=道德与法治、cnh_=历史、cng_=地理）→
打质量标签 → 先修边跨学段全量保留（收录范围与丢弃数记入 `_source.json`）。
全量收录 grade 1-16（grade 10-16 语义为"册"）。

## 上游更新检查（开发者，手动跑）

上游 `cn-math-taxonomy` 持续演进（钉死快照 `8b57f2e` 之后仍在修订）。**发现**靠本脚本 +
维护者 GitHub Watch 上游仓库兜底；**同步永远是另一票**，人工触发。
**本仓库钉死的是 `8b57f2e`，不是上游最新**（2026-11-19 上游触及 `data/` 的最新提交已前进到
`df0879d0…`）；本脚本报「上游有更新」是常态而非故障。

```bash
# 在仓库根目录执行（唯一跑法；不进 CI cron、不进 make 目标、不进应用）
python wengu-api/scripts/check_upstream.py            # 人读报告
python wengu-api/scripts/check_upstream.py --json     # 机器可读报告
python wengu-api/scripts/check_upstream.py --pinned <sha>   # 快照一致性复检（自证）
```

- **何时跑**：考虑同步上游之前，或定期手动巡检。脚本无状态、不落盘缓存，留痕 = 贴报告。
- **怎么读报告**：exit **0** = 已同步（上游最新触及 `data/` 的 commit == `_source.json` 的
  `upstream_commit`）；exit **1** = 有更新（按 raw.githubusercontent 下载该 sha 的
  `data/{topics,dependencies,questions}.json`，**只算不写**，报告 topics 总数/分带/分科、deps、
  questions 的逐指标 delta，并**点名未知前缀**——`SUBJECT_BY_PREFIX` 之外的前缀只报告、不引入）；
  exit **2** = 检查失败（缺文件/缺键、网络失败、403 限流）——**绝不静默当"已同步"**，稍后重试或人工排查。
  只读 GET、无鉴权、无 token；对 `seeds/data/` 零写入。
- **`--pinned <sha>` 复检模式**：对比指定上游快照与仓内数据，delta 全 0 → exit 0。
  自证例：`--pinned 8b57f2e353ac041f81ba705a66503c9a9e2d8ba8` 应 delta 全 0，且数字与两个
  source JSON 的 `counts` 逐字一致。
- **发现更新后的流程**：同步 = 重导入（`import_seed.py` / `import_questions.py`）+
  **按设计文档 §19-F-1 重新取证、重新策展**（provenance 键是旧快照的取证工件，不得沿用）+
  "新学科（如语文）是否引入"等产品决策——**全部另票、人工决定**。本脚本不自动创建 issue/PR、
  不自动重导入、不动 `upstream_commit`。

## 题库（P1-10，同类题考核的数据源）

- `data/questions.json` 是**运行时内存索引的唯一真源**：`app/seed/bank.py` 读入后建
  `topic_id → [题]` 倒排，**不写 SQLite**（SQLite 只存动态数据，守设计 §14）。
- 每题在装载时过 P1-5 AST 白名单沙箱核验 `verify`：能算且与答案一致 → `verified`；
  无 `verify` / 表达式用了沙箱白名单外的 `Fraction`、`range`、数学函数 / 选择题选项带单位
  → `unverifiable`（保留，供考核使用）；**纯数值题算出矛盾 → 不装载**。
  当前 14375 题：verified 12828、unverifiable 1547、mismatch 0；
  reasons 分布见 `questions_source.json` 的 `counts.load_quality`（不在此手抄）。
- 同类题检索：`services/bank.py` 的 `find_same_type(primary_topic_id, seed)` 用
  mulberry32（与上游 JS 逐位一致）按固定种子取 1 题，`replay(pick)` 可重放；
  无题知识点返回空 + `bank_gap=true`（P1-7a 退回原题重做）。全量收录后各学科均不低于
  thin 阈值（学科级 500）；P5-16 起 3557 点全有题，缺口只出现在未知/自建无题点。
- 配图安全（P5-16 路线 B）：题干与选项的内联 SVG 在**构建期**过白名单净化
  （`import_questions` 调 `app/seed/svg.py`，使用既有 `bleach` 依赖），逐段 sha256 落
  `figures_sha256.json`；装载期**验哈希**——一致才用，不一致或缺哈希 → 丢弃该题并计入
  `stats.dropped["figure_hash_mismatch"]`，绝不静默放行。家长补录题仍走装载期净化
  （`services/bank.py` / `bank_import.py` 四处不变）。前端只能渲染净化后的字符串。

重新生成题库（开发者，需上游 clone）：

```bash
make seed-questions
```

## 家长自建：local/（统一 loc_ 前缀）

> **（2026-11-17 标注）**：本节原描述的是钉死快照 `d58785ce`（2026-10-23）的事实——该快照里上游确无
> 化学/语文。上游此后已大规模扩科（2026-11-15 `8b57f2e` 实测出现 cnb_/cnc_/cnd_/cng_/cnh_/cnk_/cns_
> 等 7 个新前缀）。
> **（2026-11-19 更新，P5-16）**：扩科决策已落地——10 学科全量同步进 `data/`（语文 683 点 / 化学 147 点），
> "化学/语文空 seed 起步"作废。本地自建机制**保留**，理由 = **教材版本差异 + 家长自建章级点**。

家长复用同款 topics 契约在 `local/`
放同结构 JSON（如 `local/topics.chemistry.json`），按课本目录录**章级粗粒度 40–80 点**
（`mastery_criteria` 可精简、无诊断题、`unaudited: true`），细粒度交给"错题驱动受控生长"。
装载器容忍缺文件/空数组。

**本地 id 约定（P5-15，§19-G-3 定案一）**：统一 **`loc_` 单前缀**（`loc_001`、`loc_002`…），
学科由 `subject` 字段承载（白名单现语文/化学）；装载器/API 强制 `source='local'`，
导出脚本"本地恒保留"判据**只读 `source` 标记、不按 id 前缀**。上游 10 科前缀全在 `cn?_` 家族内，
`loc_` 永不冲突，加新学科零改动。legacy `cnl_`/`cnc_` 本地文件**装载时明确拒绝**
（`seed_loaded=false` 显式降级，错误文案含改名指引，如"请将 cnl_001 改为 loc_001"），
绝不静默装载；不提供迁移脚本（实测零 legacy 本地点，真有的家庭另开迁移票）。

## 多教材版本：mappings/ 机制照抄、数据自建

- 上游只对**人教版 2024 审定新版**做了目录核对；用其他版本教材（沪教/苏教…）需自建对照数据。
- 契约（结构照抄上游 `docs/edition-mappings.md`）：`{"edition", "label", "status": "example|draft|reviewed", "note", "entries": [{"topicId", "grade", "term", "unit", "chapter"}]}`
- **status 含义**：`example`=格式示例（占位、不得引用）、`draft`=草稿待核、`reviewed`=已核对。
- 装载器只校验 + 暴露进索引，供将来 UI 对照教材目录；**仓库不附带任何对照数据**。

## 运行时验证

启动后 `GET /api/seed/summary` 返回各学科点数、`unaudited`/`blind_verified` 计数与教材包列表。
