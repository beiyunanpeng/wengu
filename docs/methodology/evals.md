# wengu · 温故 | Evals 黄金集与持续回归方法论（已退役）

> **v2.5 / P1-12 状态**：wengu 内核已转**零模型**，系统内不再有 VLM/OCR/文本模型调用，
> `evals/` 目录、`scripts/run_evals.py`、模型评测脚本与 `model_runs` 审计表均已删除。
> 本文保留为历史方法论记录；与 `AGENTS.md` 顶部 v2.5 横幅、设计文档 §16 冲突时，以后者为准。

## 为什么退役

原 evals 体系服务于"模型在环"链路（改 prompt / 换供应商 / 升 Schema 必跑）。v2.5 后：

- 真实作业的识别、批改、讲解全部在系统外完成（外部 agent + 卷面红笔），系统内没有 prompt 与供应商可回归。
- 系统内仅剩**确定性内核**：`judgeAnswer` 归一化判分、AST 白名单沙箱 `verify`、题库/组卷/复习排期。
  这些由 **pytest 单测 + 集成测试**直接守门（含 2803 题自答全对、干扰项判错、`verify` 全过沙箱、
  固定种子 `replay` 一致），不需要"准确率基线"这种统计型评测。
- 外部转录质量的前置闸门改为**数据契约 + 核对页人工确认**：缺正答、含 `〔?〕` 一律拒转正，
  由 `tests/integration/test_imports_api.py` / `test_intake_api.py` 覆盖。

## 若将来重新引入模型

（仅当明确回退零模型决策时）恢复原则：Phase 0 决定准入、evals 做持续回归；
改 prompt / 换供应商 / 升 Schema 必跑；通过判定由代码写死，AI 不许自宣通过；
样本脱敏、不落 PII。原方法论细节见 git 历史（`docs/methodology/evals.md` 的删除前版本）。
