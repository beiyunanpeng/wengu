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
**关键：Docker 的数据目录是 `<仓库>/data/`**（compose 里 `./data:/app/data`），里面是 `wengu.db` + `inbox/` + `uploads/`。
> 注意：原生 `run-trial.ps1` 用的是 `wengu-api/data/`，和 Docker 的 `<仓库>/data/` **不是同一个目录**。若从原生迁到 Docker，把 `wengu-api/data/*` 拷进 `<仓库>/data/` 即可。

- **迁移**：停掉旧机服务 → 把旧机 `<仓库>/data/` 整个目录拷到新机 `<仓库>/data/` → 新机启动时容器会自动 `alembic upgrade head` 把库升到最新（含 0013 DROP 表）。
- **全新开始**：不拷 data，首次启动自动建空库。
- **备份（每次升级/迁移前都做）**：
```powershell
Copy-Item -Recurse .\data .\backups\pre-deploy-$(Get-Date -Format yyyyMMdd-HHmmss)
```

## 3. 启动
在 `wengu` 目录（含 `docker-compose.yml`）：
```bash
docker compose up -d --build --wait
```
- `--build` 首次或代码更新后构建镜像；`--wait` 等健康检查通过。
- **端口**：默认 API `8000`、Web `5173`。若被占用（或想沿用你之前的 8100/5000）：
```bash
WENGU_API_PORT=8100 WENGU_WEB_PORT=5000 docker compose up -d --build --wait
```
（PowerShell 写法：`$env:WENGU_API_PORT=8100; $env:WENGU_WEB_PORT=5000; docker compose up -d --build --wait`）

## 4. 访问地址
| 用途 | 地址（默认端口） | 地址（8100/5000 时） |
|---|---|---|
| Web 应用（孩子/家长用） | http://localhost:5173 | http://localhost:5000 |
| API 文档 `/docs` | http://localhost:8000/docs | http://localhost:8100/docs |
| 健康检查 | http://localhost:8000/health | http://localhost:8100/health |

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
**更新到新版**：`git pull`（或替换代码）→ 备份 `./data` → `docker compose up -d --build`（启动自动跑新迁移）。
**开机自启**：compose 里 `restart: unless-stopped`，Docker Desktop 开机启动后 wengu 会自动拉起。

## 7. 跨设备访问 & 公网安全（重要）
- **局域网内其他设备**（孩子平板/另一台电脑）访问：容器已绑 `0.0.0.0`，用部署机的局域网 IP 打开 `http://<部署机IP>:5173`（或你映射的端口）即可；注意 Windows 防火墙放行该端口。
- **公网/远程**：**默认按"本机/可信内网"设计，免登录 + 本地 PIN 不是安全边界**。要出公网**必须**先加鉴权与隔离——推荐 **Tailscale**（`docker-compose.yml` 里有可选 `tailscale` 服务块，取消注释 + 填 `TS_AUTHKEY` 即用），或反代加认证。**切勿把 5173/8000 直接暴露公网。**

## 8. 常见坑
- **端口被占**：Windows 有时保留 8000 段 → 用 `WENGU_API_PORT=8100` 覆盖。
- **数据看不到**：Docker 读写的是 `<仓库>/data/`，不是 `wengu-api/data/`；迁移/备份认准前者。
- **venv/node_modules 拷过去了**：Docker 不需要它们，且跨机不可用——用 §1 的 `git clone`/`git archive` 就不会带上。
- **改了代码没生效**：忘了 `--build`；更新镜像要 `docker compose up -d --build`。
