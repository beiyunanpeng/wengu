# wengu-web · 前端工程

**React 19 + Vite + TypeScript + Mantine + KaTeX + PWA**——本目录是 wengu 项目的前端。

> **实现约束请严格遵守仓库根的 [`AGENTS.md`](../AGENTS.md)**：React + Mantine + KaTeX（数学渲染刚需），**不引入 Redux/Zustand 之外的重型状态库**；PWA 支持离线；两角色 + 本地 PIN（不做公网账号体系）。
> **v2.5 零模型**：前端不触发任何模型调用；真实作业的批改与讲解在系统外完成。

## 页面清单

| 路由 | 页面 | 说明 |
|---|---|---|
| `/import` | 导入 | inbox 路径/单批上限说明 + 家长手填最小表单（只生成草稿） |
| `/intake` | 入库核对 | 题目 / 错答 / 正答三栏回显 + 主考点 + 错因 + 细标签 → 一键确认入本 |
| `/mistakes` | 错题本 | 按 category / concept / 错因 / 时间筛选 |
| `/mistakes/:id` | 错题详情 | 卷面订正回放 + 标签 + 复习状态（只读） |
| `/review` | 复习考核 | 到期三态（同类题作答·服务端判分 / 纸上自评 / 原题重做）+ 手动组卷 |
| `/records` | 练习记录 | 同类题考核 / 变式加练两档回看（不进错题本） |

规划中（未实现）：`/` 今日队列（P2-1/2-2）、`/dashboard` 看板（P2-5）、`/parent/**`（P2-4/2-5）、`/settings` 向导（P5-1）。

已删除（P1-12）：`/capture`、`/grading/:id`、`/explain/:id` 及对应页面 / API 客户端。

## 目录约定

```
wengu-web/
├─ src/
│  ├─ pages/          # Import / Intake / Mistakes / MistakeDetail / Review / Records
│  ├─ components/     # Mantine 组件封装 + KaTeX 数学渲染组件
│  ├─ hooks/          # 数据加载与轮询等
│  ├─ api/            # 后端调用封装（endpoints.ts / types.ts）
│  ├─ stores/         # 状态（推荐 Mantine context 或 Zustand，勿引 MobX/Redux）
│  ├─ router/
│  ├─ assets/
│  ├─ App.tsx
│  └─ main.tsx
├─ public/            # PWA manifest + sw.js + 图标
├─ index.html
├─ vite.config.ts
├─ Dockerfile
└─ package.json
```

## 快速开始

```bash
# 从仓库根跑
make install-web        # npm ci
make dev-web            # http://localhost:5173（WENGU_API_PROXY 可改后端地址）
```

构建：`npm run build`（`tsc` strict + `vite build`）。

## 关键 UI 纪律

- **核对页是唯一转正入口**：缺正答、含 `〔?〕` 的草稿禁用确认并给出原因；确认值不覆盖 agent 建议。
- **题面安全**：考核卡片只消费服务端 `QuizQuestionView`，绝不展示 `answer / accept / explanation / verify`；
  内联 SVG 只渲染服务端净化后的字符串。
- **质量标签透传**：`unaudited` / `blind_verified: false` 的 seed 数据挂角标"社区数据、未审、参考用"。
- **`【依赖图形】`**：这类题不参与系统判分，到期队列降级为纸上自评。
- **纯查询页零模型调用**：错题本 / 练习记录 / 详情页只读已有数据。
- **语气**：鼓励、共情；**不上积分/徽章/连续打卡奖励**（AGENTS §6）。
