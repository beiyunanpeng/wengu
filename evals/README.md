# evals · AI 输出黄金集与持续回归

改 prompt / 换 provider / 升 Schema / 导入外部数据**必跑**。方法论详见 [`../docs/methodology/evals.md`](../docs/methodology/evals.md)。

## 子目录

- `import/` — 豆包 JSON / 照片识别 → 结构化题目+作答 的解析准确率
- `analysis/` — 错因归因（人工确认为金标）
- `generation/` — 组卷/变式题（约束 + 人工量表）
- `regressions/` — 历史 bug 案例（修完一个坏 case 就往这里丢一个）

## 数据 PII 保护

- **`evals/**/data/` 与 `evals/**/*.json` 全 gitignore**（家长自己的作业样本、学生作答、真值）
- **只提交**：`schema.json`（样本格式）+ `README.md`（本文件）+ 少量脱敏样例（可选）
- 家长/开发者自己维护 `data/` 目录，跑 `make eval` 时读本地数据

## 起步：第一天填 30 条

参考 `../docs/methodology/phase0.md` 的**首轮实测样本**脱敏后即为初始黄金集。**别立了结构不填**（这是外部参考项目的教训）。

## 命名规范

`<学科>-<序号>-<简述>.json`，例如：
- `import/数学-012-有理数口算-潦草.json`
- `import/语文-008-字形默写-Qwen通过.json`
- `regressions/数学-011-提取对但判分错-2026-10-21.json`

## 跑分

```bash
make eval         # 从仓库根跑，输出 baseline vs current diff
```

**通过判定由代码写死**（`run_evals.py`），**不许 AI 自宣通过**。
