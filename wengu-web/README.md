# wengu-web · 前端工程

**React 19 + Vite + TypeScript + Mantine + KaTeX**——本目录是 wengu 项目的前端。

> **实现约束请严格遵守仓库根的 [`AGENTS.md`](../AGENTS.md)**：React + Mantine + KaTeX（数学渲染刚需），**不引入 Redux/Zustand 之外的重型状态库**；两角色 + 本地 PIN（不做公网账号体系）。
> **v2.5 零模型**：前端不触发任何模型调用；真实作业的批改与讲解在系统外完成。
> **v2.6 砍 PWA**（设计文档 §17-A）：无 manifest / service worker；移动端可用靠"能连到家里那台机器"（P4-1）+ 导入页投递（P1-3e），不靠离线壳。
> ~~`/settings` 向导（P5-1）~~ 仍未实现；`stores/`、`hooks/`、`router/`、`assets/` 目录**当前不存在**（旧脚手架文案，2026-11-02 按盘上事实修正）。

## 页面清单（14 页，与 `src/App.tsx` 路由一致）

| 路由 | 页面 | 说明 |
|---|---|---|
| `/import` | 导入 | inbox 路径/单批上限说明 + 家长手填最小表单（只生成草稿）；默认落地页 |
| `/intake` | 入库核对 | 题目 / 错答 / 正答回显 + 主考点 + 错因 + 细标签 → 一键确认入本（**唯一写入路径**） |
| `/mistakes` | 错题本 | 按 category / concept / 错因 / 时间筛选 + 导出打印入口 |
| `/mistakes/:id` | 错题详情 | 卷面订正回放 + 标签 + 复习状态 + 加练入口 + 作废/撤销（家长） |
| `/review` | 复习考核 | 到期三态（同类题作答·服务端判分 / 纸上自评 / 原题重做）+ 手动组卷 |
| `/practice` | 主动加练 | 按主考点固定种子抽 1–10 题，只写 `practice_records` |
| `/schedule` | 课表/日历 | 家长解锁可增删，未解锁只读；考试日放宽复习上限 |
| `/records` | 练习记录 | 考核 / 变式加练两档回看（不进错题本），加练按「这一组」分组 |
| `/dashboard` | 家长看板 | 只读确定性统计（曲线为内联 SVG，无图表库） |
| `/bank` | 题库审核 | **仅家长解锁可见**：草稿审核 + 已入库题目编辑/软作废 |
| `/local-seed` | 学科 seed | **仅家长解锁可见**：语文/化学章级点 CRUD（文件真源） |
| `/backup` | 备份 | **仅家长解锁可见**：导出一致性快照 + 列表 + 下载（恢复需停机按文档） |
| `/print/mistakes` | 打印视图 | 四区块，无导航壳（浏览器"打印→另存为 PDF"） |
| `/print/paper` | 练习卷打印 | 默认无答案；家长答案页单独分页且需解锁 |

已删除（P1-12）：`/capture`、`/grading/:id`、`/explain/:id` 及对应页面 / API 客户端。

## 目录约定（2026-11-02 按盘上实际修正）

```
wengu-web/
├─ src/
│  ├─ pages/          # 14 个页面（见上表）
│  ├─ components/     # AppLayout / MathText(KaTeX) / QuizQuestionCard / CategoryPicker /
│  │                  # QuizTopicPicker / ExplanationSlot / PomodoroTimer / ParentGate / ScheduleBrief
│  ├─ parent/         # ParentSession.tsx（两角色与解锁态）
│  ├─ api/            # client.ts / endpoints.ts / types.ts
│  ├─ lib/            # dates.ts
│  ├─ print.css       # @page A4、分组另起页、题卡不跨页
│  ├─ App.tsx / main.tsx / vite-env.d.ts
├─ index.html         # 含 viewport meta（响应式靠 Mantine 栅格，无 manifest/SW）
├─ vite.config.ts     # /api 代理到 127.0.0.1:8000
├─ Dockerfile
└─ package.json       # 零 PDF 依赖、零图表库
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
