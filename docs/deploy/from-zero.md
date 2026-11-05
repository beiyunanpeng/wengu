# 从 0 部署到手机能用（Windows 家庭机实操顺序）

> 这是一份**按顺序执行的 runbook**，不重复细节：每步都指向已有文档。
> 目标只有一件事——把 wengu 跑起来，并让手机/平板在**家里网络之外**也能连上它。
> 适用：Windows 11 + PowerShell 5.1（PS 5.1 **不认 `&&`**，多条命令请分行或用 `;`）。

---

## 第 0 步：先选形态（只选一次）

| 形态 | 什么时候选 | 数据目录 | 前端怎么起 |
|---|---|---|---|
| **A. Docker Compose**（推荐，跨机部署就靠它） | 目标机装了 Docker Desktop；想让"git pull + up"就升级 | **`<仓库>\data\`** | nginx 容器，浏览器开 `http://localhost:5173` |
| **B. 原生 `run-trial.ps1`**（不想装 Docker） | 只在这台机器试用 | **`<仓库>\wengu-api\data\`** | Vite dev server，`http://localhost:5173` |

> ⚠️ **A 和 B 的数据目录不是同一个**，两边各有一份独立的 `wengu.db`。混用会出现"我明明录过错题，
> 换种方式启动就没了"的假象——不是丢数据，是开到了另一份库。选定后别再切；真要切就按
> [`docker.md`](./docker.md) §2 把整个 data 目录拷过去。

---

## 第 1 步：装前置（只检查，不装就报错难看）

```powershell
git --version
docker --version          # 形态 A 需要；Docker Desktop 装了但 daemon 没起会报 npipe 连接失败
python --version          # 需要 ≥ 3.11（形态 B 需要）
node --version            # 需要 ≥ 18（形态 B 需要）
npm --version
```

Windows 特有：`8000` 端口有时被系统保留（Hyper-V 动态端口段）。先查：

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

若 8000 落在保留段，后面所有命令把 `8000` 换成 `8100`（形态 A 用环境变量
`WENGU_API_PORT=8100`，形态 B 需改 `run-trial.ps1` 里的 `$apiPort`）。

---

## 第 2 步：取代码

```powershell
git clone https://github.com/beiyunanpeng/wengu.git
cd wengu
git checkout v0.5.0       # 或跟 main（含 P4-1/1b/1c/P0-5，默认只绑回环 + 命令行备份）
```

> 部署**只用已合并的 main 或版本标签**，绝不用开发分支或 PR 的提交——那会造出"功能莫名丢失"的假象。
> 当前 `v0.5.0` 之后有 4 张票（默认只绑回环、命令行备份入口等）尚未进标签，见文末"标签现状"。

---

## 第 3 步：起服务

### 形态 A：Docker

```powershell
docker compose up -d --build --wait
docker compose ps                    # api 与 web 都应是 healthy
curl.exe http://127.0.0.1:5173/health # 期望 {"status":"ok"...}（nginx 把 /health 代理到 api）
```

容器入口命令是 `alembic upgrade head && uvicorn …`，**启动即自动迁移**、无需手工建库。
详细参数与常见坑见 [`docker.md`](./docker.md)。

### 形态 B：原生

```powershell
cd wengu-api
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
cd ..
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # 仅当前窗口，关掉即失效
.\run-trial.ps1
```

`run-trial.ps1` 会自己 `alembic upgrade head`，然后开两个新窗口：后端 `127.0.0.1:8000`、
前端 `localhost:5173`（Vite 把 `/api` 代理到后端）。停止：`.\run-trial.ps1 -Stop`。

### 两种形态共用的首启检查

浏览器打开 `http://localhost:5173`：

1. 顶部应出现**首次运行横幅**并引导进 `/setup`（P5-1b）——向导只做三件事：展示 seed 覆盖、
   设运行上限、标记完成。**不采集年级、不勾学科**（这是有意设计，见 AGENTS §7）。
2. 知识点树应自动装载（启动时幂等 `load_seed`；JSON 缺失则空 seed 起步并在日志里报
   "seed 装载失败"）。**不需要**手工跑 `make seed-load`——那是开发者重新生成 `seeds/data/` 的动作。
3. 右上角进**家长区**，首次会让你设置 PIN（4–8 位数字或 6–20 位字符）。
   PIN 只防误入、**不是安全边界**；孩子区全程免登录。

---

## 第 4 步：先做一次备份，再动任何东西

**形态 B（原生，有宿主机 venv）**：

```powershell
cd wengu-api
.\venv\Scripts\python.exe -m scripts.backup_cli --dry-run                       # 先看会备份哪份库
.\venv\Scripts\python.exe -m scripts.backup_cli
```

**形态 A（Docker）——今天有两条限制，先看清**：

1. api 镜像只 `COPY app / alembic.ini / migrations`，**没有 `scripts/`**，所以
   `docker compose exec api python -m scripts.backup_cli` 现在**用不了**（已登记为 **P4-1d**）。
2. 因此纯 Docker 家庭的日常备份入口是**家长区「备份」页 → 立即导出**（服务在跑时可用）。

如果你想在 Docker 形态下用命令行（本机有 venv 就行），**先停 api 再导出**最稳
——跨 Windows/Docker VM 的文件锁不适合和写入并发，而"服务停着也能备份"正是这个入口的设计初衷：

```powershell
docker compose stop api
cd wengu-api
.\venv\Scripts\python.exe -m scripts.backup_cli --data-dir ..\data --dry-run
.\venv\Scripts\python.exe -m scripts.backup_cli --data-dir ..\data
cd ..
docker compose start api
```

