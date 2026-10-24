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
    "dictation_extract": "qwen_vl"
  },
  "model_prices": {
    "doubao-seed-2-1-lite": { "input": 0.8, "output": 2.0 },
    "qwen-vl-max": { "input": 3.0, "output": 9.0 }
  }
}
```

`provider_routing` 按任务覆盖默认路由（任务键：`extract_problem` / `grade` / `solve_explain` /
`dictation_extract` / `text`；供应商：`doubao` / `qwen_vl` / `tencent`(占位) / `mock`）；
`model_prices` 单位 = CNY / 1M tokens，用于每日成本估算闸——不填就只数调用次数、不做成本估算。

未知字段会拒绝加载（`AppConfigFile` 的 `extra="forbid"`），避免拼写错误被静默忽略。
