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
├─ extract_grade.md               # 提取题目+作答+判分（P1-4/P1-5）
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
id: extract_grade
version: 1
description: 整页作业照片 → 结构化题目 + 学生作答 + 判分
applies_to: [doubao-seed-2-1-pro, qwen-vl-max]
---

（此处是发给模型的完整 prompt 正文……）
```

## 起步建议

`P0-1` 下一轮之前先把 `extract_grade.md` 落进本目录——**首轮实测用的 prompt 应该被版本化并纳入回归基线**。
