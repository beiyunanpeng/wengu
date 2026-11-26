# 数据许可（LICENSE-data）

> 本文件只约束 **seed 数据**，不约束代码。代码许可见 [`LICENSE`](./LICENSE)（纯 MIT 规范文本）。
> 分层授权 = 分目录表达：**MIT 代码 + `seeds/data/` CC BY-NC 数据 + `seeds/vocab/` MIT 数据层**；
> 因 `seeds/data/` 限非商用，**wengu 整体不称 OSI 开源软件**，但背单词 vocab 子集不继承该非商用限制。
> 第三方归属总表见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)；机器可读署名见
> `seeds/data/_source.json`、`seeds/data/questions_source.json` 与 `seeds/vocab/_source_vocab.json`（含取证链）。

## 1. 适用对象

`seeds/data/` 下随仓库分发的转换后数据：

- `topics.json` —— 全量知识点 **3557 点**（小学 1481 + 初中 1267 + 高中 809；数学 870 + 英语 791 + 语文 683 + 物理 269 + 科学 269 + 道德与法治 269 + 化学 147 + 历史 134 + 生物 66 + 地理 59）
- `dependencies.json` —— 全量先修边 **5132 条**（hard/soft；跨学段边全量保留）
- `questions.json` —— 全量题库 **14375 题**（小学 5924 + 初中 5215 + 高中 3236；数学 3627 + 英语 3164 + 语文 2732 + 物理 1076 + 科学 1076 + 道德与法治 1076 + 化学 588 + 历史 536 + 生物 264 + 地理 236）

以及它们的署名文件 `_source.json` / `questions_source.json`。家长自建数据（`seeds/local/`、
`<data_dir>/seeds_local/`）是家长自己的内容，**不属于本文件约束的第三方数据**。
`seeds/vocab/` 是另一套许可分层，见 §8；**其 MIT 数据层不受 `seeds/data/` 的 CC BY-NC 限制**。

## 2. 上游与署名（依 CC BY-NC 4.0 §3(a)）

- **上游项目**：cn-math-taxonomy —— <https://github.com/xiaoyang111222/cn-math-taxonomy>
- **作者**：**Aifeng**（GitHub `xiaoyang111222`；X `@hassanyehiaa`；站点 math.pansgo.com）
- **许可**：Creative Commons Attribution-NonCommercial 4.0 International（**CC BY-NC 4.0**；SPDX `CC-BY-NC-4.0`）
- **许可全文**：<https://creativecommons.org/licenses/by-nc/4.0/legalcode>
- **署名方式**：依上游 README 指定的"署名并注明来源（本仓库链接）"——本文件、README、
  THIRD-PARTY-NOTICES.md 与两个 source JSON 均按此格式署名并附原仓库链接。

## 3. 所用快照与取证

- **快照 commit**：`8b57f2e353ac041f81ba705a66503c9a9e2d8ba8`（2026-11-15T11:27:27Z）
- **来源形态**：git clone（`--filter=blob:none --no-checkout`，完整历史带 `.git`、blob 按需取）
  + detached checkout 到 8b57f2e；`upstream_commit` 由 `git rev-parse HEAD` **真实探测**（不再用内容寻址反查）。
  四 blob 交叉验证（2026-11-19 复核）：本地 `git hash-object` 与 pinned commit tree blob 四段全等；
  GitHub API 实测 ref=8b57f2e——topics.json `4a5d7eb0…` / questions.json `600cae28…` / README.md `92bf7606…`
  走 contents API，dependencies.json `7aab6f22…` 走 git trees API（contents 大响应网络中断，改小响应 tree 两段查询实测），
  四段逐一 match。完整证据串见两个 source JSON 的 `commit_evidence` 数组。
- **钉死的是 8b57f2e，不是上游最新**：截至 2026-11-19，上游最新触及 `data/` 的提交已前进到
  `df0879d0fe5f5da727fe2ba0d3aba8b79b354b07`（2026-11-19T08:58:33Z），本仓库按决策仍钉 8b57f2e；
  下一轮同步是**有意批量动作（人工决定）**，`check_upstream` 报「上游有更新」是常态而非故障。
- 本次全量重跑导入日 2026-11-19（P5-16 扩科）；旧 zip 目录 `../cn-math-taxonomy-main` 保持原样
  （d58785ce 取证现场），不与本快照掺混。

## 4. 已修改（modified，当前事实）

