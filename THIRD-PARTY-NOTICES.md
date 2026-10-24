# Third-Party Notices

本项目代码本身遵循 `LICENSE` 中的 MIT 协议；**本文件列出所有非 MIT 的第三方数据、算法与代码归属**。任何下游分发必须一并保留此文件。

---

## 1. `cn-math-taxonomy`（知识点树 + 题库 + 先修边 seed）

- **来源**：<https://github.com/xiaoyang111222/cn-math-taxonomy>
- **许可**：**Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**
- **许可全文**：<https://creativecommons.org/licenses/by-nc/4.0/legalcode>
- **使用范围**：wengu 项目内的 `seeds/cn-math-taxonomy/` 目录（家长按需从上游拉取，本仓库不分发数据文件）
  - 初中数学 315 知识点 + 初中英语 257 + 初中物理 92
  - 数学 1366 条先修边（分 hard/soft）
  - 题库 7431 题（数学 3459 + 英语 2896 + 物理 1076；初中 2803 题）
- **归属要求**（依 CC BY-NC 4.0 §3(a)）：
  - README / CHANGELOG / 本文件 显式署名 `cn-math-taxonomy`
  - 附原项目链接
  - **不得用于商业目的**——wengu 的"每个家长自托管、家庭非商用"用法与之一致；学校 / 培训机构 / 家教商用请自行评估授权，与本仓库维护者无关。
- **诚实标注继承**（依原作者自述）：seed 数据是 **AI 生成的初稿、未经一线教师审核**。wengu 在运行时 UI 上必须显示"知识点体系（社区数据，未经教师审核）"提示，seed 包 metadata 保留 `unaudited: true`。仅初中数学做过二遍盲解（mismatch=0），可当高可信冷启动；英语 / 物理的 `verify` 与答案**同源**、无二遍盲解，作为参考冷启动、家长复核后再用。

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
  6. Provider 文件按厂商拆组织（wrong-notebook `src/lib/ai/*-provider.ts` → wengu `providers/{doubao,qwen_vl,tencent,mock}.py`）
  7. `ReviewSchedule` 行式独立表（wrong-notebook `schema.prisma`）
- 均为**模式借鉴、Python 重写**，非源码复制；即使 MIT 允许直接搬，也保持独立实现以便审查。

## 5. 内置/依赖库（自动汇总）

生产依赖的具体版本与许可证以 `wengu-api/requirements.txt` 与 `wengu-web/package.json` 为准。CI 应加 `pip-licenses` / `license-checker` 汇总，本文件人工维护顶层归属。

---

## 分发义务（给下游打包者）

- **保留本文件与 `LICENSE`**，与所有代码一起分发。
- 若打包发布 seed 数据（如 Docker 镜像内嵌 `seeds/cn-math-taxonomy/`），**镜像 README 与 About 页必须显式署名 `cn-math-taxonomy` + CC BY-NC 4.0 + 附原仓库链接**，并声明"限个人非商用"。
- 若你打算用 wengu 做**商业用途**（培训、School 部署、SaaS 托管等），请**替换或移除 `cn-math-taxonomy` seed 数据**，因为上游 CC **BY-NC** 不允许商用；wengu 代码本身（MIT）可商用。
