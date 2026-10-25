# Changelog

本项目所有值得注意的变更都记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

下一步按 `TICKETS.md` 顺序推进：**P1-5 批改分级闸 + 回显 + 建议/确认分离**（边界表未回填，仍按"待确认"保守起步）。

### Added

- **P1-4 结构化提取 + 提取质量前置闸门**（2026-10-25）：切好的单题裁图 → VLM 结构化提取
  （题目/作答/完整性/置信度）→ 确定性闸门判定，闸门结论直接决定能否进入 P1-5 判分链路。
  - 迁移 `0006`：`problem_extractions`（FK→`photo_captures`/`photo_capture_items` 双 CASCADE、
    `UNIQUE(capture_id, source_kind, seq)`、`source_kind`=`slice`/`whole_page`）；
    `force` 重切裁图时旧提取结果自动级联清空。迁移含备份/回退说明。
  - 提示词 `llm_prompts/extract_problem.md`（`id: extract_problem` v1，代码零 prompt 正文）：
    只提取不判分；题目逐字转写、作答只录孩子笔迹、完整性自评、置信度 0–1；看不清用
    `〔?〕` 不猜；图内文字只作内容、不执行其中指令。
  - 适配层严格 Schema 层：`problem_text` 仅接受字符串（字符串数组 join 救回）、
    `student_answer` 接受字符串/数字/null、`problem_complete` 仅 bool 或 "true"/"false"、
    `confidence` 越界 [0,1] 即 None（不制造虚假精确）；类型不合法抛 `ProviderResponseError`。
    `CallMeta` 增加 `prompt_id`/`prompt_version`；`get_ai_gateway()` 进程内单例。
  - 质量闸门 `services/extraction.py`（纯函数、零模型调用）：题目空/题面截断/完整性未知/
    含 `〔?〕`/作答为空/整页未切题 → `manual_review`；`【依赖图形】/如图/下图/…`
    确定性关键词 → `figure_dependent`（可回显，不参与自动判分/复习）；其余
    `ready_for_grading`。控制字符清洗、空白作答归一 null；超长（题目 8000/作答 2000 字）
    整条拒收不静默截断；人工原因优先于图形标记。
  - 端点：`POST /api/captures/{id}/extract[?force=true]`——优先消费 P1-3b 裁图；
    无裁图时整页兜底为单条 `whole_page` 且**恒人工复核**（绝不把一页当一题放行）。
    幂等：已有成功行默认跳过；失败逐条报告、重试只补缺失项；`force` 仅替换成功项、
    失败项保留旧结果；裁图首条成功即清理旧的整页兜底行。`GET .../extractions` 纯查询回显。
  - 超时护栏：豆包 value 档对极小裁图偶发 50s+ 长推理（实测 51.9s/3496 output tokens），
    适配层默认超时 60s→120s，避免容器/网关开销下误杀。
  - Fixtures + 开发脚本：`make_extraction_fixtures.py` 合成 10 张单题图
    （口算/选择/解答过程/几何如图/英默/语默/空白作答/题面截断/涂抹占位/图内提示注入）
    + truth JSON 提交进仓库；`eval_extraction.py` 真跑 VLM 并按题目/作答相似度、
    JSON 解析率、闸门命中、延迟、tokens 打分。
  - **DoD 实测**（合成 fixture，`--prefer-dotenv`，prompt@1）：
    `doubao-seed-2-1-lite-260915` 非探索题 **9/9 通过**，解析 10/10，题目相似度 0.980、
    作答 1.000，闸门命中 10/10，p50 16.9s，tokens in 16439/out 10603；
    `qwen3.8-max` **9/9 通过**，题目 0.975/作答 1.000，p50 4.6s，tokens in 6061/out 3237；
    `qwen3.5-ocr` 仅 **1/9**（不输出 `problem_complete`、漏手写作答、把墨迹猜成可读文本）
    → 确认结构化提取默认路由豆包，Qwen OCR 档不用于该任务。涂抹题模型正确落
    `manual_review`；题面注入题作答仍为 15、未被"填 100"指令劫持。
  - 容器实跑：迁移 0006 在既有库正常升级；双页 10 题 → 10 条提取（全部 `manual_review`，
    fixture 无作答）；首轮 9/10 因 60s 超时，补跑仍超时，调至 120s 后仅补跑缺失题
    1/1 成功；幂等重跑 10 skipped / 0.10s；无锚点页 slice 422 → 整页兜底 1 条
    `whole_page` + `whole_page_unsegmented`；`force` 重切后旧 10 条提取随 FK 级联清零；
    `model_runs` 全量记录 `extract_problem@1` 与 token/延迟，不含题目全文/答案/文件路径。
  - 验证：测试 102 → **138**（闸门 20 条、适配器宽松/严格层、提取端点幂等/force/级联/
    整页兜底/错误分级、fixture 完整性），`ruff check .` 全绿。
  - 残留风险：合成印刷体 + 楷体作答 ≠ 真实手写，真实识别率须家长实拍复验；豆包 value 档
    单题 p50 16.9s、极小裁图可达 52s，10 题串行提取约 3 分钟（MVP 可接受，后续按需
    并行/关思考）；Phase 0 边界表仍未回填，`ready_for_grading` 不等于自动入库，
    P1-5 仍须保守走"待确认"。

