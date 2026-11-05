# 手机 / 平板怎么连回家里那台机器

> **远程访问只认 Tailscale（tailnet 私有网）。** Cloudflare Tunnel / 公网反向代理属于公网暴露，
> 必须先做真鉴权与用户隔离，wengu 未支持——两者不是等价选项。
>
> 本机默认**只绑回环**（Docker 的 `WENGU_BIND_ADDR` 与 Vite 的 `server.host` 都默认 `127.0.0.1`），
> 所以"手机直接打不开"是默认状态，不是故障；按下面三步走 tailnet 即可。

## 1. 手机/平板：装 Tailscale 客户端，登录同一个 tailnet

- iPhone/iPad：App Store 搜 **Tailscale**；Android：Google Play / F-Droid，或官网
  <https://tailscale.com/download> 下载 APK。
- 用**与家里那台机器相同的 Tailscale 账号**登录（即同一个 tailnet）。个人免费版够用。
- 连接后客户端的设备列表里应能看到家里那台机器的名字（下面以 `wengu-at-home` 为例）。
- 手机/平板**不需要**装 Docker、不需要改路由器、不需要端口转发。

## 2. 家里那台机器：确认默认绑定，并按平台做转发

先确认服务只绑回环（默认就是）：

```powershell
docker compose ps
docker compose port web 80      # 期望 127.0.0.1:5173（或你的 WENGU_WEB_PORT）
docker compose port api 8000    # 期望 127.0.0.1:8000（或你的 WENGU_API_PORT）
```

### Windows 11 + Docker Desktop（试用机默认，推荐这条）

Docker Desktop **不支持** `/dev/net/tun`，所以不要在 compose 里启用 tailscale sidecar。
改为在**宿主机**安装 Tailscale 客户端并登录同一 tailnet，然后：

```powershell
tailscale serve --bg 5173
tailscale serve status
```

`serve status` 会显示 `https://<主机名>.<你的 tailnet>.ts.net` 已转发到
`http://127.0.0.1:5173`。手机浏览器打开这个 https 地址即可；端口不是 5173 时换成你的
`WENGU_WEB_PORT`。关闭转发：`tailscale serve reset`。

> **语法已按 `tailscale serve --help` 核实**（2026-11-05，Windows 11 真机）：`<target>` 接受
> 裸端口（`3000`）、部分 URL（`localhost:3000`）或完整 URL（`http://localhost:3000/foo`），
> 官方示例就是 `tailscale serve --bg 3000`，所以这里用裸端口形式。
> **`--bg` 不能省**——help 里 `--bg` 默认 false，不带它 serve 会在前台占住你的终端窗口。
> 子命令 `status` / `reset` 同样在 help 里列出，写法正确。

原生 `run-trial.ps1` 形态同理（后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`），
仍然只需转发 5173。

### Linux / 群晖（Docker 支持 `/dev/net/tun`）

用 `docker-compose.yml` 里**注释块 A** 的 sidecar：取消整段注释，按注释设置 `TS_AUTHKEY`
（去 Tailscale 管理后台自建 auth key，只放宿主环境变量，**绝不提交进仓库**），然后
`docker compose up -d`。sidecar 与 web 共享网络命名空间，`deploy/tailscale/serve.json`
把 `https://<主机名>.<tailnet>.ts.net` 反代到 web 容器内的 nginx:80，访问地址形如
`https://wengu-at-home.<你的 tailnet>.ts.net`。

> 注意：Docker Desktop for Windows / macOS 走注释块 B（宿主机客户端），不要启用注释块 A。

### 不推荐：把服务直接开到局域网 / 公网

只有当**同一 Wi-Fi 下**的设备确实要直连时才考虑：

```powershell
$env:WENGU_BIND_ADDR="0.0.0.0"; docker compose up -d
```

这意味着同网段任何设备都能访问孩子区（免登录）与家长区入口（PIN 只防误入，不是安全边界）。
用完请恢复默认。**不要**把 5173/8000 暴露到公网，也不要用 Cloudflare Tunnel 代替这一步。

## 3. 跑只读自检脚本确认

```powershell
.\scripts\remote-check.ps1
```

脚本会打印 web/api 的实际监听地址、是否只绑回环、`docker compose port` 映射、
`tailscale status` / `tailscale serve status`、本机 `http://127.0.0.1:<web>/health`
的状态码，最后给一句判定：

- **仅本机可达**：默认状态；手机要按第 2 步做 tailnet 转发。
- **tailnet 已转发**：tailnet 内设备可用，且本机仍只绑回环。
- **局域网可达**：存在非回环监听（例如误设了 `WENGU_BIND_ADDR=0.0.0.0`），确认这是否是你要的。

端口不是默认值时：`.\scripts\remote-check.ps1 -WebPort 5000 -ApiPort 8100`。
脚本**只读**：不改配置、不重启服务、不写库，也不打印 cookie 或密钥。对外分享输出前，
请把 `tailscale status` 里的设备名 / 邮箱打码。