`--dry-run` 会打印**数据目录 / 实际 db 路径 / 现有备份份数 / alembic 版本 / 错题计数**。
先核对这份 db 是不是你刚录入错题的那一份，再做真实导出。产物落
`<data_dir>\backups\wengu-backup-<时间戳>.zip`，保留最近 10 份；命令行与 UI 两条入口
**同一实现、同一目录、同一轮转**。恢复是停机整库替换，见 [`backup-restore.md`](./backup-restore.md)。

---

## 第 5 步：手机/平板连回家（Tailscale，唯一被支持的远程方式）

完整说明在 [`mobile-access.md`](./mobile-access.md)，这里是执行顺序与判据：

```powershell
# 1) 部署机：确认默认只绑回环（P4-1 之后是默认值）
.\scripts\remote-check.ps1
#    期望判定：「仅本机可达」
#    如果这里显示「局域网可达」，说明有人设过 WENGU_BIND_ADDR=0.0.0.0，先确认是不是你要的

# 2) 部署机：装 Tailscale 客户端（Microsoft Store 搜 Tailscale，或 https://tailscale.com/download 下载 MSI），登录你的 tailnet

# 3) 配转发（裸端口形式，已按 tailscale serve --help 核实）
tailscale serve --bg 5173
tailscale serve status
```

> **语法核实记录（2026-11-05，Windows 11 真机 `tailscale serve --help`）**：`<target>` 接受裸端口
> （`3000`）、部分 URL（`localhost:3000`）或完整 URL（`http://localhost:3000/foo`），官方示例就是
> `tailscale serve --bg 3000`；子命令 `status` / `reset` / `clear` / `get-config` / `set-config` 都在。
> **`--bg` 不能省**——help 里 `--bg` 默认 false，不带它 serve 会在前台占住终端窗口。
> 跑通后 `serve status` 应显示 `https://<主机名>.<你的 tailnet>.ts.net` 转发到本机端口；
> 关闭用 `tailscale serve reset`。
>
> 仍未验证的只剩一件事：**手机/平板真机打开那个 https 地址**。这一步只能你自己在设备上做。

```powershell
# 4) 再跑一次自检，确认 tailnet 那一路被识别
.\scripts\remote-check.ps1
#    期望判定：「tailnet 已转发」（且本机仍只绑回环）
```

**手机侧**：装 Tailscale（iOS App Store / Android Play 或官网 APK），用**同一账号**登录，
不需要装 Docker、不需要端口转发、不需要改路由器。然后在手机浏览器打开第 3 步得到的
`https://….ts.net` 地址。

### 连不上时怎么二分定位

| 现象 | 先查什么 |
|---|---|
| `tailscale serve status` 里没有 https 条目 | 第 3 步语法不对，回到 `--help`；或 serve 没在部署机上跑（装在手机上了） |
| 手机 Tailscale 里看不到部署机 | 两边不在同一 tailnet；或部署机客户端没登录/被退出 |
| 有 https 条目但手机打开是空白/报错 | 手机浏览器直接访问 `https://<主机名>.<tailnet>.ts.net/health`，看后端是否通；不通说明 serve 转发的端口不对（形态 A 转 5173，形态 B 也是 5173） |
| 手机打开报证书/混合内容错误 | 确认走的是 `https://` 而不是 `http://`；tailnet 域名带真 TLS，不该出现此错 |
| 想先证明"应用本身能被外部访问"，排除 Tailscale 因素 | 临时 `$env:WENGU_BIND_ADDR="0.0.0.0"; docker compose up -d`，手机在同一 Wi-Fi 下访问 `http://<部署机局域网 IP>:5173`。**这一步会把免登录的孩子区开放给同网段所有设备，验完立刻清掉环境变量恢复默认**。它只是诊断手段，不是远程方案。 |

---

## 第 6 步：录入第一条数据，把闭环走一遍

1. 用外部 agent（千问办公 / 豆包）把**卷子上已订正的错题**按 `docs/templates/` 的模板转录成 JSON；
2. 丢进监听目录：形态 A 是 `<仓库>\data\inbox\`，形态 B 是 `<仓库>\wengu-api\data\inbox\`；
   或在手机上直接用 `/import` 页**粘贴整段 JSON**（P1-3e，专为手机准备）；
3. 打开**核对页**确认入本——这是错题本**唯一写入路径**，不确认不进本；
4. 到复习页看到期队列，做一次同类题考核（判分在服务端，答案不会下发到浏览器）；
5. 家长区看板复盘。

---

## 标签现状与升级

- `v0.5.0` 指向 `6cac3ab`；它之后已合并 **P4-1（默认只绑回环 + Tailscale 可达性）→ P4-1b（部署面命令体检）
  → P4-1c（命令行备份入口）→ P0-5（Windows 本地噪音）** 四张票，其中两条是**行为变更**。
- 也就是说：**跟 `v0.5.0` 部署的机器拿不到"命令行备份"和"默认只绑回环"**，而本清单第 4、5 步依赖它们。
  所以：**现在请跟 `main`**（`git checkout main && git pull`），等 `v0.6.0` 打出来再锁标签。
- 以后每次升级前先跑第 4 步备份；`v0.5.0` 那次含 `0019` DROP 表迁移，说明见
  [`upgrade-v0.5.0.md`](./upgrade-v0.5.0.md)。

## 红线（别为了"方便手机连"踩掉）

- **不做公网暴露**：Cloudflare Tunnel / 端口映射 / 直接开 8000·5173 到公网都不行——
  孩子区免登录，公网等于裸奔。远程只认 tailnet（AGENTS §2.4）。
- **模型密钥只走 `.env`**；本体内核零模型，通常不需要任何 Key。
- **日志与备份产物都不进仓库**：`data/`、`backups/`、`tailscale-state/` 已 gitignore；
  备份 zip 含全部错题与照片，别拷进工作目录、别放公开网盘链接。