- **P1-3b OCR 行聚类切题预处理**（2026-10-25）：整页照片 → 本地 OCR 行检测 → 题号锚点 +
  垂直间隙聚类 → 裁单题子图，供 P1-4 精读；全程**不联网、不调 VLM**。
  - 迁移 `0005`：`photo_capture_items`（FK→`photo_captures`、`UNIQUE(capture_id, seq)`、
    `bbox_json`/`stored_path`/`anchor_label`/`status`）；capture 状态新增
    `sliced`/`slice_failed`。迁移说明含备份/回退步骤。
  - OCR 引擎 `app/preprocess/ocr.py`：`RapidOcrEngine`（rapidocr-onnxruntime，模型随
    wheel 内置，本地 CPU）、懒加载进程内单例、`TextLine` 统一行框；识别分 < 0.4 丢弃。
    引擎以 `OcrEngine` Protocol 抽象，可换 PaddleOCR。
  - 切题算法 `app/services/slicer.py`（纯函数、可单测）：题号锚点正则
    （`12.`/`3、`/`4．`/`12)`/`第5题`，`(?!\d)` 排除小数、题号 ≤100）；行距 >
    **2.0×行高中位数**→ 新题边界（无题号的续行/小问随组）；双页中线 gutter 检测
    （35%–65% 中带列差数组，空列连续 ≥2% 图宽即判定两栏，各栏独立聚类）；8px padding、
    面积 <400 噪声丢弃、全局连续 `seq`。**零锚点整页拒绝切分**（`SliceError`，绝不瞎切）；
    切块 >60 视为 OCR 噪声失控拒绝。
  - 端点：`POST /api/captures/{id}/slice` 显式触发（Phase 0 闸门内不做自动链）——
    幂等返回已切结果、`?force=true` 先删后插并**同路径覆盖 + 清理题数变少后的旧序号
    裁图（零孤儿文件）**、重切失败保留上次成功切片不误标 `slice_failed`；
    CPU 密集 OCR 走 `asyncio.to_thread`；无锚点 → 422 + `slice_failed`；母图丢失 → 410；
    `GET /api/captures/{id}/items` 纯查询回显。裁图落
    `uploads/slices/YYYY/MM/{sha256[:16]}-{seq}.png`。
  - Fixtures + 开发脚本：`scripts/make_slicing_fixture.py` 生成双页 10 题
    （含两行题、无题号续行、`第5题`、右栏两小问）与无锚点页及 truth JSON；
    产物提交进 `tests/fixtures/`，容器无需 CJK 字体。
  - 提示词：`llm_prompts/transcribe_image.md`（`id: transcribe_image` v1，逐字转写、
    `〔?〕` 占位不猜）——首个真实 prompt 文件，供 P1-4/评测使用。
  - **DoD 对比评测** `scripts/eval_slicing.py`：整页直读 vs 逐裁图转写，difflib 相似度对
    truth；`--degrade`（旋转 1.5° + 高斯模糊 + 62% 缩放回放）模拟手机拍照劣化。
    实测 doubao-seed-2-1-lite-260915：清晰图 Δ=+0.020（基本持平，合成页对整页 VLM 太简单）；
    **劣化图 Δ=+0.057（切题显著占优，整页 0.870 vs 切题 0.927）**；单题裁图调用 p50 3.1s
    （整页 15.4s），代价是裁图模式输入 token ≈10×（成本换准确率）。**尚未用真实作业照片
    复验**，家长可拍照后跑同一脚本定论。
  - Dockerfile 修复：rapidocr 依赖 `opencv-python`（GUI 版，需 libGL/libxcb）会盖掉
    headless 包导致容器 `ImportError: libxcb.so.1`——改为安装后卸载 GUI 包并强制重装
    `opencv-python-headless>=4.10,<5`；容器内 cv2 4.14.0 导入正常。
  - 验证：测试 87 → 102（锚点形式/拒绝式样/单双栏聚类/噪声过滤/重切幂等与旧裁图清理/
    无锚点 422/零 VLM 调用），`ruff check .` 全绿；容器实跑：双页 fixture → 10 items、
    `column_split_x=1034`、2 行页眉丢弃、锚点 `['1.','2.','3、','4.',None,'第5题',...]`、
    10 张裁图、force 重切后仍 10 文件 10 行（无孤儿）、无锚点页 422 + `slice_failed` + 0 行。

