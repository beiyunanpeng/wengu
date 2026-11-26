# Third-Party Notices

本项目代码本身遵循 `LICENSE` 中的 MIT 协议；**本文件列出所有第三方数据、算法与代码归属（含 MIT 与 CC BY-NC 数据）**。任何下游分发必须一并保留此文件。

---

## 1. `cn-math-taxonomy`（知识点树 + 题库 + 先修边 seed）

- **来源**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **作者**：**Aifeng**（GitHub `xiaoyang111222`；X `@hassanyehiaa`；站点 math.pansgo.com）。上游 README 指定的署名方式 =「署名并注明来源（本仓库链接）」，本文件与 README / CHANGELOG 的署名即按此格式。
- **许可**：**Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**（SPDX `CC-BY-NC-4.0`）；数据许可分层全文与下游义务见仓库根 [`LICENSE-data.md`](./LICENSE-data.md)（代码 MIT 见 [`LICENSE`](./LICENSE)，整体不称 OSI 开源软件）
- **许可全文**：<https://creativecommons.org/licenses/by-nc/4.0/legalcode>
- **所用快照 commit**：`8b57f2e353ac041f81ba705a66503c9a9e2d8ba8`（2026-11-15T11:27:27Z）。来源为 git clone（`--filter=blob:none --no-checkout`）+ detached checkout，commit 由 `git rev-parse HEAD` 真实探测，四 blob 与 GitHub API（contents/trees）交叉验证，取证证据见 `seeds/data/_source.json` 与 `questions_source.json` 的 `commit_evidence`（方法：设计文档 §19-F-1）。**钉死的是 8b57f2e 而非上游最新**（2026-11-19 上游触及 data/ 的最新提交已前进到 df0879d0…），下一轮同步是有意批量动作（人工决定）。
- **使用范围**：wengu 项目内的 `seeds/data/` 目录（由 `wengu-api/scripts/import_seed.py` 与 `import_questions.py` 从上游转换的**全量数据**（P5-10 起小学+初中+高中，P5-16 起 10 学科），随本仓库分发；内嵌 `_source.json` / `questions_source.json` 署名）
  - 全量 3557 知识点（小学 1481 + 初中 1267 + 高中 809；数学 870 + 英语 791 + 语文 683 + 物理 269 + 科学 269 + 道德与法治 269 + 化学 147 + 历史 134 + 生物 66 + 地理 59）
  - 全量 5132 条先修边（分 hard/soft；跨学段边全量保留，初中→小学 93 条回溯可达）
  - 全量题库 14375 题（小学 5924 + 初中 5215 + 高中 3236；数学 3627 + 英语 3164 + 语文 2732 + 物理 1076 + 科学 1076 + 道德与法治 1076 + 化学 588 + 历史 536 + 生物 264 + 地理 236），运行时只读入内存索引、不进 SQLite
- **归属要求**（依 CC BY-NC 4.0 §3(a)）：
  - README / CHANGELOG / 本文件 显式署名 `cn-math-taxonomy`
  - 附原项目链接
  - **不得用于商业目的**——wengu 的"每个家长自托管、家庭非商用"用法与之一致；学校 / 培训机构 / 家教商用请自行评估授权，与本仓库维护者无关。
- **诚实标注继承**（依原作者自述）：seed 数据是 **AI 生成的初稿、未经一线教师审核**。wengu 在运行时 UI 上必须显示"知识点体系（社区数据，未经教师审核）"提示，seed 包 metadata 保留 `unaudited: true`。仅初中数学做过二遍盲解（mismatch=0），可当高可信冷启动；其余 9 学科与新增小学 / 高中段的 `verify` 与答案**同源**、无二遍盲解，作为参考冷启动、家长复核后再用。上游持续修订题目内容（相对 d58785ce：1064 道共同题内容有变、422 道答案有变），差异来自上游演进、非本地改动。

## 2. `Marble os-taxonomy`（数据格式灵感）

- **来源**：<https://github.com/withmarbleapp/os-taxonomy>
- **许可**：见上游
- **使用范围**：wengu 只参考其数据格式（topics + dependencies），不使用其代码。

