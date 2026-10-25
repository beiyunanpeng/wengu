# llm_prompts · 提示词版本化真源

**所有 prompt 文本以本目录的 `.md` 文件为唯一真源**。`wengu-api` 启动时通过 `app/prompts/loader.py` 加载，代码里**不保留 prompt 正文**。

## 强制约定（AGENTS.md §4）

- **frontmatter 必带 `id` + `version`**；语义变更**必须递增版本号**（`version: 1` → `version: 2`）。
- 每次调用模型必须记录 `prompt_version` 进 `model_runs` 审计表。
- 部署在豆包/百炼侧的模板**只是本仓库文件的部署副本**——改词先改本目录文件，再同步到云侧；**不在云侧直接改措辞**。
- Prompt 修改后**必须跑 `evals/` 相关黄金集回归**，比较准确率 / 严重错误 / 延迟 / 费用，达标才升版本号。

## 命名规范

```
llm_prompts/
├─ README.md
├─ transcribe_image.md            # 整页/裁图逐字转写（P1-3b 评测）
├─ extract_problem.md             # 题目+作答结构化提取（P1-4）
├─ grade.md                       # 过程题保守初判 + 多次采样（P1-5）
├─ mistake_analysis.md            # 错因归类（P1-6）
├─ concept_reuse.md               # 细粒度 concept 受控生长（P1-6）
├─ explain_guide.md               # 三段式引导模式（P1-8）
├─ explain_full.md                # 三段式完整讲解模式（P1-8）
├─ compose_paper.md               # 检索真题组卷（P3-2）
├─ verify_question.md             # 生成题二遍核验（若未来允许生成）
└─ summarize_learner.md           # 长期画像总结（P2-5）
```

## 模板骨架

```markdown
---
id: extract_problem
version: 1
description: 单题裁图 → 题目原文 + 孩子作答 + 完整性 + 置信度
applies_to: [doubao-seed-2-1, qwen3.8-max]
---

（此处是发给模型的完整 prompt 正文……）
```

## 起步建议

新增/修改 prompt 必须同步更新对应的 fixture truth 与评测脚本，并留下实跑数字：

- 结构化提取：`venv/Scripts/python scripts/eval_extraction.py --prefer-dotenv`
  （fixtures 在 `wengu-api/tests/fixtures/extraction/`，truth 随仓库提交）
- 切题转写：`venv/Scripts/python scripts/eval_slicing.py --prefer-dotenv [--degrade]`
- 过程题初判：`venv/Scripts/python scripts/eval_grading.py --prefer-dotenv`
  （4 道合成过程题 × 3 采样；只记 JSON 合规/延迟/tokens/结论匹配，不打印题目全文）

最新实跑（2026-10-25，`grade@1`，`doubao-seed-2-1-lite-260915`）：
JSON 合规 12/12、有效结论 4/4、p50 8.3s、tokens in 5616 / out 8590。

未跑评测的 prompt 不升版本、不进默认路由。
