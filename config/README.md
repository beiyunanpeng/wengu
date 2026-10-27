# 运行时热配置目录

`config/app-config.json` 是**运行时参数**（模型档位、每日预算、变式开关等）的热加载文件，
优先级高于 `.env`，UI 内修改后无需重启；密钥永远只放 `.env`。

- 本文件由家长在本机生成/编辑，已在 `.gitignore` 中忽略，**不提交**。
- 默认后端读取仓库根 `config/app-config.json`；Docker 内挂载到 `/app/config/app-config.json`。
- 文件不存在 → 全部使用 `.env` 默认值（P1-0 行为）。
- 格式（P1-2 起支持的字段）：

```json
{
  "model_tier_default": "value",
  "daily_call_budget_cny": 10,
  "daily_call_limit": 200,
  "variant_on_demand": true,
  "provider_routing": {
    "extract_problem": ["doubao", "qwen_vl"],
    "dictation_extract": ["qwen_vl", "doubao"]
  },
  "task_models": {
    "extract_problem": { "qwen_vl": "qwen3.8-max" },
    "dictation_extract": { "qwen_vl": "qwen3.5-ocr" }
  },
  "model_prices": {
    "doubao-seed-2-1-lite": { "input": 0.8, "output": 2.0 },
    "qwen-vl-max": { "input": 3.0, "output": 9.0 }
  }
}
```

`provider_routing` 按任务覆盖默认路由（任务键：`extract_problem` / `grade` / `solve_explain` /
`dictation_extract` / `text`；供应商：`doubao` / `qwen_vl` / `tencent`(占位) / `mock`）。
值可以是**单个字符串**（只允许该家）或**有序列表**（P1-2b 故障转移：按顺序逐家尝试，
每家最多 1 次）。默认顺序：`extract_problem` / `grade` / `solve_explain` 为
`["doubao","qwen_vl"]`，`dictation_extract` 为 `["qwen_vl","doubao"]`，`text` 为
`["deepseek"]`。本文件按任务**整条覆盖** `.env` 的 `WENGU_PROVIDER_ROUTING`，不拼接列表；
改完下一请求即生效（单例 gateway 会刷新 runtime 与 provider 实例）。

`task_models`（P1-2c）按任务给指定 provider 换模型，值必须是**字面模型 ID**；只影响该
task+provider，不改变路由顺序。内置默认只覆盖会踩模型类型的项：
`extract_problem` / `grade` / `solve_explain` 的 `qwen_vl` 用 `WENGU_QWEN_MODEL_FLAGSHIP`
（VLM），`dictation_extract` 的 `qwen_vl` 用 `WENGU_QWEN_MODEL_VALUE`（OCR）；其余沿用
`model_tier_default`。本文件同样按 task 整条覆盖 `.env` 的 `WENGU_TASK_MODELS`；显式模型
缺失会直接报配置错误，不会静默退回别的模型。

`model_prices` 单位 = CNY / 1M tokens，用于每日成本估算闸——不填就只数调用次数、不做成本估算。

未知字段会拒绝加载（`AppConfigFile` 的 `extra="forbid"`），避免拼写错误被静默忽略。
