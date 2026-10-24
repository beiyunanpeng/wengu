# wengu-web · 前端工程

**React 19 + Vite + TypeScript + Mantine + KaTeX + PWA**——本目录是 wengu 项目的前端。

> **实现约束请严格遵守仓库根的 [`AGENTS.md`](../AGENTS.md)**：React + Mantine + KaTeX（数学渲染刚需），**不引入 Redux/Zustand 之外的重型状态库**；PWA 支持离线；两角色 + 本地 PIN（不做公网账号体系）。

## 页面清单（对应 TICKETS.md）

| 路由 | 页面 | 归属工单 |
|---|---|---|
| `/` | 打开即弹**今日队列**（PWA） | P2-1 / P2-2 |
| `/capture` | 采集上传（手机/PC 浏览器 + 快捷方式说明） | P1-3 |
| `/grading/:id` | 批改结果 + **回显识别到的题目+作答** + 一键确认/纠错 + 申诉 | P1-5 / P1-9 |
| `/mistakes` | 错题本（按 category/concept/错因/时间筛选） | P1-6 / P1-9 |
| `/review/:id` | 复习页（重做原题 → 变式异步） | P1-7 / P1-9 |
| `/explain/:id` | 三段式讲解（引导阶梯 / 完整讲解 / 要答案留痕） | P1-8 |
| `/practice` | `practice_records` 派生表回看（v2.4） | P1-6 |
| `/dashboard` | 孩子**自己**的复盘看板（观察复盘型） | P2-5 |
| `/parent/**` | 家长视图（PIN 解锁：看板/长期目标/组卷/审核题库/备份） | P2-4 / P2-5 |
| `/settings` | 首次运行向导 + 热配置（`app-config.json` 优先 .env） | P5-1 |

## 目录约定

```
wengu-web/
├─ src/
│  ├─ pages/          # 上述路由对应页面
│  ├─ components/     # Mantine 组件封装 + KaTeX 数学渲染组件
│  ├─ hooks/          # useCapture / useGradeConfirm / usePwaPush 等
│  ├─ api/            # 后端调用封装
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
cd wengu-web
cp ../wengu-api/.env.example ../wengu-api/.env   # 后端先备好
make install-web                                  # 从仓库根跑
make dev-web                                      # http://localhost:5173
```

## 关键 UI 纪律

- **回显总闸**：批改结果页必须**并排展示"系统识别到的题目 + 孩子的作答"**（AGENTS §5）；识别错孩子一眼看出来。
- **`〔?〕` 占位高亮**：模型不确定的字段用占位，UI 标"待人工"色块。
- **`【依赖图形】`**：这类题**不参与自动判分/复习**，只展示归因统计，UI 上明说。
- **`unaudited` / `blind_verified: false`** 的 seed 数据（英语/物理）：知识点树上挂角标提示"社区数据、未审、参考用"。
- **纯查询页绝不触发模型调用**：Dashboard / 错题本列表页 = 只读已有数据 + 任务状态。
- **语气**：三段式讲解的引导文案温暖、鼓励，答错共情；**不上积分/徽章/连续打卡奖励**（AGENTS §6）。

## 第一张工单

**P1-0 Repo 骨架**：起一个能编译、能路由、能显示 `Hello wengu` 的空壳 + KaTeX 集成，能进 CI 冒烟即可。**不要提前堆业务页面**。
