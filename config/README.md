# 运行时配置（非密钥）

v2.5 起 wengu 内核**零模型**，模型档位、供应商路由等参数已退役。本目录只放
**非密钥运行时参数**，每次请求现读、改文件即生效（热加载），无需重启。

- 密钥（如将来接入本地模型）仍只放 `wengu-api/.env`，**绝不进本目录、绝不写进 `app-config.json`**。
- 可用环境变量 `WENGU_APP_CONFIG` 指向其他路径（测试覆盖用）。
- **P5-1a 起配置文件真源在数据目录**，见下方「文件位置」。

## 文件位置（读哪里、写哪里）

解析顺序（先命中先用）：

1. `WENGU_APP_CONFIG` 环境变量指定的路径（测试覆盖；读写都指向它）。
2. **`<settings.data_dir>/app-config.json`** —— **推荐位置，也是唯一写入目标**。
   - 原生 `run-trial.ps1`：`wengu-api/data/app-config.json`。
   - Docker：`<仓库>/data/app-config.json`（compose 已挂 `./data:/app/data`，
     **配置随 data 卷持久化，无需额外挂载**）。
3. **兼容回退**：仓库根 `config/app-config.json`（原生老用户已有文件）。
   存在则读取，但**只读不写**；`GET /api/config` 会返回 `legacy: true` 与迁移提示。
   系统**不会自动搬运或删除**该文件——需要迁移时由家长手动复制到 data 目录。
4. 都没有 → 内置默认值（不落盘；首次 `PUT /api/config` 才创建 data 目录那份）。

> Docker 形态此前读不到配置：容器里 `PROJECT_ROOT=/`，旧逻辑指向 `/config/app-config.json`，
> 而镜像未打包 `config/`、compose 也未挂载它。P5-1a 改为以 data 目录为准后修复。

## 修改方式

- **推荐**：家长区调 `PUT /api/config`（需解锁家长 PIN），白名单键 + 区间校验，
  非法值 422 且不写文件；写入走同目录 tmp + fsync + `os.replace`，并发写不会留半截 JSON。
- `GET /api/config` 返回生效值、每项来源（`file` / `default`）、当前读写路径与兼容提示。
- 也可直接编辑 data 目录下的 `app-config.json`（同样热加载）；手改值超出区间时按下方
  「缺失/非法」口径回退，不会被 API 拒写流程拦截。

| 键 | 默认 | 说明 | API 可写区间 |
|---|---|---|---|
| `daily_review_limit` | `10` | 每日到期复习上限：超过上限的到期项不显示、只计数，顺延到后续复习日，不丢失、不惩罚 | 1–200（整数） |
| `exam_day_limit_factor` | `1.5` | 日历上今天有 `kind='exam'` 事件时的上限放大系数：`min(round(上限 × 系数), 200)`；缺失/非法/小于 1 回退默认；竞赛/请假/其它事件不放宽 | 1–3（浮点） |
| `daily_recitation_limit` | `5` | 每日到期队列里"背诵铺底"最多条数：排在同类题考核之后，无到期条目则不塞；`GET /api/recitations/due` 的默认上限同上 | 1–20（整数） |
| `setup_completed` | `false` | 首次运行向导"不再提示"标记；**完成与跳过写同一个键**（不新增 `setup_skipped`）；缺失/非法按未完成 | 仅 `true` / `false`（布尔） |

> 未解锁时页面横幅读取公开只读的 `GET /api/setup/status`，只返回
> `{"setup_completed": bool}`，不含任何其它配置值；读写完整配置仍需家长解锁。

> `app-config.example.json` 是样例，复制到浏览器/编辑器里改；JSON 不支持注释，
> 样例中的 `_note` 仅作说明，读写时会被忽略（保存时原样保留）。
> 课表/日历本身只是约束层：课表不参与选题、排序或冲突检测，也不从课表生成任务。