## 3. `MistakeNotebook` / `LearnDesk`（架构与工程模式参考）

- **来源**：见 `LearnDesk-原始方案/01-参考项目/MistakeNotebook/`（本仓库不分发）
- **使用范围**：wengu 只**借鉴其工程模式**（`learning_events` 事件溯源、`ai_jobs` 幂等、prompt 版本化、豆包 JSON 导入兜底、【依赖图形】题不判分、建议值/确认值分离、evals 黄金集），**不 fork 也不复制代码**。语言栈选 Python 而非 TypeScript 是明确决定。

## 4. `KuroTutor` / `wrong-notebook`（外部对照与实现细节借鉴）

- **来源**：<https://github.com/ZYT64/kurotutor> / <https://github.com/wttwins/wrong-notebook>
- **许可**：MIT
- **使用范围**：wengu v2.4 明确吸收以下 7 项借鉴：
  1. 复习掌握度自适应间隔因子公式（Kuro `services/review.py`）
  2. OCR 行聚类切题预处理思路（Kuro `services/layout.py`）
  3. `practice_records` 派生表分离（Kuro quiz / wrong-notebook `PracticeRecord`）
  4. AESGCM + scrypt + 每日独立 git commit + `git checkout` 回滚的备份模式（Kuro `services/cloud_backup.py`）
  5. `config/app-config.json` 热配置覆盖 .env（wrong-notebook）
  6. Provider 文件按厂商拆组织（wrong-notebook `src/lib/ai/*-provider.ts`）——**v2.5/P1-12 已随零模型决策退役**，仅作历史借鉴记录
  7. `ReviewSchedule` 行式独立表（wrong-notebook `schema.prisma`）
- 均为**模式借鉴、Python 重写**，非源码复制；即使 MIT 允许直接搬，也保持独立实现以便审查。

## 5. `skywind3000/ECDICT`（背单词详情与词根含义）

- **来源**：<https://github.com/skywind3000/ECDICT>
- **许可**：**MIT**（可商用；使用时保留上游版权与许可声明）
- **所用快照 commit**：`39cfb9672c0906b63569e0453c2e6abfb9ab182a`
- **使用范围**：`seeds/vocab/words.json` 的音标、释义、词性、变形、词频与考试徽章，以及
  `seeds/vocab/wordroot_meaning.json`。只 vendored 派生 JSON；`ecdict.csv` / `wordroot.txt` 本体不进仓库。
- **构建期处理**：详情 join 走“整串精确 → 拆等价子形逐形精确”，不做模糊匹配；无详情字段留 `null`。
  文件字节数、sha256、commit 与集合判据见 `seeds/vocab/_source_vocab.json`。

## 6. `bonaysoft/engra`（词根家族与中文助记）

- **来源**：<https://github.com/bonaysoft/engra>
- **作者 / 版权**：**Ambor，Copyright (c) 2023 Ambor**
- **许可**：**MIT**（可商用；使用时保留上游版权与许可声明）
- **所用快照 commit**：`798d54beb0deae476b856719cb8d5ad33d0baab2`
- **使用范围**：`seeds/vocab/roots.json`，只展平 `dict/roots/*.yml` 的家族树、词节点与中文助记；
  `dict/glossaries/*.json` 的 14 档 CEFR/CET/考研/托福/GRE 词表**不对口 K-12，不作范围源**。
- **Windows 兼容取证**：`dict/roots/con.yml` 是 Windows 保留名，构建脚本用
  `git ls-tree` + `git cat-file --batch` 读取全部 blob，不 checkout、不 archive。
- **质量边界**：本票只保证快照清单 sha256 与条数一致，不保证家族到单词的映射质量；该质量归 P6-3 与试用反馈。

## 7. `vickysy/kebiao-english`（小学二级词表）

- **来源**：<https://github.com/vickysy/kebiao-english>
- **作者 / 版权**：**木妈AIdea (vickysy)，Copyright (c) 2026**
- **许可**：**MIT**（可商用；使用时保留上游版权与许可声明）
- **所用快照 commit**：`470117814a09d5bdd37a95ec22acc0ee9de1e9b5`（branch `main`）
- **使用范围**：`seeds/vocab/_upstream/vocab-level2.json` 原字节 vendored，作为小学二级范围源；
  整仓不进仓库。上游 `note` 自述官方 505 词、转录标记 503、人工校对恢复实收 501；
  **只有 `count` 与 `words` 实收数参与相等断言**，505 / 503 仅作来源声明。
