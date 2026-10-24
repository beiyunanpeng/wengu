# seeds · 知识点树与题库 seed 数据（家长自建，仓库不分发）

本目录存放 StudyDesk 的**外部 seed 数据**：知识点树、题库、先修边。因外部数据源 License 与隐私考虑，**这些文件不进 Git**（已在 `.gitignore`），每个家长自己按下面的方法准备。

## 主要来源：`cn-math-taxonomy`

- **上游**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **许可**：**CC BY-NC 4.0**（署名 + 非商用）
- **规模**：初中数学 315 知识点 + 初中英语 257 + 初中物理 92 · 1366 条先修边（分 hard/soft）· 题库 7431 题（初中 2803）
- **诚实标注**：上游自述"AI 生成的初稿、未经一线教师审核"；**仅初中数学做过二遍盲解**（mismatch=0），英语/物理的 `verify` 与答案**同源**、无二遍盲解 → 英语/物理**仅作参考冷启动、家长复核后再用**。
- **归属义务**：本仓库的 `THIRD-PARTY-NOTICES.md` 已显式署名；家长分发或二次开源时**必须一并保留**该文件，且**不得商用**。

## 拉取方式（家长 / 部署者）

```bash
# 1) 一次性 clone 上游到本地（不进 wengu 仓库，只作数据源）
git clone https://github.com/xiaoyang111222/cn-math-taxonomy.git ../cn-math-taxonomy-main

# 2) 用 wengu-api 的导入脚本转换 schema 到本目录
make seed-load
# 底层跑：python -m wengu-api.scripts.import_seed
#   - 读 ../cn-math-taxonomy-main/data/{topics,dependencies,questions}.json
#   - camelCase → snake_case；打 blind_verified / unaudited 标签
#   - 输出到本目录：
#     seeds/knowledge_seed.json
#     seeds/prerequisite_edges.json
#     seeds/problem_bank.json
#     seeds/_source.json          # 上游 URL + commit hash + License + 拉取时间戳
```

## 数据形态（v2.3 硬约束）

**seed 与题库以 JSON 文件形态随仓库分发、运行时按需读入内存索引，不塞进 SQLite。**
- SQLite 表只存**动态数据**（错题挂载、掌握度、复习排期）+ `external_id` 溯源；
- `import_seed` 之后不产生表数据、只更新 `seeds/` 目录里的文件 + 一份 `_source.json`；
- **题目内联 SVG 必过 HTML 净化**（AGENTS §5）再渲染，防 XSS。

## 化学、语文（上游无数据）

`cn-math-taxonomy` **不含化学、不含语文**。wengu 允许这两科的 seed **空 seed 起步**（`seeds/chemistry.json` / `seeds/chinese.json` 存在但内容为 `{"items": [], "unaudited": true}`）。

家长可**复用同款 JSON 契约**手工填**章级粗粒度 40–80 点**（`mastery_criteria` 可精简、无题、`unaudited: true`），细粒度交给"错题驱动受控生长"（§5.3）。

## 多教材版本（人教版 / 沪教 / 苏教…）

- 上游只对**人教版 2024 审定新版**做了目录核对（且部分标"待核"）；
- 本仓库提供 `seeds/mappings/<版本id>.json` 机制（结构照抄上游 `docs/edition-mappings.md`，`status: example|draft|reviewed`）；
- **家长若用其他版本教材，需自建映射数据**——现成东西为零。