- **全量收录（grade 1-16，P5-10 起；P5-16 扩至 10 学科）**：上游全库 3557 点 / 5132 边 / 14375 题全部内置，
  按学段作用域（`seed_grade_ceiling`，默认 16）呈现；初中子集 1267 点 / 1638 边 / 5215 题（9 学科）。
  上游持续修订内容：相对上一快照 d58785ce，7427 道共同题中 1064 道内容有变（422 道答案有变）、
  cnm_p109 点及其 4 题被上游删除——初中面**不再声称逐字不变**，差异全部来自上游演进、非本地改动。
- **跨学段先修边全量保留**：初中→小学 93 条边装载后回溯可达小学根因点（扩段前曾按初中子集规则丢弃）。
- 字段 camelCase → snake_case 直映；按 id 前缀显式化 `subject`（10 学科前缀映射见 `_source.json`）；打质量标签（`unaudited` / `blind_verified`，
  `blind_verified` 仅初中数学 315 点——新增学段未做二遍盲解，不伪造质量标签）。
- 题库取 `topicId ∈ 全量 3557 点` 的题；运行时只读入内存索引、不进 SQLite。
- 题目内联 SVG 在**构建期净化**（import 时 `sanitize_svg`），逐段 sha256 落 `figures_sha256.json`（640 段），
  装载期 hash 校验、不一致即丢弃并计数；家长补录题仍走装载期净化。

## 5. 非商用声明

**限个人非商用**（CC BY-NC 4.0 §3(a)）：署名 + 非商业使用。wengu 的定位是"每个家庭自托管、
家庭非商用"，与之一致。**学校 / 培训机构 / 家教 / SaaS 托管等商业用途不得直接使用 `seeds/data/` 本数据**——
请自行向上游评估授权，或替换/移除 `seeds/data/` 后再商用（代码与 `seeds/vocab/` 的 MIT 层可商用）。

## 6. 免责转述（上游自述，诚实标注继承）

上游自述 seed 数据为 **"AI 生成的初稿、未经一线教师审核"**。wengu 继承该标注：
seed metadata 保留 `unaudited: true`，UI 透传"知识点体系（社区数据，未经教师审核）"提示。
**仅初中数学做过二遍盲解**（`blind_verified: true`，mismatch=0），可当高可信冷启动；
其余 9 学科与新增小学 / 高中段的 `verify` 与答案**同源**、无二遍盲解（`blind_verified: false`），
仅作参考冷启动、**家长复核后再用**（全量 14375 题已过系统自答回归与 AST 沙箱分类，
1547 题不可自动核验、mismatch 丢弃 0，分布见 `questions_source.json` 的 `counts.load_quality`）。
数据按"现状"提供，不承担任何适用性担保。

## 7. 下游分发义务

- 保留本文件、`LICENSE`、`THIRD-PARTY-NOTICES.md` 与两个 source JSON，与代码/数据一起分发。
- 镜像 / 打包 / About 页必须显式署名 `cn-math-taxonomy` + 作者 + CC BY-NC 4.0 + 原仓库链接 + "限个人非商用"。
- 换上游快照重新生成 `seeds/data/` 时，须按设计文档 §19-F-1 重新取证钉死 `upstream_commit`
  并更新 `modified` 文案；探测不到 commit 就写 null + 警告，**严禁按日期猜 SHA**。

## 8. `seeds/vocab/`：MIT 数据层与课标词表

- **ECDICT**（skywind3000/ECDICT，MIT）：详情与词根含义；钉版 commit
  `39cfb9672c0906b63569e0453c2e6abfb9ab182a`。
- **engra**（bonaysoft/engra，MIT，Copyright (c) 2023 Ambor）：词根家族与中文助记；钉版 commit
  `798d54beb0deae476b856719cb8d5ad33d0baab2`。
- **vickysy/kebiao-english**（MIT，Copyright (c) 2026 木妈AIdea (vickysy)）：小学二级范围源；
  钉版 commit `470117814a09d5bdd37a95ec22acc0ee9de1e9b5`。
- **英语课程标准词表**：政府公开文件，事实性词汇集合不受著作权保护；官方 URL、PDF sha256、
  初中转录溯源、OCR 交叉验证与各源 verbatim 等级见 `seeds/vocab/_source_vocab.json`。
- **可商用边界**：上述三家 MIT 数据与课标词表**可商用**，不继承 `seeds/data/` 的 CC BY-NC 4.0 限制；
  分发时仍须保留 `THIRD-PARTY-NOTICES.md` 的署名与 MIT 许可声明。
- **质量标注**：初中正文是 `derived-from-transcription`，未做逐字比对；补充块是 `ocr` 且全部
  `unaudited: true`；ECDICT 无详情条目保持 null，不编造。构建期 OCR/PDF 工具不是运行时依赖。