- **补充块不换源**：初中附录3补充块与 vickysy 单独列出段重叠 143/150，但 CPC / PLA / PRC /
  UN / UNESCO / WTO 六条组织词缺失，故补充块维持课标 PDF OCR + `unaudited: true`。

## 8. 英语课程标准词表（小学 / 初中 / 高中范围）

- **官方来源**：
  - 义务教育英语课程标准（2022年版）：<http://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582349487953.pdf>
  - 普通高中英语课程标准（2017年版2020年修订）：<https://www.pep.com.cn/xw/zt/rjwy/gzkb2020/202205/P020220517522153664167.pdf>
- **许可说明**：政府公开文件；词表本身作为事实性词汇集合不受著作权保护。派生 JSON 与构建脚本沿用仓库代码 MIT；
  **`seeds/vocab/` 不继承 `seeds/data/` 的 CC BY-NC 4.0 非商用限制**。
- **来源等级**：
  - 小学二级 = vickysy 官方仓库快照（`official-repo`，MIT）；
  - 初中三级正文 = 第三方转录的结构化产物（`derived-from-transcription`），未与官方扫描 PDF 逐字比对；
  - 初中附录3补充块 = 官方扫描 PDF OCR（`ocr`），全部 `unaudited: true`；
  - 高中 = 官方 PDF 文字层逐字抽取（`official-pdf-verbatim`），保留多词短语。
- **不入库材料**：两份官方 PDF、初中转录缓存件、OCR 交叉验证件均不进 git；只在
  `seeds/vocab/_source_vocab.json` 记 URL、字节数与 sha256。转录缓存件夹带无关第三方网页正文，故不 vendored。
- **诚实边界**：义务教育 PDF 的 201 页文字层全部为 0 字符，初中正文不能在本票升级为 verbatim；
  要升级只能重做 OCR 并人工复核。补充块 OCR 偶发错字，保持 unaudited。

## 9. 内置/依赖库（自动汇总）

生产依赖的具体版本与许可证以 `wengu-api/requirements.txt` 与 `wengu-web/package.json` 为准。CI 应加 `pip-licenses` / `license-checker` 汇总，本文件人工维护顶层归属。

### 9.1 OCR 运行时（已退役）

P1-3b 曾在本地 CPU 运行 RapidOCR（`rapidocr-onnxruntime` / `onnxruntime` / `opencv-python-headless` /
`Pillow` / `numpy` 等）做切片预处理。**v2.5 / P1-12 起系统内视觉栈整体删除**，上述依赖已从
`wengu-api/requirements.txt` 与镜像中移除，不再随本仓库分发；此处仅保留历史归属记录。

---

## 分发义务（给下游打包者）

- **保留本文件与 `LICENSE`、`LICENSE-data.md`**，与所有代码一起分发；涉及学生数据的部署另须保留 `PRIVACY.md` 与 `transcribe/README.md` §0 合规 checklist。
- 若打包发布 `seeds/data/`（如 Docker 镜像内嵌 `seeds/cn-math-taxonomy/`），**镜像 README 与 About 页必须显式署名 `cn-math-taxonomy` + CC BY-NC 4.0 + 附原仓库链接**，并声明"限个人非商用"。
- 若打包发布 `seeds/vocab/`，须保留 ECDICT / engra / vickysy 三家 MIT 署名与许可声明；课标词表按第 8 节标注来源等级。`seeds/vocab/` 本身不继承 CC BY-NC 限制。
- 若你打算用 wengu 做**商业用途**（培训、School 部署、SaaS 托管等），请**替换或移除 `seeds/data/` 的 `cn-math-taxonomy` seed 数据**，因为上游 CC **BY-NC** 不允许商用；wengu 代码与 `seeds/vocab/` 的 MIT 数据层可商用。
