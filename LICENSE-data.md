# 数据许可（LICENSE-data）

> 本文件只约束 **seed 数据**，不约束代码。代码许可见 [`LICENSE`](./LICENSE)（纯 MIT 规范文本）。
> 分层授权 = 分文件表达：**MIT 代码 + CC BY-NC 数据**；因数据限非商用，**wengu 整体不称 OSI 开源软件**。
> 第三方归属总表见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)；机器可读署名见
> `seeds/data/_source.json` 与 `seeds/data/questions_source.json`（含 `commit_evidence` 取证链）。

## 1. 适用对象

`seeds/data/` 下随仓库分发的转换后数据：

- `topics.json` —— 全量知识点 **1821 点**（小学 450 + 初中 664 + 高中 707；数学 828 + 英语 724 + 物理 269）
- `dependencies.json` —— 全量先修边 **2917 条**（hard/soft；跨学段边全量保留）
- `questions.json` —— 全量题库 **7431 题**（小学 1800 + 初中 2803 + 高中 2828；数学 3459 + 英语 2896 + 物理 1076）

以及它们的署名文件 `_source.json` / `questions_source.json`。家长自建数据（`seeds/local/`、
`<data_dir>/seeds_local/`）是家长自己的内容，**不属于本文件约束的第三方数据**。

## 2. 上游与署名（依 CC BY-NC 4.0 §3(a)）

- **上游项目**：cn-math-taxonomy —— <https://github.com/xiaoyang111222/cn-math-taxonomy>
- **作者**：**Aifeng**（GitHub `xiaoyang111222`；X `@hassanyehiaa`；站点 pansgo.com）
- **许可**：Creative Commons Attribution-NonCommercial 4.0 International（**CC BY-NC 4.0**；SPDX `CC-BY-NC-4.0`）
- **许可全文**：<https://creativecommons.org/licenses/by-nc/4.0/legalcode>
- **署名方式**：依上游 README 指定的"署名并注明来源（本仓库链接）"——本文件、README、
  THIRD-PARTY-NOTICES.md 与两个 source JSON 均按此格式署名并附原仓库链接。

## 3. 所用快照与取证

- **快照 commit**：`d58785cef744341bf02d41e5568ebb953595ab18`（2026-10-23T12:40:17Z）
- **来源形态**：GitHub zip of main（解包目录**无 `.git`**），`upstream_commit` 由**内容寻址反查**钉死：
  本地 `git hash-object` 的 blob 与 GitHub contents API 在该 commit 返回的 blob 逐一相等
  （topics.json `79cd0a87…` / questions.json `76058ca5…` / dependencies.json `28cee1a8…` / README.md `cc60a25e…`），
  其父提交 `7dc3d6ad…` 的 README blob 为 `76db74d1…`（不等）→ 唯一锁定；本地 topics.json 无任何 `cnl_`（语文）
  知识点，排除全部 2026-10-24 的语文提交。完整证据串见两个 source JSON 的 `commit_evidence` 数组。
- topics 导入日 2026-10-24、questions 导入日 2026-10-29、P5-10 全量重跑 2026-11-17 均为**同一快照**，日期差只是转换脚本重跑时间。

## 4. 已修改（modified，当前事实）

- **全量收录（grade 1-16，P5-10）**：上游全库 1821 点 / 2917 边 / 7431 题全部内置，
  按学段作用域（`seed_grade_ceiling`，默认 16）呈现；初中子集（664 点 / 1018 边 / 2803 题）与扩段前逐字一致。
- **跨学段先修边全量保留**：初中→小学 74 条边装载后回溯可达小学根因点（扩段前曾按初中子集规则丢弃）。
- 字段 camelCase → snake_case 直映；按 id 前缀显式化 `subject`；打质量标签（`unaudited` / `blind_verified`，
  `blind_verified` 仅初中数学 315 点——新增学段未做二遍盲解，不伪造质量标签）。
- 题库取 `topicId ∈ 全量 1821 点` 的题；运行时只读入内存索引、不进 SQLite。

## 5. 非商用声明

**限个人非商用**（CC BY-NC 4.0 §3(a)）：署名 + 非商业使用。wengu 的定位是"每个家庭自托管、
家庭非商用"，与之一致。**学校 / 培训机构 / 家教 / SaaS 托管等商业用途不得直接使用本数据**——
请自行向上游评估授权，或替换/移除 `seeds/data/` 后再商用（代码本身 MIT 可商用）。

## 6. 免责转述（上游自述，诚实标注继承）

上游自述 seed 数据为 **"AI 生成的初稿、未经一线教师审核"**。wengu 继承该标注：
seed metadata 保留 `unaudited: true`，UI 透传"知识点体系（社区数据，未经教师审核）"提示。
**仅初中数学做过二遍盲解**（`blind_verified: true`，mismatch=0），可当高可信冷启动；
英语 / 物理与新增小学 / 高中段的 `verify` 与答案**同源**、无二遍盲解（`blind_verified: false`），
仅作参考冷启动、**家长复核后再用**（全量 7431 题已过系统自答回归与 AST 沙箱分类，
新增 4628 题中 370 题不可自动核验、mismatch 丢弃 0，分布见 `questions_source.json` 的 `counts.load_quality`）。
数据按"现状"提供，不承担任何适用性担保。

## 7. 下游分发义务

- 保留本文件、`LICENSE`、`THIRD-PARTY-NOTICES.md` 与两个 source JSON，与代码/数据一起分发。
- 镜像 / 打包 / About 页必须显式署名 `cn-math-taxonomy` + 作者 + CC BY-NC 4.0 + 原仓库链接 + "限个人非商用"。
- 换上游快照重新生成 `seeds/data/` 时，须按设计文档 §19-F-1 重新取证钉死 `upstream_commit`
  并更新 `modified` 文案；探测不到 commit 就写 null + 警告，**严禁按日期猜 SHA**。