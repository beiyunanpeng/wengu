# Alembic 迁移

- 位置：`wengu-api/migrations/versions/`，`alembic.ini` 在 `wengu-api/`。
- 数据库地址由 `WENGU_DB_PATH` 推导（默认 `wengu-api/data/wengu.db`）；迁移走同步 SQLite 连接，应用走 `sqlite+aiosqlite`，两边是同一个文件。
- SQLite 改表必须依赖 `render_as_batch=True`（已在 `env.py` 打开）。
- 迁移须**可重入**：每个 revision 的 `upgrade()` / `downgrade()` 都能重复执行而不报错；破坏性迁移必须附备份/回退说明。
- 改表流程：`make migrate M="描述"` 生成 → 人工审阅 → `make upgrade` → `make migration-test` → 提交 migration 文件。
- 初始 revision `0001_initial_empty` 只建立 `alembic_version`，不含业务表；P1-1 在其后追加。

备份：升级前复制 `wengu-api/data/wengu.db` 到仓库外（`make upgrade` 不自动备份）。
回退：`cd wengu-api && venv/Scripts/alembic downgrade -1`（或 `base`），恢复备份文件。
