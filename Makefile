# ==============================================
# wengu · 温故 | 家用自托管 AI 学习工作台
# 跨平台 Makefile (Windows / Linux / macOS)
# 遵循 AGENTS.md 硬约束：SQLite 单机、无 Redis/Celery/外部 MQ
# ==============================================

# OS 检测
ifeq ($(OS),Windows_NT)
    # cmd.exe 才能正确解析 venv\Scripts\ 反斜杠路径；每条 recipe 用 && 串成一行
    SHELL         := cmd.exe
    .SHELLFLAGS   := /C
    VENV_PY       = venv\Scripts\python
    VENV_UVICORN  = venv\Scripts\uvicorn
    VENV_PIP      = venv\Scripts\pip
    VENV_ALEMBIC  = venv\Scripts\alembic
    VENV_PYTEST   = venv\Scripts\pytest
    VENV_RUFF     = venv\Scripts\ruff
    PYTHON        ?= python3.12
else
    VENV_PY       = venv/bin/python
    VENV_UVICORN  = venv/bin/uvicorn
    VENV_PIP      = venv/bin/pip
    VENV_ALEMBIC  = venv/bin/alembic
    VENV_PYTEST   = venv/bin/pytest
    VENV_RUFF     = venv/bin/ruff
    PYTHON        ?= python3
endif

# 端口可用环境变量覆盖：make dev-api PORT=8100
# 监听地址默认仅回环（与 P4-1 一致）：确需局域网调试用 make dev-api HOST=0.0.0.0
PORT          ?= 8000
WEB_PORT      ?= 5173
HOST          ?= 127.0.0.1
M             ?= auto
D             ?= base

.PHONY: help install-api dev-api install-web dev-web \
        seed-load seed-questions migrate upgrade downgrade migration-test \
        test lint format \
        up down logs

help:
	@echo "wengu 开发命令（跨平台）："
	@echo ""
	@echo "  # 后端"
	@echo "  make install-api        创建 venv 并安装 wengu-api 依赖（PYTHON=$(PYTHON)）"
	@echo "  make dev-api            启动 FastAPI (http://$(HOST):$(PORT)，HOST/PORT 可覆盖；默认仅本机)"
	@echo ""
	@echo "  # 前端"
	@echo "  make install-web        安装 wengu-web 依赖"
	@echo "  make dev-web            启动 Vite 开发服务器 (http://localhost:$(WEB_PORT))"
	@echo ""
	@echo "  # 数据与迁移"
	@echo "  make seed-load          从上游 cn-math-taxonomy 转换生成 seeds/data/（一次性，开发者跑；需先 clone 到仓库父目录）"
	@echo "  make seed-questions     转换初中题库到 seeds/data/questions.json（一次性）"
	@echo "  make migrate            生成新 Alembic 迁移（改表后跑；M=描述）"
	@echo "  make upgrade            应用最新迁移到 SQLite"
	@echo "  make downgrade          回退迁移（D=base 或 revision）"
	@echo "  make migration-test     跑迁移测试（幂等 + 回退）"
	@echo ""
	@echo "  # 测试"
	@echo "  make test               跑所有 pytest"
	@echo "  make lint               ruff 检查"
	@echo "  make format             ruff format"
	@echo ""
	@echo "  # Docker（家长部署主路径）"
	@echo "  make up                 docker compose up -d --build --wait"
	@echo "  make down               docker compose down"
	@echo "  make logs               docker compose logs -f"
	@echo ""
	@echo "  # 备份（唯一入口：家长区「备份」页 → POST /api/backup/export）"
	@echo "  每次升级/迁移前必须先备份：解锁家长区 → 备份 → 立即导出（一致性快照，保留最近 10 份）"
	@echo "  恢复 = 停服务后整库替换，步骤见 docs/deploy/backup-restore.md"
	@echo ""
	@echo "注意：wengu 无外部依赖，SQLite + 本地卷即全部数据；无需装 MySQL/Redis。"

# ---------- 后端 ----------
install-api:
	@echo "===> 创建 venv 并安装 wengu-api 依赖..."
	cd wengu-api && $(PYTHON) -m venv venv && $(VENV_PIP) install --upgrade pip && $(VENV_PIP) install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

dev-api:
	@echo "===> 启动 FastAPI (http://$(HOST):$(PORT)/docs)..."
	cd wengu-api && $(VENV_UVICORN) app.main:app --reload --host $(HOST) --port $(PORT)

# ---------- 前端 ----------
install-web:
	@echo "===> 安装 wengu-web 依赖..."
	cd wengu-web && npm ci --registry=https://registry.npmmirror.com

dev-web:
	@echo "===> 启动 Vite 开发服务器 (http://localhost:$(WEB_PORT))..."
	cd wengu-web && npm run dev -- --port $(WEB_PORT)

# ---------- 数据与迁移 ----------
seed-load:
	@echo "===> 从 cn-math-taxonomy 转换初中 seed 到 seeds/data/（一次性，开发者跑）..."
	cd wengu-api && $(VENV_PY) -m scripts.import_seed --src ../../cn-math-taxonomy-main

seed-questions:
	@echo "===> 从 cn-math-taxonomy 转换初中题库到 seeds/data/questions.json（一次性，开发者跑）..."
	cd wengu-api && $(VENV_PY) -m scripts.import_questions --src ../../cn-math-taxonomy-main

migrate:
	cd wengu-api && $(VENV_ALEMBIC) revision --autogenerate -m "$(M)"

upgrade:
	cd wengu-api && $(VENV_ALEMBIC) upgrade head

downgrade:
	cd wengu-api && $(VENV_ALEMBIC) downgrade $(D)

migration-test:
	cd wengu-api && $(VENV_PYTEST) tests/integration/test_migrations.py

# ---------- 测试 ----------
test:
	cd wengu-api && $(VENV_PYTEST)

lint:
	cd wengu-api && $(VENV_RUFF) check --no-cache .

format:
	cd wengu-api && $(VENV_RUFF) format .

# ---------- Docker ----------
up:
	docker compose up -d --build --wait --wait-timeout 180

down:
	docker compose down

logs:
	docker compose logs -f
