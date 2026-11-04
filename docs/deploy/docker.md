# wengu · Docker 部署说明（换机器 / 长期常驻用这条）

> 面向"把 wengu 部署到另一台机器、或让它开机常驻"。开发机快速起用 `run-trial.ps1`（原生），跨机器分发用本文件的 Docker 路径。
> 对应 `docker-compose.yml` + `wengu-api/Dockerfile`（`python:3.12-slim`，启动即 `alembic upgrade head && uvicorn`）。

## 0. 需要装什么环境
- **只需装 Docker Desktop**（含 `docker compose`）。目标机**不用**装 Python、Node、也不用建 venv——依赖全在镜像里。
- 这是 Docker 相比原生跑的最大好处：跨机器零环境冲突。

## 1. 获取代码 / 打包复制过去
任选其一：

**A. 目标机能联网（最简）**——直接克隆：
```bash
git clone https://github.com/beiyunanpeng/wengu.git
cd wengu
```

**B. 离线打包**——在开发机导出"只含仓库跟踪文件"的干净包（自动排除 `venv/`、`node_modules/`、`data/`、`.env`）：
```powershell
cd D:\MyProducts\StudyDesk\wengu
git archive --format=zip -o D:\MyProducts\wengu.zip HEAD
```
把 `wengu.zip` 拷到目标机解压即可。
> ⚠️ 别用"整目录拷贝"把 `wengu-api\venv`、`wengu-web\node_modules` 带过去——它们绑机器、跨机不可用，Docker 也用不到。

## 2. 迁移数据（可选，想带着已有错题去新机才做）
**关键：Docker 的数据目录是 `<仓库>/data/`**（compose 里 `./data:/app/data`），里面是 `wengu.db` + `inbox/` + `uploads/` + **`app-config.json`（运行时配置）**。
> 注意：原生 `run-trial.ps1` 用的是 `wengu-api/data/`，和 Docker 的 `<仓库>/data/` **不是同一个目录**。若从原生迁到 Docker，把 `wengu-api/data/*` 拷进 `<仓库>/data/` 即可（含其中的 `app-config.json`）。
>
> **运行时配置随 data 卷持久化，无需为 `config/` 额外挂载**：三个运行时参数（`daily_review_limit` / `daily_recitation_limit` / `exam_day_limit_factor`）P5-1a 起以 `<data_dir>/app-config.json` 为真源，Docker 下即 `<仓库>/data/app-config.json`，改文件或调 `PUT /api/config` 立即生效、重启不丢。仓库根 `config/app-config.json` 只是原生老用户的兼容回退（只读，不进镜像）。

- **迁移**：停掉旧机服务 → 把旧机 `<仓库>/data/` 整个目录拷到新机 `<仓库>/data/` → 新机启动时容器会自动 `alembic upgrade head` 把库升到最新（含 0013 DROP 表）。
- **全新开始**：不拷 data，首次启动自动建空库。
- **备份（每次升级/迁移前都做）**：
  - 推荐：家长区解锁 →「备份」→ 立即导出（`VACUUM INTO` 一致性快照，**服务运行中可安全执行**），
    产物在 `<仓库>/data/backups/wengu-backup-<时间戳>.zip`，含 `manifest.json`（sha256/表计数）。
  - 停机整目录拷贝（不经过应用时的兜底）：
    ```powershell
    docker compose stop api
    Copy-Item -Recurse .\data .\backups\pre-deploy-$(Get-Date -Format yyyyMMdd-HHmmss)
    docker compose up -d api
    ```
  - **恢复 = 停机整库替换**，按 [`backup-restore.md`](./backup-restore.md) 操作；本系统不做运行中热恢复。

## 3. 启动
在 `wengu` 目录（含 `docker-compose.yml`）：
```bash
docker compose up -d --build --wait
```
- `--build` 首次或代码更新后构建镜像；`--wait` 等健康检查通过。
- **端口**：默认 API `8000`、Web `5173`，且**只发布到回环 `127.0.0.1`**（只有部署机自己能访问）。
  若端口被占用（或想沿用你之前的 8100/5000）：
```bash
WENGU_API_PORT=8100 WENGU_WEB_PORT=5000 docker compose up -d --build --wait
```
（PowerShell 写法：`$env:WENGU_API_PORT=8100; $env:WENGU_WEB_PORT=5000; docker compose up -d --build --wait`）
- **要让同网段设备直连**（不推荐）：显式设置绑定地址 `WENGU_BIND_ADDR=0.0.0.0`，见 §7。手机/平板远程请走 Tailscale，不要靠这一步。

