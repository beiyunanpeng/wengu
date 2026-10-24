# wengu · 温故 | Evals 黄金集与持续回归方法论

> Phase 0 是**一次性摸底**（决定哪些题型准入），evals 是**持续回归防退化**（改 prompt / 换供应商 / 升 Schema / 导入外部数据必跑）。二者互补，不能互相替代。

## 与 Phase 0 的关系

|  | Phase 0 | Evals |
|---|---|---|
| 目的 | 决定哪些题型能"自动入库" | 保证改动后**旧能力不退化** |
| 频率 | 一次性（数据扩样后可能重跑） | 每次改 prompt / 换供应商 / 升 Schema 必跑 |
| 判据 | 分档阈值（0.95/0.95/0.90/0.05） | 相对基线的准确率、严重错误、延迟、费用变化 |
| 通过判定 | 家长审 | **代码判定，不许 AI 自宣通过** |

**关键设计**：Phase 0 的实测样本脱敏后就是**初始黄金集**——第一天就该填 ≥30 条，不要立了结构没人填。

## 目录结构（`evals/`）

```
evals/
├─ import/          # 豆包 JSON / 照片识别 → 结构化题目+作答 的解析准确率
│  ├─ data/         # 数据文件 gitignore（PII）；schema.json 与 README.md 保留
│  └─ schema.json
├─ analysis/        # 错因归因（人工确认为金标）
├─ generation/      # 组卷/变式题（约束 + 人工量表）
└─ regressions/     # 历史 bug 案例（每次修完一个坏 case 就往这里丢一个）
```

## 命名规范

- 数据文件：`<学科>-<序号>-<简述>.json`，如 `数学-012-有理数口算-潦草.json`
- 每份样本必带元数据：`{ sample_id, subject, qtype, is_objective, source_date, provider_snapshot, prompt_version_snapshot, truth: {...} }`
- **PII 保护**：真值不写学生姓名、学校、班级；只写题目文本 + 学生答案文本 + 对错 + 错因分类

## 样本 schema（示例，`import/schema.json`）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "wengu evals import sample",
  "type": "object",
  "required": ["sample_id", "subject", "qtype", "is_objective", "truth"],
  "properties": {
    "sample_id": { "type": "string" },
    "subject": { "enum": ["数学", "物理", "化学", "英语", "语文"] },
    "qtype": { "type": "string" },
    "is_objective": { "type": "integer", "enum": [0, 1] },
    "legibility": { "enum": ["清晰", "一般", "潦草", "涂改", "混排", "反光"] },
    "truth": {
      "type": "object",
      "required": ["question", "student_answer", "correct"],
      "properties": {
        "question": { "type": "string" },
        "reference_answer": { "type": "string" },
        "student_answer": { "type": "string" },
        "correct": { "type": "boolean" },
        "root_cause": { "type": "string" }
      }
    },
    "expected_behavior": {
      "type": "object",
      "description": "如果 is_objective=0 或 legibility=潦草，模型应该给〔?〕占位并转人工；不是让它硬猜",
      "properties": {
        "should_placehold": { "type": "boolean" },
        "should_route_to_human": { "type": "boolean" }
      }
    }
  }
}
```

## 跑分脚本约定（`wengu-api/scripts/run_evals.py`）

- **每次运行必记**：provider / model / prompt_version / 每题结果 / 汇总指标 / 时间戳，写入 `model_runs` 审计表（不落 PII、不落题目全文）
- **通过判定由代码写死**（如 `pass_if = acc >= baseline_acc - 0.02 and severe_err_delta <= 0`），**AI 不许自宣通过**
- 输出：
  - 汇总表：`{accuracy, severe_error_count, latency_p50, latency_p95, cost_cny}` × `baseline vs current`
  - diff 报告：哪些样本变差、哪些变好、哪些是新失败案例（应打包塞进 `evals/regressions/`）
- CI 里加：改 prompt / 换 provider 的 PR 必须附最新 evals diff

## 与其他文档的关系

- 触发条件与阈值见 `docs/methodology/phase0.md`；
- 落到工程：设计文档 §5.2 批改分级闸、§5.4 复习调度；工单 `P0-2 evals 黄金集脚手架`、`P1-2 Provider 适配层` DoD 里的"跑 evals 回归"。