- **P1-3 采集双通道**（2026-10-24）：拍照秒传落库 + 豆包 JSON 兜底导入，全程零模型调用。
  - 迁移 `0004`：`photo_captures` 事实表（`sha256 UNIQUE` 幂等去重、`stored_path` 存
    uploads 相对路径哈希改名、`status='pending'` 待 P1-3b/4 消费；Phase 0 闸门内
    "触发"只到落库为止，不做识别/自动入库）。
  - 主通道：`POST /api/captures` multipart 上传——流式写盘边算 sha256、magic bytes
    嗅探（声明的 content-type 不可信，JPEG/PNG/WebP 白名单 + 声明与字节不符即 415）、
    20MB 上限；同照片重传复用旧行旧路径并自愈缺失文件，零孤儿文件；
    `GET /api/captures[?status=]` / `GET /api/captures/{id}` 纯查询。
  - 兜底通道：`POST /api/imports`——封套校验（channel 白名单/单批 ≤500 题/报文 ≤5MB）→
    逐项确定性校验归一（`services/ingestion.py`：控制字符清洗、字段类型/长度上限、
    超长不静默截断算错误跳过、未知字段丢弃计数）→ `import_batches` sha256 去重
    （重复导入返回旧 batch + `duplicate: true` 提醒）→ `ingestion_drafts` 写草稿
    （`has_placeholder`/`is_incomplete` 打标，与将来 P1-4 提取通道共用草稿结构）；
    坏项跳过 + 逐条错误报告（index/field/reason），batch 状态区分 imported/partial；
    `GET /api/imports/{id}` / `.../drafts` 纯查询回显。
  - 容器实测：真 PNG 上传 → `capture_id:1 pending`，重传 → `duplicate:true` 同 id，
    库内 1 行 1 文件；JSON 导入（含 1 坏题）→ `partial` + 错误报告 + 2 草稿，
    重复导入 → 同 `batch_id` + `duplicate:true`，库内终态 captures 1/batches 1/drafts 2。
  - 测试 64 → 87：`test_ingestion_validation`（纯函数）、`test_captures_api` /
    `test_imports_api`（真实迁移库 + ASGI 客户端，含"炸掉 AiGateway 仍通过"的
    零模型调用断言）；`ruff check .` 全绿。