## 4. 访问地址
| 用途 | 地址（默认端口） | 地址（8100/5000 时） |
|---|---|---|
| Web 应用（孩子/家长用） | http://localhost:5173 | http://localhost:5000 |
| API 文档 `/docs` | http://localhost:8000/docs | http://localhost:8100/docs |
| 健康检查 | http://localhost:8000/health | http://localhost:8100/health |

> 以上地址默认只在**部署机本机**可用（端口绑 `127.0.0.1`）。手机/平板访问见 §7。

## 5. 转录 JSON 放哪（外部 agent → 系统）
把豆包/千问办公按 `docs/templates/doubao_transcribe_v1.md` 产出的 JSON 丢进：
```
<仓库>/data/inbox/
```
容器内 watcher 每 2 秒扫一次 → 进核对队列 → 在 Web 核对页确认入本。（这是家长侧操作，wengu 自身零模型、不调任何 API。）

## 6. 日常运维
```bash
docker compose ps                 # 看两个服务健康状态
docker compose logs -f api        # 后端日志（含 alembic 迁移、inbox 导入）
docker compose logs -f web        # 前端/nginx 日志
docker compose restart api        # 只重启后端
docker compose down               # 停止（数据在 ./data，不丢）
```
**更新到新版**：`git pull`（或替换代码）→ 家长区「备份」导出（或停服拷 `./data`）→ `docker compose up -d --build`（启动自动跑新迁移）。
**开机自启**：compose 里 `restart: unless-stopped`，Docker Desktop 开机启动后 wengu 会自动拉起。

## 7. 跨设备访问 & 公网安全（重要）
- **默认只绑回环**（`WENGU_BIND_ADDR=127.0.0.1`）：`docker compose up` 后只有部署机能打开
  `http://localhost:5173`；同网段设备默认访问不到。
- **手机 / 平板 / 远程 = Tailscale（tailnet 私有网）**，完整三步见
  [`mobile-access.md`](./mobile-access.md)：
  - **Windows / macOS 试用机（默认情况）**：Docker Desktop 不支持 `/dev/net/tun`，
    在宿主机装 Tailscale 客户端并登录，然后 `tailscale serve --bg http://127.0.0.1:5173`，
    手机打开 `https://<主机名>.<tailnet>.ts.net`；**compose 不参与**。
  - **Linux / 群晖**：用 `docker-compose.yml` 注释块 A 的 sidecar（取消注释 + 宿主环境变量
    `TS_AUTHKEY`）；`deploy/tailscale/serve.json` 已按 `tailscale serve` 官方格式写好
    （`AllowFunnel=false`，只走 tailnet 不走公网 Funnel）。
  - `TS_AUTHKEY` 去 Tailscale 管理后台自建，**只放环境变量，绝不提交进仓库**。
- **确实要同网段设备直连**（不推荐）：显式 `WENGU_BIND_ADDR=0.0.0.0`，同网段任何设备都能读写
  孩子区（免登录）与家长区入口（PIN 只防误入，不是安全边界）；用完请恢复默认。
- **公网**：远程访问只认 tailnet。Cloudflare Tunnel / 公网反向代理属于公网暴露，
  **必须先做真鉴权与用户隔离，wengu 未支持**——不要把它与 Tailscale 当等价选项，
  **切勿把 5173/8000 直接暴露公网**。
- **自检**：`.\scripts\remote-check.ps1` 只读打印监听地址、`docker compose port`、
  `tailscale status` / `serve status` 与 `/health` 状态码，并给出
  「仅本机可达 / 局域网可达 / tailnet 已转发」判定。端口非默认时加
  `-WebPort` / `-ApiPort`。

## 8. 常见坑
- **端口被占**：Windows 有时保留 8000 段 → 用 `WENGU_API_PORT=8100` 覆盖。
- **同网段设备打不开**：默认只绑 `127.0.0.1`，这是预期行为；远程请走 Tailscale
  （[`mobile-access.md`](./mobile-access.md)），确需 LAN 直连才设 `WENGU_BIND_ADDR=0.0.0.0`。
- **数据看不到**：Docker 读写的是 `<仓库>/data/`，不是 `wengu-api/data/`；迁移/备份认准前者。
- **venv/node_modules 拷过去了**：Docker 不需要它们，且跨机不可用——用 §1 的 `git clone`/`git archive` 就不会带上。
- **改了代码没生效**：忘了 `--build`；更新镜像要 `docker compose up -d --build`。