- **P1-2 Provider 适配层 + 成本护栏**（2026-10-24）：视觉/文本双供应商可插拔落地，零厂商 SDK。
  - 适配器：`providers/openai_vision.py` 共享 OpenAI-compat 实现（httpx 直连 chat/completions，
    请求体绝不进错误消息），`doubao.py`（方舟 `/api/v3`）与 `qwen_vl.py`（DashScope
    compatible-mode）薄子类；`text.py` OpenAITextProvider（DeepSeek 默认，GLM/Kimi 同构可扩）；
    `tencent.py` 显式占位（调用即抛未实现）。基座 `http.py`：usage/latency 解析、
    `extract_json_object` 宽松抢救（严格校验归 Schema 层，P1-4）、图片 data URL。
  - 契约升级（`providers/base.py`）：三任务方法改收 gateway 渲染好的 `prompt: str`、
    返回 `(结果, CallMeta)`——**代码不留 prompt 正文**，调用元数据（供应商/模型/token/延迟）
    可审计；新增 `TextProvider`。mock 同步升级并新增 `MockTextProvider`。
  - 路由注册表 `providers/registry.py`：`DEFAULT_ROUTING` 按 Phase 0 实测落点
    （提取/判分/讲解→doubao，字形默写→qwen_vl，文本→deepseek），
    `config/app-config.json` 的 `provider_routing` 热覆盖；缺密钥/模型名 fail-fast
    （`ProviderConfigError`，模型名绝不猜），性价比/旗舰双档按 `model_tier_default` 选模型。
  - 三级内容哈希缓存 `providers/cache.py`：L1 内存 → L2 `data/ai-cache/*.json`（原子写），
    key = sha256(task+供应商+模型+prompt 版本+输入摘要)；prompt 改版本即全量失效
    （回归可重放）；命中零模型调用、不计护栏。
  - 成本护栏 `services/model_audit.py`：`check_daily_guard` 双闸——当日真实调用次数
    （`WENGU_DAILY_CALL_LIMIT`，默认 200）+ 按 `model_prices` token 单价的成本估算
    （`WENGU_DAILY_CALL_BUDGET_CNY`）；每次真实调用落 `model_runs`（P1-1 表复用：
    prompt 版本/供应商/token 用量/状态，错误也留痕，**零题目全文/答案/URL**）。
  - 网关 `services/ai_gateway.py`：业务唯一入口，管线 = 路由→护栏→缓存→调用→审计
    （独立 session 提交，业务回滚不丢审计）；L3 原始响应落 `data/ai-raw/{date}/`。
  - 配置：`.env.example` 重写 Provider 段（`WENGU_DOUBAO_/WENGU_QWEN_/WENGU_DEEPSEEK_`
    value/flagship 分档）；`config/README.md` 补 `provider_routing`/`model_prices` 热配置说明。
  - 验证：64 tests 全绿（新增 http/适配器/缓存/审计/gateway 端到端共 28 个用例，
    MockTransport 零网络零密钥）；ruff 零告警；容器重建 healthy，`/api/seed/summary`
    数据完好，容器内路由冒烟通过。
  - **真实连通冒烟**（2026-10-24，`python -m scripts.smoke_providers [--prefer-dotenv]`）：
    四家全验——百炼 `qwen3.5-ocr`（244 ms）/`qwen3.8-max`（1539 ms）文本调用通过；
    方舟 `doubao-seed-2-1-lite/pro-260915` **带图视觉调用通过**（64×64 试色图均正确
    答"红色"）。沉淀的坑进 `.env.example` 注释：模型 ID 全小写大小写敏感（展示名
    ≠ API id）、百炼 OpenAI 兼容地址 `.../compatible-mode/v1`（非 `/api/v1`）、
    方舟模型需控制台"开通"后才可调用、seed-2.1 为推理模型（有 reasoning_tokens，
    延迟/成本偏高，P1-4 选型再测）；`turbo-260628` 可用但 Phase 0 实测更差更贵，默认不用。

- **P1-1b 知识点 seed 装载**（2026-10-24）：`cn-math-taxonomy` 初中部分入库。
  - 转换脚本 `wengu-api/scripts/import_seed.py`（`make seed-load`，开发者一次性跑）：
    过滤 grade 7–9（664 点 = 数学 315 + 英语 257 + 物理 92），12 核心字段直映 + 按前缀显式化
    subject，`unaudited: true` 全打、`blind_verified: true` 仅数学；先修边 1018 条仅留两端点
    均在装载集内的（跨学段 74 条丢弃并计数）；`_source.json` 内嵌署名（URL/CC BY-NC 4.0/NC 声明）。
  - seed 包 `seeds/data/{topics,dependencies,_source}.json` 随仓库分发（JSON = 唯一真源；
    SQLite 为幂等装载副本 + FK 锚点）；`seeds/local/`（化学/语文自建）与 `seeds/mappings/`
    （教材包对照，status: example|draft|reviewed）家长自建、不进 Git。
  - 运行时装载器 `app/seed/loader.py`：启动自动装载（幂等可重入、fail-fast 校验、
    先修边全量同步、内存索引邻接表供回溯诊断）；教材包机制照抄、数据不附带。
  - 迁移 `0003`：`knowledge_seed` 补 `domain` 列；`GET /api/seed/summary` 只读返回
    各学科点数 + `unaudited`/`blind_verified` 计数（透传路径，纯查询不触发模型）。
  - 容器实测：`topics_total 664 / edges 1018`，数学 315/315/315、物理 92/92/0、英语 257/257/0。
  - 数据范围口径：`.gitignore` 原注释"不分发"指**外部原始仓**（`cn-math-taxonomy-main/`，
    仍被忽略、永不入库）；本次按 AGENTS §2.6 让**转换后的初中 seed 包**随仓库分发，
    `seeds/README.md`、`THIRD-PARTY-NOTICES.md §1` 同步；并修复 `.gitignore` 的 `data/`
    通配误伤 `seeds/data/` 的问题。

- **P1-1 数据模型 + 事件溯源/幂等骨架**（2026-10-24）：迁移 `0002_p1_1_core_schema` 建 13 张表——
  `learning_events`（append-only 事实源，`idempotency_key UNIQUE`，触发器钉死禁 UPDATE/DELETE）、
  `attempts`、`mistake_versions`（只追加，`UNIQUE(mistake_id, version)`，建议值/确认值分离存储）、
  `knowledge_seed`、`concepts` + `concept_aliases`、`import_batches`（sha256 去重）+ `ingestion_drafts`、
  `review_schedules`（只存排期决策事实，不存掌握度/毕业）、`ai_jobs`（`idempotency_key` + `to_event_id` 水位）、
  `model_runs`（审计不落题目全文/PII）、`user_role`、`prerequisite_edges`（hard/soft）。
  确定性重算骨架 `services/recompute.py`（mastery / is_graduated 尾部连对≥3 / stats，纯函数可重放）；
  幂等写入骨架 `services/events.py`（`record_event` / `create_import_batch` / `append_mistake_version`，
  SAVEPOINT 消化冲突、同事务不污染）。
- **P1-0 Repo 骨架**（2026-10-24）：
  - FastAPI 应用工厂 + `/health`（含数据库连通检查，失败返回 503）。
  - 配置层：`wengu-api/.env` 读取 + `config/app-config.json` mtime 热加载（优先级高于 `.env`）。
  - SQLite：异步引擎（aiosqlite）+ WAL / `foreign_keys=ON` / `busy_timeout=5000`。
  - Alembic 迁移骨架 + 初始空基线 `0001_initial_empty`（upgrade/downgrade 已验证）。
  - `VisionProvider` 抽象 + 确定性 mock provider；`llm_prompts/*.md` 版本化加载器（frontmatter `id`+`version`，重复/缺失 fail-fast）。
  - 本地 PIN scrypt 哈希/校验工具（单用户，无 JWT/多租户）。
  - React 19 + Vite + TypeScript + Mantine + KaTeX 空壳，显示 `wengu · 温故`。
  - API/web Dockerfile + compose 健康检查与 `--wait` 支持；GitHub Actions（ruff + pytest + compose config + tsc + build）。
  - 测试：12 项（配置热加载、PIN、SQLite pragma/CRUD、health、迁移、mock provider、prompt loader）。

### Changed

- Makefile 支持 Windows `cmd.exe` 与 `PYTHON`/`PORT`/`M`/`D` 变量；`install-web` 改用 `npm ci`；新增 `downgrade`；`up` 使用 `--wait`。
- compose：`wengu-api/.env` 改为可选 `env_file`，默认无需密钥即可起；挂载 `config/`；健康检查不再依赖 curl。
- API Dockerfile 增加 `PIP_INDEX_URL` 构建参数（默认清华源，加速国内构建；`docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple` 可还原）。

### Verified

- `docker compose up -d --build --wait` 双服务 healthy（2026-10-24，Docker Desktop 29.9.2）：`wengu-api` 8100→8000 `/health` 200、`wengu-web` 5000→80 页面正常；容器内 Alembic 自动 `upgrade head`。
- GitHub Actions 首跑全绿（2026-10-24，run 40095188340）：api 32s / web 19s，ruff + pytest 12 + compose config + tsc + build 全过。
- 前置：Docker Engine 配置 registry mirrors `docker.m.daocloud.io` + `docker.1ms.run`；本机 8000/5173 被 Hyper-V 动态保留段占用，用 `WENGU_API_PORT` / `WENGU_WEB_PORT` 覆盖。

### Still blocked

- P0-1 边界表未回填：P1-0 不含任何自动入库/自动排复习逻辑（AGENTS §2 闸门）。

## [0.0.0] - 2026-10-24

### Added
- 项目仓库初始化。
- 顶层文档：`README.md`（中英）、`LICENSE`（MIT）、`THIRD-PARTY-NOTICES.md`（`cn-math-taxonomy` CC BY-NC 4.0 归属 + KuroTutor / wrong-notebook / MistakeNotebook 借鉴清单）、`AGENTS.md`（编码 agent 缰绳）、`TICKETS.md`（分 Phase 工单 P0-1 ~ P5-5）、`目录结构.md`。
- 设计文档：`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`（v2.4，唯一事实来源）。
- 方法论：`docs/methodology/phase0.md`、`docs/methodology/evals.md`。
- 骨架目录：`wengu-api/`、`wengu-web/`、`evals/`、`llm_prompts/`、`seeds/`、`docs/{requirements,design,specs,manuals}/`。
- 工程配置：`pyproject.toml`、`Makefile`、`docker-compose.yml`、`.gitignore`。

### Design decisions locked（v1 → v2.4 演化摘要）

- **产品定性**：家用、自托管 Web+PWA、开源分发 = 每家长自托管单实例；不做 Hosting 多租户 / 公网账号体系 / 商业化。
- **技术栈**：Python + FastAPI + async；SQLite + WAL + Alembic；React + Vite + TS + Mantine + KaTeX + PWA；Docker Compose；Tailscale。
- **AI 工程纪律**：`learning_events` 事件溯源 + 幂等 + 确定性重算；prompt 版本化真源；`model_runs` 审计不落 PII；建议值/确认值分离；【依赖图形】题不判分；提示注入防御；三档核验模式。
- **判分架构**：**模型只提、代码才判**（客观题）；AST 白名单沙箱跑 `verify`（入库时）；`judgeAnswer` 规范化（运行时）。
- **知识点**：粗粒度预置 seed（来自 `cn-math-taxonomy`）+ 细粒度受控生长 + alias 归并 + 人工确认。
- **复习调度**：固定间隔阶梯 + 掌握度自适应因子 `× (1 + mastery × 4)` + 抗挫败三规则；FSRS 留接口。
- **变式题**：只检索真题组卷，**绝不 LLM 编题**；作答记 `practice_records` 派生表，不进错题本。
- **信奥**：判题在外部洛谷 / 一本通，**不建判题 infra**；只承接"卡壳→引导→待重做清单"。
- **家长看板**：观察复盘型，非遥控监控；两角色 + 本地 PIN；提醒只做"打开弹窗" + 家长低频周报。
- **外部对照**：KuroTutor / wrong-notebook 独立实证支持三条硬约束（禁 agent 框架 / 变式绝不进本 / 只检索真题），并吸收 7 处实现细节借鉴。
- **Phase 0 实测结论**（2026-10-21 首轮）：15 个 题型×供应商 组合全落"低置信/讲解"（题目识别 0.0–0.5 是主要瓶颈）→ 边界表本轮未回填 → Phase 1 全量按"待确认"保守起步。

### External validation
两条独立路线（本项目 16 轮"拷问式"设计盘问 vs. 用户自研 `LearnDesk-原始方案/`"调研+逐步砍"路径）+ 已实现同类开源项目（KuroTutor / wrong-notebook / MistakeNotebook）——**三方独立收敛到同一份"已砍清单"**（判题 infra / AI 编题 / 口语 ASR / 时间块日程 / 实时监控 / 多租户账号 / 云 GPU / 微服务 / Redis / K8s / 向量库 / 积分徽章 / agent 编排框架），视为方向被强验证。

[Unreleased]: https://github.com/<你>/wengu/compare/v0.0.0...HEAD
[0.0.0]: https://github.com/<你>/wengu/releases/tag/v0.0.0
