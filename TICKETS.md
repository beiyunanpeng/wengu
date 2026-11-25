# TICKETS.md — wengu 分 Phase 工单（v2.5）

每次给编码 agent **一条 ticket**，连同 `AGENTS.md` + `docs/specs/architecture/StudyDesk-设计说明文档-v2.md` 相关章节作为上下文。
**一条 ticket = 一个可跑增量 = 一次 PR，人审一次。** 每条含 目标·依赖·交付·DoD·禁止事项。
（DoD 一律含：服务能起 + 相应测试通过 + 更新文档；涉外部模板则跑转录黄金样例回归，见 AGENTS.md §8。）

> **路径说明**：以下出现的 `Phase0-实测/` 指代 wengu 仓库**外**的家长本地开发工作区（含 PII，不进仓库）；对应的仓库内方法论说明见 `docs/methodology/phase0.md`。

> **🔴 v2.5 流程改向（2026-10-28）**：批改/引导/解析**全部移出系统**，wengu 转**零模型**，提取改**外部 agent 转录已批改错题 → 监听目录导入 → 核对页确认**；新增**同类题考核**（从 Phase 3 提前）。本文件已按此重排：**被作废的票**列在文末"作废清单"并保留标题供追溯；**新增票**为 P1-3d / P1-4b / P1-4c / P1-10 / P1-11 / P1-12。**施工顺序：先建新入口 + 题库检索跑通闭环，再删旧视觉栈（P1-12 后置）**。设计依据见设计文档 §16。

---

## Phase 0 —— 摸底 + 回归基线
### P0-1 手写识别 + 分题型判分实测 → 《自动入库边界表》
- **状态（v2.5 更新）**：首轮已跑（9 题 × 5 档，45 次调用）。识别 0–0.5 是主瓶颈、边界表未回填——**但该瓶颈在 v2.5 已由"批改外移 + 只转录已批改题"绕过，边界表不再是入本前置**（真实题不在系统内判）。保留此票仅作**同类题考核判分器 `judgeAnswer` 的回归基线**与"若将来重新引入系统内识别"的参考。
- DoD：不再是 P1 入本/排期的阻塞前置；`judgeAnswer` 黄金用例并入 P0-2。
- 禁止：以"边界表未回填"为由卡住"外部转录 + 核对页确认"这条新主链。
### P0-2 evals 黄金集脚手架 + 首日填充
- 依赖：P0-1 样本。
- 交付：`evals/{transcribe,judge,generation,regressions}/` 结构 + 载入脚本 + **≥30 条脱敏黄金样本**（转录样例 + `judgeAnswer` 判分用例）+ **代码判定通过阈值** 的跑分脚本。
- DoD：改提取模板（P1-4b）/升 Schema/换判分规则时可一键回归；CI 可调用。
- 禁止：只立结构不填样本；用 AI 自宣"通过"。

### P0-3 端到端回归（把已声明的 `e2e` marker 用起来；v2.6 审计新增）
- **状态（2026-11-03）**：已交付。`tests/e2e/test_closed_loop.py` 三条全绿（`pytest -m e2e` 收集 3）；④ 的 DDL 对比在 `test_migrations.py` 覆盖 0018/0019（0019 的 7 个 DDL 对象逐字节相等），并已完成"改坏 `server_default` → 红 → 改回 → 绿"的可证伪验证。
- 背景：`pyproject.toml` 声明了 `e2e` marker，但 `pytest -m e2e` 收集到 **0 条**（266 unit + 131 integration + 0 e2e）。AGENTS §8 DoD 写了"E2E"，实际端到端只在批次⑧当时手工验过一次、不可重放。
- 交付：三条 e2e ——①投递 JSON → 核对页确认入本 → 到期队列出 quiz → 服务端判分 → streak/看板计数一致；②错题作废 → 退出到期队列 → 撤销 → 恢复；③家长导出备份 → 快照 `integrity_check=ok` 且表计数与 manifest 一致。
  ④（P5-6 审核期间追加）强化 `tests/integration/test_migrations.py`：给可逆迁移加 **DDL 原文
  before/after 对比**——升级前从 `sqlite_master.sql` 存档涉及表与索引的完整建表语句，
  upgrade 到 head 再 downgrade 回原 revision 后**逐字比对**（列类型 / NOT NULL / server_default /
  UNIQUE 与 FK 约束名 / ON DELETE / 索引定义），差异必须为空；至少覆盖 0018 与 0019。
  理由：inspector 断言只看名字集合，挡不住类型与默认值漂移。
- DoD：`pytest -m e2e` 收集数 > 0 且全绿；三条用例走真实 ASGI + 临时库 + 真迁移到 head，不 mock 服务层；CI 已跑（同一 job 内）。④ 必须真断 DDL 文本相等（不得退化成"表存在"），并给出**可证伪证据**：临时改坏 0019 downgrade 的一处 `server_default` 或约束名 → 用例变红 → 改回 → 变绿，两次输出贴进 PR。
- 禁止：为凑数写 `assert True`；把单测重贴一遍改名 e2e；只断表名存在冒充结构比对；引入 Playwright/浏览器栈（前端另议）。

### P0-4 测试基线噪音清理：`RuntimeError: Event loop is closed`（v2.6 审计追加）
- **现象**：全量 `pytest -q` 间歇出现 1–3 条 `PytestUnhandledThreadExceptionWarning:
  Exception in thread ... RuntimeError: Event loop is closed`，用例全通过。同一棵树多次跑出
  3 / 2 / 1 / 0 条不等；单独跑 `tests/e2e` + `test_backup_api` + `test_config_api` 连跑三次 0 条
  ——**是 GC 时序依赖，不是某个用例确定触发**，所以必须结构性修，逐文件改会漏。
- **根因**：**21 个测试文件**用 `create_sqlite_engine` / `create_engine` 建引擎后**从不调
  `engine.dispose()`**（`conftest.py` 也没有兜底）。aiosqlite 为每个连接起一个工作线程，
  引擎对象在所属事件循环关闭之后才被 GC，线程收尾就抛这个异常，被 pytest 报成 warning。
- **交付**：在 `tests/conftest.py` 加**一个 autouse 异步 fixture**：包装
  `app.core.database.create_sqlite_engine` 与 `sqlalchemy.create_engine`，登记本次测试创建的引擎，
  在 **teardown 内（同一事件循环还活着时）** 逐个 `await engine.dispose()`（同步引擎调 `dispose()`）。
  一处改动覆盖全部 21 个文件与以后新增的文件，**不改任何测试文件本体、不改生产代码的池配置**。
- DoD：
  - `pytest -q -W error::pytest.PytestUnhandledThreadExceptionWarning` **连续跑 5 遍全绿**
    （噪音变错误即视为未修）；
  - 全量用例数不减少（当前基线 521 passed，只允许持平或增加）；
  - `ruff check --no-cache .` 绿；
  - 5 遍全绿后，把该 filter 固化进 `pyproject.toml` 的 `filterwarnings`，**锁住不回潮**；
    若固化后 CI 因第三方 warning 变红，则回退为仅保留 fixture 修复并在 PR 里说明原因。
- 禁止：改生产 `create_sqlite_engine` 的池/参数来"绕过"（那是拿测试问题换运行时行为变化）；
  用 `warnings.filterwarnings("ignore")` 把噪音**消音**（我们要的是没有泄漏，不是看不见）；
  逐文件补 dispose 却漏掉新增文件（必须走 conftest 单点）；顺手重构测试 fixture。

### P0-5 两处 Windows 本地噪音：pytest 临时目录清理报错 + make 中文输出被 cmd 代码页吃掉（**已合并**：PR#42 squash → main `629d6d7`，2026-11-05）
- **为什么值得做**：都不影响结果（退出码 0、用例全过、CI 是 ubuntu 不受影响），但噪音攒多了就会让人
  忽略真报错——与 P0-4 同一条理由。P4-1b 与 P4-1c 连续两票都把它写进"残留"，说明它一直在。
- **事实①（审核方本机实跑）**：不带 `--basetemp` 跑 pytest，每次都在 `2 passed` 之后打
  `PermissionError: [WinError 5] 拒绝访问: …\pytest-of-roc\pytest-current`，调用链
  `_pytest/pathlib.py: cleanup_numbered_dir → cleanup_dead_symlinks → left_dir.resolve().exists()`；
  `%TEMP%\pytest-of-roc` 现有 **6** 个编号目录（默认只保留 3）——清理从未完成过。
  `--override-ini tmp_path_retain_count=1` 已验证**无效**（报错早于保留数逻辑）。
- **事实②（字节级取证，与终端无关）**：捕获 `make help` 原始字节后 `decode('utf-8')` 抛
  `invalid continuation byte`（position 34-35），输出含 **25 个 `?`**；`"创建"` 在而
  `"创建 venv 并安装"` 不在——"装"的第三个字节被吃掉。根因方向是 Windows 分支 `SHELL := cmd.exe`
  经 936 代码页转码；**所有含中文的 `@echo` 都受影响**，不只 help。
- DoD 要点（详见卡）：pytest 侧连续 3 次零 Traceback **且**编号目录数收敛 ≤3（判据是"清理完成"，
  不是"看不见报错"）；make 侧用 `decode('utf-8')` 不抛异常 + 中文子串完整作验收；两组证伪必做。
- 禁止：吞异常 / `2>NUL` / `--disable-warnings` 等消音；把 `--basetemp` 设成固定共享目录；
  升级 pytest 或加依赖；把中文 help 改英文。
- **交付与返工**：首版把噪音治好了，但审核方实测发现本机 `pytest-current` 已不存在（非管理员建不了
  链接），钩子每次都提前返回——**主动修复分支运行时零覆盖**，噪音消失实为"坏根被一次性移开"。
  返工补 5 条全打桩单测（两条修复分支 + 三条守卫用计数桩断言未被调用），不真建链接、不读写真实
  `%TEMP%`，故 ubuntu CI 同构通过。审核方三组变异证明断言真在把关（守卫改 `if True:` → 2 红；
  命名 `stale-`→`stale_` → 1 红；提示改到 stdout → 1 红）。最终 `pytest -q` **535 passed**、
  不带 `--basetemp` 三次 stderr 全 0 字节、编号目录收敛到 3、`make help` 字节级 0 个 `?`。
  本卡两处前提错误由审核方更正（`upgrade`/`backup` 原本无 echo；"6 个编号目录"应为 5 个 + 1 死链接）。

---

## Phase 1 —— 核心闭环（批改外置 + 确定性内核 + 同类题考核）

### P1-0 Repo 骨架
- 交付：FastAPI 应用 + **SQLite(WAL)** + `docker-compose.yml` + 目录 + 环境变量 + `/health` + 冒烟测试 + CI(lint/test) + React+Vite+TS+Mantine+KaTeX 前端空壳。
- DoD：`docker compose up` 起全栈、`/health` 200、CI 绿。
- 禁止：写业务；引入 Postgres/Redis/MinIO（默认本地卷/内嵌 SQLite）。

### P1-1 数据模型 + 事件溯源/幂等骨架
- 依赖：P1-0。
- 交付：Alembic 迁移建表——`knowledge_seed(category) / concepts + concept_aliases / mistake_versions / import_batches + ingestion_drafts / attempts / review_schedules / learning_events(append-only,UNIQUE) / ai_jobs / user_role`。掌握度/毕业/统计的**确定性重算函数** + **幂等写入**骨架。
  - **v2.5 数据契约补充**：外部转录字段（`standard_answer`(必填)/`verify`(可选)/`error_cause_suggestion`/`suggested_topic_id`）走 `services/ingestion.py` 归一化契约、存进 `ingestion_drafts.normalized_json`（**不加逐列**）；`mistakes` 加 `primary_topic_id`（可空、外键 `knowledge_seed.id`，是检索同类题的主考点，未确认前不排考核）；**闭环同类题考核复用 `attempts` 表**——给 `attempts` 加 `source ∈ {student_self, system_quiz, manual}` 与 `problem_bank_id`（外键），**不另建 `quiz_attempts`**（否则 `recompute` 双读两张表、破坏"唯一事实源 + 确定性重算"）；`practice_records` 保留、只承接主动加练的变式。
- DoD：迁移可 up/down + 备份说明 + **迁移测试**；重复导入/重试/重启不产生重复错题·事件·计数。
- 禁止：把易变状态存成字段（应由事实推导）。

### P1-1b 知识点 seed 装载（v2.2/v2.3 定，v2.5 补题目载入前置）
- 依赖：P1-1。交付：导入外部 `cn-math-taxonomy` (CC BY-NC 4.0) 初中部分并转换 schema——`topics.json` 里 `cnm_*`（数学 315）+ `cne_j_*`（英语 257）+ 初中物理 92 → `knowledge_seed.category`；`dependencies.json` → `prerequisite_edges`（含 hard/soft）。核心字段直映（camelCase→snake_case）。**高中 `grade 10–16` 语义为"册"非入学年**，需转换标注。
- **Seed 分档打标签**：`unaudited: true` 全部；**`blind_verified: true` 仅初中数学**（A/B 双轮盲解 1407 题、答案错 0）；**初中英语、初中物理 `blind_verified: false`**（verify 与答案同源，UI 明示"参考冷启动 + 家长复核"）。
- **化学、语文** = 复用同 JSON 契约，家长对课本目录录章级粗粒度 40–80 点（`unaudited: true`、无题），不另找源、不自建细粒度题库。
- 教材包（`mappings/<版本id>.json` + `status: example|draft|reviewed`）：现网 `mappings` 0 条、示例不得引用——机制照抄、数据家长自建。
- DoD：License 署名 + 原项目 URL + NC 声明写入 seed 包内嵌 `_source.json`；`unaudited` / `blind_verified` 透传到 UI。**题目本身不在此票载入**（见 P1-10）。禁止：硬编码学科树；把 seed 数据塞进 SQLite（应 JSON 文件随仓库分发 + 内存索引）。
- **家长自建章级 seed（化学/语文）已独立成票 P3-8**（2026-10-31 交付，见 Phase 3）。此前误挂在
  本票号下，与 2026-10-24 的"P1-1b 知识点 seed 装载"撞号，已于本次统一改标 P3-8。

### P1-2 Provider 层收缩为 mock-only（v2.5 改，原"Provider 适配层 + 成本护栏"）
- 依赖：P1-0。
- 交付：保留 `providers/base.py` + `providers/mock.py`（供测试）；**`doubao/qwen_vl/tencent` adapter、`llm_prompts/*.md`、成本护栏（每日上限/内容哈希缓存）、`model_runs` 写入路径在本票标记为"待退役"**（实际删除集中在 P1-12，先切断业务引用）。`ai_jobs` 若无在环模型调用则保留空表不强删。
- DoD：应用启动不再要求任何 provider API Key 即可跑核心闭环；`/health` 正常；无云调用发生。
- 禁止：留任何"自动去调云模型"的隐性代码路径。

### P1-3 采集：外部转录导入为主 + 手填后手（v2.5 大改，原"采集双通道"）
- 依赖：P1-0、P1-1。
- 交付：
  - **主入口** = 监听目录导入引擎（见 P1-3d）：读外部 agent 产出的已批改错题 JSON。
  - **后手** = **家长手填最小表单**（`题干 / 错答 / 正答 / 错因 / 知识点` 五字段，无任何 OCR/VLM）→ 同样落 `ingestion_drafts`。
  - 删除原"手机拍照 → VLM 主链路"与"豆包 JSON 人工兜底"的旧表述；`channel` 用 `agent_transcribe_v1`（兼容 `doubao_json`）。
- DoD：手填一条含 `standard_answer` 的错题 → 落草稿 → 核对页确认可转正；缺 `standard_answer` → 拒绝自动转正、强制人工补。禁止：把网盘当主链路；在此票判任何题对错。

### P1-3d 监听目录导入引擎（v2.5 新增，主入本通道）
- 依赖：P1-3。
- 交付：wengu 后台扫描 `data/inbox/`（路径可配）→ 发现 `*.json` → 复用 `ingestion.validate_envelope/validate_and_normalize`（**补 `standard_answer` 必填 + 长度校验 + `〔?〕` 标记**）→ `import_batches`（**sha256 对原始报文去重，重复导入返回旧 batch + `duplicate=true`**）+ `ingestion_drafts` → 归档源文件到 `data/inbox/.processed/`。**导入全程不调模型、不自动转正**。
- DoD：把一个合法 JSON 放进 inbox → 秒级落草稿、报告 `accepted_count/errors[]`；同一文件再放一次 → 命中去重 `duplicate=true`；坏项逐条报告 index/field/reason、不静默截断。服务停机时文件不丢（重启后补处理）。
- 禁止：导入时调模型/自动建错题/自动转正；跳过 `standard_answer` 校验。

### P1-3e 移动端投递入口：粘贴整段转录 JSON（v2.6 审计新增，PWA 的替代票）
- **状态：已交付并合并（2026-11-04，PR#35，`main` = `b600d4d`）**——
  `/import` 新增原文粘贴 + 本地 `.json` 读取（`file.text()`），共用 `POST /api/imports`；
  `importRawText` 原文直发避免二次序列化；422 逐行渲染 `index/field/reason`；
  e2e 第 8 条覆盖原文路径 → 部分坏项 → 重投去重 → 核对页确认入本；无迁移、无新依赖、后端零改动。
- 背景：PWA 当初为"安卓手机 / iPad 拍题"而选（已砍，见设计文档 §17-A）。但 v2.5 后拍照与转录都在系统外完成，
  手机侧真正缺的是**把外部 agent 产出的整段 JSON 送进 `data/inbox` 等价物**——今天 `POST /api/imports` 端点已存在
  （`api/imports.py:144`）且前端已在用（`endpoints.ts:252`），但导入页只有"手填一条"表单，**没有粘贴 JSON 的入口**。
- 交付（2026-11-04 出卡，补实现级细节）：
  `/import` 页新增"粘贴转录 JSON"区（Textarea 粘贴 + 本地 `.json` 文件读取，二选一进同一个提交函数）。
  ⚠️ **两个技术约束**：
  ① 走**同一个** `POST /api/imports`，但 `requestJson` 会 `JSON.stringify(body)`（client.ts:130）——
     粘贴的原文**绝不能**再走它（会被二次序列化成字符串套字符串），必须新增
     `importRawText(text)`：以原文为 body、`Content-Type: application/json` 直发（不二次编码）；
  ② 错误渲染复用 client.ts 已有的 `detail` 提取，但 422-no-valid-items 的
     `{message, errors:[{index,field,reason}]}` 要**逐行渲染**，不得只吐 message。
  其余复用：`ingest_raw_payload` 全套校验与 sha256 去重、单批上限展示（InboxInfo）、
  成功后给"跳核对页"链接。移动端可用：窄屏不破版、按钮可点、错误清单可横向滚动。
- DoD：手机浏览器（经 Tailscale 或局域网）贴一段含 3 题（含 1 坏项）的模板 JSON → 落 2 条草稿、
  坏项逐条 `{index, field, reason}` 报错不静默丢弃；同一段再贴一次 → 命中去重 `duplicate=true`
  不重复建批；**绝不产生错题本行**（仍只能经核对页转正）；375px 无横向溢出；
  `pytest -m e2e` 第 8 条走同一提交函数的原始文本路径；全量绿 + `ruff check --no-cache` + build。
- 禁止：新写一条绕过 `ingest_raw_payload` 的入库路径；给这个入口加自动转正；引入文件上传/对象存储；
  二次序列化（double-encode）；把内部异常栈原样吐给用户（P1-9b 纪律照旧）；
  为"看起来像 App"重新引入 manifest/service worker（已进 §12 反清单）。

### P1-3f 粘贴/文件导入显式剥离 BOM（P1-3e 审计登记的后续小改）
- **状态：已完成（2026-11-04，分支 `feat/p1-3f-bom`，待评审）**——
  `submitRaw` 改为先 `text.replace(/^\uFEFF+/, "")` 再 `trim()`，粘贴与文件路径共用；
  带/不带 BOM 的同内容报文归一为同一 sha256（e2e 第 9 条：双 BOM 201 → 无 BOM
  `duplicate=true` 同批次）；实测后端 bytes 路径 CPython 会按 `utf-8-sig` 识别 BOM，
  未剥离的主要后果是去重哈希分叉而非必然 400；无迁移、无新依赖、后端零改动。
- **背景（审核方实测）**：`ImportPage.submitRaw` 现在靠 `text.trim()` **顺带**去掉了 BOM——
  ECMAScript 规范把 `U+FEFF` 列为 WhiteSpace，所以 `trim()` 会去掉它；而 Python
  `json.loads` **拒绝** BOM 开头的文本（实测 `JSONDecodeError`）。也就是说：
  Windows 记事本/Excel 导出的"UTF-8（带 BOM）".json 现在能导入，**但这是巧合不是设计**——
  代码里没注释、没测试、DoD 也没要求。将来任何人把 `trim()` 换成别的空白处理
  （例如只 `replace(/\s+$/,'')` 或改成 `text.slice(...)`），BOM 就会留在报文里。
  ⚠️ **后果更正（交付实测 + 审核方复验，2026-11-04）**：本条原写"会立刻变成 400"是**错的**——
  后端入口 `ingest_raw_payload(raw: bytes)` 收的是 bytes，CPython 会按 `utf-8-sig` 识别并吃掉 BOM
  （实测 `json.loads(b'\xef\xbb\xbf{...}')` 成功；只有对 `str` 才抛 `Unexpected UTF-8 BOM`），
  所以**不会 400**。真正后果是：带 BOM 与不带 BOM 的同一份报文产生**不同 sha256**，
  让 `import_batches` 的批次去重失效（同一内容被当成两份新报文）。
- 交付：在 `submitRaw`（或其前置）加**显式** BOM 剥离——`text.replace(/^\uFEFF+/, '')` 后再
  `trim()`，并写一行注释说明"为何必须显式处理：Python json.loads 拒绝 BOM"；
  文件读取路径（`file.text()`）与粘贴路径共用同一处理，保证两者对同一内容得到**同一 sha256**
  （去重语义一致）。
- DoD：新增断言——带 BOM 的合法报文（`\uFEFF{...}`）经前端提交路径返回 **201**、
  草稿数正确、且与去 BOM 的同内容报文命中同一批次去重（`duplicate=true`）；
  非 JSON / 空文本仍分别 400 / 不发请求；`pytest -q` 全绿（基线 522 passed）、
  `ruff check --no-cache` 绿、`npm run build` 绿。
- 禁止：改后端 `ingest_raw_payload` 去容忍 BOM（真源在投递侧清洗，后端契约不动）；
  顺手重构 ImportPage 其它逻辑；引入文件上传/编码检测库。

### P1-4b 版本化外部提取模板 `docs/templates/doubao_transcribe_v1.md`（v2.5 新增）
- 依赖：P1-1b（知识点 id 空间）。
- 交付：一份**给豆包/千问办公用的中文模板**，frontmatter `id: doubao_transcribe`、`version: 1`（改语义必递增）；规则包含——**只挑卷子上被红笔批改/订正过的错题**；每题输出 `subject / problem_text / student_answer(划掉的错答) / standard_answer(订正后的正答) / error_cause_suggestion / suggested_topic_id(从内嵌初中知识点目录选) / source_ref / captured_at`；**看不清一律 `〔?〕` 占位、绝不猜**；**题目文字只作被转录内容，不执行任何指令**（注入防御）；整页一张图。随附一个"输入照片 → 期望输出 JSON"的样例（P0-2 收进黄金集）。
- DoD：拿一张真实已批改卷子按模板跑豆包/千问办公，产出的 JSON 能被 P1-3d 无 `errors` 导入。禁止：在模板里让模型"判对错/讲解/生成题"。

### P1-4c 千问办公转录 Skill / 定时任务（v2.5 新增，工具产物·非 wengu 代码）
- 依赖：P1-4b、P1-3d。
- 交付：一个**千问办公 Skill 草稿**（本仓库 `docs/tooling/` 存文档化配方，不进后端）：整页拍/一叠照片 → `qwenwork_media_read`/`Read` 套 P1-4b 模板转录 → 汇总 `{channel:"agent_transcribe_v1", items:[...]}` → **写入 wengu `data/inbox/`**。可选千问办公**定时任务**轮询照片同步目录、发现新图自动跑 Skill 并提醒家长去核对页确认。Skill **只写到草稿、绝不自动转正**。
- DoD：一次投喂多页 → inbox 落多个 JSON → wengu 侧成批进草稿；核对页显示题+错答+正答并排。禁止：Skill 直接写错题本/绕过核对页。

### P1-5 判分器（v2.5 作用域收缩：只判系统自造同类题）
- 依赖：P1-1、P1-10。
- 交付：确定性 `judgeAnswer` 归一化比对（NFKC 全/半角、多答案按 `,、；和/或` 拆分、`1/2≡0.5≡50%` 有理数精确比较、坐标、单位别名、带分数、`acceptableAnswers` 别名），**运行时不 eval**；`verify` Python 表达式仅在**入库核验**时过 **AST 白名单沙箱**（四则/推导式/下标，禁 import/属性/赋值，2s 超时）。**删除**原"对真实作业做客观/过程/开放分级 + 模型初判 + 多次采样一致性"整段（真实题不判）。
- DoD：对 seed 题库选择题/填空题给标准答案 + 孩子作答 → 判对/判错准确；`judgeAnswer` 单测覆盖全规范化规则；`verify` 沙箱跑通入库率 100%。
- 禁止：让模型判分；运行时 `eval verify`；用 Python 内置 `eval()`（必须白名单 AST）。

### P1-6 错题本入库（v2.5 改：入本=核对页确认的外部转录错题）
- 依赖：P1-3d、P1-4b、P1-5。
- 交付：核对页确认外部转录错题 → **唯一写入路径**建错题（记 `standard_answer(必填) / 错答(可空——整题没做也算错题) / 错因(确认值) / 多 concept 挂载 + `primary_topic_id`(可空)`）；**含 `〔?〕` 或缺 `standard_answer` → 不得自动转正**（占位符=看不清须重拍，区别于"留空错答"）；错因 AI 建议值 + 孩子确认值分离、来源标记（`ai / student / parent`）；知识点粗 seed 挂载 + 细粒度受控生长（优先复用、不覆盖确认值、归并需人工确认、alias）。主动加练变式 → `practice_records`；闭环同类题考核 → 记 `attempts`（`source=system_quiz`）（都不进错题本）。
- DoD：一条转录错题确认 ≤1 点击入本；无 `primary_topic_id` 仍入本（存 NULL）、只是不排同类题考核、复习退回原题重做自评；`attempts`（按 `source=system_quiz` 过滤）/`practice_records` 有可回看查询页。禁止：AI 自由生成标签泛滥；把变式/考核写入错题本；无确认静默入库。

### P1-7a 复习排期服务（用户触发，v2.5 补：考核优先/重做兜底 + 双来源）
- 依赖：P1-6、P1-10、`review_policy.py`（已交付）。
- 交付：`0009_review_schedules` 迁移 + `services/review.py`（`schedule_initial / complete_attempt / due_queue`）+ `api/reviews.py`。
  - **到期行为（v2.5）**：`due_queue()` 对每道到期错题，**先按 `primary_topic_id` 检索同类题（P1-10）→ 命中则推"同类题考核"、未命中则退回"原题重做（自评）"并标 `bank_gap`**。
  - **掌握度双来源**：`recompute.mastery()` 计入 `source ∈ {student_self, system_quiz}` 两类事件、MVP 各计 1 次仅打标签（暂不加权）；一道错题挂多 concept 取**最小 mastery**（不变）；无 concept → 0.0。
- DoD：确认错题→首次排期→到期→按"考核优先/重做兜底"出任务→完成写下一次→毕业；`recompute` 整体重放结果一致。
- 禁止：MVP 强上 FSRS；LLM 现编题；`judgeAnswer` 之外任意 eval；未经确认建错题/排复习。

### P1-10 题库检索引擎（v2.5 新增，"同类题"地基，Phase 3 提前）
- 依赖：P1-1b。
- 交付：把 `cn-math-taxonomy` `questions.json` 初中段（数学 1407 / 英语 1028 / 物理 368）**载入内存索引（不进 SQLite，守 §14 数据形态）**；建 `topic_id → [question]` 倒排；`services/bank.py`：`find_same_type(primary_topic_id, seed)` **同 topicId + mulberry32 固定种子可 `replay()`**；覆盖不足（含语文/化学=0、物理薄）→ 返回空 + `bank_gap=true`。bank 每题 `verify` **入库核验过 AST 沙箱**（复用 P1-5）。
- DoD：给定一个 `cnm_*` 知识点 + 固定种子 → 稳定返回同 topicId 题目、可重放；给无题知识点 → 明确"无同类题 + 缺口标记"；内联 SVG 过 HTML 净化。禁止：LLM 编题；把题库塞进 SQLite。
### P1-11 同类题考核闭环（v2.5 新增）
- 依赖：P1-7a、P1-10、P1-5、P1-6。
- 交付：考核页取一道同类题 → **客观/短答题系统内作答、`judgeAnswer` 比对 bank 标准答案判分**（记 `attempts`：`source=system_quiz`，**不新建错题**）；**数学解答大题**（bank `type` 非客观 或 `figure` 依赖图）→ 降级"纸上做 → 拍已批改 → 自评"（`source=student_self`）。**触发两者都要**：复习到点自动推（P1-7a）+ 家长手动组卷入口（选知识点→出 1..N 题）。考核结果计入该知识点掌握度、可整表清空。
- DoD：一道数学错题到期 → 推同 topicId 客观题 → 系统判对/错 → 掌握度变化可重放；大题 → 降级自评路径生效；家长手动组卷可用；`source=system_quiz` 的 attempts 不新建错题。禁止：让模型判考核题；把考核结果建成错题。
### P1-7b 前置知识回溯诊断（不阻塞）
- 依赖：P1-1b、**P1-10（需题库诊断题）**、P1-7a。
- 交付：`services/diagnose.py`（Python 重写 `engine.js` ~200 行：每知识点≤2 题；第 1 对=mastered、第 1 错补第 2、第 2 错=weak→未判定先修 hard 先 soft 后 DFS 压栈回溯、第 2 对=shaky 不回溯；停止 16 题(筛查 40)或栈空；根因=weak 且其先修无 weak；mulberry32 固定种子可 `replay`）+ `api/diagnose.py` + 单测。联动：诊断根因若已有错题→排期优先级↑，若无→作"待补前置"进日队列（P2-1），**不自动建错题**。
- DoD：`replay(answers)` 完整重建；根因与 engine.js 一致；栈硬上限。禁止：回溯不设停止条件；诊断结果自动建错题。
### P1-7c 自动排复习（**v2.5 作废**）
- 见文末作废清单：批改外移后不再有"模型判错即入库"的自动场景，入本一律经核对页确认。
### P1-8 三段式讲解（v2.5 改：真实题移外部，系统内仅可选复用）
- 依赖：P1-5。
- 交付：真实错题的"引导/讲解/答疑"**移出系统**（卷子上/外部豆包）。wengu 内**仅保留一个轻量讲解位**：孩子对**自造同类题卡壳**时可点"给提示"（按错因/知识点给引导、**不直接甩答案**，可选后续接入，非主链、默认关）。"要答案须先动手 + 留痕"护栏保留在配置。
- DoD：默认关时闭环不依赖讲解也能跑完；开启时对考核题给引导不泄答案。禁止：把系统讲解又做成"更漂亮的红笔"；重造答疑引擎。
### P1-9 最小 Web UI（v2.5 改五页）
- 依赖：P1-3d、P1-4b、P1-5、P1-6、P1-7a、P1-10、P1-11。
- 交付：**导入页**（拖入 inbox 说明 + 家长手填最小表单）/ **核对页**（题+错答+正答并排 + 错因确认 + **多知识点挂载 + 选主考点**）/ **错题本** / **复习+考核页**（到期任务、重做自评 or 同类题作答）/ **讲解位（默认关）**。React+Mantine+KaTeX（数学渲染）。
- DoD：家长能"外部转录→核对确认入本→复习到期→（能考就考/否则重做自评）"走通一遍；孩子见同一份。禁止：追求美观或提前做看板/规划。
### P1-9b 导入校验错误呈现（v2.5 缩小）
- 依赖：P1-9、P1-3d。
- 交付：导入失败/坏项时，前端直接显示 P1-3d 的 `errors[] (index/field/reason)`（超长/缺 `standard_answer`/含 `〔?〕`/注入可疑），给"重拍/手填补/丢弃"处置提示。**不再需要"账户/欠费/供应商"类错误呈现**（无在环模型调用）。
- DoD：一个坏 JSON → UI 精确指出第几项哪个字段为何被拒；`duplicate=true` 批次给"重复导入已跳过"提示。禁止：把内部异常栈原样吐给用户。

### P1-12 退役系统内视觉栈与 Provider（v2.5 新增，**后置**）
- 依赖：**P1-3d + P1-10 + P1-11 全部跑通、闭环实跑通过之后**才做（防断档）。
- 交付：删除 `preprocess/ocr.py`、`services/slicer.py`、`services/extraction.py`、`api/captures.py`、`api/extractions.py`、`models/extraction.py`；删 `providers/{doubao,qwen_vl,tencent,failover,http,openai_vision}.py`、成本护栏、`model_runs`、`llm_prompts/`；清路由与 DI 引用；更新 CHANGELOG + `.env.example`（去掉模型 Key 必填）。
- DoD：删后服务能起、`/health` 200、全测试绿、闭环实跑不回归；单张票可整体回滚。禁止：在新入口未跑通前删；顺手删 `providers/mock.py`（保留供测试）。
- **状态注（2026-11-02 审计）**：上面"保留 `providers/mock.py`"一条已被 AGENTS v2.5 横幅取代——实际交付把 `providers/` **整目录删除**（含 mock），因为零模型后无任何 importer。以 AGENTS 横幅为准，勿再照本行恢复 mock。

### P1-13 知识点归并 UI（补受控生长的另一半；v2.6 审计新增，2026-11-04 按盘上代码核实）
- **状态：已完成（2026-11-04，分支 `feat/p1-13-merge-ui`，PR#37 返工后待复审）**。与卡差异（以实际代码为准）：
  预览在**两个选择器都选好后**请求，不是"打开弹窗即调"；测试 helper 为复用锁定态新增
  `unlock` 参数。PR#37 返工：`merge-preview` 返回 `projected_aliases_moved`（与
  `merge_concepts` 共用投影逻辑，含源名称），确认框显示该值并与 `aliases_moved` 断言一致；
  预览响应在 `session.begin()` 块内构造，不依赖 `expire_on_commit=False`。
  实跑 `pytest -q` 526 passed（unit 344 / integration 173 / e2e 9）、`ruff check --no-cache .` 绿、
  `npm run build` 绿；临时库浏览器实测预览文案/归并/未解锁 403/375px 无溢出。无迁移、无新依赖。
- 背景：AGENTS §6"细粒度受控生长（优先复用·不覆盖确认值·**归并需人工确认**）"只交付了半条腿——
  `POST /api/concepts/merge` 后端早在 P1-6 就有了（CHANGELOG:1037），但前端**零调用**
  （`endpoints.ts` 只有 `listConcepts`(:172) 与 `createConcept`(:181)，**没有 merge 封装**），
  家长没有任何入口把重复建出来的细粒度点并掉。
- **盘上现状（审核方逐行核过，写卡以此为准）**：
  - 请求体 `ConceptMergeRequest = {source_id: int≥1, target_id: int≥1, actor: "student"|"parent"}`，
    **默认 `actor="student"`**；响应 `ConceptMergeResponse = {source, target, aliases_moved}`。
  - 三个端点（`GET /api/concepts`、`POST /api/concepts`、`POST /api/concepts/merge`）
    **当前都没有 `require_parent`**（`api/concepts.py` 全文无该依赖）。
  - 服务层 `merge_concepts` 的实际约束：只写 `source.merged_into_id` + 把源名称/别名并入目标
    （`ConceptAlias`），**不重写 `mistake_versions`**；错误分支——
    自归并 / 跨 category / 别名与第三方概念冲突 → `ConceptConflict`；
    源或目标已归并 → `ConceptMerged`；概念不存在 → `ConceptNotFound`。
  - 异常继承已核实：`ConceptMerged ⊂ ConceptConflict ⊂ ConceptError(ValueError)`，
    API 层 `except ConceptConflict → 409`、`except ConceptNotFound → 404`，**不会漏成 500**。
  - 现成可复用：`resolve_concept_map` / `resolve_concepts`（历史 id 沿 `merged_into_id` 解析到最终概念）、
    `concept_family_ids`（最终概念 + 所有已归并源，供检索展开）、
    `list_concepts` 已过滤 `merged_into_id.is_(None)`（归并后源点自然消失）。
- 交付：
  - 后端：`POST /api/concepts/merge` 加 `require_parent`（归并 = 家长动作）；
    **`GET /api/concepts` 与 `POST /api/concepts` 保持孩子区不动**（别一并锁，会断掉
    孩子边做边长标签的路径）；请求侧要求 UI 传 `actor="parent"`。
  - 新增**只读预览**能力：`GET /api/concepts/merge-preview?source_id=&target_id=`
    返回 `{source, target, source_aliases: string[], affected_mistakes: int, same_category: bool}`；
    `affected_mistakes` = 当前版本题面 `confirmed_concept_ids_json` 含源点 id 的 **active** 错题数
    （扫描方式参照 `dashboard.py:228` 的现成写法，不新建表）。
  - 前端：错题详情的知识点区（`MistakeDetailPage` 已管理 `concepts`/`listConcepts`/`createConcept`）
    新增"归并知识点"入口，**仅家长解锁可见**；两个选择器**限定同一 category**（跨 category 后端会 409）；
    确认框显示"源名称 → 目标名称、将并入 N 个别名、影响 M 道错题"，
    范式照抄 `LocalSeedPage` 的删除确认（:496 "将解绑错题 N 道…"）；成功后刷新列表。
- DoD：
  - 归并后 `merged_into_id` 与别名生效、`GET /api/concepts` 列表只出目标点、
    历史 `mistake_versions` 的 `confirmed_concept_ids_json` **逐行一字不改**（全表快照断言）；
  - 名称解析走合并家族（`resolve_concepts` 把源 id 解析到目标；`concept_family_ids` 含源）；
  - **未解锁调用 merge/preview 返回 403**；建点与列表在未解锁时仍可用（防"一并锁死"回归）；
  - 错误分支各有断言：自归并 409、跨 category 409、别名与第三方冲突 409（消息含"请先归并那个概念"）、
    源或目标已归并 **409**（⚠️ **不是幂等成功**——本票原写"重复归并幂等"是审核方误判，
    实际 `ConceptMerged` → 409，且不产生新行）、不存在 404；
  - `affected_mistakes` 与实扫结果一致（测试里造 2 道挂源点的 active 错题 + 1 道 voided，断言只计 active）；
  - 窄屏可用；`pytest -q` 全绿（当前基线 523 passed）、CI 绿、`ruff check --no-cache .` 绿、build 绿。
- 禁止：物理删除 concept 行；改写 append-only 历史标签；把归并开放给孩子区；
  **顺手把 `POST /api/concepts`（建点）也锁上 PIN**；引入"自动检测重复点并合并"的模型/相似度猜测；
  新建归并历史表或改 `Concept` 表结构（本票**零迁移**）。
- **交付状态（2026-11-04）**：已合并 PR#37（`main` = `3fc6e48`），含一次审查返工
  （`projected_aliases_moved` 与真实 `aliases_moved` 同源；预览响应构造移入事务块）。
  审核方实跑 526 passed、归并专项 4 passed、`ruff --no-cache` 绿、build 绿、CI 双绿。

### P1-13b 归并弹窗取消预选（产品决定，2026-11-04 拍板）
- **决定**：归并弹窗**一律不预选**源或目标。
- **理由**：源是"会被并掉、从列表消失的那个"，方向性后果不该由默认值替家长决定；
  错题只有 1 个 concept 时预选为源，恰好是最容易一次点错的场景。
- **现状**：`MistakeDetailPage` 打开弹窗时，若当前错题只有 1 个 concept 会把它预选为**源**，否则留空。
- 交付：删掉该预选逻辑，两个选择器初始都为空；未同时选好源与目标时确认按钮禁用
  （现有 `merge-preview` 只在两者都选定后请求，保持不变）。
- DoD：断言"打开弹窗时源与目标均为空"（含错题只有 1 个 concept 的场景）；
  断言未选齐时不发 preview、不可提交；其余归并行为与断言一字不改；
  `pytest -q` 全绿（当前基线 526 passed）、CI 绿、`ruff check --no-cache .` 绿、build 绿。
- 禁止：改归并语义 / 权限 / 预览契约；顺手加"智能推荐目标"（相似度猜测，P1-13 已禁）；
  改 `Concept` 表结构（**零迁移**）。
- **状态：已合并（2026-11-04，PR#38 squash → main `18f81b9`，随 `v0.5.0` 发布；原分支
  `feat/p1-13b-no-preselect` 已删）**：打开弹窗时源/目标
  均为空（只有 1 个 concept 也不预选）；未选齐不发 `merge-preview`、确认按钮禁用；选择器与
  顶部提示明示"源=将被并入消失 / 目标=最终保留"。前端抽 `src/pages/mergeSelection.ts` 纯函数，
  新增 Node 内置 test runner 单测 5 条（`npm test`），CI web job 增加该步骤；后端/权限/预览契约
  零改动、既有归并集成断言一字未改。零迁移、无新依赖。

### P1-16 题目图片附件写入路径激活（v2.7 D5；零迁移，唯一新依赖 python-multipart）
- **现状（2026-11-11 读盘）**：`mistake_versions.problem_images`（`models/mistakes.py:61`，Text 可空）
  为死字段，全仓零引用；`uploads/` 只在备份打包出现（`services/backup.py:225`，
  `_add_tree(zf, data_dir / "uploads", "uploads", files)` 目录名硬编码）；`core/config.py` 无 uploads
  路径定义（仅 `data_dir`:32）；全仓**无任何** StaticFiles mount / 下载端点 / multipart 上传端点；
  `requirements.txt` **无 python-multipart**。§18 D5 原文误写 `mistakes.problem_images`，已更正为
  `mistake_versions.problem_images`（当前版本行）。
- 交付：
  - `core/config.py` 加 `uploads_dir` property = `data_dir / "uploads"`（与备份打包同名，不得出现第二个目录）；
  - `requirements.txt` 加 **python-multipart**（FastAPI 收文件前置，小库；本票唯一新依赖，CHANGELOG 点名）；
  - 上传 `POST /api/mistakes/{id}/images`（孩子区免 PIN，与 `/labels` 同级）：multipart 单文件；
    校验 MIME 白名单（jpeg/png/webp）**且魔数校验**（不看扩展名）、单文件 ≤5MB、单题 ≤3 张；
    落盘 `uploads/<mistake_id>/<uuid4>.<ext>`——原始文件名绝不进路径；当前版本 `problem_images`
    写 JSON 相对路径数组；
  - 读取 `GET /api/mistakes/{id}/images/{index}`（孩子区）：只允许解析到 `uploads_dir` 内（前缀断言），
    返回 bytes + 正确 Content-Type；**禁 StaticFiles 挂 data_dir**（会连带暴露库与 inbox）；
  - 删除：仅可移除列表内本票上传的文件（移除数组项 + 删文件，删除路径必须在 uploads 内断言）；
  - 前端：`MistakeDetailPage` 在 `standard_answer` 展示块（:479-484）后加"原题图"区——缩略图并排
    （img 走读取端点）、上传按钮（≥3 枚后置灰）、移除按钮（确认框）；
  - **核对页附件不做**（草稿生命周期未收敛会留孤儿文件；真需求出现另开小票）。
- DoD：上传→详情可见→备份 zip 含该文件（集成断言）；非白名单 MIME / 魔数不符 / >5MB / 第 4 张 → 422 稳定码；
  文件名注入（`../`）不可达（存储路径断言 uuid 形态）；删除只影响 uploads 内本文件；
  `pytest -m e2e` 加 1 条（上传→揭示→备份包含）；全量绿 + `ruff check --no-cache` + build；
  **零迁移**（head 保持 0021_pomodoro_sessions）。
- 禁止：挂 StaticFiles 或暴露 uploads 之外的任何目录；引入 OCR/VLM/模型调用（零模型红线）；
  `problem_images` 出现第二条写入路径；存原始文件名；放行 SVG/HTML（XSS 面）。

### P1-17 订正笔记 correction_notes（v2.7 D6；迁移 0022 + 模板 version 2）
- **现状（2026-11-11 读盘）**：全仓无 `correction_notes`；`FIELD_LIMITS`（`services/ingestion.py:19-29`，
  9 键）无此键、未知字段静默丢弃（:111）；模板 `docs/templates/doubao_transcribe_v1.md` frontmatter
  `id: doubao_transcribe` / `version: 1`、`schema_fields` 8 键（:6）；确认请求 `DraftConfirmRequest`
  （`api/imports.py:118-124`）= primary_topic_id/standard_answer/error_cause/concept_ids/question_type/actor；
  确认映射 `services/intake.py:339-378`；mistakes **无内容编辑 PATCH**（只有 `/labels` :346）。
- 交付：
  - 迁移 **0022**（可逆；0021 已被 P2-2b `pomodoro_sessions` 占用，施工时仍取 alembic head+1）：
    `mistake_versions` 加 `correction_notes` Text 可空（应用层 ≤500 校验，不加 CHECK）；
  - 契约：`FIELD_LIMITS` 加 `correction_notes: 500`；模板 **version 1→2**（改语义必递增），
    `schema_fields` 加 `correction_notes`，规则写明**只转录卷面孩子/家长手写内容，agent 不得自产讲解**；
    P0-2 黄金样例补含/不含 notes 的对照；
  - 写入三径：核对页确认 payload 加可选 `correction_notes`（`DraftConfirmRequest` + `IntakePage` 确认表单，
    空 = 不存）；`ImportPage` 手填表单加同名可选字段；`services/intake.py` 确认映射写入当前版本；
  - 展示与编辑：`MistakeDetailPage` 与 `standard_answer` 并排展示（MathText 渲染）；
    编辑 = 新 `POST /api/mistakes/{id}/notes`（孩子区免 PIN，actor ∈ {student, parent}），
    **追加版本行**（复用现有版本追加机制，绝不改写历史版本）；
  - 定位条款（AGENTS §5 已写）：讲解移出系统 = 系统不生成讲解，不禁存手写笔记；笔记**纯展示数据**，
    不进判分、排期、掌握度任何链路。
- DoD：迁移 up/down/up + DDL before/after（P0-3 守卫）；模板 version 2 生效（加载器读到新值）、
  黄金样例回归通过；转录带 notes → 草稿 → 确认 → 详情显示；不带 → NULL；>500 → 422 不写盘；
  编辑追加版本行、历史版本行逐行不变（全表快照断言）；`pytest -m e2e` 加 1 条（转录→确认→显示→编辑→版本追加）；
  全量绿 + `ruff check --no-cache` + build。
- 禁止：agent 自产讲解文本入契约（违规打回）；把笔记接入判分/排期链路；改写历史版本行；
  借本票引入任何 AI 生成路径；把 `correction_notes` 做成必填（会挡掉整类入本）。

### P1-18 主考点可设定与更正（v2.8 §19-I；零迁移；改根表 + 事件审计）
- **状态：已合并（2026-11-14，PR#55 squash → main `1c1a951`；原分支 `feat/p1-18-primary-topic` 已删）**。
  验收：749 passed / `ruff --no-cache` 绿 / `npm test` 32 / CI 三 job 全绿 / CDP 真机三态取证；
  变异（从幂等键里拿掉 `to_topic_id`）→ 2 测红 → 还原复绿。
  ⚠️ **残留边界见 §19-J，已另开 P1-18b**：卡里钉的幂等键把恒定不变的 `base_version` 当唯一性维度，
  `A→B→A→B` 循环回改会吞掉第 3、4 次审计事件（数据正确、审计不完整）。**责任在审核方写卡，非施工偏差。**
- **现状（2026-11-14 读盘）**：
  - `primary_topic_id` 只在**根表** `mistakes`（`models/mistakes.py:41`，索引 `:50`）；全仓唯一写入点
    `services/mistakes.py:256`（核对页确认经 `api/imports.py:244`）。`/labels`（`api/mistakes.py:376`、
    `LabelRequest:111`）与 `append_label_version`（`services/mistakes.py:418-514`）**全程不碰它**。
  - ⚠️ **口径纠正（§19-I 原写"走追加版本"是审核方错误，本卡改对）**：`append_mistake_version`
    （`services/events.py:90-147`）参数里**没有 `primary_topic_id`**，版本表也无此列——追加版本承载不了主考点变更。
    append-only 触发器只钉 `mistake_versions`（0008:115）与 `learning_events`（0002:55），
    **根表 `mistakes` 未被钉**（void/unvoid 本就就地翻 `status/updated_at`）。
    → 正确做法：**写根表 + 追加一条事件做审计**，**不 bump `current_version`、不追加版本行**。
  - 下游现状（都是好消息，无需额外重算）：`bank.find_same_type`（`bank.py:395`）对 `None` → `topic_id=""`
    → 空池 → `coverage="gap"` 不抛错；`due_queue`（`review.py:988`）每次**现算** quiz/self_eval/redo，
    无落库 kind、无缓存 → 设值后下一次 due 自动出 quiz；学科卡读根表（`list_mistakes:633 → subjects.subject_for_topic`）
    → 设值后自动归位；`MistakeDetail` 响应（`api/mistakes.py:78-213`）**不含** `primary_topic_id`，详情页也不展示。
- 交付：
  ① 新端点 `POST /api/mistakes/{id}/primary-topic`，请求体 `{primary_topic_id: str | null, actor ∈ {student, parent}, base_version: int}`；
     **孩子区免 PIN**（与 `/labels`、`/notes`、`/images` 同级同口径）；
  ② 语义：`base_version != current_version` → 409（乐观锁，同 `append_label_version:435`）；`voided` → 409（同 `:433`）；
     目标值与现值**相同 → 幂等 no-op**（不写事件、不改 `updated_at`，返回当前详情）；
     `primary_topic_id = null` **允许**（撤销误设）；非空值必须存在于 `knowledge_seed`，否则 422 稳定码；
  ③ 写 `mistakes.primary_topic_id` + `updated_at`；追加一条 `learning_events`，新 type
     `mistake_primary_topic_set`，payload 只含 `from_topic_id / to_topic_id / actor / base_version`
     （**不含题干、答案、路径**），幂等键
     `mistake:{id}:primary-topic:{base_version}:{to_topic_id 或 "null"}`（同请求重放不产生第二条）；
  ④ `MistakeDetail` 补 `primary_topic_id` 与 `primary_topic_subject`（复用 `services/subjects.subject_for_topic`，
     **前端不得另建 topic→subject 映射**）；
  ⑤ 前端 `MistakeDetailPage`：展示主考点（含「未挂考点」态）+「设定/更正主考点」控件，
     复用 `CategoryPicker`（与 `IntakePage.tsx:241-256` 同款），支持清除；核对页交互与转正闸门一字不改。
- DoD：
  - **审计与不变量**：改一次恰新增 1 条 `mistake_primary_topic_set`；同值重复提交 0 新增；
    `mistake_versions` 行数与 `current_version` **保持不变**（专门断言，防有人误走版本表）；不改动任何历史事件。
  - **掌握度不受影响**：改主考点前后对全部 concept 跑 `recompute.mastery()` 结果全等（钉住"主考点不参与掌握度"）。
  - **排期不被抹掉**：既有 `review_schedules` 行数与 `due_date` 不变；改后同一 `today` 的 due 中该题
    `kind` 由 redo/self_eval 变 quiz（题库有题时），题库无题则 `bank_gap=true` 且不报错。
  - **学科卡归位**：该题从「未挂考点」移到真实学科，`inventory.unassigned_active` 相应减 1（与 P2-13 算式自洽）。
  - 权限与错误：未解锁可用；`base_version` 过期 409；voided 409；未知 topic 422；清除为 null 生效。
  - `dashboard.event_stats` 若为精确按类型断言，**按新增 type 补键值**，不得为省事改成宽松匹配。
  - 前端取证：设定 / 更正 / 清除三态 + 360/412 无横向溢出（截图 + report.json 存档路径）。
  - 全量 `pytest -q` + `ruff check --no-cache` + `npm run lint/test/build` 绿；**零迁移**（列与索引已存在）。
- 禁止：自动推断或模型建议主考点（零模型 + "不猜"红线）；批量"一键补全"脚本（无真值即猜测）；
  把主考点写进 `mistake_versions` 或为此 bump `current_version`；让主考点参与 `mastery`/排期算法/streak
  （`streak.LEARNING_EVENT_TYPES` **不收**新 type）；更新或删除历史事件；改核对页交互与转正闸门语义；
  给该端点加 `require_parent`（与同级标签端点不一致，要改须先改设计口径）。

### P1-18b 审计事件幂等键的"往返维度"纠偏（v2.8 §19-J；零迁移；同类三处调用点）
- **状态：已合并（2026-11-15，PR#56 squash → main `27b1c0f`；原分支 `feat/p1-18b-audit-key-nonce` 已删）**。
  验收：全量 **752 passed**（审核方自跑 550.30s）/ `ruff --no-cache` 全仓绿 / `tsc --noEmit` 干净 /
  `npm test` 32 / `selfcheck --strict` 18 OK 0 DRIFT / CI 三 job 绿。
  **审核方三次变异**：删 primary 的 `n` → 3 红；删 void 的 `n` → 3 红（含 e2e）；
  **关掉同值状态级早退 → 2 红**（证明"重试 0 增"不是空话，但防线是**早退不是键**，见下条 ⚠️）。
  范围 4 文件 +237/−16（含 `CHANGELOG.md`——AGENTS §8 DoD 必需项，本卡原写"只碰 service+测试"是审核方写漏）。
  ⚠️ 本卡【现状】行号为交付前快照（`1c1a951`），P1-18b/P2-11 后已漂移：三处键现位于
  `mistakes.py:399-401 / 437-439 / 590-592`，`_next_event_seq` 在 `:349`，`dashboard.py` 的
  `void_events`/`reactivate_events` 从 508-509 移到 **581-582**。
- **现状（2026-11-14 读盘 main `1c1a951`）**：
  - `_insert_or_fetch`（`services/events.py:25-39`）同 `idempotency_key` 撞 UNIQUE → 回滚 savepoint、
    取回旧行、`created=False`：**静默吞事件**，不报错、不追加。
  - `UNIQUE(idempotency_key)`（`models/events.py:26`，Text，迁移 0002:47-48），**无长度 CHECK → 加长键零迁移**。
  - 键里含**恒定不变维度**的三处调用点（同一错误类，不止 P1-18）：
    `mistakes.py:561-564` `mistake:{id}:primary-topic:{base_version}:{to}` —— 本端点**不 bump `current_version`**，
    `base_version` 恒定，区分度只剩 `to` → `A→B→A→B` 塌成 2 条；
    `mistakes.py:377` `mistake:{id}:void` 与 `:412` `mistake:{id}:reactivate` —— 完全无变化维度
    → `作废→撤销→再作废` 的第二次作废事件被吞。
  - **后果不止审计**：`dashboard.py:508-509` 的 `void_events`/`reactivate_events` 与
    `recompute.stats()`（`recompute.py:155-163`）的 `event_stats.by_type` 都**按事件行数计数**
    → 看板的"作废/恢复次数"与事件分布会**少计**（掌握度/排期/streak 不读这几个 type，不受影响）。
  - **为什么幂等键在这里其实是第二道闸**：三个函数都先做**状态级早退**
    （`set_primary_topic:549` 同值 `return mistake`；`void_mistake:365`、`unvoid_mistake:400` 状态已是目标值 `return mistake`），
    同值重试**根本走不到 `record_event`**。→ 给键加区分度，**不会**把"重复提交"变成"重复事件"。
- 交付（口径唯一，键的每个组成部分必须在真实调用序列里真的会变）：
  ① 三处键各补一个**单调序号维度** `n`：`n` = 该 mistake 下同 type 已有事件行数（
     `select func.count()` 于同事务内取），键形如
     `mistake:{id}:primary-topic:{base_version}:{n}:{to|null}`、`mistake:{id}:void:{n}`、`mistake:{id}:reactivate:{n}`；
  ② **不引入随机 UUID、不引入时钟桶、不关掉去重**（§5 可确定性重放纪律；序号是事实推导值，与 `v{version}` 同构）；
  ③ 既有事件**一字不动**（append-only，绝不回填/改写历史键或 payload）；旧键与新键天然不撞，历史链不回溯补齐；
  ④ 不动 payload、不动根表写入语义、不动 409/422/乐观锁、不动版本表与 `current_version`。
  ⑤ **既有 7 处字面键断言按新格式逐条更新、只紧不松**：`test_mistakes_api.py:409/:415/:1959-1960/:2002-2003/
     :2019-2020/:2076-2077` + `e2e/test_closed_loop.py:708-711`；严禁改成 startswith/宽松匹配/删断言。
     另：`test_mistakes_api.py:2033` 的 docstring 说"去掉 `to_topic_id` 会塌成 1 条"，**加了 n 之后这句话失效**
     （断言仍为绿，但防线移到 n 维度）——**docstring 必须同步改口径**，不许留与代码相反的历史叙述。
- DoD（每条都要能变异证伪）：
  - **往返锚点**：`A→B→A→B` 恰 **4 条** `mistake_primary_topic_set`，`from/to` 逐条正确（现有锚点
    `tests/integration/test_mistakes_api.py:2033` 只钉 `A→B`，**保留不弱化**）；
    `作废→撤销→作废→撤销` 恰 2 条 `mistake_voided` + 2 条 `mistake_reactivated`。
  - **重试仍不增行**：同值重复提交 / 已作废再作废 → 事件数 0 增、`updated_at` 不变（钉住"序号不是重复计数器"）。
  - **看板计数对齐**：上述往返序列后，`void_events`/`reactivate_events` 与 `event_stats.by_type`
    的读数 == 现场实际事件行数（独立重算双向对齐，不许写死期望值迁就实现）。
  - **不变量**：`mistake_versions` 行数与 `current_version` 全程不变；`streak.LEARNING_EVENT_TYPES` 不收新 type；
    主考点不参与 mastery/排期（沿用 P1-18 的既有断言，不得删）。
  - **零迁移**：键是应用层字符串；`git diff` 不得出现 `migrations/`。
  - 全量 `pytest -q` + `ruff check --no-cache` + `npm run lint/test/build` 绿；前端无改动（纯服务层）。
- 禁止：为凑断言去改历史事件/回填旧键；把去重整个删掉；给键加 `uuid4` 或 `datetime.now()`（不可重放、且并发下无意义）；
  顺手扩到 `review.py:557` `review:schedule:{id}:init`（**init 每错题恰一次是有意设计，本票不动**）、
  `recitation.py:602`（按日粒度为既有产品口径）、`grading.py:217`/`mistakes.py:505`（已含 `v{version}` 变化维度，本就正确）。
- ⚠️ **本卡修订记录（审核方自我纠正）**：§19-J 初稿推荐"秒级时间戳桶"，读盘确认三处都有状态级早退闸后
  **改为事件序号 `n`**——时钟桶会让同秒内的真实往返仍然塌缩、且测试须注入时钟；序号确定性可重放、可断言。
  现有代码与本卡不符时以实际代码为准，先读再改，不一致上报不要硬凑。
- ⚠️ **交付后两条补记（2026-11-15，审核方，勿静默改口径故留痕）**：
  ① **本票第 2 条投单纪律把范围写窄了**（"只应碰 `services/mistakes.py` + 相应测试文件"），
  而 AGENTS §8 的 DoD 明确要求更新 CHANGELOG——施工方没自作主张、把它单列成复核点并给了剔除命令，
  裁定**保留**。→ 出卡写范围清单时必须先对齐 §8 DoD，这是审核方第 12 次卡面口径疏漏。
  ② **重试去重的真正防线是状态级早退，不是幂等键**（变异 C 证实：把 `set_primary_topic` 的同值早退改成恒假，
  "同值重试 0 增"与往返锚点立刻 2 红）。今后任何人删/改那几个 `return mistake`，同值重试会各落一条事件——
  这条耦合**已由 `test_same_value_and_same_state_retries_add_no_events` 钉住**，不得当作键的功劳。

---

## Phase 2 —— 每日任务 + 收口看板
- **P2-1 日队列自动生成**：到期复习（含同类题考核优先/重做兜底）+ 固定背诵铺底、作业按 deadline 插入、硬事件抬权重。禁：时间块排课。
- **P2-2 番茄钟执行**：对下一项计时、完成打点入 `learning_events`。
- **P2-3 课表/日历约束层**：录入生效喂 P2-1。禁：课表当任务源主体。
- **P2-4 两角色 + 本地 PIN**：孩子默认视图 / 家长 PIN 解锁。禁：公网账号体系/多租户。
- **P2-5 家长看板（观察复盘型）**：只读确定性统计（错题存量、掌握度曲线、到期队列、`bank_gap`、申诉数、信奥待重做）。**叙述性周报**（可选）由外部 agent 生成、以"来源=ai"存字段、不进判分/排期。孩子见同一份。禁：实时催/锁屏/问责；禁：wengu 内核调模型生成周报。
- **P2-6 极简打卡**：streak + 掌握度曲线（从事实重算）。禁：积分/徽章。
- **P2-7 错题 PDF 四区块导出打印**（原题+作答+解析批注来自卷面/外部 + 同类题组卷导出；按知识点/章节聚合）。
- **P2-8 移动端导航溢出（真机发现，未开工）**：`wengu-web/src/components/AppLayout.tsx` 的
  `AppShell.Header`（固定 `height: 56`）里，品牌文字与页签组都是 `Group wrap="nowrap"`，
  页签共 **11 个**（孩子可见 8 个 + 家长解锁后追加 3 个），**没有换行、没有横向滚动、没有折叠菜单**
  → 窄屏上溢出的页签被裁掉且**滑不出来**。
  - **真机证据**（2026-11-05，安卓曲面屏，家长未解锁状态）：最后一枚可见页签是「复习考核」，
    其右侧内容直接消失，用户确认无法横向滑动。
  - **为什么不是外观问题**：家长解锁后会多出「题库审核 / 学科 seed / 备份」三枚，
    按同一布局它们极可能**完全点不到**——那会把手机上唯一的备份入口和 seed 管理一起锁死。
    开工前先确认这个推论（手机解锁家长区后看三枚页签是否可达），据实调整严重度。
  - **修法已定案（v2.7 D1，2026-11-11 确认）**：左侧分组 sidebar + 窄屏 drawer（原开放选型保留下文供追溯），但**必须解决"页签数量还会继续增长"这件事**：
    ~~A) 窄屏折叠汉堡 + Drawer；B) 页签条横向滚动；C) wrap 换行加高 header~~（开放选型已被 v2.7 D1 取代）。
    定案实施要点：`AppShell` 加 `navbar`（现仅 `header={{height:56}}`，`AppLayout.tsx:38`）；
    `NAV` 数组（:16-28，`{to,label,parentOnly?}`）按 `parentOnly` 拆孩子/家长两组，家长组仅解锁渲染
    （`useParentSession().unlocked`，:33）；桌面常驻 sidebar、断点以下汉堡 + Drawer；
    移除 header 内两处 `Group wrap="nowrap"` 页签组（:40/:49）；分组/过滤抽纯函数供单测。
  - DoD 要点：360px 与 412px 两档宽度下、**家长解锁态（11 枚全出）**逐个断言每个导航目标可达
    （`documentElement.scrollWidth === clientWidth`，且开启菜单后每项的包围盒落在视口内）；
    桌面宽度布局不回退；`npm run lint` / `npm run build` 绿、CI 绿；零迁移、零新依赖。
  - 禁止：为省事删页签或合并功能入口；把导航改成底部 Tab Bar 之类全站重构（除非实测证明 A/B/C 都不成立）；
    顺手改 `AppShell` 之外的页面布局。
  - **DoD 度量法修订（v2.7，审核方确认）**：盘上无 DOM 测试栈（`npm test` = node --test 纯函数，
    无 vitest/jsdom/playwright）→ 可达性断言改为 ① NAV 分组/过滤抽纯函数 + Node 单测
    （断言 11+3 分组与解锁过滤）；② 真机/手工浏览器 360/412 两档、家长解锁态逐枚点击可达 +
    `documentElement.scrollWidth === clientWidth`，截图与 console 输出贴 PR。
    **不为此引入 DOM 测试栈**（新重依赖，反清单）。断言对象不减弱，只换度量手段。
  - **状态：已合并（2026-11-11，PR#43 squash → main `cdb4ba4`；原分支 `feat/p2-8-sidebar-nav` 已删）**：`AppLayout` 改为左侧
    分组 sidebar（孩子组 8 / 家长组 3，仅解锁渲染）+ `sm` 以下汉堡 Drawer；header 内两处
    `Group wrap="nowrap"` 页签组已移除。`src/lib/nav.ts` 提供 `groupNavItems` / `isNavActive`
    纯函数，`tests/nav.test.ts` 5 条 Node 单测（11 项总数、未解锁过滤、8+3 分组与顺序、不改入参、
    路径高亮）。手工浏览器 + CDP 360×780 / 412×915 两档、家长解锁态 11 枚逐枚点击：路径全部命中、
    两档横向溢出 0、11 项包围盒全在视口内、点击后 `aria-current` 指向该项；1280px 桌面 sidebar
    常驻、汉堡隐藏、11 项全可见。`npm run lint` / `npm run build` / `npm test` 绿；零迁移、零新依赖。

### P2-2b 专注计时：进行中轮次服务端续走 + 时长可设（v2.7 D7，缺陷修复）
- **背景（2026-11-11 读盘）**：`PomodoroTimer.tsx` `TOTAL_MINUTES=25`(:8)、纯 `useState+useRef+setInterval`(:42)，
  **刷新/切页即丢一轮**（仅挂载 `ReviewPage.tsx:499`，index===0）；后端只有 `POST /api/pomodoros`
  （`api/pomodoro.py:40-42`，`PomodoroCreate` = mistake_id/duration_minutes/started_at/completed_on/actor），
  只收"已完成"轮；`clamp_duration` 5–120（`services/pomodoro.py:45-50`）；幂等键
  `pomodoro:{started_at ts}`(:90)；事件 `pomodoro_completed`(:27)；**无进行中会话表**。
- 交付：
  - 新可逆迁移（编号施工时取 alembic head+1，预计 0021）建 `pomodoro_sessions`
    （id/started_at/planned_minutes/mistake_id/actor/status ∈ {active,completed,abandoned}）；
  - 端点（孩子区免 PIN，与现有 recordPomodoro 同权限）：`POST /api/pomodoros/start`、
    `GET /api/pomodoros/active`（返回进行中轮供续走）、`POST /api/pomodoros/{id}/complete`
    （body duration_minutes = 实际分钟，**保留提前完成**）、`POST /api/pomodoros/{id}/abandon`；
  - complete 按现有语义写 `pomodoro_completed` 事件（payload 键不变）+ session 置 completed；
    abandon 不写事件；complete 两次命中现有幂等键 + session 状态守卫，不产生第二条事件；
  - 前端：挂载时 GET active → 按 remaining = planned - (server now - started_at) 续走；
    时长选择器 5–120（默认 25）；删 TOTAL_MINUTES 硬编码；切页/刷新/换设备可续。
- DoD：迁移可逆 + DDL before/after（P0-3 守卫）；集成：start → 模拟新客户端 GET active → complete →
  事件恰 1 条；abandon → 无事件；duration 4/121 → 422；complete 两次不重复；看板番茄统计不变；
  全量绿 + `ruff check --no-cache` + build；窄屏可用。
- 禁止：改 `pomodoro_completed` 事件语义/payload 键（看板依赖）；引入暂停语义（本票不做）；
  前端 localStorage 当真源；abandon 写事件；顺手重构 ReviewPage 其它逻辑。

### P2-9 错题本：全文搜索 + 掌握状态筛选（v2.7 D8）
- **现状（2026-11-11 读盘）**：`GET /api/mistakes`（`api/mistakes.py:246-253`）参数
  status(active/voided/all)/category_id/concept_id/error_cause/limit/offset，**无搜索参数**；
  `MistakesPage.tsx` 硬编码 `status:"active"`(:56)，筛选仅 categoryId/errorCause；
  `endpoints.ts` `MistakeFilters.status` 已支持三值(:67)。
- 交付：后端加可选 `q`（≤100 字符，超 → 422）：对**当前版本** `problem_text` + `standard_answer`
  大小写不敏感 LIKE；加可选 `mastery_state` ∈ {pending, consolidating, graduated}：
  graduated = recompute 毕业（错数归零 + 尾部连对 ≥3）、consolidating = 未毕业且 rung≥1、
  pending = 未毕业且 rung==0，**全部由 review_schedules + recompute 推导，不加新列**；
  前端搜索框 + 状态 Select（全部/待复习/巩固中/已掌握），与现有筛选可组合。
- DoD：q 命中题干/答案各有断言；空 q = 不过滤；mastery_state 三值各造 fixture 断言
  （rung0/rung1/graduated）；与 category/error_cause 组合过滤正确；超长 422；
  全量绿 + `ruff check --no-cache` + build；窄屏无横向溢出。
- 禁止：引入 FTS5/虚拟表/搜索依赖（LIKE 足够）；把掌握状态存成列；搜 mistake_versions 历史版本；
  顺手改 void 语义或列表分页契约。

### P2-10 回收站视图：已作废列表 + 恢复入口（v2.7 D8）
- **现状（2026-11-11 读盘）**：软删 active/voided；`POST /api/mistakes/{id}/void`(:295-299) /
  `/unvoid`(:322-326) 均 `require_parent`；`MistakesPage` 恒查 active(:56)，作废题仅详情页可达
  （`MistakeDetailPage.tsx:342/:364`）——**删了却找不到恢复入口**。
- 交付：MistakesPage 加"在本 / 回收站"视图切换，**回收站仅家长解锁可见**；回收站视图走
  `listMistakes status:"voided"`（封装已支持）；每行"恢复"→ 现有 `unvoidMistake`（**不新增端点**）；
  确认框范式照抄 LocalSeedPage；恢复后刷新两视图并显示计数。
- DoD：unlocked=false 入口不可见且 unvoid 403（既有）；集成复用 e2e ② 路径：
  void → 退出 due → unvoid → 回到 due；零迁移、零新端点；全量绿 + `ruff check --no-cache` + build。
- 禁止：新写恢复端点；物理删除；把回收站暴露给孩子区；顺手改 void/unvoid 权限。

### P2-13 看板信息层级：主 CTA + 各科入口卡（v2.7 D2；零迁移）
- **现状（2026-11-14 读盘）**：`DashboardResponse`（`api/dashboard.py:118-134`）里
  `weak_subjects` = `SubjectWeaknessView`（`:34-36`）**只有 `subject` + `active_mistakes` 两键**，
  不含掌握度与收录总数；`DashboardPage.tsx:306-498` 是"标题 → ScheduleBrief → StreakCard →
  9 张 MetricCard → 曲线+知识点表 → 薄弱分布+题库缺口 → 事件事实"，**没有任何主 CTA、也没 import react-router**；
  硬编码色在 `:100/:108/:111/:201`。
  > 存档提示（2026-11-15）：本条是 P2-13 **交付前**的读盘快照，故意不改。P2-13 合并（`b996f9a`）后
  > `DashboardPage.tsx` 整体下移 4 行，硬编码色现在是 **`:104/:112/:115/:205`**；
  > 给 P2-11/P2-14 用的现行行号以它们自己的卡与 §19-K 为准。
- ⚠️ **两条读盘纠正（§18 D2 原设想踩空的点）**：
  ① **`category_id` 不是学科**——它是 `knowledge_seed.id`（粗粒度知识点，`Concept.category_id`、
  `mistake_versions.confirmed/suggested_category_id` 都指它）；学科在 `KnowledgeSeed.subject`（`models/knowledge.py:20`），
  看板学科是 `_weak_distribution`（`services/dashboard.py:312-342`）用 topic_id 反查 seed 得到、
  查不到落 `UNASSIGNED_SUBJECT="未挂考点"`（`:68`）。所以"点学科卡进该科列表"**不能复用 `category_id`**。
  ② **"已掌握"在盘上有两个语义不同的入口**：`recompute.is_graduated()`（`:142`，按 mistake 的
  `attempt_correct/wrong` 全事件尾部连对 ≥ `GRADUATION_STREAK`，看板 `graduated_total` 用它）vs
  `review_policy.mastery_state()`（`:62`，经 `review.py:495 derive_review_state` 重放 `review_scheduled`+review 事件，
  错题本筛选 P2-9 用它）。**本票口径唯一 = `is_graduated`**；⚠️ 但它与看板 `graduated_total` **不同源**——
  后者沿用旧口径、**不按 status 过滤**（含"已作废但曾毕业"），所以 `sum(subjects[].graduated) == graduated_total`
  数学上不成立（原卡据此写断言是审核方错误，交付时已修正为下方可证伪的三条）；
  若实现中发现两口径对同一数据集给不同数，**上报不要自行折中**。
- 交付：
  ① `GET /api/dashboard` 新增 `subjects: [{subject, active, graduated, total}]`——`active`=该学科在册未掌握数、
     `graduated`=该学科 `is_graduated` 数、`total = active + graduated`（**voided 不计入任何一项**）；全部现算、不存列；
  ② 主 CTA「开始今日复习」→ 跳 `/review`（`DashboardPage` 首次引入 `useNavigate`）；`due.total === 0` 时
     CTA 文案改「今天没有到期复习」并仍可见（不做禁用态，避免孩子以为坏了）；
  ③ 各科入口卡（收录 / 已掌握 + 进度条），点击跳 `/mistakes?subject=<学科>`；
  ④ 为让卡片有真实消费方，`GET /api/mistakes` 新增可选 `subject` 参数（经 seed 反查归并到学科，
     **必须复用 `_weak_distribution` 同一映射**，不得另建第二套 topic→subject 逻辑）；
     `MistakesPage` 从 URL 读 `subject`、显示为可清除筛选项，并计入「清除筛选」覆盖范围（四项 → **五项**）；
  ⑤ 既有 9 张 MetricCard、曲线、薄弱分布**不删不改语义**（只新增）。
- DoD（交付时由施工方反驳、审核方确认并修正——原卡两条算式互斥）：
  ① `sum(subjects[].total) == inventory.active`；② 独立重算 `expected_graduated`（对 active_ids 跑
  `is_graduated`）与卡片 `sum(graduated)` 双向对齐；③ `graduated_total - sum(subjects[].graduated) ==
  已作废且已毕业数`，并做撤销作废往返断言（`graduated_total` 不变、卡片归位）；
  `subject` 参数与既有 `q`/`category_id`/`error_cause`/`mastery_state` 可组合、分页 `total` 为过滤后总数；
  未知学科名返回空集不报错；`/mistakes?subject=` 深链进入即已筛选；
  CTA 跳转有测试或取证；360/412 无横向溢出（取证截图）；全量 `pytest -q` + `ruff --no-cache` + build 绿；**零迁移**。
- 禁止：新建第三套"已掌握"口径；用 `category_id` 冒充学科；为卡片存易变列；删改既有看板区块语义；
  把 dashboard 变成写路径；给卡片加"点击后还要再选一次"的中间步骤。

### P2-13b 打印导出接 `subject`（v2.7 D2 补口；纯前端、零后端改动、零迁移）
- **状态：已合并（2026-11-16，PR#60 squash → main `10c6ec3`；原分支 `feat/p2-13b-print-subject` 已删）**。
  验收：审核方自跑 `npm test` **55/55**、`tsc` exit 0、build ✓、`ruff --no-cache` 全仓绿、
  后端全量 **763 passed / 355.30s**（`git diff -- wengu-api/` = 0 字节）、CI 三 job 绿；
  `groupMistakes` 按**函数体提取后 diff** 证实逐字节未变。
  审核方自主变异：无视 `subject` 解析 → **7 fail**；日期标签只看 `from` 不看 `to` → **1 fail**；
  知识点缺省标签改空串 → **4 fail**；**负变异**（从 `useEffect` 依赖删 `subject`）→ **55/55 仍全绿**。
  - ⚠️ **观察项（带触发条件，暂不排期）**：`PrintMistakesPage.tsx:134` 的 `useEffect` 依赖数组
    **只由 CDP 断言看守、不进 CI**（负变异实证）。现在**不**改造成"单一 `queryKey` 依赖"——
    本票【禁止】已把参数集合冻在 5 个，为假想的第 6 个参数加机制正是反过度工程要挡的。
    **触发条件写死在此**：谁要给打印页加第 6 个筛选参数，**必须先改成单一 `queryKey` 依赖、再加参数**，
    否则新参数会静默漏进依赖数组之外、页眉与实际再次不符。
  - 现行锚点（合并后 `10c6ec3` 实读）：`parsePrintQuery` 调用 `:58`、依赖数组 `:134`、文档头标签 `:174`；
    `MistakesPage` 导出按钮 `:253`；纯函数面 `src/lib/printQuery.ts`（四个缺省字面串 `:10-13`、
    `parsePrintQuery:27`、`printLabels:46`、`printToolbarSummary:65`、`printDocMeta:70`、
    `buildPrintMistakesQuery:83`）。
- **状态：已合并（2026-11-16，PR#61 squash → main `0928104`；原分支 `feat/p5-5-oss-baseline` 已删）**。
  验收：审核方自跑全量 **782 passed / 299.25s**、`ruff --no-cache` 全仓绿、`selfcheck --strict` 18 OK / 0 DRIFT、
  `npm test` 55/55、`tsc` exit 0、build ✓；`git diff -- wengu-api/app/ wengu-web/src` 为空；
  数据条目数 **664 / 1018 / 2803 未扩**、`grade 7-9` 过滤器一字未动。
  ✅ **外部判定达成**：合并后 `gh api repos/beiyunanpeng/wengu --jq .license.spdx_id` 回 **`MIT`**
  （原 `NOASSERTION`）——A 方案的唯一硬指标由服务端确认，不是本地推断。
  - **本票经历过一次打回（两处）**：① `PRIVACY.md` 引文把**教师侧**"严禁将个人信息、考试试题等敏感数据输入
    AI 工具"当成用户侧法规强制、发文主体写成"教育部"（实为**教育部基础教育教学指导委员会**，2025-05），
    现改为如实区分三角色原文 + 把六条 checklist 标注为 **wengu 自定的内部硬门槛**；施工方另主动把 §5
    "另受…约束"改成"以…为自我约束参照"。② **README 前三行定位改写未落地——根因是审核方漏列**：
    TICKETS 的 ① 项在搬进投单块时被我丢掉，故施工方没做符合它收到的票（**审核方第 15 次卡面疏漏**），
    现按 AGENTS §7 补齐（中英两行、移除"AI 学习工作台 / AI learning workbench"）。
  - 审核方自主变异**七次**（跨两轮、全部换靶点）：PRIVACY 字段改坏 / 单侧去 `code_spdx` / `commit_date` 改一分 /
    README 版本句写死 / 发文主体改回"教育部《…》明确" / README 定位改回"AI 学习工作台" / 删"对**学生**"那句
    —— **全部按预期变红**，还原 sha256 一致。
  - **审核方侧未完成项**：仓库 `description` / `topics` / `homepage`、首个 Release、Discussions ——
    均需决策人点头后再执行（Release 的内容边界属对外宣布，不宜顺手发）。
- **现状（2026-11-16 读盘 main `0e960a3`）**：
  - `PrintMistakesPage.tsx:57-60` 只读 `category_id / error_cause / from / to`；`useEffect` 依赖 `:134` 同样只有这四个
    → 传了 `subject` 也不会重新拉数。
  - `MistakesPage.tsx` 的「导出打印」按钮只转发 `category_id` + `error_cause`（构造 `URLSearchParams` 那一段），
    **不转发 `subject`** → 看板学科卡 → 错题本 → 导出，这条链在最后一跳丢筛选。
  - **页眉会撒谎（本票真正的危害）**：`categoryLabel` 缺省"全部知识点"、`errorLabel` 缺省"全部错因"
    （`PrintMistakesPage.tsx:137-147`），工具栏摘要 `:156` 与文档头 `print-meta` `:179` 都用它俩。
    只含数学的一份打印稿会印成"知识点：全部知识点 · 错因：全部错因"——**纸面自述与实际内容不符**，
    而这张纸会直接发到孩子手里。
  - 分组口径**保持不变**：`groupMistakes`（`:31-52`）按 `labels.category_id` 分组、组名取 `category_name`、
    `__none__` 殿后、按 zh 拼音排序，页脚已写"共 N 个知识点页组"（`:180`）。
    ⚠️ **§19-I 原写"接 subject 时分组口径必须一起换"是审核方错误（2026-11-16 读盘推翻）**——
    按学科导出时"一学科下各知识点各成一页组"正是想要的结果，改成分组按学科反而把几十题挤成一组。本票**不动分组**。
  - 后端零改动即可支撑：`api/endpoints.ts:95-97` 的 `listMistakes` 早已支持 `subject`；
    `services/mistakes.py:659-741` 的学科过滤走 `subject_for_topic`（**与看板学科卡同一把尺**，不是 `category_id`）。
    既有行为：未知学科名匹配不到任何行、**返回空集不报错**（入口都是看板给的学科名，暂不额外校验）。
- 交付：
  ① `MistakesPage` 的「导出打印」**转发 `subject`**（与现有 `category_id`/`error_cause` 同段构造，不新增端点、不改路由）；
  ② `PrintMistakesPage` **读取 `subject`**，进 `loadAll` 的 `listMistakes` 入参 **和 `useEffect` 依赖数组**；
  ③ 页眉新增**学科标签**：有值显示「学科：X」、无值显示「全部学科」；
     工具栏摘要与文档头两处**都要带上**（缺一处就是撒谎没修完）；
  ④ 把"参数解析 + 学科/知识点/错因/日期四个标签的拼装"抽成纯函数模块（建议 `src/lib/printQuery.ts`），
     用 `node --test` 覆盖——**本仓禁 DOM 测试栈**，不抽出来就只能靠截图，断不了"标签撒谎"这一类。
- DoD（每条都要能变异证伪）：
  - **逐类各一条，不以一类代全部**（§19-L 纪律②）：`subject` 单独、`subject`+`category_id`、`subject`+`error_cause`
    **三种组合各一条断言**，断言"页眉标签集合"与"实际筛选参数"一一对应——
    特别是 `subject` 单独时**知识点必须显示"全部知识点"、学科必须显示该学科**，不许留空或错标。
  - 导出按钮转发断言：列表态带 `subject=数学` 时构造的打印 URL **必须含 `subject=数学`**，
    且中文百分号编码可原样解回；变异：删掉那一行转发 → 断言必须红。
  - 依赖数组断言：`subject` 变化触发重新拉取（纯函数层断"参数集合"，渲染层用 CDP 断"两次请求 query 不同"）。
  - **空态不撒谎**：某学科在册 0 道时，页眉仍显示该学科 + 0 道、打印按钮禁用；**不得**回落成"全部知识点"。
  - **分组回归断言**：页组仍按 `category_id` 聚合、`__none__` 殿后（防有人照旧笔记去换分组口径）。
  - 前端零新依赖、零后端改动（`git diff -- wengu-api/` 为空）、零迁移；`npm run lint/test/build` 绿；
    CDP 取证：浅色与深色下各截一份"学科筛选打印页"页眉（打印豁免已在 P2-14 立过，本票不得回退）。
- 禁止：改 `groupMistakes` 的分组口径；为 `subject` 新增后端端点或学科合法性校验；
  顺手转发 `q`/`mastery_state`（它们**没有对应页眉标签**，转发就等于制造新的"内容自述与实际不符"，见【残留】）；
  引入 DOM 测试栈；借本票重构打印页布局。
- 残留（登记不排期）：`q`（关键词）与 `mastery_state`（掌握状态）同样被导出按钮丢弃，
  但打印页没有这两个标签位，补齐属文案设计、无真实使用信号——等家长真在筛选态下导出再说。

### P2-11 错因聚合卡（v2.7 D9；只读聚合、零新增状态）
- **状态：已合并（2026-11-15，PR#57 squash → main `b321919`；原分支 `feat/p2-11-error-cause-card` 已删）**。
  验收：审核方自跑 **755 passed** / `ruff --no-cache` 全仓绿 / `tsc` 干净 / `npm test` 32 / build ✓ / CI 三 job 绿；
  自主变异三次分别 **2 / 1 / 1 红**（绕过 `effective_labels`、换尺不排除已毕业、`unlabeled` 折进 `other`），
  还原 sha256 逐字节一致。
  ⚠️ **本卡白名单漏列（审核方第 13 次卡面口径疏漏，2026-11-15 认领）**：投单块只列了
  `services/dashboard.py`、`api/dashboard.py`、`DashboardPage.tsx`、`api/types.ts`、测试、CHANGELOG，
  **没有 `MistakesPage.tsx`**——而 `error_cause` 原来是组件内 state，不改它深链 `?error_cause=<键>` **根本不生效**，
  DoD 做不到。施工方扩了该文件并把它单列为复核点（还顺手修掉"清除筛选"两次 `setSearchParams` 基于旧闭包互相覆盖的真 bug）。
  裁定：**不属越界，属审核方漏列**。→ 纪律加一层：**白名单必须覆盖 DoD 可达性所需的全部文件**，
  不能只对齐"改哪些模块 + CHANGELOG"。
  ⚠️ **本卡【现状】里的行号是交付前快照，现已漂移、故意不改**（漂移值按 `b321919` 实读，只给定义起始行、不猜区间）：
  `_mistake_rows` 229 → **248**、`_confirmed_concept_ids` 236 → **278**、`_subject_inventory` 360 → **402**，
  本票新增的 `_error_cause_distribution` 在 **433**（`services/dashboard.py` 自身加了 88 行）；
  `DashboardPage` 硬编码色 `104/112/115/205` → **106/114/117/207**。
- **现状（2026-11-15 复核行号，原卡 2026-11-14 读盘）**：`ERROR_CAUSES` 在 `services/mistakes.py:52-60`，7 键原文
  `prerequisite_gap / concept_unclear / method_missing / calculation / careless / expression / other`；
  错因两列都在 `mistake_versions`（`models/mistakes.py` `suggested_error_cause:80`、`confirmed_error_cause:81`），
  **取值优先级唯一入口是 `effective_labels()`（`:121-144`）**：`confirmed_by is not None` 用确认值、否则用建议值；
  `services/dashboard.py` **零处错因聚合**（grep 无命中），且 `_mistake_rows`（**`:229-233`**）只读根表
  （`id/status/primary_topic_id`）、不加载 `MistakeVersion`——本票要扩到版本列，但**不得绕过 `effective_labels` 自己拼优先级**。
  - ⚠️ **新增一条必须避开的照抄陷阱（2026-11-15 读盘）**：`dashboard.py` 里**已有**一个查版本列的先例
    `_confirmed_concept_ids`（**`:236-258`**），它带 `MistakeVersion.confirmed_by IS NOT NULL` 过滤
    （只看已确认 concept）。**错因聚合绝不能照抄这个过滤**——错因口径是"确认值，否则建议值"，
    照抄会把"只被外部 agent 建议、孩子还没确认"的题整类漏掉，数字看起来正常但少计。
  - 检索侧现状：`list_mistakes`（`services/mistakes.py:659-741`）已有 `error_cause`（`:665`）与 `subject`（`:666`）过滤，
    前端点击跳转直接复用，不新增端点。
- 交付：`GET /api/dashboard` 新增 `error_cause_distribution: [{cause, label, count}]`——
  口径 = **在册未掌握**（`active` 且非 `is_graduated`，与 P2-13 同一把尺）按 `effective_labels().error_cause` 计数；
  **未填错因单列 `unlabeled`**（不塞进 `other`，否则会把"没标"误读成"其他原因"）；
  前端看板加一张横向条卡（与薄弱分布同风格），点击某条跳 `/mistakes?error_cause=<键>`（复用 P2-9 既有筛选）。
- DoD：造 confirmed/suggested 混合 fixture，断言计数走 `effective_labels` 优先级（改判后数字随之变、不重复计）；
  **自洽算式右端必须用可证的既有量**：`sum(error_cause_distribution) + unlabeled == sum(subjects[].active)`
  ——且**复用同一个 `graduated_ids` 集合与同一份 `_mistake_rows` 输入**（`_subject_inventory:360-388`），
  不得为错因卡另算一套未掌握口径。⚠️ 右端**不许**写成 `inventory.active`：那个量是"未作废在册"、含已毕业，
  拿它当右端会重犯 §19-H 第 4 条的互斥算式错误（审核方 2026-11-15 自查时按同一教训改掉了本卡原写法）。
  `other` 与 `unlabeled` 分列断言；零新增列/零迁移；360/412 不破版；全量绿 + ruff + build。
- 禁止：引入模型/AI 归类错因（零模型红线）；把 `suggested_*` 当确认值统计；新建第三套未掌握口径；
  为聚合结果存列或建缓存表；用 `other` 兜底空值；照抄 `_confirmed_concept_ids` 的 `confirmed_by IS NOT NULL` 过滤。

### P2-12 复习日历（v2.7 D9；只读投影，非自动排课）
- **状态：已合并（2026-11-15，PR#58 squash → main `4156e60`；原分支 `feat/p2-12-review-calendar` 已删）**。
  验收：审核方自跑 **763 passed** / `ruff --no-cache` 全仓绿 / `tsc` 干净 / `npm test` **33** / build ✓ / CI 三 job 绿；
  范围 11 文件 +1354/−15（3 新建），无迁移、无依赖改动、CR 全 0。
  - **本票发生过一次守卫补强返工（审核方变异发现）**：首轮实现是对的，但"删掉白名单里一个 type"全绿
    —— 9 个 type 齐不齐**没有测试看守**，而卡里坑一讲的是 **5 类**无 `completed_on` 的事件会整类消失，
    当时只有 `review_scheduled` 一类被覆盖。打回补两条守卫（同分支、**只加测试不碰实现**，
    `calendar.py` 补强前后 sha256 逐字节相同 `62fa8edb…`）：
    ① `set(CALENDAR_EVENT_TYPES) == {9 个字面串}`；② 5 类各造一条无 `completed_on` 事件、**各占不同** `occurred_at` 日
    + 每类恰一条总量断言。审核方复验：删 `mistake_primary_topic_set` → 2 红；**换删** `mistake_voided` → 同样 2 红
    （证明逐类独立生效，不是只守演示过那一类）。→ 纪律见 §19-L。
  - 卡里【现状】行号为交付前快照，本票自身造成漂移（只列实读到的定义起始行）：
    `services/review.py` `due_queue` 915 → **937**、逾期判定 951 → **973**、新增 `task_pick` **915** / `task_kind` **927**；
    `nav.ts` NAV 由 11 项变 **12 项**。`quiz_seed` 865 未变；`models/review.py`、`dashboard.py`、
    `mistakes.py`、`streak.py`、`App.tsx` 打印路由行、`SchedulePage.tsx` 未被本票触碰。
- **现状（2026-11-14 读盘）**：`review_schedules` 列（`models/review.py:16-47`）为
  `id / mistake_id / rung / base_interval_days / due_date(NOT NULL) / source_event_id(FK, unique) /
  completed_attempt_id / completed_at / created_at`——**没有 status 列**；"下一次排期" =
  `completed_at IS NULL` 的那一行（部分唯一索引 `uq_review_schedules_open_mistake:41-46`）；
  `ix_review_schedules_due_date:35` 已存在，按日期扫表可直接用。
  `due_queue()`（`services/review.py:915-1019`）逾期判定 = `due_date <= today` 且未完成（`:949-953`）、
  排序逾期在前（`:977-979`）；`GET /api/reviews/due`（`api/reviews.py:159-172`）**只返回过去/今日、无区间端点**，
  全仓没有其它 ReviewSchedule 查询端点。`SchedulePage.tsx` 是周课表（`:217-313`）+ 未来 30 天硬事件
  （`:315-427`）且写操作挂 PIN（`:195-199`）。NAV 11 项（`src/lib/nav.ts:15-27`）、路由在 `App.tsx:28-46`。
- 交付：
  ① 新只读端点 `GET /api/reviews/calendar?from=&to=`（默认 `today-7` 至 `today+30`，跨度 >92 天 → 422）：
     返回按日 `{date, planned: [{mistake_id, due_date, kind, overdue}], done: [{date, type, mistake_id?}]}`；
     `planned` 取该日 `due_date` 的排期行（含历史已完成行，用 `completed_at` 判是否已完成）、
     `kind` 沿用 `due_queue` 的 quiz/redo 判定，**不得另建判定**（判定实现在 `services/review.py:986-994`：
     `quiz_seed` → `find_same_type(mistake.primary_topic_id, seed, bank=await get_runtime_bank(session))` →
     `question is None` 则 `redo`、`mode == "self_eval"` 则 `self_eval`、否则 `quiz`）。
     ⚠️ P1-18 之后主考点可事后设定 → **未来某天的 `kind` 会随主考点更正而变，这是按查询时现算、不是快照**，
     日历不得把 kind 落库；交付说明里要写清这条语义。
  ② `done` 来自 `learning_events` 按日归属。**⚠️ 2026-11-15 复核：本条原写"与 `dashboard.py:160-184` /
     `streak.py:64-79` 同一口径"是审核方的事实错误——盘上是两套口径**：
     `dashboard.py` 的 `_review_completed_on`（**195 起**）与 `_recitation_completed_on`（**210 起**）
     缺 `completed_on` 时**直接返回 None、不回退**；真正"优先 `completed_on`、否则回退 `occurred_at`"的
     是 `streak.py` 的 `_learning_day`（**`:77-88`**，回退实现在 `:88`，配套 `_fallback_day:64-74`）。
     日历**采用 streak 那套**（`completed_on` 优先 → 回退 `occurred_at` 的日期），理由不是偏好，是事实：
     `mistake_labeled / mistake_voided / mistake_reactivated / review_scheduled / mistake_primary_topic_set`
     这 5 类事件**payload 里根本没有 `completed_on`**（全仓只有 pomodoro/quiz/recitation/review 四处写它），
     若照抄 dashboard 口径，这五类会在日历上**整类消失**。
     **不得复用 `_learning_day` 本身**——它按 `streak.LEARNING_EVENT_TYPES`（`:31-33`，只有 3 个 type）过滤；
     P4-4 的 `ix_learning_events_occurred_at`（`models/events.py:31`、迁移 0023）正是为这类区间扫描准备的。
     **事件类型白名单必须是显式常量**，真实写入的 type 全集现在是 **9 个**（P1-18 新增第 9 个）：
     `attempt_correct`、`attempt_wrong`、`recitation_reviewed`、`pomodoro_completed`、`review_scheduled`、
     `mistake_labeled`、`mistake_voided`、`mistake_reactivated`、**`mistake_primary_topic_set`**
     （常量 `mistakes.py:62-65`、写入点 `:531` / `:587`；⚠️ 盘上**不存在** `mistake_confirmed`，
     测试夹具里出现过该字符串属误导，不得当事实写进实现）；
  ③ 新路由 `/review-calendar` + NAV 追加 `{to:"/review-calendar", label:"复习日历"}`
     （插在 `/schedule` 之后、`parentOnly` 三项之前；`groupNavItems`/`isNavActive` 自动生效）；
     月视图每天标「N 道计划」，点某天看清单并可跳 `/review`。
- DoD：造 3 条不同 `due_date`（含 1 条已完成、1 条逾期）断言按日归属与逾期标记正确、且不重复计；
  投影数字与 `due_queue` 在今日一致（同一把尺）；跨度 >92 天 → 422；与 `/schedule` 硬事件互不混入；
  只读——**任何写操作都不新增**；360/412 月视图不破版（CDP/真机取证截图）；全量绿 + ruff + build；**零迁移**。
- 禁止：自动排课/时间块式日程（§12 已砍）；为日历存状态列或建派生表；前端 localStorage 当数据源；
  臆造不存在的 event type；把 PIN 写操作混进只读页；用 `due_queue` 之外的第二套逾期/kind 判定。

### P2-14 主题切换（v2.7 D10；纯前端，零后端改动）
- **状态：已合并（2026-11-16，PR#59 squash → main `3950229`；原分支 `feat/p2-14-theme-toggle` 已删）**。
  审核方独立取证：`npm test` 40/40、`tsc --noEmit` exit 0、build ✓、`ruff --no-cache` 全仓绿、
  后端全量 **763 passed**（`git diff -- wengu-api/` 为空、依赖清单未触碰）；
  自主变异三次（换靶点，全打纯函数层）分别 **2 / 2 / 1 fail**，还原 sha256 逐字节一致（`14a75157…`）。
  三条观察项登记于设计文档 **§18 D10-obs**（均不排期）。
  - ⚠️ **本票造成的行号漂移（实读值，合并后 main `3950229`）**：`DashboardPage.tsx` 硬编码 hex **已全部消失**
    （原 106/114/117/207 五值换成 `chartTokens`）——**今后任何卡都不应再引用那几个行号**；
    `print.css` 因在文件头部插入 16 行而整体下移：`.print-toolbar` 11 → **27**、`.print-sheet` 73 → **85**、
    `@media print` 251 → **267**，新增 `html:has(.print-shell)` 在 **18** / 其 body 兜底在 **22**，
    含色值行数 30 → **33**（+3：两条规则各一行 + 注释里并列的 `#eef0f3/#111` 一行）；
    `main.tsx` 的 `MantineProvider` 17 → **28**；`AppLayout.tsx` 切换按钮在 **108**。
    `nav.ts`、`App.tsx`、两个打印页 tsx 未被触碰。
- **现状（2026-11-15 复核行号，原卡 2026-11-14 读盘；⚠️ 本段是**交付前快照**——P2-14 合并后"无 `createTheme`、无 theme 文件、前端没用过 localStorage"三条已整体反转，勿再当现状引用）**：`main.tsx:17` 写死 `<MantineProvider defaultColorScheme="light">`，
  全仓**无 `createTheme`、无 theme 文件、前端完全没用过 localStorage**（grep `createTheme|localStorage|useMantineColorScheme` 零命中）；
  `DashboardPage` 有 **4 处硬编码色，行号已因 P2-13 与 P2-11 两次合并累计推高 6 行**：现在是 **`:106`（曲线网格 `#e9ecef`）、
  `:114` 与 `:117`（曲线描边/端点 `#228be6`）、`:207`（番茄钟格 `#12b886` / `#e9ecef`，**一行两个色值**）**；
  两个打印页各自 import `../print.css`（`PrintMistakesPage.tsx:9`、`PrintPaperPage.tsx:14`，样式根 `.print-shell` 在 `:145`），
  路由挂在 `AppLayout` 之外（`App.tsx:28-29`）；
  `@mantine/hooks@8.3.18` 已在依赖（`package.json:15`）；后端 app-config 白名单只有 4 键
  （`runtime_config.py:221-225`：`daily_review_limit`、`daily_recitation_limit`、`exam_day_limit_factor`、`setup_completed`）。
  - ⚠️ **2026-11-15 两处卡面纠正（审核方）**：
    ① `api/config.py:24` 的 `require_parent` 挂在 **router 级 `dependencies`**，**连 `GET /api/config` 也被挡**
    （原卡写"`PUT` 整挂"弱化了事实，方向不变：主题确实不该进 app-config）。
    ② `print.css` 的硬编码色**远不止原卡列的 4 处**——全文件 **30 行含颜色声明**（`grep -cE '#[0-9a-fA-F]{3,8}'` = 30），除 `.print-shell:5-6`、
    `.print-toolbar:21-22`、`.print-sheet:73`、`@media print:251`（`:259` 是 `#fff !important`、`:264` 白底）外，
    还有 `:59/:60` 的 `#1c4ed8`、`:162/:163` 的 `#fff5f5`+`#a11`、`:167/:168` 的 `#f0fff4`+`#116329` 等
    （`#a11`/`#116329` 是卷面"错答/订正正答"的红绿语义色）。→ 豁免口径改成**可测断言**，不再靠数行号：
    **`@media print` 下必须白底深字**（`:259/:264` 保持），且**深色主题屏幕态下 `.print-sheet` 仍须白底深字**
    （打印页是纸面样式，不参与换肤）；DoD 用深色模式打印预览截图取证。
- 交付：`createTheme` + `useMantineColorScheme`，头部加浅色/深色切换按钮（孩子区与家长区都可见，
  解锁与否都能切）；偏好存 **localStorage（Mantine 内置 storage key）**——理由写进代码注释：
  主题是**每设备的呈现偏好、不是学习数据**，因此不进 app-config（那会被 PIN 挡住，孩子改不了自己设备外观），
  也不进数据库；把 `DashboardPage` 4 处硬编码色改为 Mantine 语义色 / `var(--mantine-color-*)`；
  **打印豁免**：`.print-shell` 与 `@media print` 在深色下仍保持浅色底，打印页工具栏若用 Mantine 组件需固定 light。
- DoD：切换后刷新保持、且**不触发任何数据请求**；深色下桌面 + 360/412 三档取证截图
  （文字对比度、掌握度曲线、徽标、表格、复习页计时器、复习日历月视图）；**打印豁免逐页各一条**——
  `/print/mistakes` 与 `/print/paper` **各自**在深色下截图，断言屏幕态 `.print-sheet` 仍白底深字、
  `@media print` 仍白底、卷面红绿两色仍可区分（原卡只写"打印预览仍白底"= 以一类代两类，2026-11-15 按 §19-L 加严）；
  localStorage **只有主题键**——用 CDP 读 `Object.keys(localStorage)` 全量列出并贴出实际键名，
  断言不含任何题目/答案/学习数据（**本仓禁 DOM 测试栈**，这三条只能 CDP 取证，不得为此加 jsdom/vitest）；
  可证伪两处且**换靶点**（某处改回硬编码 hex、删一条打印豁免规则）；
  `npm run lint`/`test`/`build` 绿；**后端零改动**。
- 禁止：把主题写进 app-config 或数据库；用 localStorage 存任何业务/学习数据；为暗色引入新 UI 依赖；
  改打印内容结构（只允许配色豁免）；借主题之名重构页面布局。

---

## Phase 3 —— 内容扩展（按 ROI）
> v2.5：**"检索真题组卷"的题库检索引擎已提前到 P1-10、"出同类题考核"到 P1-11**。Phase 3 只保留增量。
- **P3-1 真题库增量录入流水线**（已完成 2026-10-31）：家长/外部 agent 帮录**新题**入 `problem_bank`（含 `answer/verify/topic_id/难度/错因`）+ 审核队列；入库题走 AST 沙箱 `verify` 核验。**交付**：`doubao_bank_transcribe_v1` 模板、`bank_drafts` 草稿表（迁移 0016）、inbox 按 channel 分派、四个 `require_parent` 端点、家长「题库审核」页 + 手填表单。**红线**：`answer` 只从卷面/答案册转录或家长手填，**模型不得自行解题生成答案**；缺答案拒入库；家长题只进 SQLite，不写 seed JSON。禁：LLM 现编无钥匙题。**P3-1b（已完成 2026-10-31）**：入库题已合并进运行时检索池（`get_runtime_bank`），参与到期考核与手动组卷；approve/手填后清缓存；统计/coverage 随池重算；旧 pick 跨池 `replay` 显式抛 `BankReplayError`。**P3-1c（已完成 2026-10-31）**：题库条目修订 = 编辑 + 软作废（`status ∈ {active, voided}`，迁移 0017 可逆）；`GET/PATCH /api/bank/items` + `void/unvoid`（全挂 `require_parent`）；编辑合并后重跑同一套闸门（缺答案/占位/沙箱/choice key/数值矛盾 → 422 稳定码），不改 `external_id`；作废题退出检索池但不物理删除、不改写历史 attempts/事件/排期；`replay` 按题 id/`pool_ids` 判定，内容修订不回溯；前端 `/bank` 已入库列表 + 编辑 + 作废/撤销。禁：物理删除题目；改写历史事件/attempts；动 seed 文件；把题库审核面暴露给孩子区。
- **P3-2 主动加练变式（`practice_records`，不影响掌握度）**（已完成 2026-10-31）：错题详情「加练同类题」按 `primary_topic_id` 从运行时题池固定种子抽 1–10 题（可重放、答案不下发）；系统题服务端 `judge_answer` 判分，解答/依赖图题孩子自评。**结果只写 `practice_records(kind='variant')`**——不写 attempts、不产生事件、不新建错题、不计入掌握度/排期/打卡，可整表清空；无主考点或题池为空时入口置灰并提示「该知识点暂无同类题」（200 不报错）。**P3-2d（已完成 2026-10-31）提交幂等**：迁移 **0018**（可逆）给 `practice_records` 补 `topic_id`/`seed`/`dedup_key` + 部分唯一索引；同 `(topic_id, seed, question_id)` 重复提交不增行、回看已有行并返回 `reused=true`（不覆盖原作答），不同 seed 各自成行；既有 NULL 行不受影响；`GET /api/practice` 支持 `topic_id`+`seed` 过滤、练习记录页按组展示。**交付**：`services/practice.py`、`POST /api/practice/start|submit`、`GET/DELETE /api/practice`（全部孩子区免 PIN）、`/practice` 页 + 错题详情入口 + 「练习记录 → 变式/加练」tab 与清空确认；迁移 0018；6 条集成测试。**残留**：仅按主考点检索（category/错因/难度筛选未做）；「再练一组」不保存上一组身份用于重放。禁：与闭环考核混淆；禁 LLM 编题/判分；禁给 practice 写事件/attempts。
- **P3-8 家长自建章级 seed（语文 / 化学，文件真源 + 受控 CRUD）**（已完成 2026-10-31，PR#20；
  幂等硬化补齐于 PR#23）：补齐"化学、语文空 seed 起步"缺口，是 P3-5 语文客观并入的前置。
  **JSON 文件是唯一真源**（`<data_dir>/seeds_local/topics_<学科>.json`），SQLite `knowledge_seed`
  只是装载副本；装载顺序 `seeds/data/topics.json`（仓库只读）→ `seeds/local/*.json`（开发机可选）
  → `<data_dir>/seeds_local/*.json`（家长运行时），按 id upsert 幂等、id 冲突拒绝并记 error、
  单文件坏 JSON 只告警跳过不阻塞其余源。语文前缀 `cnl_`、化学 `cnc_`（与 `cnm_`/`cne_`/`cnp_` 隔离），
  本地行强制 `source='local'` / `unaudited=true` / `blind_verified=false`。
  **id 永不复用**：`_id_counters.json` 单调记录各学科已发放最大序号，分配取
  `max(计数器, 文件与 DB 同前缀最大序号)+1`，先原子预留再落盘，删除不回退，计数器损坏 fail-closed；
  装载器与导出脚本跳过下划线开头的簿记文件。CRUD 原子写（同目录 tmp + fsync + `os.replace` + 进程内锁）；
  删除知识点同步移除文件与行、解绑错题/题目（`SET NULL`，历史不动）并返回受影响计数；
  被 `mistake_versions` 标签引用时 409。端点 `GET/POST/PATCH/DELETE /api/local-seed/topics*`
  **全挂 `require_parent`**；前端 `/local-seed` 页（仅家长解锁可见）带"家长自建·未经教师审核"提示。
  单科上限 200 点、章级 40–80 点即止。**无迁移**。
  禁：写回 `seeds/data`（上游只读）；复用已发放 id；把细粒度知识点树做成家长手工录入（细粒度仍走错题受控生长）。
- **P3-3 英语背诵（自评间隔重复，档③）**——v2.6 定：内容来源按 **B → A → C** 三阶段推进，各成一 PR。
  - **P3-3a 家长手填背诵条目 + 记忆阶梯自评闭环（先做）**
    - **状态（2026-11-03）**：已交付。迁移 `0020_recitation`（可逆；up/down/up 与 DDL 逐字对比）。
      纯函数复用 `MEMORY_LADDER`；`remembered` 进档、`forgot` 不倒退、实际自评日起算、最高档毕业；
      同日幂等、只写 `learning_events(recitation_reviewed)`，全表快照证明不碰
      `mistakes/mistake_versions/attempts/review_schedules`。热配置 `daily_recitation_limit`
      （默认 5、上限 20）；`/recitations` 页 + 看板"今日背诵 x/N" + streak 白名单显式变更。
      `pytest -m e2e` 收集 **4** 条（新增手填→到期→混合自评→阶梯→看板/streak 咬合）；
      全量 **442 passed**（unit 293 / integration 145 / e2e 4）；`ruff check --no-cache .` 与
      `npm run build` 全绿。
    - 数据：新增 `recitation_items`（`id / subject / prompt / answer? / unit? / status(active|retired) /
      created_at / created_by`，`UNIQUE(subject, prompt)` 防手填重复）与 `recitation_reviews`
      （`id / item_id / verdict(remembered|forgot) / rung / reviewed_on / scheduled_next? /
      event_id / created_at`）。**背诵条目不是错题**，绝不写 `mistakes` / `mistake_versions`；
      **也不写 `attempts`**（`attempts` 语义是"作答"，混入会脏掉练习记录页）。
    - 事实：每次自评追加 `learning_events(type=recitation_reviewed, mistake_id=NULL)`，
      payload 含 `item_id / verdict / rung / scheduled_next / completed_on`；排期状态全部可从事件重算。
    - 阶梯：复用 `review_policy.MEMORY_LADDER = (1, 3, 7, 14, 30)`（英语已在 `MEMORY_SUBJECTS` 内）；
      `remembered` 进一档、`forgot` **保持当前档**（抗挫败：不倒退），下次到期日一律从
      **实际完成日**起算；到最高档仍 `remembered` → `scheduled_next=NULL`（毕业，不再排但条目保留）。
    - 调度：日队列新增"背诵铺底"——每天固定塞 `daily_recitation_limit`（`config/app-config.json`
      热加载，默认 5、上限 20）条到期条目，排在同类题考核**之后**；无到期条目则不塞、不硬凑。
    - 打卡口径（**显式变更**）：把 `recitation_reviewed` 纳入 `streak` 计入白名单——
      连续天数语义从"有作答的日子"改为"有学习动作的日子"，孩子只背诵不做题也算打卡；
      必须同步改注释与测试，不得悄悄改。
    - API：`GET /api/recitations`（家长/孩子可列）、`POST/PATCH /api/recitations*`
      （**挂 `require_parent`**，手填归家长）、`GET /api/recitations/due`、
      `POST /api/recitations/{id}/review`（孩子区免 PIN，幂等键 `recitation:{item_id}:{reviewed_on}`
      → 同一天重复提交不产生第二条事实）。
    - 前端：`/recitations` 页（孩子：今日卡片 + "记得 / 没记住"；家长解锁后可增删改）；
      看板加"今日背诵"计数；窄屏可用（手机是目标场景）。**无迁移 0020 之外的结构改动**。
    - DoD：迁移 0020 可逆且 **DDL before/after 用例覆盖**（沿用 P0-3 加的守卫）；
      全表快照断言 `mistakes / attempts / review_schedules` 零变化（证明不污染掌握度）；
      同日重复自评幂等；阶梯与"不倒退"有测试；streak 口径变更有测试；`pytest -m e2e` 加第 4 条
      （手填条目 → 到期 → 自评 → 阶梯推进 → 看板与 streak 一致）。
    - 禁：LLM 生成背诵内容或判"背得对不对"；把条目塞进错题本；背诵计入掌握度；
      做"自动检测重复条目"的相似度猜测。
  - **P3-3b 教材词表批量导入（第二期，2026-11-03 定稿）**：家长上传/粘贴**CSV 或 TSV 文本**
    （每行 `prompt, answer, unit`，首行表头可选），服务端 `POST /api/recitations/import`
    （**挂 `require_parent`**）解析入库。**不再依赖 P5-4**——词表导入只需要一个 CSV 契约，
    教材包机制（整套 seed 安装）是更重的另一回事，别为它卡背诵。
    - **编码只收 UTF-8**（带/不带 BOM 均可）；UI 提示 Excel 用户用"CSV UTF-8"导出
      （Windows 记事本/Excel 默认 ANSI/GBK 是经典坑）。
    - **导入即不可信输入**（AGENTS §5 照抄）：单次 ≤500 行、body ≤256KB、
      `prompt ≤200 / answer ≤500 / unit ≤40` 字符，超限整批 422 并说明哪条超了。
    - **去重**：命中 `UNIQUE(subject, prompt)` 的行逐条报 duplicate（**不静默丢弃、
      也不更新已有行**——已有行是家长录的，覆盖须经家长手改或删除后重导）。
    - **坏行不阻断好行**：逐条 `{line, field?, reason}`，合法行照常入库；无草稿暂存——
      词表来自家长本人（可信来源），与外部 agent 转录（必须过核对页）是两种信任级，
      这条边界写进代码注释。
    - 幂等：同一份文本重复提交 → 全部命中 duplicate，不产生第二条数据，天然幂等。
    - 前端：/recitations 家长区加"批量导入"区（文件选择 + 粘贴文本二选一）+ 报告渲染
      （成功 N / 重复 N 列前几条 / 错误逐条）；默认 subject=英语（本票 UI 只露英语，
      字段保留通用性）。
    - DoD：集成测试覆盖 成功 / 混合（坏行+重复）/ 超限 422 / BOM 兼容 / 未解锁 403 /
      subject 与行数上限；`pytest -m e2e` 加第 5 条（导入 3 行含 1 重复 1 坏 → 好行入库 →
      孩子端自评走阶梯）；全量绿 + `ruff check --no-cache` + build。
    - 禁：LLM 生成/翻译词表内容；静默丢弃或静默更新已有行；引入 pandas/CSV 库依赖
      （Python stdlib `csv` 足够）；为"防呆"做导入前暂存草稿表。
    - **状态（2026-11-03）已交付** ✅：`services/recitation_import.py` + `POST
      /api/recitations/import`（`require_parent`）+ `/recitations` 家长区批量导入；
      stdlib `csv`、无新依赖、无迁移、未改 0020 DDL。新增单测 11 + 集成 11 + e2e 第 5 条；
      **全量 465 passed（unit 304 / integration 156 / e2e 5）**，`ruff check --no-cache .`
      与 `npm run build` 全绿。实测：首导 4 行 → 成功 2 / 重复 0 / 第 4 行空 prompt；
      同文本重导 → 成功 0 / 重复 2（行号正确），数据仍 2 条；自评进第 2 档、看板 1/5。
  - **P3-3c 从错题抽词（第三期，2026-11-03 定稿）**：把**英语错题**出现过的词补进背诵池。
    **候选是视图不是表（本票零迁移）**：从 active 英语错题（`primary_topic_id → knowledge_seed.subject='英语'`）
    当前版本的 `problem_text` 确定性抽取英文 token（正则 `[A-Za-z][A-Za-z'-]+`，lowercase、去尾 `'s`、
    长度 ≥2），排除 ① 已在任何状态的 `recitation_items` 里、② 内置英文停用词起步集（~40 个功能词，
    硬编码常量并注明"按试用反馈增删，不做配置化"），按**出现错题数降序**取前 50。
    - API（全部 `require_parent`——抽词与入库都是家长动作）：`GET /api/recitations/candidates`
      返回候选词与错题数；`POST /api/recitations/candidates/batch`（body `{words, unit?}`）→
      **复用 `create_item`**（subject='英语'，UNIQUE 去重逐条报 duplicate），批量创建后前端给
      "撤销本批"按钮 = 对本批 ids 逐条 `PATCH status='retired'`（不新增撤销端点）。
    - **必须家长勾选确认才入库**：候选只读展示，绝不自动写入 recitation_items；
      不给候选词自动配释义（`answer` 留空，家长可后续手补，卡面只显示 prompt）。
    - DoD：候选去重 / 词频排序 / 停用词 / 排除已有条目各有断言；批量创建走 UNIQUE 去重逐条报告；
      四表快照断言（mistakes / mistake_versions / attempts / review_schedules）零变化；
      撤销后条目 retired 且退出 /due；`pytest -m e2e` 加第 6 条（确认 2 条英语错题 → 候选排序与
      去重正确 → 批量入库 → /due 出现 → 自评）；全量绿 + `ruff check --no-cache` + build。
    - 禁：LLM 抽词/翻译/选词；TF-IDF 之类权重算法（只有"错题数降序"一把尺）；中文词抽取
      （本票只做英文 token）；自动定期同步（候选每次现算，无后台任务）；未经家长确认自动入库。
    - **状态（2026-11-03）已交付** ✅：`services/recitation.py` 的
      `english_word_tokens` / `extract_word_candidates` / `candidate_words` +
      `services/recitation_import.py` 的 `add_candidate_words`；`GET
      /api/recitations/candidates` 与 `POST /api/recitations/candidates/batch`
      （均 `require_parent`）+ `/recitations` 家长区「从错题抽词（英语）」。
      **无迁移、无新依赖、未改 0020 DDL、未改错题链语义**。新增单测 11 + 集成 7 + e2e 第 6 条；
      **全量 484 passed（unit 315 / integration 163 / e2e 6）**，`ruff check --no-cache .`
      与 `npm run build` 全绿。实测：确认 2 条英语错题 → `diligent` 跨题计 2 次排第一、
      同题重复只算一次、停用词不进候选 → 勾选 2 词入库 → `/due` 出现且 answer 为空 →
      自评 remembered 进第 2 档 / forgot 保持第 1 档；四表快照零变化。撤销 = 前端逐条
      `PATCH retired`，retired 后退出 `/due` 且**不再出现在候选**（再提交同名词报 duplicate）。
- ~~**P3-4 听力+默写**：默写=卷面批改后走转录导入；听力"教材音频+TTS"+组卷。禁：口语 ASR。~~
  （2026-11-20 决策轮修订，详见下方 **P3-4 详卡**：① 默写结果回录由"走转录导入"改为
  **页内勾选**——卷面词单系统已知，建第三条转录通道（新模板+新契约+草稿表）属重炮打蚊子，
  拍照转录留作后续可选票，触发条件 = 家长回录负担成为真实证据；② 听力拆为 **P3-4b 听写**
  （音频→手写→勾选，触发条件已满足：课程音频可导出普通本地文件）与 **P3-4c 听力理解题**
  （音频+题面，触发 = 课程题目确实需要录入）两票递进，均不进 P3-4；③ TTS 出局（内核零云推理）、
  口语 ASR 仍禁做；④ 新增分发面纪律：第三方课程音频落 `data_dir/audio/`，**绝不进 uploads 树**
  （实测 `backup.py:226` 会把 uploads 整树打进备份 zip），不进仓库、不外发。）
- **P3-5 语文客观并入**：字音/病句/默写并入转录；作文/阅读理解只走外部讲解不进本。
  **前置已交付（P3-8，2026-10-31）**：家长可自建语文章级 seed（`cnl_`）、语文题可挂
  `topic_id`、语文错题可挂主考点，到期考核 `quiz` 闭环已实跑；本票只剩题库内容接入。
- **P3-6 信奥独立流**：卡壳→外部引导→"待重做清单"（复用转录）；需要时手动组卷（C++ 题库检索）；C++ 技能图谱 seed。禁：判题 infra、自动排复习。
- **P3-7 长期计划**：覆盖型（seed 图谱+掌握度自适应）+ 积累型（streak）；家长与 AI（外部）共创、AI 生成后审核。
  **2026-11-21 决策轮：两档均押后，本票今天不出卡**——积累型核心 streak 已随 P2-6/P3-3a 交付
  （实测生产库 `current_streak=0`、`learning_days_total=4`、10-30 之后 22 天零活动、
  `recitation_items` 0 条），剩下的"家长与 AI 共创目标"在零模型下等于新开一条外部通道，
  不是小票量级。两档触发条件与 **D2/§5.7 待裁决口径**详见设计文档 §19-M 定案二及其补充。

---

## Phase 4 —— 基础设施演进（孩子真在用之后）
- **P4-1 Tailscale 可达性 + 裸奔口子收紧**（手机/平板连回家里那台机器）。
  - 口径修订（2026-11-04 出卡时读盘）：原写"Tailscale/CF Tunnel 稳定化"——**Cloudflare Tunnel 属公网暴露**，
    按 AGENTS §2.4 必须先恢复真鉴权与用户隔离，本票**不做**，也不得在文档里与 Tailscale 并列成等价选项；
    远程边界只承认 tailnet（私有网）。
  - 已知事实（详见 `docs/tooling/qoder-build-plan.md` 的 P4-1 卡）：前端全部走相对 `/api/…` 且
    `nginx.conf` 反代到 `api:8000` ⇒ 只需打通 web 一个入口；compose 现在把 api/web 两个端口都发布到
    0.0.0.0；被注释的 tailscale 块引用了**不存在的** `deploy/tailscale/serve.json`，且
    `/dev/net/tun` + `network_mode: service:` 在 Docker Desktop for Windows 上不成立；
    原生形态 `run-trial.ps1` 后端只绑 127.0.0.1，但 `vite.config.ts` 的 `server.host = true` 让 5173 局域网可达。
  - **状态：已合并（2026-11-05，PR#39 squash → main `170b5da`；原分支
    `feat/p4-1-tailscale-reachability` 已删）**：compose 端口默认
    `127.0.0.1`（`WENGU_BIND_ADDR` 可覆盖）；vite `server.host` 改回环；新增
    `deploy/tailscale/serve.json`、分平台 Tailscale 说明、只读 `scripts/remote-check.ps1` 与
    `docs/deploy/mobile-access.md`；CF Tunnel 与 Tailscale 的并列表述已统一掉。无迁移、无新依赖。
    审核证据：`pytest` **526 passed**、`ruff check --no-cache` 绿、`npm run lint`/`build` 绿、
    `docker compose config -q` 静默通过且渲染出 `host_ip: 127.0.0.1`（api 8000 / web 5173 两组）、
    CI run `41954176088` success。**两项待试用机实测**：`tailscale serve --bg http://127.0.0.1:5173`
    的 CLI 形式（以 `tailscale serve --help` 为准）、sidecar 路径 A 在 Linux/群晖的运行时验证。
- **P4-1b 部署面命令体检**（**已合并**：PR#40 squash → main `6f6c4cf`，2026-11-05）：本票只做一件事——
  **仓库里写给家长/开发者敲的每条命令都必须真能跑**。审核方 2026-11-05 读盘 + 只读实跑核实九条事实，
  其中六处缺陷与处置（原文保留，便于日后回看"当初到底哪里坏了"）：
  ① `make backup`（Makefile:135-138）调全仓不存在的 `scripts.local_backup`（实跑
  `No module named scripts.local_backup`）→ **已删除该目标，没有新造 CLI 备份实现**；
  ② 同行注释指向 `docs/manuals/ops/backup.md`，该**文件不存在**（`docs/manuals/{guide,ops}/` 只是
  建仓时留的空骨架，各有一个 `.gitkeep`）→ 空骨架已删，备份/恢复口径统一指家长区导出与
  `docs/deploy/backup-restore.md`；③ `.PHONY` 声明了 `restore` 但**没有该规则** → 已删；
  ④ `make dev-api` 曾 `--host 0.0.0.0`，是 P4-1 收紧后**最后一处默认全网卡**，而 README 叫家长敲它
  → 默认 `HOST=127.0.0.1`，局域网调试须显式 `HOST=0.0.0.0`；⑤ `make lint` 不带 `--no-cache`，
  正是本仓反复踩的 `.ruff_cache` 假绿口子 → 已补；⑥ `seeds/README.md` 的
  `--src ../cn-math-taxonomy-main` 比 Makefile 的 `../../` 少一级（上游 clone 在仓库根的上一级），
  且 `help` 把 seed-load 描述成"从 seeds/ 装载"而 recipe 实际是"从上游转换生成" → 已对齐。
  另修 `docs/deploy/backup-restore.md` 里 `run-trial.ps1` 的错误调用形式（脚本只认 `-Stop` 开关与
  无参启动，原写的 `stop` / `start` 位置参数会被拒）。
  现行唯一备份路径是家长区 `POST /api/backup/export`（P5-2），恢复走停机整库替换 `scripts/restore.ps1`。
  出卡正文（九条事实 + 禁止项 + 我那条写坏的 grep DoD 及其修订口径）完整保留在
  `docs/tooling/qoder-build-plan.md` 的 P4-1b 卡，**不得为指标归零而删改**。
- **P4-1c 不停服务的命令行备份入口**（**已合并**：PR#41 squash → main `8bbef94`，2026-11-05）：动机是真实缺口——
  `0019` 这类破坏性迁移要求"服务没起的时候也能先备份"，而现在只有家长区 UI 一条路。技术上无悬念
  （`create_backup(settings)` 是同步函数，`VACUUM INTO` 对运行中的 WAL 库就是安全一致性快照）。
  **四问已由审核方 2026-11-05 定案，不再讨论**：① 产物与 UI 同落 `<data_dir>/backups/`、共用
  `KEEP_BACKUPS=10` 轮转（两套轮转互相看不见必然出事）；② **不加 PIN、不加鉴权**——能执行命令就等于
  有本机物理访问权，套 PIN 是自欺，代价必须写进 `--help` 与文档；③ 要给 Windows 计划任务示例（须实测）；
  ④ 失败只做退出码 + 日志，不做推送（反清单）。硬约束：只**调用** `app/services/backup.py`，
  禁止在 CLI 里另写快照/打包/manifest/轮转；必须支持 `--data-dir` 并默认打印用的是哪一份库
  （本机实测存在 `data/` 与 `wengu-api/data/` 两份平行库，版本与错题数都不同，"备份错了那份"是最容易
  发生的事故）。
- **P4-1d api 镜像缺 `scripts/`，纯 Docker 家庭用不上命令行备份入口**（2026-11-05 出 `docs/deploy/from-zero.md`
  时发现，登记未开工）：`wengu-api/Dockerfile` 只 `COPY app / alembic.ini / migrations`，没有 `scripts/`，
  所以 `docker compose exec api python -m scripts.backup_cli` 必然 `No module named scripts`；
  而纯 Docker 家庭**宿主机没有 venv**，P4-1c 那条命令行入口对他们等于不存在，日常只剩"服务在跑时点 UI"
  一条路——恰好绕回 P4-1c 立票要解决的那个缺口（"升级前服务已停也能备份"）。
  修法很小：镜像 `COPY scripts ./scripts`（`backup_cli` 只依赖 `app.*` 与标准库），并补一条
  `docker compose exec api python -m scripts.backup_cli --dry-run` 的实测；文档同步改
  `docs/deploy/from-zero.md` 第 4 步与 `backup-restore.md`。
  ⚠️ 注意别顺手把 `import_seed.py` / `import_questions.py` 变成容器里的"可跑入口"——它们读的是
  仓库外的上游 clone，镜像里没有，`--dry-run` 式的路径校验要一并说明。
- **P4-2 可移植部署**：Docker 镜像原样上云（搬 SQLite 文件 + 挂载卷 + `data/inbox`）；Postgres 迁移为**可选**路径。
- **P4-3（可选）本地模型层**：若购置带 N 卡主机，Qwen-VL/PaddleOCR 经 Provider 接入做**隐私化系统内识别/转录**（替代外部 agent）。禁：为省 API 去租云 GPU。
- **P4-4 后端健壮性与可观测性小修（v2.8 §19-E；含一张迁移）**：
  - **背景（2026-11-12 读盘）**：`main.py:49-53` 用 `except Exception: logger.exception(...)` 吞掉 seed 装载失败、以空 seed 继续；
    `models/events.py` 的 `occurred_at` 无索引（仅 `mistake_id`/`type`），看板曲线全量排序；`runtime_config.save_config`
    在 async 链上直调含 fsync 的同步写；0013/0019 upgrade `drop_table`、downgrade 只重建空表，缺数据回退说明。
  - 交付：
    ① seed 失败可观测：启动加载失败时记录进程内状态，`GET /api/setup/status`（公开只读）增加
       `seed_loaded: bool` + `seed_error: string | null`（只给错误类别，**不得含题目/PII/绝对路径明细**）；
       前端 `AppLayout` 在 `seed_loaded === false` 时显示红色横幅"学科 seed 未装载：检查 seeds/data/*.json"。
       服务不因空 seed 崩溃（家庭可用性优先），但界面必须显式降级。
    ② 迁移（编号取施工时 head+1）给 `learning_events.occurred_at` 建索引 `ix_learning_events_occurred_at`；
       可逆 + DDL before/after（P0-3 守卫）。
    ③ `runtime_config.save_config` 的同步写盘改 `asyncio.to_thread`（文件锁语义与原子写保持不变）。
    ④ `docs/deploy/backup-restore.md` 补 0013/0019「数据不可回退」说明：升级前备份是硬前置，downgrade 只保结构不保数据。
  - DoD：seed 坏文件启动 → 服务可用 + 状态端点 `seed_loaded=false` + 前端横幅出现（集成 + 手工取证）；seed 正常 → 横幅不出现；
    索引存在性/回退后不存在（迁移测试）；`save_config` 并发写测试保持绿；全量绿 + `ruff check --no-cache` + build；
    CHANGELOG/STATUS 更新。
  - 禁止：seed 失败直接 crash 服务；把 seed 错误明细（题目/路径）暴露给前端；async 路由内保留同步 fsync；
    顺手改 0013/0019 历史行为；给 dashboard 加缓存绕过索引。

### P4-5 mastery 近期窗口（v2.8 §19-E；改掌握度语义，零迁移）
- **背景（2026-11-12 读盘）**：`services/recompute.py:98-125` 的 `mastery()` = 该 concept **全部历史**正确率，
  docstring 自述"确定性占位实现"；而 `review_policy.review_interval()` 用 `基础档 × (1 + mastery × 4)` 算间隔
  → 两年前答对 10 次、最近连错 3 次的孩子 mastery 仍高、间隔反被拉长（评估报告 §4.2 #7 / §5.1）。
- **参数已定（2026-11-12 用户确认）**：窗口 **N = 20**（按 concept 取最近 20 次计入掌握度的作答事件，
  沿用 `_counts_toward_mastery` 与 `_dedupe_grading_versions`）；**样本 < 5 回退全历史**（避免冷启动抖动）；
  多 concept 仍取最小 mastery；`is_graduated` 与 `GRADUATION_STREAK` **一字不改**。
- 交付：
  - 模块级常量 `MASTERY_WINDOW_SIZE = 20`、`MASTERY_MIN_SAMPLE = 5`（便于回归与将来调参，**不做运行时可配**）；
  - `recompute.mastery()` 改窗口实现：沿用 `_events_for_mistake` 的确定性排序（`occurred_at` + `repr` 稳定键），
    按 concept 过滤后取末尾 N 条；样本不足回退全历史；docstring 写明窗口值、回退阈值、仍为推导值可整体重算；
  - 设计文档 §5.4/§16 的"掌握度自适应"表述与代码对齐（不再暗示已实现时间衰减）；STATUS/CHANGELOG 记录语义变更
    与影响面（复习间隔可能整体缩短，属预期）。
- DoD：单测覆盖 ①窗口内全对 → 1.0；②窗口内全错但历史全对 → mastery 显著下降（证明窗口生效，非全历史）；
  ③样本 <5 → 与全历史结果一致（回退）；④恰好 20 / 21 条边界；⑤申诉改判在窗口内仍只计最高 `grading_version`；
  ⑥多 concept 取最小值不变；⑦`is_graduated` 既有断言一字未改仍绿；⑧同输入两次重算相等（幂等）。
  全量 pytest 绿 + `ruff check --no-cache`；**零迁移**。
- 禁止：把 mastery 存成列或缓存；改 `GRADUATION_STREAK`/毕业条件；引入 FSRS 或新依赖；
  把窗口参数做成运行时可配（无证据，先常量）；顺手改 `review_interval` 的公式形状。

### P4-6 公式题判分：受限 LaTeX 子集归一 + sympy 语义等价（v2.8 §19-E；零新依赖）
- **背景（2026-11-12 读盘）**：`requirements.txt` 已声明 `sympy>=1.13,<2`（注释写"judgeAnswer 用"），
  但全仓 `grep sympy` **零命中**——声明未使用；判分实际只走 `judge/normalize.py` 的字符串/有理数规范化，
  `\frac{1}{2}` vs `0.5`、`2(x-3)+4=3x-5` 的等价变形在字符串比对下会误判（评估报告 §5.2 公式盲点）。
- **路径已定（2026-11-12 用户确认"按建议"）**：**不引入 antlr**（`sympy.parsing.latex` 需 antlr4-python3-runtime，
  属新重依赖）；改**受限 LaTeX 子集归一 + `sympy.sympify` 等式判断**；超出子集或解析失败 → **降级自评并标 `formula_fallback`**，
  绝不猜对错。
- 交付：
  - 新增 `judge/latex_subset.py`：确定性字符串规则转换器，支持子集 `\frac{a}{b}` / `\sqrt{a}` / `a^{b}` /
    `\cdot` `\times` `\div` / `\left` `\right` / `\%` / `\pi` / `e^{x}` / 四则括号与等号两侧；
    **超出子集（积分、求和、矩阵、`\begin{...}`、未识别宏）抛 `UnsupportedLatex`**；
  - `judge/normalize.py` 增 `formula_equivalent(a, b) -> bool | None`（None = 不可判）：先走现有 NFKC/有理数规则，
    再试 sympy；`sympify` 前后做变量与运算白名单检查，**禁 eval/exec、禁任意属性调用**，只做 `Eq` / `simplify(lhs-rhs)==0`；
  - `judge_answer` 接入：仅当题目为公式类时尝试——**触发面 = 题面/答案含 `\宏` 或 `^` 标记**
    （卡原写的 `answer_kind == formula` 未实现，2026-11-13 交付后由审核方收敛口径）；
    返回 正确 / 错误 / **unknown → fallback**；
  - fallback 走既有自评路径（`source=student_self`），UI 标注"公式题：系统未自动判定，请自评或家长核对"，
    `formula_fallback` 作为标签记入 payload（**不进判分结论、不影响掌握度算法**，须有集成断言锁定）；
  - 题库 `verify` 表达式仍走 AST 沙箱，本票不改。
- DoD：正例 ≥12 条（`\frac{1}{2}≡0.5`、`\sqrt{16}≡4`、常数/单位等价等；**纯文本等式如 `2(x-3)+4=3x-5`
  与 `x=3` 不进公式分支**，由既有文本/有理数规范化比对处理，等价性仅在 `formula_equivalent` 函数层断言）；
  负例不误判为对；`UnsupportedLatex` 用例（积分/矩阵/未知宏）→ 返回 None 且走自评、不报错；
  **白名单必须被"语法合法但结构被禁"的输入直接打到 `_parse_formula_side` 上并断言精确拒绝码**
  （属性访问/下标/多参或关键字调用/白名单外名/下划线名/字符串常量/裸 lambda/超大常数），
  且变异"关掉 `_validate_formula_ast` 闸门"时这批用例必须全部变红；同输入重放一致；
  全量 pytest 绿 + `ruff check --no-cache` + build；**`requirements.txt` 零变化**。
- 禁止：引入 antlr4-python3-runtime 或任何新依赖；`eval`/`exec` 或 unrestricted `sympify`；
  把 fallback 伪装成"判对"；对依赖图形的题（`figure`）启用公式判分；改 `judgeAnswer` 既有非公式路径行为。

---

## Phase 5 —— 开源分发与打包
- **P5-1 首次运行向导 + 热配置**——2026-11-03 拆成两票，先修地基再做界面。
  - **背景（审计发现的真实缺陷，必须先修）**：`app/core/config.py` 里 `PROJECT_ROOT = API_DIR.parent`。
    原生跑时它是仓库根、`config/app-config.json` 读得到；**Docker 形态下 `API_DIR=/app`（WORKDIR），
    `PROJECT_ROOT=/`，`app_config_path()` 指向容器根的 `/config/app-config.json`** ——Dockerfile 没有
    COPY `config/`、compose 也只挂载 `./data` 与 `./seeds`，于是 `daily_review_limit` /
    `daily_recitation_limit` / `exam_day_limit_factor` **在 Docker 下永远读不到、静默用默认值**，
    AGENTS §5 承诺的"UI 内改免重启"在主部署路径上是空的。
  - **P5-1a 配置持久化修复 + 家长配置端点（先做，本票）** —— **已完成（2026-11-04，待评审）**
    - 交付：`runtime_config` 三级解析（`WENGU_APP_CONFIG` → `<data_dir>/app-config.json` →
      仓库根 `config/` 只读回退）、原子写 + 并发锁、`GET/PUT /api/config`（`require_parent`、
      白名单 + 区间、422 不写盘）、备份打包 `<data>/app-config.json`（manifest 记 sha256）、
      `restore.ps1`/备份文档/config 文档/docker 文档/AGENTS §5 同步。
      无迁移（head 仍 `0020_recitation`）、无新依赖、未做 `/setup` UI。
    - 路径改为：`WENGU_APP_CONFIG`（测试覆盖）→ **`<data_dir>/app-config.json`**（Docker 与原生都持久）
      → 兼容回退仓库根 `config/app-config.json`（原生老用户，读到就用并提示迁移，**不自动搬、不静默覆盖**）；
      写入一律落 `data_dir` 那份（同目录 tmp + fsync + `os.replace`，参照 `services/local_seed.py` 的原子写）。
    - `GET /api/config`（**require_parent**）返回生效值 + 来源（file/default/env）+ 当前落盘路径；
      `PUT /api/config`（require_parent）只接受白名单键并校验区间：
      `daily_review_limit 1..200`、`daily_recitation_limit 1..20`、`exam_day_limit_factor 1..3`；
      非法 422 且不写文件；未知键拒绝（防"顺手写脏配置"）。
    - **备份纳入**：`services/backup.py` 打包清单加 `<data>/app-config.json`（存在才加），
      顺带解决 P5-2 已知边界"换机恢复后热参数回默认"；manifest 的 `files` 记录其 sha256。
    - 文档：`config/README.md` 与 `app-config.example.json` 说明新位置与兼容回退；
      `docs/deploy/docker.md` 增补"配置随 data 卷持久、无需额外挂载"；AGENTS §5 的路径口径同步。
    - DoD：Docker 布局回归测试（monkeypatch `API_DIR=/app` 断言解析落 `data_dir`）；
      原生老路径仍可读且**不被写入**；PUT 成功后**不重启**、`GET /api/reviews/due` 的上限立即变化
      （热加载的真实证据）；未解锁 GET/PUT 403；备份包含该文件且恢复后值不丢；全量绿 +
      `ruff check --no-cache` + build。
    - 禁：把密钥写进 app-config（密钥仍只 `.env`）；自动搬运/删除老路径文件；接受白名单外的键；
      为"以后可能要"预留配置项。
  - **P5-1b 首次运行向导 UI（已交付 2026-11-04，PR#33 已合并）**
    - **口径修正（2026-11-04，覆盖 AGENTS §7 的旧表述）**：向导**不采集年级、不做"勾选学科"**。
      理由：v2.5 后 seed 全量装载初中 7–9 三个年级、复习与考核都不以年级为输入，采集了没有任何
      逻辑消费它 = 装饰字段 + 多余 PII；家里就一个孩子，全部学科都是他的，勾选同样无作用。
      AGENTS §7 那句"孩子/年级→勾选学科→选教材 seed"按本票口径执行（向导只做**真有作用**的三件事）。
      **年级重开条件（2026-11-04 定，与 AGENTS §7 同步）**：默认不采集年级；只有出现真实年级噪音
      （到期队列大量涌出已学完年级的知识点、反复考已会的）才做过滤，且顺序必须是
      **先写消费逻辑（过滤 + 测试）再加采集字段**；注意 `cn-math-taxonomy` 的 `grade 10–16`
      语义是"册"不是入学年（设计文档 §14），做错会造成"该复习的看不见"这类实质伤害。
    - `/setup` **单页**（家长解锁才让写，复用 `ParentGate`），三块内容：
      ① **seed 覆盖实况**：调既有 `GET /api/seed/summary`，按数学/英语/物理/语文/化学五科展示
         `topics` 数——注意 `group_by` 对**零主题学科不返回行**，前端必须把"缺席"当 0 处理；
         语文/化学为 0 时引导去 `/local-seed` 建章级点（给链接，不自动建）。
      ② **复习与背诵上限**：调 P5-1a 的 `GET/PUT /api/config`（`daily_review_limit` /
         `daily_recitation_limit` / `exam_day_limit_factor`），保存后无需重启即生效。
      ③ **完成/跳过**：`PUT /api/config {setup_completed: true}`；"跳过"与"完成"写同一个键
         （语义是"不再提示"），**不新增第二个标记键**。
    - 新增配置键 **`setup_completed: bool`**（进 P5-1a 白名单）：⚠️ 现有 `_reject_bool` 校验器
      只挂在三个数值键上，加布尔键时必须**按字段分别校验**——布尔键只认真正的 true/false，
      数值键继续拒绝布尔，不得为省事把"拒绝布尔"改成全局放开或全局禁止。
    - 未完成时 `AppLayout` 顶部一条横幅 + 进入 `/setup` 的链接；**不劫持路由**
      （孩子一打开就被迫填表是错的），完成后横幅消失。
    - DoD：横幅出现/消失有测试；向导写入的上限经 `GET /api/reviews/due` 的 `daily_limit` 立即生效
      （不重启）；`setup_completed` 拒绝非布尔值且数值键仍拒绝布尔；语文/化学零主题时向导显示 0
      并给出 `/local-seed` 链接；窄屏可用；`pytest -m e2e` 加第 7 条（全新库 → 横幅出现 →
      向导设上限并标记完成 → 横幅消失 → due 的 `daily_limit` 为新值）。
    - **交付（2026-11-04）**：
      - 后端：`setup_completed` 进白名单，布尔键按字段独立校验（`true/false` 之外 →
        422 不写盘），三个数值键仍拒绝布尔；新增公开只读 `GET /api/setup/status`
        （仅返回该布尔，供未解锁横幅）；完整 `GET/PUT /api/config` 仍 `require_parent`。
      - 前端：`SetupPage` 单页 + `/setup` 路由 + `AppLayout` 未完成横幅；seed 五行
        `?? 0`、零主题显示 0 与 `/local-seed` 链接；上限保存提示“已生效，无需重启”；
        完成/跳过共用 `setup_completed=true`；`ParentGate` 解锁后才可写。
      - 验证：`pytest -q` **521 passed**（unit 344 / integration 170 / e2e 7），
        `pytest -m e2e` 7 条全绿（含新增第 7 条），`ruff check --no-cache .` 绿，
        `npm run build` 绿；无迁移（head `0020_recitation`）、无新依赖、未劫持路由。
    - 禁：采集姓名/生日/年级/照片；强制路由劫持；在向导里放模型 Key 输入（v2.5 零模型，
      放了就是邀请回归）；新增 `setup_skipped` 之类第二个标记键；把单页做成多步向导机；
      为了"覆盖情况"新建端点（`GET /api/seed/summary` 已够用）。
- **P5-2 一键备份/恢复（UI 内 + 可选云备份）**：本地导出 SQLite + 图片目录 + `data/inbox` zip / 导入恢复；可选云备份（KuroTutor 模式）AESGCM+scrypt 逐文件加密 → 每日独立 git commit 推家长私有仓库 → `git checkout` 回滚；清空级联清理原文/派生/证据/`practice_records`（`attempts` 里 `source=system_quiz` 的行随错题级联）。
  **已完成（2026-10-31，v1）**：家长区「备份」页导出 `VACUUM INTO` 一致性快照 + `uploads/` + `seeds_local/`（含 `_id_counters.json`）+ 未处理 `inbox/` + `manifest.json`（各文件 sha256、alembic 版本、表计数），只留最近 10 份；导出全程只读、不写业务表。恢复走 `scripts/restore.ps1` + `docs/deploy/backup-restore.md`（停服 → 安全副本 → 整库替换 → `/health` 核对），**明确不做运行中热恢复**；三端点挂 `require_parent`，下载名做路径遍历防护。**剩余**：可选加密云备份/回滚、清空级联清理、在线导入 UI。
- **P5-3 可选密码 session 鉴权开关**（默认关）；README/首页醒目警告公网须先加鉴权与隔离或走 Tailscale。禁：做用户体系/多租户。
- **P5-4 教材 seed 包机制**：多教材 JSON/YAML 可安装可切换。
- **P5-5 开源基线**：LICENSE + 中英 README（一行安装）+ 隐私声明 + CHANGELOG + `.env.example`；合规点名《个人信息保护法》《未成年人网络保护条例》；**第三方数据 License 署名 + NC 声明**强制。
  ⚠️ **本行原有括注"v2.5 后无任何云转录/云推理，题目图片不进网络"已删除**（审核方 2026-11-16）：
  内核确实零模型，但**可选外部转录会把擦除 PII 后的卷面送进境内第三方 AI**，该句是文档过实、
  与本票 ③/⑦ 的口径自相矛盾。准确表述：wengu 内核零云推理；上云只发生在家长自行启用的外部转录，
  须过 `transcribe/README.md` §0 checklist，或走离线 `/import`。
  **现状（2026-11-16 复核 main `545ca3d`）**：`LICENSE` / 中文 `README.md` / `CHANGELOG` /
  `wengu-api/.env.example` / `THIRD-PARTY-NOTICES.md` / 合规点名（README:149 一句）**已在盘上**；
  仍缺 = 英文 README、独立 `PRIVACY.md`、GitHub 仓库元数据与 Release；
  另实测到三处**盘上不一致**：① `README.md:45` 克隆地址仍是占位符 `https://github.com/<你>/wengu.git`
  （`docs/deploy/docker.md:15`、`from-zero.md:46` 已是真地址——旧卡 ② 记成已完成项，属半拉子当完成）；
  ② `LICENSE:15-17` 把第三方数据声明段**插在 MIT 正文中间**，导致 GitHub
  `license.spdx_id = NOASSERTION`（仓库对外看像"未声明许可"）；
  ③ README 文档地图把唯一事实来源写成"v2.5，§16 定稿"，盘上已是 **v2.8（含 §18/§19）**。
  - **v2.8 扩卡（§19-F，2026-11-12 确认）**：
    ① README 前三行定位改"本地优先的错题复习工作台（AI 转录为可选外挂）"，明写不判真实作业、不生成讲解、零模型内核；
    ② 克隆地址 `<你>/wengu.git` 改真实地址 `beiyunanpeng/wengu`；
    ③ 新增独立 `PRIVACY.md`：数据本土化、外部转录上云字段清单与擦除指引、监护人告知与单独同意文案、离线 `/import` 路径；
       **修正旧句"题目图片不进网络"**——内核零模型，但可选外部转录会把擦除 PII 后的卷面送境内第三方 AI（见 `transcribe/README.md` §0）；
    ④ CC BY-NC §3(a)(1) 全项：原作者姓名、版权声明、许可通知、免责声明、原始 URI、"已修改（转换初中子集）"标注、
       `upstream_commit` 钉死为具体 SHA；补 SPDX；表述为 **"MIT 代码 + CC BY-NC 数据"分层**（整体不称 OSI 开源）；
       核对 LICENSE 使 GitHub API `license` 不再为 `NOASSERTION`；
    ⑤ 仓库 `description` / `topics` / `homepage`、首个 GitHub Release、开启 Discussions
       —— **均为审核方侧 gh 动作，不进本票**；施工方不得声称完成。发布说明底稿 `tag-v0.6.0.txt`
       在**仓库外**工作区（不在 git 内），且其 head 仍写 `0020_recitation`（现 0023），发 Release 前须按当前 main 复核；
    ⑥ DoD：陌生人 5 分钟内从 README 完成合规判断并装起来；克隆地址可直接复制；隐私声明与 transcribe checklist 口径一致；
       CC 署名可人工核对；GitHub 识别 MIT；Release 可下载。
    ⑦ 禁：声称"完全不上云"；隐瞒外部转录；删除历史条目。
    ⑧ **2026-11-16 范围防漏（审核方补，因本票必读会读到 §19-G-1 的"全量内置"定案）**：
       本票**不得**改 `import_seed.py` / `import_questions.py` 的 `grade 7-9` 过滤器、
       **不得**向 `seeds/data/` 增加任何知识点/先修边/题目（那是 P5-10）；
       `LICENSE-data.md` 与 `_source.json` 的 `modified` **只写当前事实**（初中 664 点 / 1018 边 / 2803 题），
       不得写"后续将全量导入"这类预告。DoD 加一条自证：**`topics.json` / `questions.json` 条目数不变**。
       理由：提前扩数据会毁掉 P5-9"作用域先被证伪再扩段"的前提，顺序是 AGENTS §7 写死的。
  - **2026-11-16 定案（A 方案）+ 上游事实取证**：
    **A 方案** = `LICENSE` 回到**纯 MIT 规范文本**，数据许可另置新文件 `LICENSE-data.md`
    （GitHub 可识别 MIT、下游合规扫描判对，"代码 MIT + 数据 CC BY-NC"分层更清楚；
    备选 B"段落后移"识别结果不确定、C"接受 NOASSERTION"对目标受众最易误读，均否）。
    上游事实（已取实，非推断）：作者 **Aifeng**（GitHub `xiaoyang111222`、X `@hassanyehiaa`、pansgo.com），
    许可 **CC BY-NC 4.0**，所用快照 commit
    **`d58785cef744341bf02d41e5568ebb953595ab18`**（2026-10-23T12:40:17Z）。
    **SHA 取证方法**（来源是 GitHub zip、无 `.git`，故 `upstream_commit` 才一直是 null）：
    按内容寻址反查——本地 `git hash-object` 的 blob 与 GitHub contents API 在该 ref 返回的 blob 逐一相等
    （`topics.json 79cd0a87…`、`questions.json 76058ca5…`、`dependencies.json 28cee1a8…`、`README.md cc60a25e…`），
    父提交 `7dc3d6ad…` 的 README blob 为 `76db74d1…`（不等）→ 唯一锁定；
    本地 `topics.json` 无任何 `cnl_` 语文知识点，排除全部 10-24 的语文提交。
    `topics` 导入 10-24、`questions` 导入 10-29 但**同一快照**（三个 blob 全等即证）。
    ⚠️ 纪律：**探测不到就写 null + 警告，严禁按日期猜 SHA**；`import_seed.py:133` / `import_questions.py:171`
    新增 `--upstream-commit` 显式覆盖。可投单正文见 `docs/tooling/qoder-build-plan.md` 的 P5-5 块。
- **P5-6 交付口径与盘上一致性清理（v2.6 审计新增）**：把审计报告里 B/C 类"文档说的和代码不一致"一次性收干。
  - **孤儿表退役**：`photo_captures` / `photo_capture_items` / `problem_extractions` 是 v2.5 视觉栈退役后的遗留
    （迁移仍建表、但业务代码**零引用**；`problem_extractions` 的两个 FK 还指向另两表）→ 出**可逆迁移 0019**
    DROP 三表（先子后父，`downgrade` 重建表结构，不承诺找回数据），同步删 `models/ingestion.py` 里的两个
    ORM 类与 `__init__` 导出；`backup.py` 的 `COUNT_TABLES` 同步去掉这两张表（`problem_extractions` 本不在其中）。
  - **口径复核**：`docs/STATUS.md` 的 Phase 5 行与 §7 表格按盘上事实改写（不许再出现"中英 README 已就位"这类过实）；
    `wengu-web/README.md` 的目录/页面清单已按实际修正（2026-11-02）。
  - DoD：迁移 up/down/up 可重入并有 `test_migrations.py` 覆盖；DROP 前文档写明"先跑家长区导出备份"；
    全测试绿；表清单与 STATUS 一致（业务表数随之从 22 变 19，需在 STATUS 明写）。
  - 禁止：顺手 DROP 任何仍被读的表；手改生产 `wengu.db`；把迁移写成不可逆。
  **已完成（2026-11-03，孤儿表切片）**：迁移 `0019_drop_orphan_photo_tables` 实跑 up/down/up；
  三张孤儿表及显式索引已一次 DROP（不留悬空外键），ORM 类/`__init__` 导出/`backup.py` 表计数同步清理；
  业务表 22 → 19，STATUS §4.18/§5.2 已写清；全量 398 passed、`ruff check --no-cache .` 绿。**剩余**：
  Phase 5 行与 §7 表格的进一步口径复核。

### P5-7 转录可选包 T1：原型收口与两处包内修复（v2.8 §19-D；纯新增）
- **背景**：`transcribe/` 目录（7 文件）目前未跟踪；审核方 2026-11-12 实跑：`evals` 13/13 通过、UTF-8 下 `selfcheck`
  10 OK / 2 DRIFT / 1 WARN；但在 Windows 默认 GBK 控制台 **`selfcheck` 因记录名含 `↔` 抛 `UnicodeEncodeError`**
  （打不到汇总、退出码被 traceback 取代）；`selfcheck` 只读 `docs/tooling/wengu-transcribe.md` 的 frontmatter，
  **未校验真正分发的 `transcribe/skills/wengu-transcribe/SKILL.md`**。行为锚定（后端测试消费 fixtures）归 P5-8。
  方案与原型见根目录两份 2026-11-12 文档（不进仓库）。
- 交付：
  - 修 `validate.py` 输出编码：`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（或记录名全 ASCII、详情保留中文），
    保证 Windows 默认控制台 `selfcheck` / `evals` / `check` 三命令跑完并正确返回 0/1；
  - `selfcheck` 增加 **portable Skill 校验**：读 `transcribe/skills/wengu-transcribe/SKILL.md` frontmatter 的
    `template_ref` / `contract_ref`，断言文件存在且与契约 `template.id/version`、`channels.primary` 对齐，不一致报 DRIFT；
  - 将 `transcribe/` 7 文件（含上述修复）作为本票提交入 main；`contract/ingestion_v1.json` 保持 `"status": "proposal"`；
  - **修 `transcribe/validate.py` 的 2 处 ruff `UP038`**（`isinstance` 元组写法改 `X | Y`）：审核方 2026-11-12 实跑确认
    票内路径 `ruff check --no-cache app tests ../wengu-web/src ../wengu-web/tests` 全绿，但**全仓** `ruff check ..` 报这 2 处；
    目录一旦提交进 main，CI 的 ruff 步骤就会变红，必须在本票内修掉（不得靠 ruff 配置排除目录绕过）；
  - CHANGELOG `[Unreleased]` 加条目；README/STATUS 不夸大（不得写"转录准确率已验证"）。
- DoD：Windows 默认 `cmd`/PowerShell（GBK）下 `python transcribe/validate.py selfcheck` 输出完整汇总且无 traceback；
  有 DRIFT 时 `--strict` 退出 1、无 DRIFT 时 0；`evals` 13/13；`py_compile` OK；portable Skill 引用被校验
  （人为改坏 `template_ref` → DRIFT，可证伪）；`wengu-api/requirements.txt` 与 Docker 镜像零变化；
  fixtures 无真实作业内容（抽检 + 文档声明）；提交仅 `transcribe/**` + CHANGELOG。
- 禁止：把 transcribe 接入后端运行时/API/CI 主链；修改 `docs/templates` 或旧 Skill（属 P5-8）；
  引入第三方依赖（含 jsonschema）；用"文档说明请设置 PYTHONIOENCODING"代替修复（必须在默认控制台可跑）。

### P5-8 转录契约收口 T2：模板 v2 + 文档口径 + CI + 行为锚定（v2.8 §19-D；改现有文件）
- **背景（读盘 2026-11-12）**：模板 `docs/templates/doubao_transcribe_v1.md` `version: 1`、`schema_fields` 8 项（缺 `verify`），
  与后端 `FIELD_LIMITS` 9 项不一致；模板「与 wengu 系统的契约」与旧 Skill 仍要求 `evals/transcribe/`（P1-12 后不存在）；
  旧 Skill 硬编码 `D:\MyProducts\...` 且 inbox 路径错误；契约 `status: proposal`；CI 无 transcribe job；
  `validate.py` 与后端校验是两份实现（selfcheck 只比常量）。
- 交付：
  ① **模板版本已由 P1-17 升到 v2**（含 `correction_notes`），本票**不得重复升版**：只做 `schema_fields` 与契约的字段收口——
     补 `verify` **或**明确写"verify 不向转录端暴露、仅题库通道使用"（二选一并写理由）；「与 wengu 系统的契约」改指 `transcribe/evals/`。
     **仅当本票确实改了模板语义时**才升到 v3，并在 CHANGELOG 说明为什么不是 v2。
  ② `docs/tooling/wengu-transcribe.md` 改为指向 `transcribe/skills/wengu-transcribe/SKILL.md`，删除本机绝对路径与错误 inbox 路径。
  ③ 契约 `status: active`、`template.version` 与模板一致（P1-17 后应为 2，本票若升 v3 则同步为 3）；
     `selfcheck` 增加模板 `id` ↔ 契约 `template.id` 断言。
  ④ **行为锚定**：`wengu-api/tests/` 新增集成测试，直接加载 `transcribe/evals/fixtures/*.json`，用后端真实
     `validate_envelope/validate_and_normalize` 断言与 `_expect` 一致（不得复制校验逻辑；后端模块不可 import 时用最小驱动）。
  ⑤ CI 新增独立 `transcribe` job：`selfcheck --strict` + `evals` + `py_compile`，不装额外包、不并入 api job。
- DoD：`selfcheck --strict` 0 DRIFT；模板 `version` 与契约 `template.version` 一致（P1-17 后为 2，本票若升 v3 需说明理由）；文档不再出现不存在的 `evals/transcribe/`；旧 Skill 无本机绝对路径；
  后端新测试消费 fixtures 全绿，且**人为改坏一处后端校验逻辑 → 该测试变红**（可证伪）；CI 双绿 + 新 job 绿；全量 pytest/ruff/build 绿。
- 禁止：恢复模型在环/视觉依赖；让后端 import transcribe 包（测试读 fixtures 文件即可）；把契约改成第二真源；
  顺手改 P1-16/P1-17 语义；在 CI 安装额外依赖。

### P5-9 学段作用域 `seed_grade_ceiling`（v2.8 §19-G；开源多家庭前置；服务端过滤、零迁移）
- **状态：已合并（2026-11-17，PR#62 squash → main `efd7c1b`；原分支 `feat/p5-9-seed-grade-ceiling` 已删）**。
  验收：审核方自跑全量 **824 passed / 317.80s**（782 + 42）、`ruff --no-cache` 全仓绿、
  `selfcheck --strict` 18 OK / 0 DRIFT、`npm test` 57/57、`tsc` exit 0、build ✓、CI 三 job 绿；
  零触碰独立复核（`migrations/`、`seeds/data/`、`app/services/`、`app/models/`、依赖清单全未动）。
  审核方自主变异三次（换靶点）：默认上限 16→9 → **12 fail**；quizzes 侧作用域恒真 → **5 fail**；
  SQL 侧 `<=`→`<`（边界包含性）→ **6 fail**；还原 sha256 一致。
  - ⚠️ **两处卡面缺陷由审核方认领**：① **DoD 双断言自相矛盾（第 16 次，类型同 §19-H 的互斥算式）**——
    我写"ceiling=9 时诊断路径仍返回该低学段点，**同时它不出现在 `quiz_topics` 里**"，
    但 ceiling=9 是上限式、本就包含小学，有题的小学点就该能选。施工方**没有**用退化夹具凑过这条断言，
    而是按正确语义实现、另加测试钉死（`test_lower_stage_stays_selectable_within_ceiling`）并上报矛盾
    → 新规矩见 **§19-L 纪律⑥**。② **白名单第三次写窄**：漏了 `test_config_api.py`
    （`describe_config` 增键后全量 dict 断言的必然连带）与新建 `src/setup/gradeScope.ts`
    （前端可单测的前提）；两处施工方都主动标注"白名单外"，未静默扩面。
  - 实现要点留档：SQL 与 Python 两侧**同一把尺**（连 `CAST('七年级')` 得 0 → 恒保留这种怪语义也在
    Python 侧逐字复刻）；`_grade_scope_condition()` 的 docstring 把字典序坑写进代码；
    枚举守卫用**行为探针**（"-2..20 里被接受的整数集合恰为 {6,9,16}"），不止断言常量。
  - 下一步：**P5-10 扩数据**（小学 450 点 / 高中 707 点）才真正改变数据面，做完是 `v0.7.0` 的自然节点。
- **为什么先做这票**：方案 1 定案 = **全量内置 + 学段作用域**（决策人 2026-11-16 点头）。
  AGENTS §7 已写死顺序"**先写消费逻辑（过滤 + 测试），再加采集字段**"，所以本票只做作用域，
  数据扩段是 **P5-10**。本票落地后库里仍只有初中 664 点，作用域是**可被证伪的空跑**——
  这不是浪费，正是 P5-10 的前置验收闸门。
- **现状（2026-11-16 读盘 main `81ce118`）**：
  - `KnowledgeSeed.grade` 是 **Text 可空列**（`app/models/knowledge.py:23`），装载后存数字字符串
    （`tests/integration/test_seed_loader.py:88` 断言 `by_id["cnm_001"].grade == "7"  # 文本列`）。
    ⚠️ **本票最大的坑在这里**：SQLite 对 Text 做 `<=` 是**字典序**，`'16' <= '9'` 为 **真**。
    任何 `KnowledgeSeed.grade <= "9"` 式写法都会把高中点（10-16）当成"不超过 9"放进来，
    作用域**形同虚设且不报错**（库里现只有 7-9，测试还会全绿）。
    必须显式 `func.cast(KnowledgeSeed.grade, Integer)`——同类先例见 `api/seed.py:64-66`
    那条注释（Boolean 直接 sum 会被结果处理器转成 True/False，必须显式 cast）。
  - 三个知识点列表/计数面（router **均未挂** `require_parent`，孩子区可达）：
    `api/seed.py:90` `GET /api/seed/topics`（conditions 只有 subject/q；前端 `endpoints.ts:234`）、
    `api/quizzes.py:116` `GET /api/quizzes/topics`（遍历 `bank.topics`，按 subject/keyword 过滤；`endpoints.ts:459`）、
    `api/seed.py:57` `GET /api/seed/summary`（按 subject 计数 + 边总数）。
  - 运行时配置现状：`core/runtime_config.py` `_RULES:221-224`、`_ALLOWED_KEYS:225`（现 4 键）、
    `validate_updates:186` 返回签名是 **`dict[str, int | float | bool]`**、每键一个访问器
    （先例 `daily_review_limit:268`）；写入落 `<data_dir>/app-config.json`，`.env` 优先。
  - ⚠️ **配置读取面的约束**：`app/api/config.py:24` 把 `require_parent` 挂在 **router 级**，
    **连 `GET /api/config` 都要 PIN**。所以作用域**绝不能由前端读值再过滤**——孩子区读不到那个键，
    且孩子能给自己放宽范围。**过滤必须发生在服务端**，前端只显示返回结果。
  - 上游 grade 实测为 **int 1–16、无 NULL**（快照 `d58785ce`：小学 450 / 初中 664 / 高中 707；
    初中→小学先修边 **74** 条、初中→高中 **0** 条，故"上限式"过滤足以覆盖现实场景）；
    而**本地 seed 点可以没有年级**（`LocalTopicCreatePayload.grade?: number | null`，语文/化学走 `api/local_seed.py`）。
- 交付：
  ① 新配置键 **`seed_grade_ceiling`**，取值只能是字面枚举 **{6, 9, 16}**，**默认 16**
    （= 全量可见 = 现有安装零行为变化，开源用户升级后不会突然看不见东西）；6=只小学、9=小学+初中、16=全部。
    **不做多选 list**：`validate_updates` 的 int|float|bool 签名装不下 list，为它扩类型系统不值当（另票再议）。
  ② 服务端过滤：`seed_topics` 与 `quiz_topics` 按 `cast(grade, Integer) <= ceiling` 收窄；
    `seed_summary` 的计数**必须用同一把尺**（否则"设置页说 1114、选择器里只有 664"这类自相矛盾会复发）；
    **`grade` 为 NULL 的点一律保留**（家长自建语文/化学点不能被作用域吃掉）。
  ③ **回溯与诊断路径明确不受 ceiling 限制**：`PrerequisiteEdge` 遍历、前置诊断、错题已挂载的点
    （错题本/详情/复习队列）**一律照常显示**。ceiling 管"能主动选什么"，不管"能看见什么根因"——
    做成硬隔离就等于把 P5-10 要买的回溯能力当场锁死。
  ④ `SetupPage.tsx`（家长区，唯一写 `/api/config` 的页面，`endpoints.ts:1042/1046`）加**三档单选**
    （"小学"/"初中"/"高中" → 6/9/16），文案写明"只影响可主动选题的范围，不影响复习与诊断回溯"；
    **不做数字输入框、不做年级多选**。
  ⑤ `runtime_config.py` 补访问器 `seed_grade_ceiling()`（照 `daily_review_limit:268` 写法）；
    非法值 → `ConfigError` 稳定码，`PUT` 返回 422。
- DoD（每条都要能变异证伪）：
  - **字典序反例（本票主锚点）**：造 grade `"9"` 与 `"16"` 各一点，`ceiling=9` 时断言 `"16"` **不在**结果、`"9"` 在。
    **变异**：去掉 cast、退回字符串比较 → 该断言必须红；红不了说明测试本身也在用字符串比较，一起返工。
  - **枚举字面串钉死**（§19-L 纪律①）：断言合法值集合**等于字面串** `{6, 9, 16}`（不许引用被测常量），
    且 `ceiling=7` / `ceiling="9"` / `ceiling=0` 全部 422。
  - **默认零变化**：不写该键时，三个面的读数与合并前**逐字相同**（快照断言或独立重算对齐，不许写死期望值）。
  - **NULL 保留**：`grade=None` 的本地 seed 点在 `ceiling=6` 时仍在列表内。
  - **回溯不受限**：造一条 `初中 → 小学` 先修边，`ceiling=9` 时诊断/前置路径**仍返回小学点**，
    ~~同时该小学点**不出现在** `quiz_topics` 里（两件事必须同时成立，缺一即口径写歪）。~~
    ⚠️ **后半句是审核方 DoD 自相矛盾（第 16 次，类型同 §19-H 互斥算式），P5-9 验收时由施工方上报**：
    `ceiling=9` 是**上限式**、本就包含小学，有题的小学点就该能主动选。
    正确不变量三条：回溯链完整（`prerequisites_of` / `edges_total` 不受 ceiling 影响）+
    **有题的低学段点仍可主动选** + 越界学段不可选。已按此实现并另加测试钉死，规矩见 §19-L 纪律⑥。
  - **计数同尺**：`seed_summary.topics_total` == 同 ceiling 下 `seed_topics` 的 total（一条集成断言钉死）。
  - **服务端过滤证明**：`wengu-web/src` 内**不得**出现 `ceiling` 字样的过滤逻辑（grep 断言）；
    且孩子区未解锁时 `GET /api/config` 仍被挡、而列表端点照常按 ceiling 收窄（证明不依赖前端读配置）。
  - 全量 `pytest -q` 绿（当前基线 **763**，如实报新数）、`ruff check --no-cache .` 绿、
    `npm run lint/test/build` 绿；**零迁移**（不动 `grade` 列类型、不新增表）。
- 禁止：把 `grade` 列改成 Integer（迁移成本 + 与 `test_seed_loader.py:88` 既有断言冲突，本票用 cast 解决）；
  在前端做过滤或让前端读 ceiling；做成多选/年级选择器；把 ceiling 用于隐藏复习队列或诊断回溯；
  顺手导入小学/高中数据（那是 P5-10，混投会让"默认零变化"断言失去意义）；
  为容纳 list 值而扩 `validate_updates` 的类型系统；把作用域存进 SQLite 新表或 app-config 之外的新位置。

### P5-10 全量收录小学与高中 seed（v2.8 §19-G-1 的后半；改变数据面；零迁移、零新依赖）
- **状态：已合并（2026-11-17，PR#63 squash（含修复轮 `08a3007`）→ main `6edd2b8`；原分支 `feat/p5-10-full-seed` 已删）**。
  验收（审核方独立复算，不采信自述）：数据自数 **1821 = 450/664/707**、**2917**（边带 初初 1018 / 初小 74 /
  小初 620 / 高高 1006 / 高初 196 / 高小 3，无悬空端点）、**7431 = 1800/2803/2828**（topicId→grade 关联，0 悬空）；
  `load_bank` 实测 verified **5996** / unverifiable **1435** / figures **267** / `dropped={}`，
  reasons 七键与 `load_quality.full` **逐键相等**；耗时 `load_bank` 1.52 s、`load_seed` 冷 0.36 s（阈值 3 s）；
  初中子集用 `git show origin/main` 旧 blob 与现文件各自筛 7–9 后**逐条语义全等**（664/2803/1018）；
  TSV 665 行、664 数据行 grade 全 ∈ {7,8,9}、对 HEAD 零 diff；策展键（`upstream_commit` / `commit_evidence` /
  spdx）逐字未动。全量 **pytest 833 passed**、`ruff --no-cache` 全仓绿、`selfcheck --strict` 18 OK / 0 DRIFT /
  0 WARN、前端 57 + tsc + build 绿、CI 三 job 绿。自主变异（换靶点）：导出常量 `range(7,10)→range(7,11)` →
  **双红**；`DEFAULT_SEED_GRADE_CEILING 16→9` → **12 红**；合成矛盾题探针 → `dropped={'verify_mismatch':1}`
  且不入库（丢弃路径活着；真实数据 mismatch=0 是真的没有矛盾，不是静默收下）。变异还原 sha256 一致。
- **修复轮 1（CI api 1 failed，其余两 job 绿）**：唯一红 `test_tsv_stays_junior_scoped` 的逐字节比对——
  `export()` 用 `write_text("\n".join(...))`，换行随平台：Windows 翻成 CRLF 恰与仓库 CRLF blob 相等（本机绿），
  Linux 产出 LF（CI 红）。`08a3007` 改 `open(..., newline="\r\n")` 写死修复：单文件 +3/−1、TSV 零 diff、
  **断言未放宽**；审核方复验（diff 范围 / 字节 / 15 passed / CI 三绿）通过后合并。
  归因：**审核方新增断言的跨平台盲区**（Windows 绿 ≠ CI 绿），固化为 §19-L 纪律⑦。
- **两条登记**：
  ① 票面白名单漏 4 个**必然连带**的测试文件（`test_import_questions` 夹具补 grade + 新增 2 条参数化守卫、
     `test_reviews_api` 的 thin 测试改受控合成池、`test_bank_runtime` / `test_bank_lifecycle` 物理基线
     368→1076 等）——审核方白名单**第 4 次写窄**；施工方逐个单列上报而非静默扩面，是合规动作。
  ② 10 处文档口径清单**漏了 `seeds/README.md`**（审核方第 17 次卡面缺陷，认领）——施工方如实上报、
     未擅自扩面；裁定**另票清理**（连同 CHANGELOG P5-9 词条"升级零行为变化"的失效括注与耗时措辞）。
- **前置**：P5-9 学段作用域已上线（`seed_grade_ceiling`，默认 16）。
  **顺序不可反**——AGENTS §7 写死"先写消费逻辑（过滤 + 测试），再加采集字段"，
  作用域先被证伪，扩数据才是纯增益、可回滚。
- **三条定案（决策人 2026-11-17 点头）**：
  ① **ceiling 默认值保持 16（方案 A）**。理由：默认 9 对高中家庭是**功能不可用**（组不了本学段卷）、
     对初中家庭只是**噪音**（列表多出够不到的点），不可用 > 噪音；且开源产品不替用户假设孩子学段。
     代价与缓解：初中家庭升级后选择器出现小学/高中点 → README 与 STATUS 明确写
     "初中家庭建议在家长设置把学段作用域调到 9"，向导文案同步改口径。**不新增采集字段**（方案 C 否）。
  ② **转录目录维持初中-scoped**（`topics_junior.tsv` 仍 665 行），扩段与"候选集变化"分两票——
     后者要真实使用信号（非初中家庭真用转录时才设计按家庭生成目录）。
  ③ **新增数据 mismatch != 0 → 丢弃并上报**，不整批暂缓、也不静默收。
- **现状（2026-11-17 读盘 main `e95fc66`）**：
  - `scripts/import_seed.py`：`JUNIOR_GRADES = range(7, 10)`（:27）、过滤 :76、
    先修边"两端点都在装载集内" :104-116（跨学段丢弃计数 :128）、`filter` 与 `grade_semantics_note`
    两个字面串 :174-175。快照 commit 已钉死 `d58785ce…`（P5-5），**扩段不需要重取快照**——
    小学与高中数据本来就在快照里，只是被过滤器筛掉。
  - 上游快照实测：知识点 **1821 = 小学 450 + 初中 664 + 高中 707**；先修边 **2917**
    （初中→初中 1018、初中→小学 **74**、小学→小学 620、高中→初中 196、高中→小学 3、高中→高中 1006）；
    题 **7431 = 小学 1800 + 初中 2803 + 高中 2828**。**初中→高中先修边 0 条**（回溯只向下）。
  - 现库 664 / 1018 / 2803；`load_bank` 实测 **373 ms**（verified 1738 / unverifiable 1065，
    其中 532 无 `verify`、492 `sandbox:forbidden_call`）。全量线性外推约 1.0 s——**性能不是约束**。
  - ⚠️ **转录目录是"借来的过滤"（本票最容易漏的一处）**：`scripts/export_topics_junior.py` 的 docstring
    明写"过滤（grade 7–9）已在 P1-1b 的 import_seed.py 完成，这里不重造逻辑"。import_seed 一旦不过滤，
    `docs/templates/topics_junior.tsv`（现 665 行 = 表头 + 664）会**静默涨到约 1822 行**，
    外部转录的 `suggested_topic_id` 候选集随之含小学/高中点、发给第三方工具的提示文本体积近三倍。
  - 会被推翻的测试（4 处，都是"改对"不是"放宽"）：`test_bank_seed.py`（`total == 2803`、
    `topics_total == 664`、`topics_with_questions == 664`，以及 P1-5 的"2803 题自答全对"硬回归）、
    `test_seed_provenance.py:186-188`（664/1018/2803）、`test_quiz_api.py:417`
    （P5-9 的 ceiling 测试**前提就是"真实 seed 题库 664 点全为 7–9"**）、
    `test_local_seed.py:632`（TSV `1 + 664 + 1` 行——只要导出脚本自己过滤就继续成立）。
  - 会被推翻的文档口径（10 处）：`AGENTS.md:72`「seed 全量装载初中 7–9」、`README.md:99` 的 2803 题、
    `LICENSE-data.md:12-14` 三条计数、`THIRD-PARTY-NOTICES.md` §1、`docs/STATUS.md` 140/290/301/582/668/915、
    `docs/methodology/evals.md:13`「2803 题自答全对」、`SetupPage.tsx:198`「初中 7–9 全量装载」、
    `_source.json` 的 `filter` / `modified` / `counts` / `grade_semantics_note` 四字段。
- 交付：
  ① `import_seed.py` / `import_questions.py` 的学段过滤改为**参数驱动**（如 `--grades primary,junior,senior`，
     默认仍 7-9 以保持脚本可复现），实际生效的过滤写进 `_source.json.filter`；产出全量 1821 / 2917 / 7431。
     **不得**把 `JUNIOR_GRADES` 语义删掉而不留可复现路径。
  ② **转录目录自己过滤**：`export_topics_junior.py` 显式按 grade 7–9 过滤（不再继承 import_seed 的行为），
     `topics_junior.tsv` 仍 665 行；本票**不改模板 `version`**（契约字段未变、只是候选集来源变了），
     但 CHANGELOG 须记一句"目录生成改为脚本内过滤，输出内容不变"。
  ③ 两个 source 文件同步：`filter`、`modified`（改为"全学段收录；小学/高中为新增"）、`counts`
     （含新增部分的 verified/unverifiable/mismatch 分布）、`grade_semantics_note`；
     **`upstream_commit` 与 `commit_evidence` 不变**（同一快照，改了要重新取证）。
  ④ 测试改对：`test_seed_provenance.py::test_seed_data_not_expanded` **改名**为
     `test_seed_data_counts_match_snapshot` 并断言 1821 / 2917 / 7431；`test_bank_seed.py` 的条数与
     "自答全对"回归扩到全量，**mismatch 必须为 0**；`test_quiz_api.py:417` 的 ceiling 测试
     **改用受控夹具**，不再依赖"真实库全为 7–9"。
  ⑤ 文档 10 处口径同步（逐条列行号）；向导文案改"全学段收录 + 可用学段作用域收窄"；
     README/STATUS 加"初中家庭建议设为 9"。
- DoD（成对断言已按 §19-L 纪律⑥逐条验过可满足性）：
  - **收录完整性**：`topics.json` 1821 且分桶 == 450 / 664 / 707；`dependencies.json` 2917；
    `questions.json` 7431 且 == 1800 / 2803 / 2828。**断言写死数字字面，不从被测文件反算**（纪律①）。
  - **转录目录不受扩段影响**（与上一条**可同时成立，已验**）：`topics_junior.tsv` 仍 `1 + 664 + 1` 行、
    且不含任何 grade ∉ 7–9 的行。**变异**：删掉导出脚本的过滤 → 必须红。
  - **初中面零变化**：扩段前后 `ceiling=9` 时 `seed_topics` / `quiz_topics` / `seed_summary` 读数逐字相同。
    ⚠️ **不得**写成"默认 16 时零变化"——扩段后那句**不可满足**（这正是纪律⑥要拦的写法）。
  - **回溯复活**：取真实数据里一条 初中→小学 先修边，断言 `prerequisites_of(初中点)` 返回该小学点、
    `edges_total == 2917`；并断言该小学点在 `ceiling=9` 下**仍可主动组卷**（有题）——上限式不是硬隔离。
  - **新增数据质量如实上报**：报新增 4628 题的 `verified / unverifiable / mismatch` 分布与丢弃数；
    **mismatch != 0 时本票不得合并**，停下上报后另定策略（装载器已有 `verify_mismatch` 丢弃路径，
    静默缩水比报错更坏）。
  - **实测启动耗时**：`load_bank(7431)` 与 `load_seed`（1821 点 + 2917 边 upsert 到临时库）各实测报数，
    **阈值 3 s**；超阈值不得靠"少导一点数据"绕过，须上报原因。
  - 全量 `pytest -q` 绿（当前基线 **824**，如实报新数）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 仍 18 OK / 0 DRIFT、`npm lint/test/build` 绿；**零迁移**、零新依赖。
- 禁止：重取上游快照或改 `upstream_commit`；引入语文（上游 `cnl_` 是 2026-10-24 新增、**不在本快照**）
  或化学（上游从未做过）；把 `topics_junior.tsv` 扩到全学段；为"按家庭生成目录"给向导加采集字段
  （撞 AGENTS §7 年级红线）；放宽 `test_bank_seed.py` 的自答回归或删 mismatch 丢弃逻辑来"让它过"；
  改模板 `version`；只改文档不改测试，或只改测试不改文档；把 ceiling 默认值改成 9（定案是 16）。

### P5-11 文档口径清理（纯文档；零代码、零测试改动；P5-10 的收尾票）
- **状态：已合并（2026-11-17，PR#64 squash（施工方 `8a7436d` + 审核方 nit `12894ea`）→ main `2bb4e0d`；原分支已删）**。
  验收：diff 四项逐条对卡、历史词条原文零改动、范围恰白名单 3 文件；旧串 grep 零残留
  （`docs/` 内唯一命中为 P5-11 投单块自身引用，存档同类不改）；数字与 source JSON `counts` 逐字一致；
  审核方实跑 pytest **833 passed**（694.69s，与施工方后台轮并发故偏慢）/ `ruff --no-cache` 全仓绿 /
  `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN / CI 三 job 绿（run `44071512052`）。
  过程记录两条：① 审核方按决策人指令顺手改耗时措辞 nit（双括号并单括号），与施工方提交**竞态**
  （其 `8a7436d` 已含旧措辞）——nit 以独立 commit 进同一 PR，**不 amend 他人提交**；
  ② 教训：旧串"零残留"DoD 应显式把**投单块自身**列入豁免清单，本次按常识判定、未改动它。
- **前置**：P5-10 已合并（main `6edd2b8`）。**基线：pytest 833 passed / main `86dd1c5`**。
- **背景**：P5-10 交付时 `seeds/README.md` 不在票面文档清单内（审核方第 17 次卡面缺陷，已在 P5-10 卡登记、
  裁定另票清理），该文件与两处小口径仍停留在扩段前。**本票纯文档，不许碰任何代码/测试/数据文件**。
- **范围（4 项）**：
  1. **`seeds/README.md`（主体）**：
     - 目录布局注释（:12-14）：`664 个初中知识点（315/257/92）` → **1821（450/664/707；数学 828/英语 724/物理 269）**；
       `1018 条先修边（两端点均在初中集内）` → **2917（跨学段边全量保留）**；
       `2803 道初中题（1407/1028/368）` → **7431（1800/2803/2828；3459/2896/1076）**。
     - 转换规则段（:48-51）："过滤初中（grade 7–9）"与"跨小学/高中的 74 条丢弃"改
       "**学段过滤 `--grades` 参数驱动（默认 junior，可复现可回退）；跨学段边全量保留**"；
       删"上游 grade 10–16 语义为'册'（高中），本次未导入"，改"全量收录 grade 1-16（grade 10-16 语义为'册'）"。
     - 题库统计段（:60）：`当前 2803 题：verified 1738、unverifiable 1065（no_verify 532、sandbox 498、
       选项带单位 35）` → **7431 题：verified 5996 / unverifiable 1435 / mismatch 0**；
       reasons 分布**指向** `questions_source.json` 的 `counts.load_quality`（不在 README 手抄明细，免得下次再漂）。
     - thin 说明（:64-65）：`物理 368 题按学科总量标 thin` → "全量收录后各学科均不低于 thin 阈值（学科级 500）"。
     - "仅初中数学做过二遍盲解"（:26）**保留不动**（仍然为真）。
  2. **`CHANGELOG.md` P5-9 词条尾部加一条缩进括注（原文一字不改）**：P5-10 落地后"默认 16 升级零行为变化"
     对**当前读者**失效——默认 16 = 全学段可见（选择器多出小学 450 + 高中 707 个点），
     初中家庭建议把学段作用域调到 9（详见 P5-10 词条）。
  3. **耗时措辞**：`CHANGELOG.md:30` 与 `docs/STATUS.md:270` 的 `≈1.33 s` → "约 **1.3–1.5 s（随机器而异）**"
     （审核方沙箱实测 1.52 s，同在 3 s 阈值内；避免"数字对不上"被当成破绽）。
  4. **`CHANGELOG.md` 记一条 Changed**："文档口径清理（P5-11）：seeds/README 全量口径 + P5-9 词条括注 +
     耗时措辞"；**不升版本号、不改任何历史词条原文**（P5-9 只许词条尾加括注）。
- **DoD**：
  - 旧串 grep 零残留（贴输出）：`664 个初中知识点`、`1018 条先修边`、`2803 道初中题`、`过滤初中（grade 7–9）`、
    `本次未导入`、`verified 1738`、`物理 368 题`——在 `seeds/README.md` 与 `docs/` 内不得再出现
    （`CHANGELOG.md` / `TICKETS.md` 的历史词条除外，那是存档不许动）。
  - 新口径数字与 `seeds/data/_source.json` / `questions_source.json` 的 `counts` **逐字一致**
    （1821/450/664/707、2917、7431/1800/2803/2828、5996/1435）。
  - 全量 `pytest -q` 仍 **833 passed**（本票不动任何测试文件）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN。
  - `git diff --name-only` **不含** `wengu-api/app`、`wengu-api/scripts`、`wengu-api/tests`、`seeds/data`、`migrations`。
- **白名单**：`seeds/README.md`、`CHANGELOG.md`、`docs/STATUS.md`。
- **禁止**：改 `seeds/data/*`、任何测试/代码、转录模板 `version`；改写 CHANGELOG 历史词条原文
  （只允许 P5-9 词条尾加括注）；把 `docs/STATUS.md` §67 等历史数字改掉（那是扩段前快照存档，已带注释）；
  在 README 手抄 verify reasons 明细（指向 source JSON 即可）。

### P5-12 上游更新检查脚本（纯开发者侧；零应用改动、零新依赖、零迁移；人工决定同步）
- **状态：已合并（2026-11-17，PR#65 squash → main `caf3b45`；原分支已删；合并时一次 502，只读对账确认服务端已生效）**。
  验收：全量 pytest **875 passed**（833 + 42 新）、`ruff --no-cache` 全仓绿、selfcheck 18 OK / 0 DRIFT / 0 WARN、
  CI run `44084515667` 三 job 绿（head `7dd3443`）；范围恰白名单 5 文件（2 新 + 3 改）。
  **双实跑独立复现**：常规模式 exit 1——上游已前进至 `8b57f2e`（2026-11-15），topics 1821→**3557** /
  deps 2917→**5132** / questions 7431→**14375**，7 个未知前缀点名（cnb_/cnc_/cnd_/cng_/cnh_/cnk_/cns_）；
  `--pinned d58785ce` 复检 **delta 全 0 / exit 0**，数字 == counts 逐字。
  自主变异（换靶点）：update 分支 `exit 1→0`（静默当已同步方向）→ **1 红**
  （`test_main_update_exit_1_even_when_delta_zero`），还原 sha256 一致。
- **发现留档（本票的"发现"成果，同步决策的输入）**：上游 HEAD 比钉死快照多 **+1736 点 / +2215 边 /
  +6944 题**，且出现 7 个新学科前缀（化学 `cnc_` ×3415 为最大头）；**实测无 `cnl_`**——卡面"语文 2026-10-24
  新增 `cnl_`"的例证与上游 HEAD 不符（疑已改名或重组），归"同步另票"核实时处理。是否引入、引入哪些学科
  属人工产品决策，本票只报告。
- **过程记录**：① `--pinned` 语义为**卡面歧义**——卡写"可覆盖读取值（自证用）"，但上游已动后唯一可满足
  DoD"delta 全 0"的读法是"下载 raw@SHA 对比仓内"的复检模式；施工方选复检并上报，解读正确，
  **审核方第 19 次卡面缺陷**；② P5-11 交付报告两条残留折入本票（`seeds/README.md:11`「初中包」→「全量包」、
  `docs/STATUS.md:265` 状态行翻「已合并」），化学/语文节加时间性标注（commit `7dd3443`）；
  ③ **定案①已执行：审核方已 Watch 上游仓库**（`gh api` subscription，`subscribed: true`）；
  ④ STATUS 存量"待评审"漂移面大（P4-4/P4-5/P4-6/头部快照日期/P5-5/"首个 Release 未做"已过实）
  → **另立 P5-13 对账票**，含流程固化"每票合并留痕必须翻转 STATUS 状态行"。
- **前置**：P5-10 钉死快照 `d58785ce`（P5-5 取证方法 §19-F-1）。上游 2026-10-24 起已新增语文（`cnl_`，
  **不在本快照**），未来必有更新；目前**没有任何机制**提醒"上游动了"。而同步 = 重导入 + 重新取证 +
  重新策展，成本高、涉及"语文是否引入"等产品决策——**必须人工触发**。所以本票只做"**发现**"，不做"同步"。
- **三条定案（决策人 2026-11-17 确认方向）**：
  ① 发现机制 = **仓内脚本手动跑**（不进 CI cron、不进 make 目标、不进应用）+ 维护者 **GitHub Watch
     上游仓库**（`xiaoyang111222/cn-math-taxonomy`）兜底推送——后者是审核方侧动作，本票合并后执行。
  ② **不做应用内外呼**：FastAPI 生命周期、`apscheduler`、前端一律不碰；只有这个脚本联网，且只读 GET、无 token。
  ③ **同步永远是另一票**：本票脚本对 `seeds/data/` **零写入**，只产报告。
- **任务**：
  1. 新建 `wengu-api/scripts/check_upstream.py`：
     - 从 `seeds/data/_source.json` 读 `upstream_commit`（**不硬编码**；缺文件/缺键 → 明确报错）；
     - `GET /repos/xiaoyang111222/cn-math-taxonomy/commits?path=data&per_page=1`（stdlib `urllib`，
       无鉴权）取最新触及 `data/` 的 commit sha + 日期；
     - sha 相同 → 报"已同步"，exit **0**；不同 → 按 raw.githubusercontent 下载该 sha 的
       `data/{topics,dependencies,questions}.json`，**只算不写**：topics 总数 / 分带（450/664/707 同尺）/
       分科、deps、questions、**未知前缀检测**（凡 `SUBJECT_BY_PREFIX` 之外的前缀——如 `cnl_`/`cnc_`——
       必须点名上报，不引入只报告）；
     - 输出人读报告（`--json` 可选），exit **1** = 有更新；
     - 网络失败 / 403 限流 → 明确报错 exit **2**，**不猜、绝不静默当"已同步"**。
  2. 测试（网络层薄壳不进单测，可测部分全测；基线 833 如实报新数）：
     - 纯函数：API 响应解析、delta 计算字面钉死（fixture 快照 vs 仓内真数据，`d58785ce` 下 delta
       必须全 0——纪律①）、未知前缀检测（`cnl_` fixture 必须被点名）；
     - pinned sha 从 `_source.json` 读取（tmp fixture）；
     - 零写入守卫：脚本无任何写路径参数，测试断言计算函数不接受输出路径。
  3. 文档：`seeds/README.md` 加「上游更新检查」段（何时跑、怎么读报告、有更新后走什么流程——指向
     §19-F-1 重取证，明确"同步是另一票"）；`docs/STATUS.md` 下一步口径；`CHANGELOG.md` Added 一条。
  4. **附加：P5-11 交付报告两条残留（审核方裁定并入本票，白名单已覆盖这两文件）**：
     - `seeds/README.md:11`：目录布局首行注释仍写"转换后的 cn-math-taxonomy **初中包**"，与 :12-14
       全量口径同块矛盾 → 改"全量包（小学+初中+高中）"（P5-11 卡漏列此行，**审核方第 18 次卡面缺陷**）；
     - `docs/STATUS.md:265`：P5-10 bullet 标题仍写"**已交付（待审核）**" → 改
       "已合并（2026-11-17，PR#63 → main `6edd2b8`）"（审核方合并流程漏项：合并留痕未翻转状态行）；
       该 bullet 内文不动。
- **DoD**：
  - 自证路径：`--pinned d58785ce…` 对仓内真数据跑 delta **全 0** 且报告数字字面 == source JSON
    `counts`（这同时是对"快照一致"的复检）；
  - 残留清理自证：`grep -rn "cn-math-taxonomy 初中包" seeds/README.md` 与
    `grep -n "P5-10 全量收录已交付（待审核）" docs/STATUS.md` 均**零命中**（贴输出）；
  - 未知前缀单测红得起（删检测 → 测试红）；
  - 全量 `pytest -q` / `ruff check --no-cache .` / `selfcheck --strict` 绿；
    `git diff --name-only` 不含 `wengu-api/app`、`migrations`、`requirements.txt`、`seeds/data`、`wengu-web`；
  - 网络代码与解析/计算代码分层，网络层无业务逻辑；脚本**无状态**：不落盘缓存，留痕 = 贴报告。
- **白名单**：`wengu-api/scripts/check_upstream.py`（新）、`wengu-api/tests/unit/test_check_upstream.py`（新）、
  `seeds/README.md`、`docs/STATUS.md`、`CHANGELOG.md`。
- **禁止**：改 `seeds/data/*`、`app/`、`migrations`、依赖清单、前端；接入 `apscheduler` / 生命周期 /
  CI cron / make 目标（跑法就是 `python wengu-api/scripts/check_upstream.py`，写进 README）；
  自动创建 issue / PR / 自动重导入；把 token 或 secret 写进仓库；本票做"同步"或动 `upstream_commit`。
- **审核方侧（票外）**：合并后执行 Watch 上游仓库（`gh api` subscription）。**已执行**（2026-11-17，
  `subscribed: true`）。

### P5-13 STATUS 状态行对账 + 留痕流程固化（纯文档；零代码、零测试改动）
- **状态：已合并（2026-11-18，PR#66 squash → main `9f78d98`；原分支已删）**。
  验收：19 处状态词逐处最小翻转、锚点实查全对（#39→`170b5da`、#33→`285fba7`、#51/#52/#53/#50/#61/#65）、
  bullet 正文与历史数字一字未动、homepage/Discussions 照实保留；审核方自跑 **875 passed**、
  `ruff --no-cache` 全仓绿、selfcheck 18 OK / 0 DRIFT / 0 WARN、双 grep 零命中；
  CI run `44221089249` 三 job 绿（api 3m6s 为 Linux 全量）。范围恰白名单 3 文件，两提交
  `e2c17f2`（主票）+ `8e58e97`（折入）。
  **折入**：Phase5 行「首次运行向导…未做」同类过实 → P5-1b 已合并（#33→`285fba7`），其余四项保留
  （施工方按"禁止顺手扩面"上报、审核方裁定折入，处理正确）。
  **登记第 20 次卡面缺陷**：卡写"17 处"、盘上实为 **19 处 / 18 行**——教训：**卡面不写会漂的计数，
  只写判定规则**（本卡"以 grep 实况为准"的规则救了自己）。
  **本票合并留痕即 §8「合并留痕双写」首次实践**（TICKETS + STATUS 同步翻转，见 STATUS :285 新 bullet 与 :4 基线）。
- **背景**：P5-10 / P5-12 两次交付报告都撞见同一类残留——票早已合并，`docs/STATUS.md` 状态行还写
  "待评审/待审核"（盘上实测 17 处），另有两处事实过实（头部快照停在 2026-11-13；"首个 Release 未做"
  而 v0.7.0 已于 2026-11-17 发布）。根因在**审核方自己的留痕流程**：合并留痕只写 TICKETS、从不翻
  STATUS。本票一次对账清零 + 把规则固化进 AGENTS §8，防再犯。
- **对账清单（行号以开工时盘上 `grep -n "待评审\|待审核" docs/STATUS.md` 实况为准，逐条翻转）**：
  - 头部 :3-4：快照日期/基线 → 更新为开工时 `origin/main` 实况（`git log --oneline -1` 实查）；
  - :205 / :224 / :234：P4-4 / P4-5 / P4-6「已交付（待评审）」→ 已合并（PR#51 / #52 / #53）；
  - :275 / :290：P5-12「已交付（待审核）」→ 已合并（PR#65 → main `caf3b45`）；
  - :289 / :303 / :1133 / :1198：P5-5「已交付待评审」→ 已合并（PR#61 → `0928104`）；
  - :302 / :1183 / :1186-1188 / :1194 / :1201：P4-1 / P4-4 / P4-5 / P4-6 / P5-1b / P5-8 行内
    「待评审」→ 已合并（P5-1b 的 PR 号**实查后填**；P5-8 = PR#50 → `30785d0`）；
  - :303 / :1198："首个 Release / 发布打包**未做**" → 已做：v0.7.0 已发布（tag→`9bbcb6b`，
    2026-11-17，`gh release view v0.7.0` 实查）、description/topics 已设；**homepage 留空、
    Discussions 未做照实保留，不得写成已做**。
- **规则（写死）**：只翻状态词 + 补"PR 号 → squash SHA"锚点；**bullet 正文一字不动、历史数字不动**；
  每处锚点必须实查（`git log --oneline` / `gh pr view --json number,mergeCommit`），
  查得到才翻、查不到保留原样并上报，**不许凭记忆填 SHA**。
- **流程固化（本票第二件事）**：AGENTS.md §8 加一条——**每票合并后的留痕提交必须同步翻转
  `docs/STATUS.md` 对应 bullet/表格行的状态词并附 PR→SHA 锚点；只写 TICKETS 不翻 STATUS 视为留痕不完整**。
- **DoD**：
  - `grep -n "待评审\|待审核" docs/STATUS.md` **清零**（贴前后对照，逐条列全 17 处的去向）；
  - 每处翻转附实查锚点输出片段；
  - 全量 `pytest -q` **875 passed**（不动任何测试）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN；
  - `git diff --name-only` 不含代码/测试/`seeds/data`。
- **白名单**：`docs/STATUS.md`、`AGENTS.md`、`CHANGELOG.md`。
- **禁止**：改 bullet 正文与历史数字；动代码/测试；凭记忆填 SHA（查不到就保留原样上报）；
  顺手改 TICKETS / 设计文档；把 homepage / Discussions 写成已做；升版本。

### P5-14 英文 README（纯文档 + 守卫；清掉 AGENTS §7 最后一项"中英 README"缺口）
- **状态：已合并（2026-11-18，PR#67 squash → main `847bc03`；原分支已删）**。
  验收：定位句两侧**逐字一致**（462 字符，审核方逐字符比对 True）、11 个字面串逐个命中、
  `AI learning workbench` 两侧均无；守卫 7 条（含 `test_no_merged_item_drift`：两侧 × 三个旧口径字面）；
  三轮提交 `2e1da9a`（主票）/ `1b16067`（一次折入中文侧）/ `b1b8117`（二次折入英文侧镜像 + 漂移守卫）
  均普通追加、不 amend。审核方实跑：881 passed（主票树全量）+ 26 passed（守卫 7 + 中文侧 19）、
  `ruff --no-cache` 全仓绿、`selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN、前端 `npm test` 57/0；
  **自主变异第三个靶点**（把 `剩英文 README` 塞回**中文侧** → 漂移守卫 1 红，施工方只演示过英文侧），
  还原 sha256 一致。CI run `44259395949` 三 job 绿（api 2m41s = Linux 全量 **882**）。
  AGENTS §7「LICENSE + 中英 README + 隐私声明 + CHANGELOG + .env.example」至此**全部达成**，P5-5 遗留清零。
- **§8 双写第二次实践**：本条留痕同时翻转 `docs/STATUS.md` 四处（`:297 / :312 / :1142 / :1207`）
  「英文 README 已交付（待评审）」→「已合并（PR#67 → `847bc03`）」，其余内容一字不动。
- **登记**：**第 21 次卡面缺陷**（行号漂移：卡写定位句在 `README.md:5`，实为 `:6`）、
  **第 5 次白名单/范围写窄**（第一次折入只授权 `README.md` + `CHANGELOG.md`，漏英文侧镜像——
  施工方按"白名单未列不动"上报，处理正确）。两次卡面补强已落 main `c4875a2` / `6d59c6e`。
- **前置**：v0.7.0 已发布（tag→`9bbcb6b`）；P5-13 已把 STATUS 状态行对账清零。本票是 P5-5 遗留的
  最后一块"仍缺"（盘上四处：`docs/STATUS.md:297 / :312 / :1142 / :1207` + `目录结构.md:8` 注释）。
- **形态定案（决策人 2026-11-18 点头 = 方案 A）**：仓库根 **`README-en.md`** + 中文主页顶部一行互链。
  否掉 B（`docs/en/` 目录树 = 为"整站本地化"这一**无消费方的假想需求**铺路）与 C（单文件双语混排
  会把中文主页撑长近一倍，并破坏"前 12 行定位"守卫窗口）。
- **任务**：
  1. 新建 `README-en.md`：10 个 section 全译（核心闭环 / 明确不做 / 技术栈 / 快速开始 / 本地开发 /
     当前进度 / 文档地图 / 安全与合规 / 贡献 / License）。硬约束：
     - **首段定位句与 `README.md:5` 的英文句逐字一致**（两处不许分叉）；
     - 数字与命令与中文侧同源同值：seed **1821 / 2917 / 7431**、`docker compose` 命令、
       端口 `5173 / 8000`、投递目录 `./data/inbox`；
     - 许可分层必须含 `MIT` + `CC BY-NC 4.0` + **non-commercial**，并明说
       **not OSI-approved open source**（不许简化成 "open source"）；
     - "当前进度 / 文档地图"里指向中文文档的链接**保留中文标题 + 英文括注**
       （那些文档本身没有英文版，不假装翻译）；
     - 顶部一行回指 `README.md`，并写明"中文为准（Chinese version is authoritative）"。
  2. `README.md` **只加一行互链**（顶部；中文正文一字不动）。
  3. 新建守卫 `wengu-api/tests/unit/test_readme_english.py`（断言右侧一律**字面串**，§19-L 纪律①）：
     - `README-en.md` 前 12 行含 `local-first`、`no grading of real homework`、
       `no generated explanations`、`zero-model`；
     - 负断言：不得出现 `AI learning workbench`（与中文侧 `test_readme_positioning_in_first_lines` 同口径）；
     - 互链双向：`README.md` 含 `README-en.md`、`README-en.md` 含 `README.md`；
     - 定位句一致性：两个文件都含**测试里写死的那句**英文定位句（不从被测文件反算期望值）；
     - 数字字面：`README-en.md` 含 `1821` / `2917` / `7431`；许可分层含 `MIT` / `CC BY-NC 4.0` /
       `non-commercial` / `not OSI`；
     - 变异自证：删任一互链 → 红；把 `zero-model` 写成 `AI-powered` → 红。
  4. STATUS 四处 + `目录结构.md:8` 同步：`docs/STATUS.md` 的"英文 README 仍缺/另票"改为
     "**英文 README 已交付（待评审）**"；**本票不许写死 PR 号**（合并后由审核方按 §8 留痕双写
     翻成"已合并 PR#xx → SHA"）；`目录结构.md:8` 注释改为列出 `README-en.md`。
  5. `CHANGELOG.md` Added 一条。
- **DoD**：
  - 全量 `pytest -q` 绿（基线 **875**，如实报新数）；新守卫 6 组断言 + 两处变异 RED→GREEN 贴输出；
  - `ruff check --no-cache .` 全仓绿；`selfcheck --strict` 仍 18 OK / 0 DRIFT / 0 WARN；
  - 前端 `npm run lint / test / build` 仍绿（本票零前端改动，跑一遍自证）；
  - `grep -n "英文 README" docs/STATUS.md` 四处均为"已交付（待评审）"口径、无"仍缺/另票"残留（贴输出）；
  - `git diff --name-only` 恰白名单 6 文件；`README.md` 的 diff **只允许一行新增**（中文正文零改动）。
- **白名单**：`README-en.md`（新）、`README.md`（仅互链一行）、`wengu-api/tests/unit/test_readme_english.py`（新）、
  `docs/STATUS.md`、`目录结构.md`、`CHANGELOG.md`。
- **禁止**：翻译 `PRIVACY.md` / `LICENSE-data.md` / `THIRD-PARTY-NOTICES.md` / `AGENTS.md` / `TICKETS.md` /
  `docs/**`；引入 i18n 框架、`docs/en/` 目录树或任何构建期本地化机制；改 `README.md` 中文正文；
  写死未来 PR 号；把"不称 OSI 开源软件"译成 `open source`；动代码/前端/`seeds/data`；
  为"顺手"多翻别的文档。
- **卡面补强（2026-11-18，交付报告复核后审核方裁定折入；原文保留、下列两条被推翻）**：
  - ~~任务 2「`README.md` 只加一行互链（顶部；中文正文一字不动）」~~ → 改为
    **`README.md` 允许三处改动**：① 顶部互链一行（已交付，保持现状紧贴标题、不加空行）；
    ② 「当前进度」✅ 列表末尾新增一行 **P5-14 英文 README**；③ 改写 :122「⏳ 下一步」一行——
    该行现有**三处过实**：`P4-1c 命令行备份入口（需先定四问）` 早已合并（PR#41 → `8bbef94`）、
    `P5-5 剩英文 README（另票）` 本票已交付、`首个 Release 属审核方侧动作` 已发布 v0.7.0
    （剩 homepage / Discussions）。改写为：
    `- ⏳ 下一步：P0-1 样本扩容 + P1-7b 前置回溯诊断仍待做；发布打包剩 homepage / Discussions（审核方侧 GitHub 动作）；英文 README 已交付（见上条 P5-14）。`
    理由：施工方按原卡"中文正文禁改"上报了分叉（复核点 2），而中文主页那行"下一步"与本票交付直接矛盾——
    留着就是文档过实，正是 P5-13 对账票要消灭的毛病；折入本票最省（文件已在白名单、分支未 push）。
  - ~~DoD「`README.md` 的 diff 只允许一行新增（中文正文零改动）」~~ → 改为
    **`git diff README.md` 只允许 +2 行 / −1 行**（互链、P5-14 进度条目、:122 改写），
    其余中文正文一字不动；`grep -n "P4-1c 命令行备份入口\|剩英文 README" README.md` **零命中**。
  - **登记第 21 次卡面缺陷（行号漂移类）**：卡写定位句在 `README.md:5`，盘上实为 `:6`（`:5` 是空行）。
    教训同 §19-L：行号只认实读到的那一行、每合并一票重跑引用校对。
- **卡面补强二（2026-11-18，折入交付报告复核点 2 后审核方裁定；**白名单/范围第 5 次写窄**）**：
  折入时我只把 `README.md` + `CHANGELOG.md` 放进补充任务，**漏了英文侧镜像**——`README-en.md` 的
  「⏳ Next」行（:118）同样带着已被推翻的三处过实（`P4-1c CLI backup entry (four questions…)`、
  发布打包旧口径），且进度列表缺 P5-14 条目。施工方按"白名单未列不动"上报，处理正确。
  追加授权（同属本票，分支未 push）：
  - `README-en.md` 允许两处改动：① 进度 ✅ 列表末尾（P5-10 条目之后）新增一行 **P5-14**（英文，
    内容与中文侧同口径：本文件即英文 README、定位句与中文侧逐字一致由守卫钉死、
    `1821 / 2917 / 7431` 与 `5173 / 8000` / `./data/inbox` 同源、MIT + CC BY-NC 4.0 + non-commercial +
    not OSI-approved、Chinese version remains authoritative）；② 改写 :118「⏳ Next」行为新中文行的镜像：
    `- ⏳ Next: P0-1 sample expansion + P1-7b prerequisite backtracking diagnosis still pending; release packaging remaining: homepage / Discussions (maintainer-side GitHub actions); the English README is delivered (see P5-14 above).`
  - **新增 1 条守卫**（防同类漂移复发，两侧同一把尺）：断言 `README.md` 与 `README-en.md` 均**不含**
    已合并项的"待做"字面——`P4-1c 命令行备份入口`、`P4-1c CLI backup entry`、`剩英文 README`；
    变异自证：把旧句塞回任一侧 → 该测试必须红。
  - `CHANGELOG.md` 的 P5-14 条目把折入范围表述补全为「中文侧 + 英文侧镜像 + 漂移守卫」。
  - DoD 追加：`grep -n "P4-1c CLI backup entry\|剩英文 README" README.md README-en.md` 零命中；
    `git diff README-en.md` 相对 `1b16067` 只允许 +2 / −1。

### P5-15 本地自建命名空间解耦（§19-G-3 定案一；判据改按 `source='local'`；先于同步票）
- **状态：已合并（2026-11-18，PR#68 squash → main `4f7e101`；原分支已删）**。
  验收：全量 pytest **887 passed**（882 + 5 新守卫）、`ruff --no-cache` 全仓绿、`selfcheck --strict` 18 OK、
  前端 `tsc` 0 / 57 pass / build ✓；`docs/templates/topics_junior.tsv` **零 diff、仍 665 行**；
  范围恰 11 文件，`migrations/`、`seeds/data/`、依赖清单零改动。
  main 上判据实测确认：`export_topics_junior.py:58` 为 `topic.get("source") == "local"`、
  两模块各自 `LOCAL_PREFIX = "loc_"`、`LOCAL_SUBJECT_PREFIXES` 在三个源文件中出现次数为 0。
  **审核方自主变异（两个新靶点，都在打标侧；施工方三个都在判据/常量/异常侧）**：
  ① 删 `export` 的 `item["source"] = "local"` → `test_upstream_chinese_filtered_by_grade_not_prefix` 红；
  ② 删 `loader.validate_local_topic` 的 `topic["source"] = LOCAL_SOURCE` → **4 红**
  （装载合并/重启存活、CRUD、id 计数器、删除解绑）——DB 侧标记同样被守住；还原 sha256 一致。
  施工方三条变异（判据退回按前缀 / `LOCAL_PREFIX="cnl_"` / 删 `except LegacyLocalIdError: raise`）各自红、还原绿。
  CI run `44294872213` 三 job 绿（api 3m40s = Linux 全量 887）。分支两提交：`4cd41de`（主票）+
  `55ca6ab`（折入 README 双语 P3-8 括注）。
- **裁定采纳的三点施工方判断**：① 常量形态 dict → `LOCAL_PREFIX` + `LOCAL_SUBJECTS` tuple（单前缀下
  per-subject dict 冗余；export 保持纯标准库不 import app，重复由字面守卫 + 相等探针双保险）；
  ② 化学夹具用 `loc_101` 而非 naive 的 `loc_001`（单前缀下两科共用序号空间，会撞语文 `loc_001..003`）；
  ③ **legacy 两侧语义差异**——runtime 硬拒绝整次装载 + P4-4 降级，export 工具 warn+skip 带改名指引
  （沿用 dev 工具"坏文件跳过并告警"契约），两侧都有测试钉死。没有为了"看起来统一"把 export 改成硬失败，
  这个取舍是对的。
- **登记第 22 次卡面缺陷（引用清单漏项）**：卡面写"STATUS 现状口径三处"，盘上实为四处（漏 P1-1b 表格行）；
  施工方按"以实际代码为准"一并更新并上报。教训同 §19-L：清单类引用必须由 grep 实况生成，不手写条数。
- **前置**：设计文档 §19-G-3 三条定案已落盘（main `06628a2`）。本票是"全量同步扩科"的**前置闸门**，
  顺序不可反（同 AGENTS §7「先写消费逻辑（过滤 + 测试），再加采集字段」）。
- **为什么要改**：上游 `cnc_` = **语文**（其 README 明写 `subject=chinese`、编号 `cnc_j`/`cnc_p`），
  上游**没有 `cnl_`**；而我们现有约定 `LOCAL_SUBJECT_PREFIXES = {"语文": "cnl_", "化学": "cnc_"}`。
  同步扩科后两处危害：① 家长本地点与上游语文点撞进同一 ID 空间；
  ② `export_topics_junior._in_junior_catalog` **按前缀**判"本地恒保留" →
  上游语文点会被当本地点**绕过 grade 过滤**，转录目录静默膨胀——**P5-10"借来的过滤"坑的第二次复发形态**。
- **定案（决策人 2026-11-18 选 A）**：本地自建统一 **`loc_` 单前缀**（`loc_001`、`loc_002`…），
  学科由 `subject` 字段承载。理由：上游 10 个前缀全在 `cn?_` 家族内，`loc_` 永不与之冲突；
  加新学科零改动；判据天然与前缀识别解绑。代价明记：id 上看不出学科（UI 与导出都有 subject 列）。
- **现状读盘（行号为本会话实读）**：
  - `app/seed/loader.py`：`:37 LOCAL_SOURCE = "local"`、`:38 LOCAL_SUBJECT_PREFIXES`、
    `:160-176 validate_local_topic()`（学科白名单 + `id.startswith(prefix)` + 强制
    `source/unaudited/blind_verified`）、`:200-210 next_local_id(prefix, taken_ids, issued)`；
  - `app/services/local_seed.py`：`:4` docstring「只有语文（cnl_）/ 化学（cnc_）允许本地录点」、
    `:170-176 _require_subject()`、`:296 prefix = LOCAL_SUBJECT_PREFIXES[subject]`；
  - `scripts/export_topics_junior.py`：`:9` docstring、`:37` 同名常量、
    `:44-50 _in_junior_catalog()`（按前缀恒保留）、`load_local_topics()`（约 :110-125，按前缀校验本地条目）；
  - `wengu-web/src/pages/LocalSeedPage.tsx:420`：文案「这里只管理语文（cnl_）与化学（cnc_）」；
  - 判据基础：`KnowledgeSeed.source` 为 `Text nullable`（`app/models/knowledge.py:31`），
    上游行 NULL、本地行已由 `validate_local_topic` 写 `'local'`；
    **`seeds/data/topics.json` 不含 `source` 键** → 导出脚本侧必须由 `load_local_topics`
    给本地条目**同样打 `source='local'`**，判据改读该标记。
- **任务**：
  1. 命名空间：本地前缀常量统一改为 `loc_`（保留 `LOCAL_SUBJECT_PREFIXES` 结构还是换成单一
     `LOCAL_PREFIX = "loc_"` 由施工方按最小改动决定并在交付里说明）；`validate_local_topic` 的
     id 校验改判 `loc_`；`next_local_id("loc_", …)`；`local_seed.py` 与 `export_topics_junior.py` 同步。
     **学科白名单的键（语文/化学）不动**（扩白名单是另一件事，见【禁止】）。
  2. 判据：`_in_junior_catalog` 从"按前缀"改为 **按 `source == 'local'`**；
     `load_local_topics` 为本地条目补 `source='local'`（与 loader 同一约定）。
  3. **legacy 本地文件（`cnl_`/`cnc_` 开头）→ 装载时明确拒绝并降级**，复用 P4-4 的
     `seed_loaded=false` + 安全错误类别机制，错误文案给出改名指引（"本地知识点 id 需以 `loc_` 开头，
     请将 `cnl_001` 改为 `loc_001`"）。**不写迁移脚本**——审核方实测两个运行时目录均无 `seeds_local/`、
     生产库 `concepts` 各只有 1 条 `source='student'`、零 `cnl_`/`cnc_` 本地点；
     真出现有本地点的家庭再开迁移票。
  4. 前端文案 `LocalSeedPage.tsx:420` 改为不点名 `cnl_`/`cnc_`（改述"本地自建点统一 `loc_` 前缀"）。
  5. 测试：`test_local_seed.py`（大量 `cnl_`/`cnc_` 字面，含 `next_local_id("cnl_", …)`、
     TSV 行 `cnl_001\t语文`、重复 id 冲突警告）与 `test_seed_status.py:251-271`（夹具 `cnl_z`）
     字面全部改 `loc_`；新增 DoD 要求的两条守卫 + legacy 拒绝守卫。
  6. 文档：`seeds/README.md`（local 一节 + 前缀说明）、`目录结构.md`、
     `docs/STATUS.md:43 / :594 / :977` 现状口径、`CHANGELOG.md`。
- **DoD（成对断言先验可满足性，§19-L 纪律⑥）**：
  - **核心可证伪夹具**：造一个**上游语文点 `cnc_j001`（`source` 非 local、grade=10）**，
    断言它在 `ceiling=9` 下**被过滤掉**、且**不出现在转录目录**；
    变异：把 `_in_junior_catalog` 判据改回"按前缀" → 该测试必须红。
  - **回流守卫**：断言本地前缀常量**不含任何 `^cn[a-z]_` 形态**值（防手滑改回 `cnl_`）。
  - **转录目录零副作用**：`docs/templates/topics_junior.tsv` 仍 665 行、**零 diff**
    （本票不碰上游数据、本地无点 → 输出必然不变；这是判据改造无副作用的自证）。
  - **legacy 拒绝路径有测试**：给一个含 `cnl_001` 的本地文件 → 装载报错 + `seed_loaded=false`，
    错误文案含改名指引；**不得静默装载**。
  - 全量 `pytest -q` 绿（基线 **882**，如实报新数）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN、前端 `npm run lint / test / build` 绿；
  - **零迁移、零新依赖**，`git diff --name-only` 不含 `migrations/`、`seeds/data/`；
  - 三个源文件 + 前端文案 + 文档四处**不得**再把 `cnl_`/`cnc_` 当本地约定；
    `wengu-api/tests/unit/test_check_upstream.py` 里的 `cnl_`/`cnc_` 是"上游未知前缀样例"，
    **本票豁免不动**（同步票必须重审它，已写进同步票范围防丢项）。
- **白名单**：`wengu-api/app/seed/loader.py`、`wengu-api/app/services/local_seed.py`、
  `wengu-api/scripts/export_topics_junior.py`、`wengu-web/src/pages/LocalSeedPage.tsx`、
  `wengu-api/tests/integration/test_local_seed.py`、`wengu-api/tests/integration/test_seed_status.py`、
  新建守卫测试文件、`seeds/README.md`、`目录结构.md`、`docs/STATUS.md`、`CHANGELOG.md`。
- **禁止**：扩本地学科白名单（语文/化学之外）；动 `seeds/data/*` 或做任何数据同步（下一票）；
  写 id 迁移脚本；改 `check_upstream.py` 的前缀样例；把 TSV 行数/内容改掉；
  引入新依赖或迁移；用 `--skip`/`xfail` 让测试"过"。
- **卡面补强（2026-11-18，交付报告复核后审核方裁定折入；白名单/范围第 6 次写窄）**：
  施工方复核点 6 上报"README 两处 P3-8 历史条目仍旧前缀 + '空 seed 起步'措辞"，按原卡"白名单未列不动"
  未扩面，处理正确。裁定折入（AGENTS §3 同一句话已在 main `06628a2` 加删除线推翻，README 是家长第一眼
  读的入口，留着就是文档过实——正是 P5-13/P5-14 刚治过的病）：
  - 白名单追加 `README.md`、`README-en.md`；
  - **只在两条历史条目尾部各加一句括注，正文一字不改**：
    `README.md:112` 与 `README-en.md:108` 的 P3-8 条目末尾加
    `（2026-11-18 P5-15 括注：本条是当时的事实记录；上游此后已含语文/化学，本地命名空间统一 `loc_`，
    见设计文档 §19-G-3 与 AGENTS §3 的推翻标注）`（英文条目用对应英文措辞）；
  - 不得改动这两条目的其余内容，不得顺手更新其它进度条目；
  - DoD 追加：`grep -n "空 seed 起步" README.md README-en.md` 命中处必须紧邻括注（贴前后文）。
  - **登记第 22 次卡面缺陷（引用清单漏项）**：卡面"现状口径三处"实为四处（漏 `docs/STATUS.md` 的
    P1-1b 表格行）；施工方按"以实际代码为准"一并更新并上报，处置正确。教训同 §19-L：
    清单类引用必须用 grep 实况生成，不手写条数。

### P5-16 全量同步扩科（10 学科，新快照 `8b57f2e`；含重新取证 + SVG 净化前移/装载验哈希；改变数据面）
- **状态：已合并（2026-11-20，PR#69 squash → main `7ca7014`；原分支已删）**。
  验收：起点 **29 failed / 870 passed** → 归零，main 上审核方实跑 **901 passed**（461.64s）；
  `load_bank(14375)` 实测 **1873 / 1960 ms**（两轮，均 ≤ 3000 闸门）；`mismatch = 0`、`figures 640`、
  verified 12828 / unverifiable 1547；TSV **1268 行 / CRLF 1268 / 裸 LF 0 / 无 BOM**，9 学科初中分布吻合；
  ruff 全仓绿、selfcheck 18 OK、前端 57/57 + tsc + build ✓；CI 两轮三绿（run `44556121325`、`44621201299`）。
  **四段 blob 审核方用 GitHub tree API 独立复核全部一致**（含改走 trees 的 `dependencies.json`）；
  `commit_evidence` 如实区分 contents/trees 两条路径、记录上游两次前进（`aa2c2205` → `df0879d0`）
  与"按卡停下上报、决策人裁定继续钉 `8b57f2e`"，并记录**上游自身 `package.json` 声明 ISC 而 README
  声明 CC BY-NC 4.0 的不一致**（`code_spdx` 随之改为 ISC，wengu 只取数据）。
  自主变异：施工方三靶点（判据退回按前缀 / `LOCAL_PREFIX="cnl_"` / 删 `except LegacyLocalIdError`）+
  **审核方四靶点**（篡改 `figures_sha256.json` 一条哈希 → 丢 1 题并计数；`check_upstream` 删 `cnc_` → 8 红；
  TSV `newline` 改回平台默认 → 字节守卫红；注释掉边的全量重建 → 幽灵点测试红），全部还原 sha256 一致。
  commit 拆分诚实性经 detach 实测（`962f8fa` 单跑 8 个受影响文件 = 107 passed）。
- **CRLF 事故认领（审核方责任，非施工方）**：折入轮 Qoder CN 撞到 4121+/3897− 幻影 diff，根因是
  **审核方沙箱内 git 读不到用户级 `core.autocrlf=false`（只剩系统级 `true`），为验 commit 独立全绿
  做 `git switch --detach` 往返，把两个 commit 之间有差异的 5 个文档按 CRLF 写回工作区**。
  施工方正确怀疑"外部转换来源"并自行修复（CRLF→LF 还原 + 对未推送的 `21cb913` 做 amend → `57f863c`）；
  审核方复核 8 个文件盘上字节 == HEAD blob、CR 字节为 0。
  **整改已生效**：审核方所有 git 命令一律显式带 `-c core.autocrlf=false`；**根治方案 = P5-17**
  （普查发现 HEAD blob 含 CRLF 的文本文件有 9 个而非 1 个，根因是 import 脚本 `_write_json` 用
  `Path.write_text()`，Windows 生成即 CRLF）。
  **amend 处置认可**：`21cb913` 从未推送，amend 不违反"不改写已推送历史"；事故经过保留在本留痕与
  PR body，不因 amend 而消失。
- **登记第 23 次卡面缺陷（措辞过实）**：卡面写"两个 commit 各自可回滚"，而本仓一律 **squash 合并**，
  回滚粒度是整票——多 commit 只利审查可读性。措辞已在 P5-16 / P5-17 卡校准。
- **前置**：P5-15 判据解耦已合并（main `4f7e101`）——本票是 §19-G-3 定案一的**后半**：消费逻辑已就位，
  现在才允许加数据。
- **三条已定案（不要重开）**：① **全要 10 科**、可以重新取证；② 转录目录那把尺**不变**（仍按
  `grade ∈ 7–9`），行数随数据自然增长（干跑实测 1268 行）；③ 性能走**路线 B**（净化移到构建期 +
  装载验哈希），**3 s 阈值不动**。
- **审核方干跑实测（施工方须自跑复核，不一致上报不要硬凑）**：

  | 项 | 新快照 `8b57f2e` | 现仓库 |
  |---|---|---|
  | 知识点 | **3557**（primary 1481 / junior 1267 / senior 809） | 1821 |
  | 先修边 | **5132**，`dropped_cross_boundary = 0`，悬空端点 0 | 2917 |
  | 题 | **14375**（5924 / 5215 / 3236），`out_of_scope = 0`、`topics_without_questions = 0` | 7431 |
  | `mismatch` 丢弃 | **0**（`dropped={}`） | 0 |
  | verified / unverifiable | 12828 / 1547 | 5996 / 1435 |
  | 配图 | 640 段 / 1.67 MB | 267 |
  | `load_bank` | **4404 ms**（verify 877 / svg 净化 1937 / json 168） | 1829 ms |
  | `load_seed` | 冷 956.7 ms / 热 620.3 ms | 361 / 275 |
  | 转录目录 | 1268 行（CRLF 逐行、无 BOM） | 665 行 |
  | `questions.json` 体积 | 11.54 MB（净化后预计下降） | 6.12 MB |

  干跑第一步就抛 `SeedConvertError: 未知学科前缀: cnb_j001`——证实前缀表必须扩，不是推测。
- **任务**：
  1. **取快照方式改为 `git clone`（带 `.git`）**：`upstream_commit()` 走真实探测，不再靠 zip 内容寻址反查；
     仍用 blob 逐一比对做**交叉验证**（`data/topics.json` / `dependencies.json` / `questions.json` /
     `README.md` 四段 blob 与 GitHub contents API 对齐）。`_source.json` / `questions_source.json` 的
     策展键**整体按新快照重写**（`upstream_commit` / `upstream_commit_date` / `upstream_author` /
     `upstream_spdx` / `code_spdx` / `filter` / `grade_semantics_note` / `modified` / `disclaimer` /
     `counts` / `commit_evidence`）；`commit_evidence` 要**如实说明取证方法变了**，不得沿用 `d58785ce`
     的证据串，也不得把旧快照证据掺进当前值。
     - **必须 `git checkout` 到 `8b57f2e353ac041f81ba705a66503c9a9e2d8ba8`（detached），不是"最新 main"**；
       clone 前 `git rev-parse` 确认，装载后 `upstream_commit` 必须逐字等于该 sha。
       **若上游已再次前进（HEAD ≠ `8b57f2e`），停下上报，不得擅自同步到更新的快照**——本卡全部实测数字
       都是针对 `8b57f2e` 的，换了快照就得重新干跑一遍归因与闸门。
     - **旧 zip 解包目录 `../cn-math-taxonomy-main` 保持原样不动**（它是 `d58785ce` 的取证现场）；
       新 clone 另起目录（如 `../cn-math-taxonomy`），交付里写清实际路径。
  2. **`SUBJECT_BY_PREFIX` 扩到 10 科**（三处：`import_seed.py`、`import_questions.py`、`check_upstream.py`），
     映射由上游 `subject` 字段实测得出：`cnm_`数学 / `cne_`英语 / `cnp_`物理 / `cnc_`**语文** / `cnk_`化学 /
     `cnb_`生物 / `cns_`科学 / `cnd_`道德与法治 / `cnh_`历史 / `cng_`地理。`GRADE_BANDS` 不变；
     `blind_verified` **仍只给初中数学**（新快照初中数学 315 点，与现值相同，但必须复算不得照抄）。
     **连带**：`check_upstream.py` 里把 `cnl_`/`cnc_` 当"未知前缀样例"的实现与测试必须重审——同步后
     `cnc_` 已是已知学科，样例换成上游真不存在的形态（如 `zzz_`）；`test_constants_match_import_scripts`
     的三模块一致性守卫随之覆盖 10 项。
  3. **SVG 净化前移到构建期**：`import_questions.py` 写 `questions.json` 前对 `figure` 与
     `choices[].figure`（现 :176 / :199 原样透传两处）调 `sanitize_svg`，并生成**逐段 sha256 清单**
     落新文件 `seeds/data/figures_sha256.json`（键 = `question_id` + 槽位 `main` / `choice:<key>`；
     不放 `questions_source.json`——那是署名文件，不是完整性工件）。
     `app/seed/bank.py` 装载侧：`:206` / `:244` 的 `sanitize_svg(...)` 改为**哈希校验**——命中且一致 →
     直接用净化后文本；**不一致或缺哈希 → 丢弃该题并计入 `stats.dropped["figure_hash_mismatch"]`**，
     绝不静默放行。
     **家长题路径一行不动**：`services/bank.py:265/299`、`bank_import.py:209/407` 继续装载/入库期净化
     （用户输入没有构建期哈希可验）。`svg.py` 只更新 docstring 的净化时机说明，`sanitize_svg` 本体不变。
  4. **产出数据与转录目录**：重生成 `seeds/data/*` 三件 + `figures_sha256.json`；
     `docs/templates/topics_junior.tsv` 重生成（预计 1268 行），**CRLF 写死与无 BOM 的既有纪律不得回退**
     （§19-L 纪律⑦）。
  5. **测试改对而非放宽**：`test_seed_full_coverage.py`（分桶 450/664/707 → 1481/1267/809、
     题 1800/2803/2828 → 5924/5215/3236、TSV 665/664 → 1268/1267、`edges_total` 2917 → 5132）、
     `test_bank_seed.py`（figures 267 → 640、干扰项 4730 → 11478、verified/unverifiable 新值、
     自答全对扩到 14375）、`test_seed_provenance.py`（计数与策展键字面）、`test_check_upstream.py`
     （样例重审）、`test_local_seed.py`（TSV 行数断言），其余因数据变化而失效的字面**由 grep 实况列出**。
     新增守卫：① 篡改 `questions.json` 任意图配 → 该题丢弃且 `dropped["figure_hash_mismatch"]` 计数；
     ② 缺哈希条目同样丢弃；③ **家长题路径仍净化**的回归断言（防止这次改动把它一起"优化"掉）。
  6. **文档口径同步**：`README.md`、`README-en.md`、`LICENSE-data.md`、`THIRD-PARTY-NOTICES.md`、
     `seeds/README.md`、`docs/STATUS.md`、`docs/methodology/evals.md`、`CHANGELOG.md`；含把
     "上游无语文/化学"类残句一并清掉（AGENTS §3 已在上轮推翻），并按实测写清**数据体积涨幅**（家长 clone 成本）。
- **DoD**：
  - **收录完整性**：topics **3557**（1481/1267/809）、deps **5132** 且
    `dependencies_dropped_cross_boundary = 0`、questions **14375**（5924/5215/3236）且
    `questions_out_of_scope = 0`、`topics_without_questions = 0`——断言写死字面，不从被测文件反算。
  - **质量闸门（定案三不变）**：`mismatch` 丢弃**必须为 0**；不为 0 → **停下上报、本票不合并**。
  - **性能闸门**：`load_bank(14375)` 实测 **≤ 3000 ms**（预估 ≈2.5 s）、`load_seed` 冷 **≤ 3000 ms**
    （预估 ≈0.96 s）。**不得**靠"少导一点"或"把阈值提到 6 s"绕过；超阈值须给出分相归因
    （json / verify 沙箱 / svg / 其余 四段）后停下上报。
  - **防线不降级证明**：① 篡改图配 → 丢弃 + 计数（RED→GREEN 贴输出）；
    ② `grep -n "sanitize_svg" wengu-api/app/services/bank.py wengu-api/app/services/bank_import.py`
    四处调用**仍在且未被改动**；③ 干净产物上 `stats.dropped == {}`。
  - **转录目录**：1268 行（表头 1 + 数据 1267）、逐行 CRLF、无 BOM、grade 全 ∈ 7–9；
    删导出过滤必须红（P5-10 守卫继续有效）。
  - **体积如实上报**：`seeds/data/*` 与 TSV 的前后字节数、仓库总量涨幅。
  - 全量 `pytest -q` 绿（基线 **887**，如实报新数）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN、前端 `npm lint / test / build` 绿；
    **零迁移、零新依赖**（`bleach` 已在）。
- **提交结构**：一个 PR、**两个 commit**——`commit 1`＝净化前移 + 装载验哈希 + 三条新守卫
  （在现数据上就能全绿）；`commit 2`＝新快照同步 + TSV 重生成 + 文档口径。性能改造与数据变更各自可回滚。
- **白名单**：`wengu-api/scripts/{import_seed,import_questions,check_upstream}.py`、
  `wengu-api/app/seed/{bank,svg}.py`、`seeds/data/{topics,dependencies,questions,_source,questions_source}.json`
  + 新建 `seeds/data/figures_sha256.json`、`docs/templates/topics_junior.tsv`、受影响的测试文件
  （unit：`test_seed_full_coverage` / `test_bank_seed` / `test_seed_provenance` / `test_check_upstream` /
  `test_import_seed` / `test_import_questions`；integration：`test_local_seed` / `test_quiz_api` /
  `test_bank_runtime` / `test_bank_lifecycle` / `test_reviews_api` 等按 grep 实况）、
  `README.md`、`README-en.md`、`LICENSE-data.md`、`THIRD-PARTY-NOTICES.md`、`seeds/README.md`、
  `docs/STATUS.md`、`docs/methodology/evals.md`、`CHANGELOG.md`。
- **禁止**：动 `app/services/**`、`app/api/**`、`app/judge/**`、`migrations/**`、`requirements.txt`、前端源码；
  把 3 s 阈值改成 6 s 或删掉闸门；用 `--skip`/`xfail`/放宽断言让数字"过"；沿用 `d58785ce` 的
  `commit_evidence` 或在新证据里掺旧串；把 TSV 改成 LF 或动转录模板 `version`；
  为 `difficulty` 新档 `challenge`（1447 题）加枚举/UI/字段——**全仓无消费方，只如实透传**；
  重新引入 `cnl_`/`cnc_` 本地前缀（P5-15 已统一 `loc_`）；把家长题的装载期净化"顺手"去掉。

### P5-17 行尾根治（生成侧显式钉死 LF + `.gitattributes` + 一次性 renormalize；零功能改动）
- **背景（两次事故 + 一次普查）**：
  ① P5-10 修复轮——TSV 逐字节守卫在 Linux CI 红、Windows 全绿（§19-L 纪律⑦由此而立）；
  ② P5-16 折入轮——Qoder CN 撞到 CRLF 幻影 diff（4121+/3897−），**成因是审核方沙箱 git 读不到
  用户级 `core.autocrlf=false`（只剩系统级 true），做 `git switch --detach` 往返时按 CRLF 写回工作区**；
  ③ 本票出卡前普查 HEAD blob（327 tracked）发现**含 CRLF 的文本文件有 9 个，不是 1 个**：
  `docs/templates/topics_junior.tsv`（1268，P5-10 有意为之）、`seeds/data/` 全部 6 个 JSON
  （`questions.json` 481,568、`topics.json` 107,491、`dependencies.json` 30,794、
  `figures_sha256.json` 642、`_source.json` 55、`questions_source.json` 104）、
  `tests/fixtures/extraction/truth.json`（110）、`tests/fixtures/two_page_spread.truth.json`（49）。
  **根因 = `import_seed` / `import_questions` 的 `_write_json` 一直用 `Path.write_text()`，
  在 Windows 生成即 CRLF**。P5-10 只治了被断言撞见的那一个 TSV，其余八个没人比对就一直脏着。
  直接后果：**Linux 上重跑 import 会产出 LF 文件，与仓库 blob 逐字节不同**——纪律⑦ 的病灶仍在。
- **三条定案**：
  ① 全仓文本 **LF**，唯一例外 `docs/templates/topics_junior.tsv` 保持 **CRLF**（P5-10 定案，
     导出脚本已写死 `newline="\r\n"`，不动）；
  ② **先治生成侧，再 renormalize**——顺序反了就是埋雷：下次谁重跑 import，Windows 又产 CRLF，diff 再炸；
  ③ renormalize **单独成 commit** 并机械自证"内容零变化"，不许混进功能 commit。
- **任务**：
  1. 生成侧写死换行：`_write_json`（`import_seed.py` / `import_questions.py`）与 `figures_sha256.json`
     写入处改为显式 `open(..., "w", encoding="utf-8", newline="\n")`；**仓库文本产物禁用 `Path.write_text()`**。
     重跑两个 import 脚本（同一快照 `8b57f2e`，`--upstream-commit` 显式传），产物**仅换行差异、内容零变化**。
  2. 新增 `.gitattributes`，规则逐条写死（不许只留一行 `* text=auto` 敷衍）：
     - `* text=auto eol=lf`
     - `docs/templates/topics_junior.tsv text eol=crlf`（**显式路径**，不用 `*.tsv` 通配，防将来新 TSV 误继承）
     - `*.ps1 text eol=lf`（PS5.1 要 BOM+LF；BOM 属内容不受 eol 影响。现状 3 个 `.ps1` 已是 LF）
     - `*.png binary`（`*.jpg` / `*.gif` / `*.ico` 预防性列出；当前二进制仅 12 个 PNG）
     - 无此类文件就不要加 `.min.js -diff` 之类规则（别造需求）
  3. 一次性 `git add --renormalize .`，单独 commit。
  4. 守卫（新测试文件）：
     - 遍历 tracked 文本文件，断言 HEAD blob 内 `b"\r\n"` 计数为 **0**，例外清单**有且仅有**
       `docs/templates/topics_junior.tsv`（白名单式例外，新增 CRLF 文件必须显式进例外才放行）；
     - 断言 `.gitattributes` 存在且含上述关键规则行；
     - 断言两个 import 脚本源码**不再出现** `write_text(`（源码级守卫，防回退）；
     - 变异自证：① 把 `_write_json` 改回 `write_text` → 源码守卫红；② 往某 `.md` 塞 CRLF 并 add →
       产物守卫红。两处 RED→GREEN 贴输出。
  5. 文档：`AGENTS.md §8` 加一条（新文本产物一律 LF；换行由 `.gitattributes` 决定，
     **不得依赖本机 `core.autocrlf`**）；设计文档 **§19-L 纪律⑦ 泛化**——原文只覆盖"产物字节 == 仓库文件"
     的比对场景，本次升级为"**凡生成进仓库的文本，生成侧必须显式钉死换行与编码；仓库侧以
     `.gitattributes` 兜底**"，并把这次的 9 个 CRLF blob 与两次事故记进去；
     `seeds/README.md` 重生成段补一句"产物为 LF，TSV 例外"；`CHANGELOG.md` Changed 一条。
- **DoD**：
  - **内容零变化自证（最关键）**：renormalize 前后每个受影响文件"去掉全部 CR 后逐字节相等"，贴全量比对；
    `seeds/data/*` 的 `json.load` 结果前后完全相等；
  - **跨平台可复现**（本次要买到的东西）：Windows 重跑 import 的产物与仓库 blob **逐字节一致**——必须实测，不许推理；
  - **TSV 未被波及**：`topics_junior.tsv` 仍 1268 行、CRLF 1268、blob 字节与 renormalize 前完全一致；
    P5-10 那条"删导出过滤必红"的守卫仍绿；
  - 全量 `pytest -q` 绿（基线 **901**，如实报新数）、`ruff check --no-cache .` 全仓绿、
    `selfcheck --strict` 18 OK / 0 DRIFT / 0 WARN、前端 `npm run lint / test / build` 绿；
  - `git diff --name-only` 不含 `app/api/**`、`app/services/**`、`migrations/**`、`requirements.txt`；
    **零迁移、零新依赖**。
- **提交结构**：三个 commit——① 生成侧写死 LF + 重跑产物；② `.gitattributes` + `--renormalize`（纯换行）；
  ③ 守卫 + 文档。（squash 合并下不构成回滚粒度，仅为审查可读性——措辞按 P5-16 教训校准。）
- **白名单**：`.gitattributes`（新）、`wengu-api/scripts/import_seed.py`、`wengu-api/scripts/import_questions.py`、
  `seeds/data/*`（仅换行变化）、`wengu-api/tests/fixtures/**/*.json`（仅换行变化）、新守卫测试文件、
  `AGENTS.md`、`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`seeds/README.md`、`CHANGELOG.md`。
- **已知代价（需决策人知情）**：renormalize 会产生一个约 **62 万行 / 19 MB** 的纯换行 commit
  （`questions.json` 48 万行占大头），人眼不可审，只能靠"去 CR 后逐字节相等"的机械自证。
  一次痛换永久干净，本票认为值得，但明确写在此处。
- **禁止**：改 `topics_junior.tsv` 的字节；改任何 seed 数据**内容**（只允许换行）；
  把 `.gitattributes` 写成只有 `* text=auto` 的敷衍版；renormalize 混进功能 commit；
  用 `git checkout --` 还原或改写已推送历史；为"顺手"引入 `.editorconfig` / prettier / lint-staged
  （无消费方）；动 `app/**` 运行时逻辑（本票只碰生成脚本）。
- **卡面补强三（折入轮 2026-11-20；审核方变异发现，登记第 26 次卡面缺陷）**：
  原任务 4 只要求"断言两个 import 脚本源码**不再出现** `write_text(`"。审核方把
  `import_seed.py:233` 的 `newline="\n"` 改成 `newline="\r\n"` 后**四条守卫全绿**——只禁 `write_text`
  挡不住"保留 `open()` 但换行取值回退"这条更现实的回头路（git 层在 `add` 时归一，产物守卫抓不到；
  工作区守卫只比 HEAD blob 白名单里的 CRLF，`open()` 换行写错不等于文件里有 CRLF）。
  防线本身是真的，但卡面承诺的"生成侧**显式钉死**换行"没有守卫兜着。补一条守卫：源码级钉死**取值**
  ——两个 import 脚本必须出现 `newline="\n"` 且不得出现 `newline="\r\n"`；对称钉死
  `export_topics_junior.py` 保留 `newline="\r\n"`（P5-10 定案，现状只有 Linux CI 才抓得到）。
  折入以分支上一个**普通追加 commit** 交付（不 amend `fed4dd0`），白名单不变（守卫测试文件 + `CHANGELOG.md`）。
- **卡面补强四（2026-11-20；施工方上报、审核方定性为第 27 次卡面缺陷）**：
  原任务 1 写"重跑两个 import 脚本（同一快照 `8b57f2e`），产物**仅换行差异、内容零变化**"。照字面执行会毁掉两份
  source JSON 的人工策展键——脚本只发射 10 个基础键，`_source.json` / `questions_source.json` 里的 `commit_evidence`
  等 9 键、`counts.load_quality`、`name` 的「10 学科」后缀都不在发射集内，重跑即覆盖（`imported_at` 另带今天日期戳）。
  施工方**没有照做**：改在仓库外 scratch 目录重跑取证（四个纯产物与 HEAD blob 去 CR 逐字节相等、新产物 CRLF 全 0），
  仓内两份 source JSON 只由 renormalize 做换行处理，并如实上报——判定正确，`seeds/README.md` 本就警告过覆盖风险。
  **性质**：卡把"四个纯产物（可覆盖）"与"两份含策展键的 source JSON（只能换行级）"混成一句指令，属**会诱导施工方
  破坏数据**的卡面错误，比措辞不准更重。已泛化为 `AGENTS.md §8`「重跑生成脚本的覆盖边界」。
  **本条不改变 P5-17 折入轮的白名单与要求**（施工方已按盘实况处理，无追加动作）。
- **状态：已合并（2026-11-20，PR#70 squash → main `2daa331`；原分支已删，`ls-remote` 复核为空）**。
  四个 commit：`f6d3de8` 生成侧 LF + 重跑产物 / `7aa3c51` `.gitattributes` + renormalize /
  `fed4dd0` 守卫 4 条 + 文档 / `f846bc2` 折入轮第 5 条守卫。审核方独立实跑：全量 **906 passed**
  （512.48s，= 基线 901 + 新 5）、守卫单跑 5 passed、`ruff check --no-cache .` 全仓绿；
  renormalize 前后 8 个受影响文件"去 CR 逐字节相等"+ `json.load` 全等；TSV blob sha `f4939df6…` 未变；
  合并后 main 上 CRLF 普查仅剩 TSV（1268）、`check-attr` 实测 TSV `text: unset` 其余 `text: auto`+`eol: lf`；
  合并 commit 恰好 16 个文件、全在白名单内、无 `app/**`/`migrations/**`/`requirements.txt`；
  CI 三绿（api/web/transcribe）、`mergeable=MERGEABLE`。
  自主变异：施工方三靶（退回 `write_text` / README 塞 CRLF 并 add / 删 TSV 例外行）+ **审核方三靶**
  （① `import_seed.py` 取值改 `\r\n` → 旧四条守卫全绿，坐实第 26 次缺陷；② `export_topics_junior.py`
  取值改 `\n` → 第 5 条守卫红；③ `import_seed.py` 另加一处 `\r\n` writer 并保留原 LF 行 → 红在
  `not in` 断言，补齐施工方披露的"两靶同落 107 行"取证边界）。全部还原 sha256 一致、工作区干净。
  前端 `tsc / 57 tests / build` 由施工方实跑，审核方本轮未复跑（如实标注）。
- **登记第 24 / 25 / 26 / 27 次卡面缺陷**（本票四笔，全部归审核方）：24 = TSV 例外行写成
  `text eol=crlf`（实测 `text` 一设、add 即把 blob 归一成 LF，正解 `-text`）；25 = 守卫规范自相矛盾
  （要求"只查 HEAD blob"同时要求"塞 CRLF 并 add 必红"，归一生效后不可能同时成立）；
  26 = 源码守卫只禁 `write_text(`、未钉换行**取值**；27 = 任务 1 把"可覆盖的纯产物"与"含人工策展键、
  只能换行级处理的 source JSON"混成一句指令，照做会毁策展数据。24/25/27 由施工方实测或上报发现，
  26 由审核方变异发现。27 已泛化为 `AGENTS.md §8`「重跑生成脚本的覆盖边界」。
- **本轮新增环境事实（审核方侧，写下防再踩）**：① 沙箱对 `wengu-api` 设访问控制会偶发
  `Failed to update ACL ... : 5`（连 `echo` 都跑不起），此时改走主机授权执行；② 会话环境里
  `GIT_CONFIG_KEY_0` / `GIT_CONFIG_VALUE_0` 因名字含 KEY 不持久化、而 `GIT_CONFIG_COUNT` 会——
  泄漏后主机上每次 git 都报 `missing config key GIT_CONFIG_KEY_0`，造成守卫假红（本轮我第一次跑
  守卫的 2 failed 就是这个原因，与施工方无关）；今后一律 `-c safe.directory=<repo>`，弃用 env 三件套；
  ③ 交付分支上游常被 `switch -c ... origin/main` 设成 `origin/main`，推分支必须显式 refspec。

### P5-18 K12-KGraph 只读对照审计脚本（零依赖、零联网、零写入；报告落仓库外）
- **背景（审核方 2026-11-20 实测；①–⑧ GitHub 侧，⑨–⑲ HuggingFace 全量侧，均可复现）**：
  ① GitHub 副本仓库外 `D:\MyProducts\StudyDesk\K12-KGraph`，`clone --depth 1`，HEAD
     `865bc3556768224d929825d7c258a5e77ac1aab0`（2026-09-28 22:59:02 +0800）；
     `LICENSE` 首行 = CC BY-NC-SA 4.0（sha 前缀 `6c16319398a96728`），`LICENSE-CODE` = MIT。
  ② GitHub **只发 demo**：`demo/kg/math_7a_rjb.json` 一本书（157 节点 / 285 边，sha 前缀
     `568582a7d4fc06e3`），`demo/manifest.json` 的 `schema_version = "0.1.0"`。
  ③ demo schema：节点 `id/label/name/properties`，**类型字段是 `label` 不是 `type`**；
     边两形态——`source/source_name/target/target_name/type`（`is_a`/`prerequisites_for`/`relates_to`
     带 `properties.evidence`）与 `source/source_stem/type/target_name_to_ids[]`（`tests_*`）；
     demo 带 evidence 边 90 / 285。
  ④ `books.yaml` 48 条 = 数学 23 / 生物学 9 / 物理 9 / 化学 7，含
     `book_prefix/subject/stage/grade/publisher`。
  ⑤ 我们侧真源：`seeds/data/topics.json` 3557 点、`seeds/data/dependencies.json` 5132 边
     （键 `topic_id/prerequisite_id/strength/reason`）。
  ⑥ 全仓 grep `cycle|topolog|成环|dag` 实测零命中 → 5132 条先修边从未做 DAG 体检。
  ⑦ 备份面实测：`app/services/backup.py:226-229` 只打包 DB 快照 + `data_dir/uploads` +
     `data_dir/seeds_local` + `inbox` + `app-config.json`，不 sweep 任意目录。
  ⑧ demo 对齐率：Concept+Skill 116 名 vs 我们 `grade=7` 数学 119 点精确同名 9（7.8%）、
     子串互含 46（39.7%）；45 条 `prerequisites_for` 两端名字都在我们点表内的仅 2 条。
  ⑨ **全量三层**（HF `lhpku20010120/K12-KGraph`，直连不通、`hf-mirror.com` 通）：
     `global_KG/` = **瘦图**（`nodes.json` 10685 条仅 `id/label/name`，label 分布
     Concept 6574 / Skill 1364 / Exercise 1174 / Experiment 652 / Section 609 / Chapter 264 /
     Book 48；`edges.json` 23278 条仅 `source/target/type`，9 类边，**带 evidence 0 条**）；
     `subject_specific_KG/{math,physics,chemistry,biology}.json` = **富图**（节点带
     `properties{definition,importance,pages?,examples?}`、边带 `properties{relations?,evidence?}`）；
     `afterclass_exercises/*.json` = 15 本分册习题。数据集根另有 K12-Bench / K12-Train / SFT-Baselines。
  ⑩ **四科富图实测规模**：math 2711/5273（evidence 1473 = 27.9%，prereq 817/853 = 95.8%）；
     physics 2025/4092（1430 = 34.9%，644/648 = 99.4%）；chemistry 3491/8141
     （3734 = 45.9%，1335/1344 = 99.3%）；biology 2458/4965（1919 = 38.7%，858/858 = **100.0%**）。
  ⑪ **边类型不得硬编码**：瘦图 9 类含 `verifies`；富图并集也 9 类，但**数学富图只有 8 类、无
     `verifies`**（物理/化学/生物各有）。按 9 类遍历会在数学上 KeyError。
  ⑫ **他们全局图实测有 2 个 2-节点环**（瘦图 prereq 3703 条、自环 0；数学子集无环）：
     `chemistry_xzxbx2_rjb_cpt100 极性分子 ↔ cpt108 相似相溶规律`、
     `chemistry_xzxbx1_rjb_skl2 根据键能估算反应热 ↔ cpt10 化学键能量变化与反应热`；
     与 README 声称的"Automatic DAG validation on `is_a` and `prerequisites_for` subgraphs"**不符**。
  ⑬ **同样这 2 个环在富图 `chemistry.json` 内独立复现**（prereq 1344 条 → 多节点环 2、自环 0），
     且四条边**全部带 `properties.evidence`**（极性分子/相似相溶两侧同一段教材文字；
     键能反应热两侧分别是 H₂+Cl₂ 微观讨论段与 436 kJ 键能计算段）。
     → **环检测与 evidence 取回都在富图一层完成，瘦图只作规模对照**。
  ⑭ 学段定位实测：节点**无 book 字段**；`id` 去掉最后一段即 `book_prefix`
     （`math_7a_rjb_cpt1` → `math_7a_rjb`；`chemistry_xzxbx2_rjb_cpt108` → `chemistry_xzxbx2_rjb`），
     切出 48 个与 `books.yaml` 一一对应；`appears_in` 的 target 是 Section（瘦图 9689）或
     Chapter（1082）；`books.yaml` 数学 = 小学 12 / 初中 6 / 高中 5。
  ⑮ **学科名逐字不等**：他们 subject = `数学/物理/化学/生物学`；我们 = `数学 870 / 英语 791 /
     语文 683 / 道德与法治 269 / 物理 269 / 科学 269 / 化学 147 / 历史 134 / 生物 66 / 地理 59`。
     判等结果：数学/物理/化学 True，**`生物学` vs `生物` = False**。对照面只有 4 科，
     **6 科无对照**（英语/语文/道德与法治/科学/历史/地理）。
  ⑯ **学段口径不同**：他们 grade 是中文册名（`七年级上册`…`选择性必修三`），我们是 int 1–16。
     册名→int 的对应**本票无实测依据**，只允许按 `stage` 三档对齐。
  ⑰ 全量规模对齐率复测：他们数学初中 555 名 vs 我们 `cnm_` grade7-9 的 315 点精确同名 44
     （**7.9%**）、vs 全 3557 点 53（9.5%）、子串互含 287（51.7%）；数学全量 1886 名 vs 全表 9.5%。
     独有名为符号化短名（`aas判定法`、`30直角三角形性质`、`x2pqxpq型因式分解`）。
  ⑱ 粒度差异实测坐实（定案三 ④ 类）：他们化学 Concept 2302 vs 我们化学 147 点；
     他们生物 Concept 1648 vs 我们生物 66 点；他们数学初中 555 vs 我们 grade7-9 315。
  ⑲ `importance`（掌握 672 / 重要 621 / 了解 173 / 理解 1 / 无 1244）与 `pages`（238 节点）
     **无消费方** → 不进清单、不进报告字段。
- **五条定案（不要重开）**：
  ① 零新依赖、脚本不联网、全量下载不进本票（决策人手动放件，脚本探测布局）；
  ② 只出**候选表 + 结构体检**，**禁止输出"覆盖率"结论**（7.9% / 9.5% 是实测底子）；
  ③ 报告一律落仓库外 `D:\MyProducts\StudyDesk\kg-audit\`；他们的 `definition/examples/stem/answer`
     一律不得复制进任何进仓库的文件（抄文本即构成 Adaptation、触发 SA）；本地报告可带 evidence 片段；
  ④ **主层是富图**：环检测与 evidence 都从 `subject_specific_KG/*.json` 取；瘦图仅用于规模对照与
     交叉验证，两层结论不一致时**以富图为准并如实报差异**；
  ⑤ **映射表写死**：学科 `{"数学":"数学","物理":"物理","化学":"化学","生物学":"生物"}`，
     学段只按 `stage` 三档（小学→grade 1–6 / 初中→7–9 / 高中→10–16）；
     **禁止用字符串包含或前缀猜学科与年级**（⑮ 就是陷阱本体）。
- **任务**：
  1. 新增 `wengu-api/scripts/audit_kg.py`，**照 `check_upstream.py` 三层写法**（纯解析/计算层不吃
     路径不联网不写盘 → 只读输入层 → 输出层）。CLI：`--kg-dir`（默认
     `D:/MyProducts/StudyDesk/K12-KGraph-hf`，须同时支持 GitHub demo 布局
     `D:/MyProducts/StudyDesk/K12-KGraph`，靠文件探测判布局；认不出 → 可读错误 + 非零退出）、
     `--out-dir`（默认 `D:/MyProducts/StudyDesk/kg-audit`）、`--json`、`--subject`（默认四科全跑）。
     **两个路径任一落在仓库内即拒绝运行**（判定写成纯函数、单测覆盖）。
  2. 解析层支持三种形态：瘦图（`nodes.json`/`edges.json`，无 properties）、学科富图
     （`nodes`/`edges`，节点 `properties.definition/importance`、边 `properties.relations/evidence`）、
     书级 demo（边另带 `source_name/target_name` 与 `tests_*` 的 `target_name_to_ids[]`）。
     边类型一律按**实测集合遍历**，不得硬编码 9 类（⑪）。
  3. 结构体检段：复现 ⑨ 的瘦图 label 分布与 23278 边 0 evidence、⑩ 的四科规模与 evidence 率、
     ⑪ 的数学缺 `verifies`；副本不完整/布局不认识/文件字节与 sha 锚点不符 → 明确报错非零退出，
     **不得静默出半份报告**。
  4. 环检测段（两侧都做，Kahn 判有无环 + Tarjan 取强连通分量，纯标准库）：
     我们侧 `dependencies.json` 5132 边 → **必须打印 `cycles=0` 并保留该节**（实测就是 0）；
     他们侧富图 chemistry → **必须复现 ⑬ 那两个 2-节点环并附四条边的 evidence 原文**；
     其余三科富图与瘦图全局 → 复现"0 环 / 全局 2 环"。任一复现不出即为脚本缺陷。
  5. 候选表段：两档（精确同名 / 归一化子串互含），每条带我们 id、他们 id、双方名字、
     他们 `appears_in`→Section/Chapter 定位、富图 evidence 前 80 字；数学初中规模实测
     **555 名 / 精确同名 44 / 子串互含 287**，报告数字必须对得上。
  6. gap 分类按定案三四类：① 整学科缺失（实测 6 科，见 ⑮）② 前置边缺失/方向相反/成环
     （本票实测产出即 ⑫⑬ 那两个环，处置走 B 提上游 issue）③ 知识点缺失
     ④ 粒度差异（实测数字见 ⑱，**单列、不计入缺失总数**）；反向 gap（我们有他们没有）
     标注"不算问题、不得据此删点"。**无 evidence 的 gap 不得进 ②③ 清单**。
  7. 新增 `wengu-api/tests/unit/test_audit_kg.py`：纯函数层单测覆盖三种形态解析、label 归类、
     evidence 抽取（含"瘦图无 evidence 不得进 ②③"）、两档候选匹配、布局探测失败报错、
     仓库内路径拒绝、学科映射表（**必须有一条断言：`生物学` 映射到 `生物` 且拒绝包含式匹配**）、
     Kahn/Tarjan（人造 3 环与 2-节点互环都必须检出）。
  8. 文档：`CHANGELOG.md` 一条；设计文档 §19-G-3 定案二/三 追加"三层 schema + 四科规模 +
     实测 2 个上游化学环（含 evidence）+ 6 科无对照 + 学科名逐字不等"；
     `docs/STATUS.md` 交付区新增本票条目（AGENTS §8 补严）。
- **DoD（逐项贴输出，全部可同时成立）**：
  - 对 HF 布局与 GitHub demo 布局各跑通一次，报告落 `kg-audit/`（JSON + Markdown 两件套）；
  - 实测复现：⑩ 四科规模与 evidence 率、⑪ 数学缺 `verifies`、⑬ 两个化学环 + 四条 evidence、
    我们侧 `cycles=0`、数学初中 555/44/287；
  - **零写入证明**：运行前后 `git status --porcelain` 为空；`seeds/data/*` 与
    `docs/templates/topics_junior.tsv` 逐个 sha256 不变；
  - **不进备份证明**：实跑一次备份导出，贴 zip 文件清单，断言不含 `kg-audit` 与任何 K12 路径；
  - **零依赖 / 零联网证明**：`requirements.txt` 零变化；源码 grep 无
    `requests|urllib|httpx|socket|sqlite3|datasets|huggingface|networkx`；
  - 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，如实报新数）；`ruff check --no-cache .` 绿；
    既有 5 条行尾守卫仍绿；
  - 零迁移、不动 `app/**`、不改 loader / `seeds/**`、不建 `seeds_external` 装载。
- **白名单**：`wengu-api/scripts/audit_kg.py`（新）、`wengu-api/tests/unit/test_audit_kg.py`（新）、
  `CHANGELOG.md`、`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`docs/STATUS.md`。
- **禁止**：引入依赖；脚本联网；把报告或他们的文本写进仓库任何位置（含被忽略的 `data/`）；
  输出"覆盖率 X%"；用 `importance`/`pages` 造字段（无消费方）；用字符串包含猜学科或年级；
  做逐册年级映射（本票无实测依据）；做可视化 / 导入 UI / 教材包机制 / `seeds_external` 装载；
  改 `seeds/data/*` 或 loader；`--skip`/`xfail`；把"四科富图"说成"全学科对照完成"。
- **运行期输入（已就位，不由本票产生）**：仓库外 `D:\MyProducts\StudyDesk\K12-KGraph-hf\` 六件，
  sha256 前缀 `global_KG/nodes.json 99d7d4b86e7c92f6`、`global_KG/edges.json b7b2bea4a16467b5`、
  `subject_specific_KG/math.json 00ed25179bb4ad09`、`physics.json 2108bcb685554ecb`、
  `chemistry.json 6441ec8e247f8535`、`biology.json c775d68709aaca2c`；
  GitHub demo 布局在 `D:\MyProducts\StudyDesk\K12-KGraph`。脚本必须在这两个目录任一缺失时
  给出可读错误，不得回退成"假装无差异"。
- **取证副次产物**：审核方干跑脚本 `D:\MyProducts\StudyDesk\_kg_probe.py` / `_kg_probe_global.py` /
  `_kg_probe_ss.py` / `_kg_probe_final.py`（仓库外，可复跑复核）。
- **状态：已合并（2026-11-20，PR#71 squash → main `2b8b033`；原分支已删，`ls-remote` 复核为空）**。
  两个 commit：`e555cfa` 脚本+单测（1052+360 行，23 条）/ `5aa6775` 文档三处
  （交付报告笔误写作 `5aa8775`，盘上实为 `5aa6775`，nit 已记入 PR body）。
  审核方独立复验：两种布局各实跑 exit 0，卡面锚点全部复现——瘦图 10685/23278/0 evidence；
  四科 2711/5273=27.9%、2025/4092=34.9%、3491/8141=45.9%、2458/4965=38.7%，prereq 带 evidence
  95.8/99.4/99.3/100.0%；数学缺 verifies；化学富图 2 个 2-节点环且四边 evidence 原文在报告；
  瘦图交叉 consistent；我们侧 cycles=0；555/44/287；gap ①6 ②17 ③5150 ④13、排除 922、反向 4；
  demo 157/285/90、精确 9 / 串含 61（全学段）/46（grade7 口径）。全量 **929 passed**
  （施工方 514.64s + 审核方 main 复跑 473.90s 同数）、ruff 全仓绿；零写入（git status 前后空、
  seeds 7 件 sha256 不变）；合并后 main 复跑守卫 28 passed、CRLF 普查仍仅 TSV。
  读盘纠正三笔经审核方实测确认属实：瘦图 tests_* 扁平形态；子串口径 = 同学科全学段（287，
  同学段限 223），精确档 44 不变；evidence 有字符串与 `{text,page}` 字典双形态
  （math 1396+77=1473、demo 77+13=90，卡面总数口径成立）。自主变异两靶（施工方未演示）：
  ① `map_subject` 退化包含式匹配 → `test_subject_map_literal_equality_only` 红；
  ② `edge_type_counts` 预种 9 类 → `test_label_and_edge_type_counts_iterate_measured_set` 红
  （红在 `"verifies" not in counts`）；还原 sha256 一致、23 passed、工作区干净。
  无 evidence 原文进仓库：diff 命中 3 处均为节点名与"××段"定位描述。
- **后续（另票）**：化学 2 环提上游 issue（定案三 B，人工决定时机）；册名→int 年级逐册映射
  如将来需要，必须先实测取证再写卡（本票无依据）。

### P3-4 英语默写闭环（卷面生成 + 页内回录 + 既有二档调度复用；听力线拆两票）
- **背景（审核方 2026-11-20 读盘实测）**：
  ① 权威口径：设计文档 §5.9 表——默写·听写 = ①客观 + 拍照批改 + 进（客观驱动）；
     听力 = 需音频+题 + 教材音频+TTS + 进（**依赖音频来源**）；口语 ASR **不做**。
     旧一句话卡（本文件「P3-4 听力+默写」行）写于 v2.5 前，本票修订其"走转录导入"为
     "页内勾选"（决策 D2=A），原句已加删除线注记保留追溯。
  ② 可复用链路实测在位：`recitation_items`（subject/prompt/answer/unit/status）+
     `recitation_reviews`（item_id/verdict/rung/reviewed_on，迁移 0020）；
     `services/recitation.py` 的 `decide(rung, verdict)` 二档调度（`VERDICTS=(remembered, forgot)`，
     remembered 进档/毕业、forgot 保持不倒退）；`POST /api/recitations/{item_id}/review`
     单条回录端点已存在（require_parent）；词表 1–3 列（prompt 必填 / answer、unit 可选）；
     `RecitationsPage` 与 `ReviewPage` 已挂背诵到期入口；打印先例 `PrintPaperPage`（`window.print()`）；
     **迁移下一号 = 0024**；schemas 内联在 `api/recitations.py`（ItemView/ReviewRequest/ReviewResponse）。
  ③ 架构口实测：`transcribe/` 契约只绑定 `doubao_transcribe_v1`，`transcribe/CONTRACT.md:76` 明说
     bank 通道"后续按同一模式补第二份契约，**不要混写**"——默写卷若走拍照转录 = 第三条通道
     （新模板 + 新契约 + `validate.py` 扩展 + 新草稿表），而卷面词单在生成时系统已知，
     家长批完只需标记错词（每卷约 30 秒）→ **本票不建转录通道**。
  ④ 红线实测：v2.5 后 wengu 内核零云推理 → 云 TTS 出局；`services/mistake_images.py:38` 的
     `ALLOWED_MIME` 只允许 JPEG/PNG/WEBP → 音频不是顺路可传；`app/services/backup.py:226` 把
     `data_dir/uploads` **整树**打进备份 zip → 第三方版权音频绝不进 uploads；
     设计文档既有定案"背诵自评保持二档不动" → 默写对错必须直映二档；
     P3-3a 边界"背诵条目不是错题" → 错词不进错题本。
- **五条定案（不要重开）**：
  ① 听力线**不进本票**，拆为两票递进：**P3-4b 听写**（音频→手写→勾选回录）、
     **P3-4c 听力理解题**（音频+题面，走现有题库录入/组卷/judgeAnswer 链路）。
     **触发条件已满足**：决策人 2026-11-20 确认所购课程听力部分可导出为普通本地音频文件（非 DRM）。
     P3-4b 前置取证要点已记录：音频落 `data_dir/audio/`（绝不进 uploads 树，理由见背景④）、
     挂接粒度只到"一张卷/一个单元"、不逐词对时间戳、不规避技术措施、目录内留来源记录、
     `PRIVATE-DO-NOT-SYNC.md` 须加"第三方课程音频不进备份/不外发"条目。口语 ASR 仍不做；TTS 仍出局。
  ② 结果回录 = **页内勾选**（卷由 `dictation_sheets` 表持久化，打印与回录可跨天/跨设备）；
     拍照转录通道留作后续可选票（触发 = 家长回录负担成为真实证据）；页内键入默写禁止；
  ③ 判分主体 = 家长卷面红笔（v2.5 外部批改口径），**系统零判分代码**，只做一致性检查与调度；
  ④ 错词只走 `recitation_reviews` 重默循环，不进错题本；对错直映二档，`decide()` 原样复用；
  ⑤ 卷面只做"看提示写"，**打印视图与孩子可达 API 一律不出现 answer**（单测 + 组件测试双断言）。
- **任务**：
  1. 迁移 `0024_dictation_sheets`（可逆）：`id PK / created_on Date / created_by Text / subject Text /
     unit Text? / item_ids Text(JSON 有序数组) / status Text('open'→'recorded') / recorded_on Date?`；
     FK/CHECK/UNIQUE 按迁移 0020 风格；含迁移测试（up/down/up）。
  2. `models/recitation.py` 加 `DictationSheet`；`api/recitations.py` 内联新增 schemas；新端点：
     `POST /api/recitations/sheets`（item_ids 非空、全部 active、词序按提交顺序固化，require_parent）、
     `GET /api/recitations/sheets` + `GET /api/recitations/sheets/{id}`（详情**响应不含 answer**）、
     `POST /api/recitations/sheets/{id}/results`（`results=[{item_id, verdict}]`，校验归属 + 二档，
     事务内逐条写 `recitation_reviews` 并调 `decide()`，返回每条新 rung 与下次到期；
     `open→recorded` 状态机，重复提交 409；缺失/停用条目跳过并在响应中报告）。
  3. 新 `services/dictation.py`（纯函数层 + 输入层）：生成快照、回录校验、与 `decide()` 的集成——
     **同一 fixture 同一输入下，批量回录每条的 rung/下次到期必须与现有单条 review 端点逐项相等**
     （复用性自证，测试断言）。
  4. 前端：`RecitationsPage` 加「生成默写卷」（勾选 active 条目 → POST → 跳打印）与 open 卷列表 +
     「回录」视图（按卷词序逐词 对/错 → 批量提交 → 显示每词新档位与下次到期）；
     新 `PrintDictationSheetPage`（卷号/日期/词序表/提示/空行，**不渲染 answer**，`window.print()`）；
     `App.tsx` 路由；`api/endpoints.ts`/`types.ts` 新端点。
  5. 测试：`tests/unit/test_dictation.py`（纯函数：生成快照/校验/状态机/缺失条目跳过/与 decide() 一致性）
     + `tests/integration/test_dictation_api.py`（全链：生成→回录→due 变化→毕业；重复提交 409；
     权限口径随现有 API 测试）。
  6. 文档：`CHANGELOG.md` 一条；设计文档 §5.9 表下加注（默写回录 = 页内勾选，2026-11-20 修订，
     原"走转录导入"保留删除线；拍照转录为后续可选票及触发条件；听力拆 P3-4b/P3-4c 及各自触发条件）；
     `docs/STATUS.md` 交付区新增本票条目（AGENTS §8 补严）。
- **DoD（逐项贴输出，全部可同时成立）**：
  - 迁移 0024 up/down/up 绿；`alembic head` 前后贴对照；
  - **answer 零泄漏**：打印视图 DOM 与 `GET /sheets/{id}` 响应均断言无 answer 字段/值；
  - 复用性自证：批量回录与单条 review 端点在同一输入下 rung/下次到期逐项相等；
  - 状态机：重复提交 409；缺失条目跳过并在响应中列明；
  - 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，当前 **929**，如实报新数）；
    `ruff check --no-cache .` 绿；前端 `npm run lint / test / build` 绿；行尾守卫 5 条仍绿；
  - 零新依赖、零联网、不动 `app/judge/**`、不改 `decide()`/`VERDICTS`、不碰 `seeds/**` 与错题写入路径。
- **白名单**：`wengu-api/migrations/versions/0024_dictation_sheets.py`（新）、
  `wengu-api/app/models/recitation.py`、`wengu-api/app/services/dictation.py`（新）、
  `wengu-api/app/api/recitations.py`、`wengu-api/tests/unit/test_dictation.py`（新）、
  `wengu-api/tests/integration/test_dictation_api.py`（新）、`wengu-web/src/api/endpoints.ts`、
  `wengu-web/src/api/types.ts`、`wengu-web/src/pages/RecitationsPage.tsx`、
  `wengu-web/src/pages/PrintDictationSheetPage.tsx`（新）、`wengu-web/src/App.tsx`、
  `CHANGELOG.md`、`docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`docs/STATUS.md`。
- **禁止**：听力/音频/TTS/ASR 任何形式（P3-4b/c 的事）；拍照转录通道/新模板/契约扩展；
  页内键入默写；别名字段（`acceptable`）；第三档或改 `decide()` 调度语义；把错词写进错题本；
  打印视图或孩子可达 API 出现 answer；导出统计图表/电子表格（无消费方）；
  **为"将来好挂音频"给 `dictation_sheets` 或任何表预留 nullable 的 audio/时间戳字段**
  （P3-4b 需要时由它自己的迁移加列——无消费方就不加）；
  动 `app/judge/**`、`seeds/**`、错题写入路径；`--skip`/`xfail`。
- **后续票（2026-11-20 决策轮登记）**：**P3-4b 听写音频线**（前置 = P3-4 合并；触发条件已满足，
  紧随其后即可投）；**P3-4c 听力理解题**（触发 = 课程题目确实需要录入，届时先读盘取证
  `doubao_bank_transcribe_v1` 与组卷链路能否零改动承载"音频+题"）。
- **卡面补强（折入轮 2026-11-20；登记第 28 / 29 次卡面缺陷，均归审核方）**：
  **第 28 次 = 白名单反推漏项（我的第 5 次漏）**：DoD 写了"迁移 0024 up/down/up 绿"，却没反推出该断言
  落在 `wengu-api/tests/integration/test_migrations.py`（`EXPECTED_TABLES` 与 `== 22` 表数断言）——
  任何新表必炸它。施工方按盘上实况做了最小越界改动（+`dictation_sheets`、22→23，共 2 行）并主动上报，
  **审核方认可保留，不另开票**。
  **第 29 次 = 要求了本仓不存在的设施**：定案⑤写"单测 + 组件测试双断言"，而
  `wengu-web/package.json:11` 的测试命令是 `node --test tests/*.test.ts`，无 jsdom / testing-library /
  vitest。**接受其替代取证三层**（打印页源码 `answer` 出现 0 次 + `SheetItemView` 无该字段 +
  浏览器实测），今后卡面对前端只写可执行层级（tsc + node --test + 源码级守卫 + 浏览器实测），
  不再写"组件测试"。
  **审核方五靶变异结论**：M2 放开"一卷一学科"（`len(subjects) != 1` → `> 2`）→ 红；
  M3 `ensure_open` 改空函数 → 红；M4 模型+迁移同时预留 `audio_path` 列 → 红
  （`test_0024_dictation_sheets_up_down_up` 抓到，**"接口预留禁止"确有守卫**）；
  M5 响应模型加 `answer: str = ""` 字段 → 红（`test_sheet_projection_and_schemas_have_no_answer_field`）；
  **M1 把 `MAX_SHEET_ITEMS` 从 200 改成 200000 → 全绿 = 守卫缺口**（该上限是施工方自报的边界决策，
  无测试兜着）。另核实 `backup.py:42` 的 `COUNT_TABLES`（14 项，含 `recitation_items` /
  `recitation_reviews` / `pomodoro_sessions`）未含 `dictation_sheets` → manifest 少一项计数；
  施工方因该文件不在白名单而未动，处置正确。
- **折入两项与白名单扩充（本票追加授权）**：`wengu-api/app/services/backup.py`、
  `wengu-api/tests/integration/test_backup_api.py`（原白名单之外的两个文件，仅此折入用途）；
  其余仍限原白名单。折入以分支上一个普通追加 commit 交付（不 amend `98ba64c`），
  新 commit 的 `git diff --name-only` 恰好五个文件（两处测试 + `backup.py` + 备份测试 + `CHANGELOG.md`）。
- **状态：已合并（2026-11-21，PR#72 squash → main `8da6ddf`；原分支已删，`ls-remote` 复核为空）**。
  三个 commit：`19ff8f4` 代码 / `98ba64c` 文档 / `1f72f8d` 折入轮（普通追加、未 amend）。
  审核方独立复验：临时库迁移 up/down/up（24→23→24 张表、DDL 恰好 8 列无预留列、两条 CHECK
  各插非法行均被拒、DDL 列集合 == ORM 列集合）；合并后 main 上 head = `0024_dictation_sheets`、
  业务表 23 张、守卫+默写+备份 36 passed；全量 pytest **954 passed**（施工方 410.16s + 审核方
  595.74s 同数）；ruff 全仓绿；行尾守卫 5 passed；CRLF 普查仍仅 TSV；生产库 mtime 早于交付时间
  （"浏览器金路径走 scratch 数据目录、真实库零触碰"属实）。一处观察记一笔不算缺陷：
  `item_ids` 存非法 JSON 文本时 DB 层不拦，约束完全在服务层。
  审核方自主变异**八靶**（施工方自证之外的目标）：折入前——放开"一卷一学科"红、`ensure_open`
  空函数化红、模型+迁移同时预留 `audio_path` 列红（**"接口预留禁止"确有守卫**）、响应模型加
  `answer` 字段红、`MAX_SHEET_ITEMS` 调大**全绿（= 守卫缺口，触发折入）**；折入后——上限常量调大红、
  `>` 写成 `>=` 红、`COUNT_TABLES` 删新表红、`_table_counts` 保留键但值恒 0 红
  （证明 manifest 断言测的是计数值而非"键存在"）。全部还原 sha256 一致、工作区干净。
- **教训一条（非卡面编号，已泛化进 `AGENTS.md §8`）**：原上限测试用 `MAX_SHEET_ITEMS ± 1` 推导边界，
  常量一动测试跟着漂 → 变异全绿。§19-L 纪律①"断言右侧字面钉死、不从被测文件反算"此前只在
  **数据字面**场景执行过，本次在**边界常量**上复发；折入已改为手写字面值（`== 200` + 200/201 两侧）。

### P3-4b 听写音频线（卷级挂接 + 目录扫描 + index 化播放端点 + 听写卷面隐藏提示；零新依赖、零联网）
- **背景（审核方 2026-11-21 读盘实测，①–⑪ 均可复现）**：
  ① `data/` 现有 `ai-raw/ backups/ backups_tmp/ inbox/ uploads/`，**无 audio 目录**；
     原生形态 `wengu-api/data/` 另有 `ai-cache/`。
  ② `git check-ignore -v` 实测：`data/audio/*` 命中 `.gitignore:35 data/`，
     `wengu-api/data/audio/*` 命中 `.gitignore:38` → 两种运行形态天然不进 git，无需新增忽略规则。
  ③ `backup.py:227-232` 只打包 `data_dir/uploads`、`data_dir/seeds_local`、`inbox`、
     `app-config.json` + DB 快照 → `data_dir/audio/` **由构造不进备份**（但需守卫防漂移）。
  ④ 媒体服务唯一先例 = `GET /api/mistakes/{mistake_id}/images/{index}`（`api/mistakes.py:561-587`）：
     index 化 URL（不含文件名）、只解析 `uploads_dir` 内文件、bytes + 正确 Content-Type +
     `Cache-Control: no-store`；404（`MistakeNotFound`/`ImageNotFound`）与 422 `{message, code}`
     （`ImageError`）分层。
  ⑤ `main.py` **无 StaticFiles 挂载**、`vite.config.ts:13-18` 只代理 `/api` → 音频必须走 `/api`
     端点返回 bytes；引入 StaticFiles 会同时改变图片与上传面的暴露方式，属越界改动。
  ⑥ 校验先例 `services/mistake_images.py:30-70`：`MAX_IMAGE_BYTES`、`ALLOWED_MIME`、
     `_sniff()` 只看魔数不看扩展名/声明类型、`_resolve_within_uploads()` 用 `is_relative_to` 拦越界。
  ⑦ 配置先例 `core/config.py:53-60`：`inbox_path` / `uploads_dir` 均为 `data_dir / "<子目录>"` 的
     `@property` → 新增 `audio_dir` 同构，不引入新环境变量（`WENGU_DATA_DIR` 已能整体搬迁）。
  ⑧ `services/dictation.create_sheet(item_ids, unit, created_by, today)`；`dictation_sheets` 现有
     **8 列、无音频列**（审核方 M4 变异验过加列会红，确认 P3-4 未预留）；`unit` 缺省取条目公共单元、可空。
  ⑨ 上限常量先例：`runtime_config.py:31-41` `DEFAULT_*`/`MAX_*` 成对 + `SEED_GRADE_CEILINGS`；
     `dictation.py:34-35` `MAX_SHEET_ITEMS = 200` / `MAX_LIST_LIMIT = 200`。
  ⑩ 扫目录先例：`inbox.py:294-306` `sorted(inbox_dir.glob("*.json"))` + `_unique_target()` 防重名。
  ⑪ **产品要点（审核方自查发现）**：听写卷面若照旧印 prompt，练习退化成抄写——挂音频的卷必须隐藏提示，
     且该切换要能在**纯函数层**断言（本仓前端无 DOM 设施，见 P3-4 第 29 次卡面缺陷）。
- **六条定案（2026-11-21 决策人全按 A 拍板，不要重开）**：
  ① 音频由家长手动放入 `data/audio/`（Docker 形态即宿主机 `./data/audio/`），**本票不做上传端点**；
     触发条件 = 手动放文件确实成为负担，届时另票做上传（等于把 `mistake_images` 再写一遍）；
  ② 播放端点**孩子区可读**（与"孩子区读取原题图"同构；听写必须让孩子听）；
  ③ 格式白名单 `mp3 / m4a / wav`，**魔数嗅探**（`ID3`/帧同步、`ftyp`、`RIFF…WAVE`），
     扩展名与嗅探不一致即拒；
  ④ 挂接 = `dictation_sheets.audio_ref`（可空 TEXT，存文件名），一卷一音频，默写卷留空；
     不提供改挂端点、不做多音频、不逐词对时间戳；
  ⑤ `MAX_AUDIO_BYTES = 64MB`、`MAX_AUDIO_LIST = 500`（列表截断并报 `truncated`），
     硬常量，**不进 UI 配置**（无消费方）；
  ⑥ 有 `audio_ref` 的卷面**只印序号 + 空行、不印 prompt**。
- **任务**：
  1. `core/config.py` 加 `audio_dir` property（`data_dir / "audio"`），docstring 写明
     "第三方课程音频，绝不进 git、不进备份包（设计文档 §19-G-3 定案二同一条理由）"。
  2. 新 `services/dictation_audio.py`：纯函数层（文件名合法性、`_sniff_audio()` 魔数判定、
     列表排序与截断、`resolve_within_audio_dir()` 用 `is_relative_to`）+ 输入层（扫描 `audio_dir`）。
     **目录不存在 → 返回空列表，不是错误**（家长还没放文件是常态）。
  3. 迁移 `0025_dictation_sheet_audio_ref`（可逆）：`dictation_sheets` 加 `audio_ref TEXT NULL`；
     含 up/down/up 测试；**列集合断言写手写字面值**（9 列全名逐个列出，不许用"原列 + 1"推导——
     AGENTS §8「边界常量必须字面钉死」同源纪律）。
  4. 端点：`GET /api/recitations/audio`（列出合法音频：index + name + size + `truncated` 标志）；
     `GET /api/dictation/sheets/{id}/audio`（**孩子区可读**，bytes + 嗅探出的 media_type +
     `Cache-Control: no-store`；卷无 `audio_ref` → 404 稳定码；文件被移走 → 404 稳定码，
     **不得 500**）；`POST /api/recitations/sheets` 增可选 `audio_ref`，服务层校验文件在
     `audio_dir` 内且嗅探通过，否则 422 `{message, code}`。**不提供改挂端点**。
  5. 前端：生成卷弹窗加"听写音频（可选）"下拉（来自列表端点）；`PrintDictationSheetPage` 按
     `audio_ref` 切换卷面；卷详情（家长区与孩子区）加 `<audio controls>` 指向播放端点
     ——浏览器原生控件自带时长/进度，**不解析元数据、不引入 ffprobe/mutagen**。
  6. 打印数据准备抽纯函数（如 `build_print_rows(detail)`）：有 `audio_ref` 时行内**不含 prompt 字段**、
     无 `audio_ref` 时含——两侧都用手写字面断言。
  7. 备份面守卫：`tests/integration/test_backup_api.py` 加断言——在 `data_dir/audio/` 放一个假音频后
     导出备份，zip 清单**不得含 `audio/` 任何条目**（防将来把音频塞进 uploads 或改打包根）。
  8. 文档：`CHANGELOG.md` 一条；设计文档 §5.9 注记（听写线落地 = 卷级挂接 + 目录扫描 + index 化播放；
     不逐词时间戳、不做上传、不解析元数据；课程音频不进 git/备份）；
     `docs/STATUS.md` 交付区新增本票条目（AGENTS §8 补严）。
- **DoD（逐项贴输出，全部可同时成立）**：
  - 迁移 0025 up/down/up 绿；列集合手写字面断言（9 列）绿；
  - 嗅探三格式各造一个真字节头样本通过；**伪装样本必拒**（`.mp3` 实为 PNG 头 → 422）；
  - 听写卷面两侧断言：有 `audio_ref` 的行集合无 prompt、无 `audio_ref` 的行集合含 prompt；
  - 播放端点：无 `audio_ref` → 404 稳定码；文件缺失 → 404 稳定码（不得 500）；
    正常 → 200 + media_type + `Cache-Control: no-store`；孩子区可读（无 parent 门槛）实测；
  - 备份清单不含 `audio/`（实跑导出贴清单）；
  - `git check-ignore -v` 两形态实测贴出（确认无需新增忽略规则）；
  - 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，当前 **954**，如实报新数）；
    `ruff check --no-cache .` 全仓绿；行尾守卫 5 条仍绿；前端 `tsc` + `node --test` + `build` 绿；
  - 零新依赖、零联网、不动 `app/judge/**`、不改 `decide()`/`VERDICTS`、不碰 `seeds/**` 与错题写入路径。
- **白名单**：`wengu-api/app/core/config.py`、`wengu-api/app/services/dictation_audio.py`（新）、
  `wengu-api/app/services/dictation.py`、`wengu-api/app/models/recitation.py`、
  `wengu-api/migrations/versions/0025_dictation_sheet_audio_ref.py`（新）、
  `wengu-api/app/api/recitations.py`、`wengu-api/tests/unit/test_dictation_audio.py`（新）、
  `wengu-api/tests/unit/test_dictation.py`、`wengu-api/tests/integration/test_dictation_api.py`、
  `wengu-api/tests/integration/test_backup_api.py`、`wengu-web/src/api/endpoints.ts`、
  `wengu-web/src/api/types.ts`、`wengu-web/src/pages/RecitationsPage.tsx`、
  `wengu-web/src/pages/PrintDictationSheetPage.tsx`、`CHANGELOG.md`、
  `docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`docs/STATUS.md`。
  （已核：本票加**列**不加**表**，`test_migrations.py` 的 `EXPECTED_TABLES` 与表数断言不受影响，
  故不在白名单——这是 P3-4 第 28 次缺陷的反向检查，不是遗漏。）
- **禁止**：上传端点 / multipart；引入 StaticFiles 挂载；改挂、多音频、逐词时间点；
  把音频放进 `uploads`（会被备份打包）或写进仓库任何位置；解析音频元数据或引入 ffprobe/mutagen；
  把 `MAX_AUDIO_*` 做成 UI 配置；预留其他列；引入 jsdom/testing-library；`--skip`/`xfail`；
  动 `decide()`/`VERDICTS`/错题写入路径。
- **审核方侧动作（不进施工方白名单）**：`PRIVATE-DO-NOT-SYNC.md`（仓库外）扩一条——第三方课程音频
  `<data_dir>/audio/` 不进备份、不外发，性质同 K12-KGraph（**是许可问题不是隐私问题**）。
- **状态：已合并（2026-11-21，PR#73 squash → main `c24fb8d`；原分支已删，`ls-remote` 复核为空）**。
  两个 commit：`7a98b8c` 代码（15 文件）/ `325bbf7` 文档（3 文件）。
  审核方独立复验：全量 `pytest -q` **976 passed / 647.70s / EXIT=0**（= 954 + unit 16 + integration 6）；
  `ruff check --no-cache .` 全仓绿；行尾守卫 5 passed（首跑 2 failed 为沙箱 git 访问抖动造成的假红，
  已用"本票 18 个改动文件逐个 `tr -dc '\r' | wc -c` 全为 0"独立证实真实状态）；迁移+音频子集 7 passed；
  新前端测试 `node --test` 直跑 4 pass / 0 fail；合并后 main 定向六文件复跑 **81 passed / 75.42s**。
  分发面三项自查：`git ls-files` 全仓零 `.mp3/.wav/.m4a` 样本；`git check-ignore -v` 两形态命中
  `.gitignore:35`/`:38`（零新增规则）；`print.css:283-285` 实测 `@media print { .print-toolbar {
  display: none !important } }` —— 播放器屏幕可见、落纸隐藏，与施工方第 6 条说法一致。
  生产库未被触碰：`data/wengu.db` mtime 18:45、`wengu-api/data/wengu.db` mtime 10-28，均早于交付
  00:57；演示件在仓外 `_p34b_demo/data/audio/`。
  审核方自主变异**五靶全红**：M1 `MAX_AUDIO_BYTES` 64MB→128MB（字面钉死生效）、M2 嗅探末尾兜底放行
  未知字节（伪装件必拒生效）、M3 播放端点不再映射 `AudioNotFound`→404（"不得 500"有牙）、
  **M4 备份打包根加 `audio/` → 红**（正是本票最担心的那条漂移，`test_backup_excludes_audio_dir` 兜住）、
  M5 前端 `listening` 恒 false → 红。四文件还原 sha256 逐个一致、工作区干净。
  CI `api / web / transcribe` 三绿、`MERGEABLE`；**web 作业补上了审核方本地跑不了的前端三件套**
  （沙箱内 `npm` 命中的是 WSL"未安装分发版"占位程序）。
- **第 30 次卡面缺陷（审核方，白名单反推第 6 次漏）**：任务 6 要求"打印数据准备抽纯函数 + node 测试"，
  白名单却没含新前端模块的落点（`wengu-web/src/pages/dictationPrint.ts`、
  `wengu-web/tests/dictationPrint.test.ts`）。施工方循 `mergeSelection.ts` 先例新建并主动上报，
  **追认保留**。教训并入既有纪律：反推白名单时必须把"新抽象层会落在哪个新文件"一并列出，
  不能只列被改的既有文件。
- **遗留（本票不处置）**：
  ① **ORM 逐字对照降级**——0025 是 `ALTER TABLE ADD COLUMN`，`sqlite_master` 文本与 `CreateTable`
     编译产物不再逐字相等，原 0024 的 ORM 对照被移除（理由成立），现由"9 列手写字面"承接，
     **只覆盖列名 + 可空性，类型与 `server_default` 无人对照**。审核方自查证实 `dictation_sheets`
     在"alembic 建库"与 `Base.metadata.create_all()` 两条路径下结构化完全一致，故一条**限定本表**的
     结构等价测试可行且当前即绿 —— 处置：写入 `STATUS.md §7` 第 19 条，**下一张碰到
     `dictation_sheets` 的票必须顺带补**；若长期无此类票，再单开一张纯测试小票。
  ② 播放路径前缀 `/api/dictation/...` 与 `/api/recitations` 不一致，统一属独立重构、无消费方不动。

### P3-5 语文客观并入（题池全收 + 转录侧"不进本"闸门 + 语文闭环证据测试；零新依赖、零迁移）
- **背景（审核方 2026-11-21 读盘实测，①–⑦ 均可复现）**：
  ① 语文题池已在仓库：`seeds/data/questions.json` 语文 **2732 题**，`topic_id` 命中 seed
     **2732/2732（0 孤儿）**，全部 `type=choice`、全部 4 选项、全部有 `answer` 与 `verify`、无配图；
     真实装载 `app/seed/bank.py load_bank()` 实测 **verified 2732 / 2732 = 100%**、`dropped == {}`。
  ② 题面形态：初中语文题 prompt **中位 16 字 / p90 26 字 / 最长 44 字**，`≥120 字` **0 题**，
     "阅读下面材料/文段"触发词 **0 命中** → domain 标"阅读理解/习作基础"的 480 道初中题实为
     独立短选题。**按 domain 设闭环闸门会误伤这 480 题**——决策轮原口径 A3 由此修订为 A3′
     （定案见设计文档 **§19-M 定案一**）。
  ③ 判分侧零缺口：`app/judge/normalize.py:272 _parse_choice()`、`:316-319` 单选比对、
     `:355-360` 支持 `unordered` 集合比对 → **本票不写任何判分代码**。
  ④ 转录侧闸门缺失：`docs/templates/doubao_transcribe_v1.md`（frontmatter `version: 2`）第 32 行
     只有"做对的题、空白没做的题、与题目无关的页眉页脚一律不转录"，**没有一句"作文/需整篇材料的题
     不转录"**；`subject` 枚举（第 36 行）已含语文。
  ⑤ 版本耦合由 CLI 探针守护而非 pytest：`transcribe/validate.py:382` 比对
     `fm_template.version == contract["template"].version`，不一致报 DRIFT；审核方 grep 证实
     **pytest 侧无模板版本断言** → DoD 必须实跑 `selfcheck` 贴输出。
  ⑥ UI 现状：`RecitationsPage.tsx:440` 标题「英语背诵」、`:84/:90` 默认 `subject="英语"`，
     但 `:59-66 IMPORT_SUBJECTS` 已含 语文/历史/道德与法治/道法/生物/地理；`:706` 「从错题抽词（英语）」；
     `services/recitation.py:51 CANDIDATE_SUBJECT = "英语"`。
  ⑦ 证据缺口：生产库 `data/wengu.db` 错题 3 条 `primary_topic_id` **全 NULL**、最近事件 2026-10-30；
     `wengu-api/data/wengu.db` 错题 2 条同样全 NULL → **语文闭环从未有过一条真实或测试证据**。
- **四条定案（不要重开；出处 = 设计文档 §19-M 定案一）**：
  ① **题池全收**：语文 choice 题与数学/英语走同一条检索与判分链路，**运行时不加任何按 domain
     或按学科的闭环白名单**；
  ② **"不进本"闸门落在转录模板指令**：作文/续写/仿写/看图写话/需整篇材料才能作答的阅读理解大题
     一律不转录 → 天然不进错题本、不排复习，只留外部讲解与成长记录；
  ③ 改模板语义**必须递增 `version`（2→3）并同步契约 `template.version`**，
     Skill 只引用不内嵌（`transcribe/skills/wengu-transcribe/SKILL.md:44` 既有纪律）；
  ④ 抽词线保持英语专用（`CANDIDATE_SUBJECT` 不动）：语文古诗文是整句/整篇默写，
     词形抽取不适用，§5.9 亦无此要求。
- **任务**：
  1. `docs/templates/doubao_transcribe_v1.md`：在「只转录这些题」段内新增"不进本"口径
     （作文/续写/仿写/看图写话/需整篇材料或整段语境才能作答的阅读理解大题 → 一律不转录；
     独立可判分的短小题——课文常识、字词、拼音、古诗文理解选择等——照旧转录），
     frontmatter `version: 2 → 3`，正文标题与"唯一真源"表述同步 v3。
  2. `transcribe/contract/ingestion_v1.json`：`template.version` 同步为 3，其余字段一律不动。
  3. `transcribe/README.md`：两处示例 `--template-version 2` → 3（第 44、63 行），
     并把第 113 行"模板 v2 / 契约 1 → DRIFT"示例表更新为 v3 口径（不得留过实文档）。
  4. 新集成测试 `wengu-api/tests/integration/test_yuwen_closed_loop.py`：夹具走**全链**——
     语文转录报文 → `POST /api/imports` → 草稿 → 核对页确认（挂 `cnc_` 语文主考点）→ 排期 →
     到期 → 组卷抽到语文 choice 题 → `judgeAnswer` 判分 → 事件与掌握度更新；断言
     **语文与数学走同一条代码路径、零学科分支**（同一夹具仅换 `subject`，行为等价），
     并断言"不进本"面**不产生任何 `mistakes` 行**（靠转录侧不产出，不靠代码过滤）。
  5. `wengu-web/src/pages/RecitationsPage.tsx`：标题「英语背诵」→「背诵与默写」；默认 `subject`
     保持"英语"；在抽词卡片补一句"语文古诗文请用手填 / 批量导入整句，抽词只适用于英语词形"；
     **不改 `IMPORT_SUBJECTS` 枚举、不改抽词逻辑**。
  6. 文档：`CHANGELOG.md` 一条；设计文档 §5.9 表下加注（"不进本"闸门实现位置 = 转录模板 v3；
     按 domain 切闸门已被实测否证，见 §19-M 定案一）；`docs/STATUS.md` 交付区新增本票条目。
- **DoD（逐项贴输出，全部可同时成立）**：
  - `python transcribe/validate.py selfcheck`（或既有等价入口）**18 OK / 0 DRIFT / 0 WARN**，
    其中模板-契约版本那条必须显示 **v3 == 3**；
  - 模板与 README 不再残留 `--template-version 2` / `version: 2`（grep 输出为证）；
  - 新集成测试绿，贴出"语文错题入本 → 排期 → 组卷 → 判分"四步的关键断言行；
  - 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，当前 **976**，如实报新数）；
    `ruff check --no-cache .` 全仓绿；行尾守卫 5 条仍绿；前端 `tsc` + `node --test` + `build` 绿；
  - **零迁移、零新依赖、不动 `app/judge/**`、不动 `app/seed/**`、不加任何按 domain/学科的代码闸门**；
  - `seeds/data/*` 逐文件 sha256 不变（本票不重跑 import——§19-G-3 定案二与第 27 次卡面缺陷纪律）。
- **白名单**：`docs/templates/doubao_transcribe_v1.md`、`transcribe/contract/ingestion_v1.json`、
  `transcribe/README.md`、`wengu-api/tests/integration/test_yuwen_closed_loop.py`（新）、
  `wengu-web/src/pages/RecitationsPage.tsx`、`CHANGELOG.md`、
  `docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`docs/STATUS.md`。
  反推依据：模板与契约由 `validate.py:382` 硬耦合 → 两文件必须同改；README 两处示例 + 一处
  DRIFT 表引用版本号；pytest 侧无版本断言（已 grep 证实）故不列其它测试文件；
  Skill 文件只引用 `template_ref` 不内嵌版本号，**不改**（改了反而违反"不要内嵌"纪律）。
- **禁止**：在 `bank.py`/`quiz.py`/`review.py`/`subjects.py`/`ingestion.py` 里加按 domain 或按学科的
  闭环白名单；改 `CANDIDATE_SUBJECT`；重跑 import 或改 `seeds/data/*`；改判分器与 AST 沙箱；
  把模板正文内嵌进 Skill；只改模板不改契约版本号（必 DRIFT）；只改契约不改 README 示例；
  用 `--skip`/`xfail`；**把"语文题池 100% verified"表述成"语文闭环已验证"**——
  验证由本票第 4 项交付，交付前不得这样写。
- **后续（同批登记，暂不投）**：语文默写（古诗文背默）复用 P3-4/P3-4b 卷线，
  `create_sheet` 要求一卷一学科、学科取自条目 → 语文条目今天已可用，**本票不动那条线**；
  若试用后发现家长不会用，另开一张纯 UI 引导票。
- **卡面补强（折入轮 2026-11-21；登记第 31 / 32 次卡面缺陷，均归审核方）**：
  **第 31 次 = 卡面任务 1 只写了"新增不进本口径"，没要求给指令级约束配回退守卫**。
  审核方变异 M-C 证实：把模板那两条"不进本"bullet 整行删掉，`selfcheck` 与 pytest **全部仍绿**
  ——闸门是纯文本承诺，谁都能静默删掉。折入补一条字面守卫测试。
  **第 32 次 = 卡面把 v4 的靶子写小了**：原话是"模板 `suggested_topic_id` 未列 `cnc_`"，
  实读发现模板硬编码了**两张**过时清单——第 44 行前缀枚举只 3 个（`topics_junior.tsv` 实测 1267 行、
  覆盖 9 个学科 9 个前缀：`cnm_` 315 / `cne_` 257 / `cnc_` 189 / `cnh_` 134 / `cnd_` 110 /
  `cnp_` 92 / `cnb_` 66 / `cng_` 59 / `cnk_` 45），第 38 行 subject 枚举只 5 科
  （历史/道德与法治/生物/地理 不在内，而 seeds 已有 10 科）。只补 `cnc_` 治不了根，下次扩科照样腐化。
  后端 `ingestion.py:20 FIELD_LIMITS["subject"] = 20` 只做长度校验、**无枚举闸门**，
  故删除硬编码属零代码改动。v4 因此改为"两处硬编码清单删除、《知识点目录》为唯一真源"，
  并在示例 JSON 里新增一条语文条目（few-shot 才是模型实际模仿的对象）。
  **审核方四靶变异结论**：M-A 装载层加按 domain 的闭环闸门 → 红（定案①有守卫）；
  M-B 契约 `template.version` 3→2 → 红（selfcheck 16 OK / **2 DRIFT**，探针有牙）；
  M-C 删模板两条口径 → **绿（缺口，即第 31 次）**；M-D 前缀枚举加 `cnc_` → 绿（未被锚定，v4 零风险）。
- **折入白名单扩充（仅此折入用途）**：`wengu-web/src/lib/nav.ts`、
  `wengu-web/src/pages/PrintDictationSheetPage.tsx`、`wengu-api/tests/unit/test_template_gate_literals.py`（新）、
  `docs/specs/architecture/StudyDesk-设计说明文档-v2.md`、`docs/STATUS.md`。
  折入 = 分支上一个普通追加 commit（不 amend `896e6ed`），`git diff --name-only` 恰好 9 文件。
  现状表述同步只许改四处（设计文档第 152、1009 行与 STATUS 第 421、1357 行的"模板 v3"），
  **历史条目一律不得改写**（CHANGELOG 旧行、STATUS 第 1383 行 P5-8、模板"v2 内收口未升版"句）。
- **状态：已合并（2026-11-21，PR#74 squash → main `1478476`；原分支已删，`ls-remote` 复核为空）**。
  三个 commit：`19ee321` 功能 / `896e6ed` 文档 / `8d7c762` 折入轮（普通追加、未 amend）。
  审核方独立复验：`selfcheck --strict` **18 OK / 0 DRIFT / 0 WARN** 且两条版本项均为 **模板=4 契约=4**；
  `validate.py evals` **13/13**；全量 `pytest -q` **983 passed**（= 979 + 新字面守卫 4，施工方与审核方
  双实跑同数）；`ruff check --no-cache .` 全仓绿；合并后 main 上行尾 5 + 字面守卫 4 + 语文闭环 3 +
  转录回归 + 契约锚定 = **35 passed**；CRLF 普查仍仅 TSV。三条 grep 零命中：无 `version: 3` /
  `--template-version 3` 残留、`wengu-web/src` 无「英语背诵」、模板内两张硬编码清单字面值已消失。
  **后端零改动**：`git diff --name-only` 不含 `wengu-api/app/**`。
  示例挂点质量抽查：`cnc_j004` 回目录实读 = `语文/7/上/古代诗歌四首/古诗文积累/七年级上册 第1单元`，
  与示例题面《观沧海》"竦峙"**真实对应**——不是随手填的 id，说明施工方读了目录。
  审核方自主变异**六靶**：F1 删一条"不进本"口径 → 守卫①红；F2 写回多加了"历史"的学科枚举 → 守卫②红；
  F3 契约 `template.version` 4→3 → selfcheck **16 OK / 2 DRIFT** 非零退出；
  F4 示例 `cnc_j004` 换成 `cnm_042` → 守卫④红；F5 只改 frontmatter 为 5 → 守卫③红 + DRIFT；
  **F2b 写回"无空格排版"的学科枚举 → 绿（已知局限，见下）**。全部还原 sha256 一致、工作区干净。
- **已知局限（记录，不返工）**：守卫②是**字面串**断言，只拦"原格式写回/在原格式上追加"（F2 已证），
  拦不住换排版的变体（F2b）。要拦变体须用正则解析清单结构——等于给一条文档守卫加台机器，
  按反过度工程不做。替代防线：卡面纪律"新增学科/前缀清单必须走《知识点目录》"。
- **施工方四条需复核点的裁定**：① §19-M 改"v2→v3 引入、v4 沿用"——认可（历史与现状都在）；
  ② STATUS 交付条目仍写 979/新增 3——认可它不擅扩 scope，最终态由本留痕更新为 **983 + 4 条字面守卫**；
  ③ 守卫④判定宽度——认可；④ 守卫③出现 2 条 DRIFT——认可（卡面只要求出现 DRIFT 且非零退出）。
- **环境事实（审核方侧，第三次复发，固化）**：沙箱里跑 `test_repo_eol.py` 会因内部 `git` 子进程
  读不到 `safe.directory` 而**稳定假红**（本轮两次：首跑 2 failed，复跑 5 passed）。
  今后凡复跑该守卫必须带 `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=<repo>`
  注入，且**不得只看包装器退出码**——后台任务的 exit 1 可能来自"归还文件属主"步骤而非测试本身；
  判定一律用第二种独立方法钉死（逐文件 `tr -dc '\r' | wc -c` 计数 + 复跑）。

### P5-19 迁移与 ORM 的结构等价测试（限定 `dictation_sheets`；纯测试、零生产改动）
- **背景（审核方 2026-11-21 实测，①–⑥ 均可复现）**：
  ① 欠账来历：P3-4b 的 0025 用 `ALTER TABLE ADD COLUMN` 加 `audio_ref` 后，`sqlite_master` 文本与
     ORM `CreateTable` 编译产物不再逐字相等，原 0024 的 ORM 逐字对照被移除，现由
     `test_0025_audio_ref_up_down_up`（列名 + 可空性手写字面）与
     `test_sheet_model_and_view_expose_audio_ref`（模型侧 9 列字面）承接——
     **类型与 `server_default` 已无人对照**（登记于 `docs/STATUS.md` §7 第 19 条）。
  ② 审核方自查（alembic `upgrade head` 建库 vs `Base.metadata.create_all()` 建库，结构化比对）：
     **`dictation_sheets` 两侧完全一致**——列集合
     `{id, created_on, created_by, subject, unit, item_ids, status, recorded_on, audio_ref}`，
     类型 INTEGER/DATE/TEXT 一致、可空性一致、`status` 默认值 `'open'` 一致、主键一致、
     CHECK 名 `{ck_dictation_sheets_status, ck_dictation_sheets_recorded_on}` 一致。
     → 本测试**今天即绿**，是补守卫不是修 bug。
  ③ **不可扩面**：同一脚本对 23 张表比对发现约 **30 处历史性差异**，形态是迁移 DDL 有
     `server_default`（`attempts.created_at` = CURRENT_TIMESTAMP、`bank_drafts.status` = 'draft'、
     `concepts.status` = 'suggested' 等）而 ORM 模型未声明。运行期只走 alembic，暂不影响正确性；
     **扩到全仓会把历史欠账一次性变红**，属另一件事（未立项）。
  ④ 两条技术约束（实测得出，卡面必须遵守）：`inspect().get_check_constraints()` 在 SQLite 下
     返回的 **sql_text 是空串**，只能比 CHECK **名字**；`sqlite_master` 文本两侧**必然不同**
     （ALTER 追加），**禁止比文本**。
  ⑤ 注册面实测：`import app.models` 即注册全部 23 张表（含 `dictation_sheets`，虽然
     `models/__init__.py` 只显式导入 `RecitationItem`/`RecitationReview`）；
     `Base` 在 `app/core/database.py:21`，审核方曾误用 `from app.models import Base` 得 0 表。
  ⑥ 现有工具函数在 `wengu-api/tests/integration/test_dictation_api.py`：`_alembic_config`(:52)、
     `_tables`(:614)、`_master_ddl`(:623)。**本票不 import 别的测试文件**，自带小工具。
- **三条定案（不要重开）**：
  ① **只比 `dictation_sheets` 一张表**，不得扩到全仓（理由见背景③）；
  ② 比较**结构化六项**：列名+类型+可空性+默认值 / 主键 / CHECK 名 / 外键 / 唯一约束 / 索引；
     禁止比 `sqlite_master` 文本、禁止只比列名（那是弱化既有覆盖）；
  ③ **禁止 skip 语义**：任一侧没建出 `dictation_sheets` 就必须失败并说明是哪一侧——
     防止"两边都空所以相等"的假绿。
- **任务**：
  1. 新文件 `wengu-api/tests/integration/test_schema_equivalence.py`：
     - 前置断言两侧都建出目标表（`create_all` 侧必须先 `import app.models`）；
     - 一个纯函数 `describe_table(inspection, name) -> dict`，返回六项结构化指纹；
     - 断言两库指纹相等，**不等时必须打印差集**（列名级），禁止裸 `assert a == b` 无信息失败；
     - 表名以常量 `TABLE = "dictation_sheets"` 写明范围，docstring 指向 STATUS §7 第 19 条。
  2. 文档：`CHANGELOG.md` 一条；`docs/STATUS.md` §7 第 19 条**更新处置状态**
     （从"下一张碰该表的票顺带补"改为"已由 P5-19 单独补齐；全仓 30 处历史差异仍未处置、未立项"）
     + 交付区新增本票条目。
- **DoD（逐项贴输出，全部可同时成立）**：
  - 新测试绿（今天即应绿，两侧结构本就一致）；
  - **变异自证两靶都必须 RED→GREEN，且失败信息要指到具体列**：
    ① 只给 ORM 模型加一列、不加迁移 → 本测试红；② 只给迁移加一列、不改 ORM → 本测试红；
    两靶各自还原后 sha256 一致，交付 diff 里不得出现模型或迁移的残留改动；
  - 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，当前 **983**，如实报新数）；
    `ruff check --no-cache .` 全仓绿；行尾守卫 5 条仍绿；
  - **零生产代码改动**：`git diff --name-only` 不含 `wengu-api/app/**`、不含 `migrations/**`；
    零迁移、零新依赖、零联网。
- **白名单**：`wengu-api/tests/integration/test_schema_equivalence.py`（新）、`CHANGELOG.md`、
  `docs/STATUS.md`。**只有三个文件**——本票不碰模型、不碰迁移、不碰前端。
- **禁止**：扩到全仓 23 表；比 `sqlite_master` 文本；把六项指纹弱化成列名；
  用 `skip`/`xfail`/`try-except 跳过`处理"表不存在"；import 其它测试文件的私有工具函数；
  顺手去修背景③那 30 处历史差异（未立项，动了就是越界）；
  把 STATUS §7 第 19 条删除而不是更新为已补状态。
- **裁定记录**：本票源自审核方自查（`D:\MyProducts\StudyDesk\_p34b_schema_equiv_probe.py`，可复跑），
  不是施工方缺陷；它是当前队列上唯一"今天做比明天做便宜"的一张。
- **状态：已合并（2026-11-21，PR#75 squash → main `e951e80`；原分支已删，`ls-remote` 复核为空）**。
  单 commit `8e679a6`，3 文件恰等白名单，零生产代码改动。
  审核方独立复验：新守卫绿；`ruff check --no-cache .` All checks passed；全量 `pytest -q`
  **984 passed / 569.30s / EXIT=0**（= 983 + 1，双实跑同数）；行尾守卫 **5 passed**
  （首跑 2 failed 为沙箱 git 抖动假红，**第四次复发**，已用两种独立方法钉死真实状态：分支 3 文件
  逐个 CR=0 + HEAD blob 层 CRLF 普查仅 `topics_junior.tsv`）；合并后 main 上守卫+行尾+迁移回归
  25 passed、`selfcheck` 18 OK / 0 DRIFT / 0 WARN。
  审核方自主变异**四靶**：M2 ORM `audio_ref` `Text`→`Integer`（不动迁移）→ **红**，类型真在尺子上；
  M3 迁移 `status` 的 `server_default` `'open'`→`'OPEN'`（不动 ORM）→ **红**，默认值真在尺子上；
  M4 从指纹里删掉 `check_names` → 绿（元守卫不守自己，符合预期，不要求补）；
  M1 注释掉 `import app.models` → 绿——**根因是审核方靶子设计失误，非守卫缺陷**：
  `tests/conftest.py:33-35` 模块级 `from app.seed.state import …` / `from app.services.bank import …` /
  `from app.services.session import …` 已把 23 张表注册进 `Base.metadata`，
  所以"两边都空所以相等"这条假绿路径在本仓测试环境下**结构上不存在**，
  那条前置断言属**冗余保险而非失效防线**（实测 `Base` 单独导入时 metadata 0 表、
  `import app.models` 后 23 表；alembic 迁移脚本与 `env.py` 均不 import 模型）。
- **第 33 次卡面缺陷（审核方，白名单/必改清单反推第 6 次漏）**：施工方把 STATUS 第 462 行
  「当前待审」指针从"P3-5（已交付）"翻正为"P5-19"，超出卡面任务 2 的字面范围——但原句与头部
  "P3-5 已合并 PR#74"**自相矛盾**，属我上一轮留痕的残留。**追认该改动**，缺陷记我：
  卡只列了"§7 第 19 条 + 交付区条目"，没把 STATUS 内其它"当前待审/指针"类现状句列入必改清单。
  这是第 28 次（漏 `test_migrations.py`）、第 30 次（漏新前端模块落点）之后**同一类反推漏项的
  第三次复发**，已固化为 `AGENTS.md §8`「状态类票的必改清单」，本票留痕即按该规则执行
  （头部三行 + 交付区条目 + 队列指针三处同翻）。
- **裁定记录**：② 头部基线与全量数由本留痕收口（正确，不属施工方 scope）；③ isort 把 `app`
  归第三方块——认可，不改配置是对的（动配置会波及全仓排序）；④ 默认值取 inspector 原始串、
  两侧同尺——认可，与"对照库结构而非映射配置"的定位一致。

---

### P5-20 文档"当前态"自述与盘上事实对齐 + 字面守卫（纯文档订正 + 一条单测；零生产改动、零迁移）

- **状态**：**待投**（基线已就绪——P6-2 于 2026-11-25 合并 PR #76 → main `10f731b`，卡内行号
  即按合并后的 main 实读；开工时仍以当时 `origin/main` 复核锚点）。
- **背景（第 34 / 35 次卡面缺陷的根治票，审核方 2026-11-25 实测）**：
  "文档自述的 alembic head / 业务表数"与盘上事实不一致，已**第三次复发**——P3-4 翻过一次、
  P6-2 又翻一次（`目录结构.md` 0021→0026），但**全仓普查从未做过**：P6-2 卡面的必改清单
  只列了 `目录结构.md` 一处，实际盘上另有三处旧自述。止血不改根治 = 每票重新发现一遍。
  本票既翻正现存三处，又留一条会红的守卫，把"文档必须跟随迁移推进"变成 CI 事实。
- **盘上事实（审核方两种独立方法核对，施工方开工时须以当时 `origin/main` 复核）**：
  - 单一 head = `0026_recitation_source`（`alembic heads` 与按 `migrations/versions/*.py`
    解析 revision/down_revision 链推导，两法同数；26 个 revision 文件连成一条线无分叉）。
  - 业务表 23 张（`Base.metadata.tables` 23 项，与 `test_migrations.py` 的 `EXPECTED_TABLES`
    逐字同集）。22→23 的唯一原因是 `0024_dictation_sheets` 新建表；0025 / 0026 均加列不加表。
  - 仍是"当前事实"口吻却写旧值的三处（本票要改；**只认锚点子串、不给行号**——STATUS 每票留痕
    都会让 §1 之后的行号整体位移，实测同一条 §4.8 已从 626 → 644 → 670）：
    `wengu-api/README.md` 目录树的 `├─ migrations/` 行（`# Alembic（head = 0021_pomodoro_sessions）`）、
    `docs/STATUS.md` §4.8 基础设施（`- SQLite WAL + Alembic（head 0023）`）、`docs/STATUS.md` §5.2
    （`- Alembic head \`0023_learning_events_occurred_at\`；**22 张业务表**`）。
  - 已正确、本票要"钉住别退回"的一处：`目录结构.md:88`（P6-2 已翻正 0026）。
- **三条定案（不要重开）**：
  ① **只改"当前态"文档**，历史留痕一律不动——`CHANGELOG.md` / `TICKETS.md` /
    `docs/tooling/qoder-build-plan.md` / `docs/deploy/*.md` / `docs/specs/**` 里的旧 head 串
    是**当时的事实记录**，翻正它等于篡改审计链；真需要口径说明走仓库既有括注先例
    （`README.md` 的 P3-8 / P5-10 尾部「本条为当时的事实记录」，实测该括注先例 2 处）。
  ② 守卫的 head 与表数**必须从盘上派生**（扫 `migrations/versions/` 求唯一 head、
    取 `len(Base.metadata.tables)`），**禁止在测试里写死 `0026_recitation_source` 或 `23`**——
    写死等于每加一条迁移就要改守卫，是把债换个地方欠。派生自证由另一条断言与
    `EXPECTED_TABLES` 交叉制约（两个真源相互制约）。
  ③ 守卫**只扫白名单锚点句、不扫全文**：`docs/STATUS.md` §7 等处含 `业务表 **19 张**`、
    `业务表 19 → **21**` 这类历史证据句，全文扫必假红。
- **任务**：
  1. 翻正三处当前态自述（head 一律写 revision 全名，不写裸 `0026`）；§5.2 那句的括号内
     照既有写法补 0024（新增 `dictation_sheets`，表数 22→23 的唯一来源）/
     0025（`audio_ref` 加列）/ 0026（`source` 加列）三条来历。
  2. 新文件 `wengu-api/tests/unit/test_docs_current_state.py`，风格逐字照
     `tests/unit/test_template_gate_literals.py`（`REPO_ROOT = Path(__file__).resolve().parents[3]`
     + 纯 `read_text(encoding="utf-8")`，**绝不调 subprocess 跑 git 或 alembic**——沙箱内
     `git ls-tree` 会以 dubious ownership 假红，本仓已复发四次）。四组断言见 DoD。
  3. 文档：`CHANGELOG.md` 一条；`docs/STATUS.md` 交付区新增本票 + 头部快照/基线 +
     **§1 内所有「当前待审」指针句一并翻转**（第 33 次纪律）。
- **DoD（逐项贴输出）**：
  - 全量 `pytest -q` 全绿，条数 = 开工基线 + 本票新增条数（基线用
    `venv/Scripts/python.exe -m pytest --collect-only -q` **实取**写进 PR，不照抄卡面数字）。
  - 变异自证四靶各 RED→GREEN、还原后 sha256 逐字节一致，且失败信息要指到具体文件与串：
    ① `目录结构.md` 的 head 改回 `0021_pomodoro_sessions` → 红；
    ② `wengu-api/README.md` 的 `├─ migrations/` 行改成裸数字 `0026` → 红；
    ③ §5.2 的 `23 张业务表` 改回 22 → 红；
    ④ 把 `CHANGELOG.md` 任一条 `head 仍 \`0020_recitation\`` "顺手更新成 0026" → 被反向
    历史留痕断言钉住红。
  - 派生有牙的负向验证：临时往 `migrations/versions/` 放一个 `revision="0027_probe"` /
    `down_revision="0026_recitation_source"` 的空迁移 → 守卫必须红（文档没跟上），
    删除后 → 绿。**临时文件当场删除并 `git status` 复核为空，严禁提交**。
  - 本票零 schema 影响：`alembic upgrade head` 前后 `recitation_items` 的 `sqlite_master`
    dump 一字不变（贴比对输出）。
  - `ruff check --no-cache .` 全仓绿；`tests/unit/test_repo_eol.py` 5 绿；新测试文件 LF + UTF-8 无 BOM。
- **必改清单**：`wengu-api/tests/unit/test_docs_current_state.py`（新增）/ `wengu-api/README.md` /
  `docs/STATUS.md`（§4.8、§5.2、§1 头部、交付区、所有「当前待审」指针句）/ `目录结构.md`
  （锚点措辞若变）/ `CHANGELOG.md`。
- **禁止**：不改任何迁移 / 模型 / 服务代码 / `seeds/**` / `wengu-web/**`；不动历史留痕文件的旧
  head 串；不引入新依赖；不调 git / alembic 子进程；不把 `TICKETS.md:341`、build-plan 各票正文里
  "票内历史描述"的旧 head 当缺陷去改；守卫里不得出现写死的当前 revision 串或表数。
- **残留风险（交付时如实报告）**：守卫只覆盖白名单锚点句，新写的"当前态"句子若不走这些锚点
  格式仍会漏网；将来加迁移时 `docs/STATUS.md` 头部与 §5.2 必须同改两处（守卫会红并指名文件），
  这是**刻意摩擦**、不是缺陷；多 head 分叉会让派生断言炸，属预期报警。

---

## Phase 6 —— 背单词数据层（2026-11-25 决策轮登记；草稿源自工作区 `vocab-drafts/` 四份文档 + 联网核实）

> 本轮只覆盖**数据层**，不含背单词前端页。依赖图：`P6-1 ∥ P6-2 → P6-3(需 P6-1) → P6-4(需 P6-2+P6-3)`。
> **本次只把 P6-2 落成可投的完整卡**；P6-1 / P6-3 / P6-4 落骨架 + 已定口径——
> P6-1 的完整卡面依赖重新拉取 ECDICT/engra/官方 PDF 后的真实探测值（当前草稿里
> 所有 `commit` / `sha256` 仍是 `<待补>` 占位），现在写成完整卡就又是一次"盘上的卡投不出去"。

### 范围与来源定案（全部实测，别再走回头路）
- 范围源 = **官方课标三档**：小学二级 / 初中三级正文 + 附录3 补充块 / 高中 3066。
  **已实测否决**：engra glossaries（CEFR/CET/考研/托福/GRE，不对口 K-12）；
  社区中考词库（对官方三级正文只覆盖 **87.9%**，漏 197、多 561，且多美式拼写）——
  最多当"真题高频拓展包"并标 `unaudited`，**不能当 base**。
- 详情层 = **ECDICT**（skywind3000，MIT）：音标/释义/词性/变形 `exchange`/词频 `frq`/`tag`；
  词根助记层 = **engra**（bonaysoft，MIT）：`dict/roots/*.yml` 2233 棵递归树，节点 `mnemonic` 为中文词根拆解。
  join 键 = `word`，实测命中 99%+。**只需 `sw`(strip-word) 模糊键兜底，不需要英式/美式变体生成器**
  （ECDICT 已同时收录 colour/color，原"必须双轨"判断被实测推翻）。
- ⚠️ **许可分层**：ECDICT/engra 是 **MIT 可商用**，与 `seeds/data/`(cn-math-taxonomy **CC BY-NC 4.0**)
  的"限个人非商用"红线**性质不同**，须在 `LICENSE-data.md` / `THIRD-PARTY-NOTICES.md` 显式分开，
  不得让 vocab 子集继承非商用限制（wengu 整体仍因 cn-math-taxonomy 不称 OSI 开源）。
- ⚠️ **engra 含 Windows 保留名文件**（`dict/roots/con.yml`），本机 `git checkout` 必失败——
  构建期取数一律 `git -C <repo> show HEAD:<path>` 或 Linux CI。
- 高中锁 **2017版2020修订（3066，官方 PDF 逐字抽取）**；2025修订(3122) 是纯扫描图抽不出，不采用。

### 五条口径裁定（2026-11-25，本地实测 + 联网交叉核实后定）
1. **`counts` 记三数、只断言一个**：`words`（实收）为唯一相等断言基准；
   `official_level2_claim: 505`（官方说明）、`transcription_level2_marked: 503`（转录版 meta 实测）
   只作署名，**不参与相等断言**。链路解释：官方声明 505 → 转录实际标出 503 → 归一去重后实收 501。
2. **`miss` / `Miss` 定性：官方表内确为两行，非转录错误、非数据脏**。
   独立转录源（逐词带官方编号）显示 `864. mirror / 865. miss / 866. Miss * / 867. mistake`——
   小写 `miss` 无星、大写 `Miss` **带二级星**，本地数据完全对应（相邻两行、`is_level2` 一 False 一 True）。
   官方编号末位为 **`1601. zoo`**，而官方说明写"共收录 **1600** 个单词"——差的这 1 即 miss/Miss 计一个词目。
   故 `_source_vocab.json` 须同时记 `rows: 1601` 与 `official_word_count: 1600` 并写明差因。
3. **删除"OCR 95.4% 印证"**：该数**复现不出**。实测两版交集 **1507** → 对正文 1600 为 **94.19%**、
   对 OCR 侧为 **97.41%**，无一种算法得 95.4%。改为可复现陈述：
   "两版交集 1507 / 正文 1600（94.19%），OCR 侧匹配率 97.41%；OCR 漏短词且二级 `*` 标记大量丢失
   （其 level2 计数仅 213），故 OCR 不作 verbatim 升级依据，仅作交叉印证"。
4. **初中正文 verbatim 等级降级**：`transcription+ocr-confirmed` → **`transcription+ocr-crosschecked`**。
   理由：转录源自身 meta 标 `verbatim: false` / `draft: true` / "落盘前须逐字比对官方PDF"，
   而我们**没做逐字比对**（官方 PDF 是 201 页扫描图）。宁可标注不足，不可宣称过度——
   与当年 `unaudited` 标签同一条纪律。升级到 verbatim 另票。
5. **大小写口径 = 保留官方原样（决策人选 A）**：seed 导入**不做 `lower()` 归一**，
   `miss` 与 `Miss` 作为两条独立词条并存。现网 `uq_recitation_items_subject_prompt` 是
   `(subject, prompt)` 上的 TEXT 唯一约束，SQLite 默认**区分大小写**，故两行天然共存、**无需改约束**。
   错题候选词路径继续 `strip().lower()` 不动（`recitation_import.py:281`）。
   ⚠️ 归一与去重是**两套并存规则**，出卡必须写明，别混：入库归一 `strip().lower()`（候选路径）
   vs 去重比对 `prompt.strip().casefold()`（`recitation.py:239`）。

### 复用现网引擎的核实结论（逐条 grep 过，以本条为准、别按草稿旧描述）
- 盘上迁移 head = **`0025_dictation_sheet_audio_ref`**（`down_revision = 0024_dictation_sheets`）；
  `目录结构.md:88` 仍写 `head = 0021_pomodoro_sessions`——**过时**，P6-2 留痕翻正到 0026。
- `recitation_items` 现有约束：`ck_recitation_items_status`（status IN active/retired）+
  `uq_recitation_items_subject_prompt`（subject, prompt）✅ 逐字对上。
- `recitation_reviews` 两条 FK：`fk_recitation_reviews_item_id` → `recitation_items` **ON DELETE CASCADE**；
  `fk_recitation_reviews_event_id` → `learning_events` **ON DELETE RESTRICT**。
  **重建表时两条都要保住**，不是一条。
- 阶梯：`recitation.py:38` 直接 `from app.services.review_policy import MEMORY_LADDER`，
  值为 `(1, 3, 7, 14, 30)`；**不走** `SUBJECT_LADDERS` 分科字典 → 英语词表排期语义与现有背诵一致，
  **无分科坑**（审核方曾疑此，实测证伪）。
- 函数落点：`create_item` 在 **`recitation.py:335`**；`import_items` 与 `add_candidate_words`
  实际在 **`recitation_import.py:209 / :253`**（草稿多处写错文件）。
  `candidate_words`（只读视图）在 `recitation.py:255`。
- 内存索引样板：`app/seed/bank.py` 的 `load_bank(seeds_dir)` + frozen dataclass + `BankStats` ✅ 可仿。
- 作用域复用现成 `runtime_config.seed_grade_ceiling()`（`SEED_GRADE_CEILINGS = frozenset({6, 9, 16})`，
  默认 16），**不新造配置键**。band 映射：6→仅 primary、9→+junior、16→+senior。
- P6 编号在 TICKETS 中此前未被占用 ✅（`grep -c 'P6-' = 0`）。
- 上游输入现状：本机 `_research/` 已清理、工作区无 ECDICT/engra/PDF 残留 →
  **P6-1 开工第一件事是重新拉取并真实探测 sha256/commit**，不一致即中止上报。

### 产物清单（统一口径，取消草稿间的冲突）
```
seeds/vocab/
├─ levels.json              # 范围 base（union 3212；word/forms/stages[]/senior_tier/block）
├─ words.json               # ECDICT join 详情（音标/释义/词性/变形/徽章/frq）
├─ roots.json               # engra 词根家族 + 中文助记
├─ wordroot_meaning.json    # ECDICT wordroot.txt 转出的词根含义/语源/类别
├─ _source_vocab.json       # 分源 verbatim 署名与取证（真实探测，禁猜 SHA）
└─ _upstream/junior_body_transcript.txt   # 三级正文转录（vendored，记 sha256）
```
- ⚠️ **取消 `junior_supplement.json` 独立文件**（工单草稿列了它、落地清单文件树没有）——
  补充块 150 条已由 `levels.json` 的 `block` 字段承载（实测 block 非空恰 150：
  专有名词 67 / 数词 40 / 其他 19 / 月份 11 / 星期 7 …）。
- 官方 PDF（义务教育 31.5MB / 高中 7.7MB）**不进 git**，只在 `_source_vocab.json` 记 URL + sha256。
- 补充块 22 个专有名词/文化词 ECDICT 无详情 → **详情字段留 null，不编造、不另找源**。

### P6-2 recitation_items 加 source 列（迁移 0026 + 模型 + 迁移测试）【完整卡，已合并】
- **状态**：**已合并（PR #76 → main `10f731b`，2026-11-25）**。
- **交付后事实修正（审核方在 `c756f72` 上实读，两条卡面基线不实）**：
  ① 卡面 DoD 6 写"head 断言从 0025 推到 0026"——`tests/integration/test_migrations.py` 在父提交
  里**没有任何** head 字面断言（grep `version_num` / `0025` / `head ==` 零命中），本票是**新增**
  `assert head == "0026_recitation_source"`；② 卡面 DoD 7 写"照 0025 风格补一行"——
  `migrations/README.md` 的条目实际只到 0019（无 0020–0025 条目），施工方改照 0018/0019 风格补。
  两处施工方均主动上报、未硬凑，我核为真；记第 35 次卡面缺陷（归审核方）。
  ③ 卡面白名单只列 `目录结构.md` 一处过时 head 自述，漏 `wengu-api/README.md`、`docs/STATUS.md`
  §4.8 / §5.2 三处——记第 34 次卡面缺陷，欠账翻正另立 **P5-20**，本票不越票改。
- **依赖**：无（schema 独立，但必须先于 P6-4）。
- **背景（按盘上事实）**：见上"复用现网引擎的核实结论"四条约束项。本票是**加法式 schema 增量**，
  只动 `recitation_items` 一列一约束，不碰其它表、不碰判分/复习逻辑、不碰服务函数签名。
- **任务**：
  1. 新增 `wengu-api/migrations/versions/0026_recitation_source.py`：
     `revision = "0026_recitation_source"`、`down_revision = "0025_dictation_sheet_audio_ref"`；
     模块 docstring 记 Revision ID / Revises / Create Date / 用途 / 备份回退（照 0025、0018 风格）。
     SQLite 加 CHECK 必须重建表：`with op.batch_alter_table("recitation_items", recreate="always") as batch:`
     内 `batch.add_column(sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'manual'")))`
     + `batch.create_check_constraint("ck_recitation_items_source", "source IN ('seed','manual','candidate')")`。
     既有行经 `server_default` 自动回填 `'manual'`。
     **幂等**：先 `sa.inspect(op.get_bind())` 探测——无 `source` 列且无 `ck_recitation_items_source` 才执行；
     重复 upgrade 不报错。
     **downgrade**：batch recreate 删该列 + 删该约束；必须保住 `ck_recitation_items_status`、
     `uq_recitation_items_subject_prompt`、`fk_recitation_reviews_item_id`(CASCADE)、
     `fk_recitation_reviews_event_id`(RESTRICT)。
  2. `wengu-api/app/models/recitation.py`：`RecitationItem` 追加
     `source: Mapped[str] = mapped_column(Text, nullable=False, default="manual", server_default=text("'manual'"))`
     与 `CheckConstraint("source IN ('seed','manual','candidate')", name="ck_recitation_items_source")`，
     与迁移逐字一致。**只加字段+约束，不改 `create_item` 等"怎么用"的服务逻辑（那是 P6-4）。**
- **DoD（要运行态证据，逐项贴输出）**：
  1. `alembic upgrade head` 到 0026 成功；`downgrade -1` 回 0025 干净；再 upgrade 可重复不报错。
  2. **DDL before/after 逐字比对**（沿用 P0-3④ 模式）：升级前存 `recitation_items` 完整建表语句
     （含两个既有约束 + 索引），到 0026 后必须 = 原语句 + `source` 列 + 新 CHECK，
     **既有 CHECK/UNIQUE 一字不差仍在**；downgrade 后与升级前逐字相等。差异必须为空。
  3. **唯一约束未被改动**：断言 `uq_recitation_items_subject_prompt` 的列集合仍为
     `(subject, prompt)`、**`source` 不在任何唯一键里**（这是"不把 source 纳入键"的可红点）。
  4. **FK 完整性**：upgrade 后 `PRAGMA foreign_key_check` 为空；插一条 `recitation_reviews` 指向某
     item 成功、`ON DELETE CASCADE` 仍生效（删 item 带走 review）；`event_id` 那条 RESTRICT 未被降级。
  5. 最小单测：建 `source='seed'` 能读回；塞 `source='bogus'` → CHECK 红；不传 → 默认 `'manual'`。
  6. 既有 recitation 单测/集成测**全绿**（默认 manual 不破坏历史行为）。
  7. `test_migrations.py` head 断言从 `0025` 推到 `0026`（字面 revision 串），
     并加 `source` 列 + `ck_recitation_items_source` 存在断言。
  8. `migrations/README.md` 备份/回退段补一行（照 0025 风格）。
  9. 全量 `pytest -q` 绿（基线以 `--collect-only` 实取，当前 **984**，如实报新数）；
     `ruff check --no-cache .` 全仓绿；行尾守卫 5 条仍绿。
- **必改清单（状态类票纪律，AGENTS §8）**：`tests/integration/test_migrations.py`；
  `目录结构.md:88` 的 `head = 0021_pomodoro_sessions` 翻正为 **0026**；
  `docs/STATUS.md` 头部三行 + 交付区新增本票条目（含 PR→squash SHA 锚点，实查
  `git log` / `gh pr view --json number,mergeCommit`，**严禁凭记忆填 SHA**）+
  **所有「当前待审」指针句一并翻转**；`CHANGELOG.md`。
- **白名单**：`wengu-api/migrations/versions/0026_recitation_source.py`（新）、
  `wengu-api/app/models/recitation.py`、`wengu-api/tests/integration/test_migrations.py`、
  `wengu-api/migrations/README.md`、`目录结构.md`、`CHANGELOG.md`、`docs/STATUS.md`。
  （反推依据：新列必连带 `test_migrations.py` 的 head 与 DDL 断言——这是 P3-4 第 28 次缺陷的
  同类场景，本次**预先列入**而非等施工方越界。）
- **禁止**：新建 `vocab_reviews` 表（裁定③=复用背诵引擎）；把 `source` 纳入唯一键或让同词
  出现两行（破坏"一词一条记忆轨"）；用 id 前缀识别来源（判据**只读 `source` 列**，沿用 P5-15
  §19-G-3）；手改生产 SQLite；丢任一既有 CHECK/UNIQUE/FK；downgrade 静默改既有行内容；
  改 `create_item`/`decide`/`due_items` 等服务逻辑（P6-4 的事）；`--skip`/`xfail`。
- **残留风险（交付时如实报告）**：`batch_alter_table(recreate="always")` 靠反射重建约束/索引/FK，
  若某约束名未被反射保留，DoD 2 的逐字 diff 会暴露——**必须按 DoD 2/3/4 兜住，不能只断"列存在"**。
  若一次 recreate 对"加列+加 CHECK"有边界问题，可拆两步同迁移，但 DoD 2/3/4 不变。

### P6-1 背单词 seed 数据 + 构建期抽取器 + 授权署名【骨架，待细化】
- **状态**：骨架。**细化前置**：① 重新拉取 ECDICT/engra/官方 PDF 并真实探测 commit/sha256；
  ② 五条口径裁定已定（本文件上方），填数即定稿。
- **交付轮廓**：`seeds/vocab/*`（见产物清单）；`wengu-api/scripts/import_vocab.py`（编排，
  风格逐字对齐 `import_seed.py`：argparse + `upstream_commit()` 真实探测 + `_write_json` 钉
  `newline="\n"` + `ensure_ascii=False, indent=1` + `SeedConvertError` + `main(argv)->int`）；
  `wengu-api/scripts/vocab_extract/{extract_junior,extract_junior_supp,extract_gsenior,build_levels,vocab_join}.py`；
  授权三节（`THIRD-PARTY-NOTICES.md` ECDICT/engra/课标；`LICENSE-data.md` MIT 与非商用红线分开；
  `seeds/README.md` vocab 节 + 重新生成命令）。
- **DoD 要点（细化时补全）**：`seeds/vocab/*.json` 全 LF（`test_repo_eol.py` 覆盖面扩到 `seeds/vocab/`，
  塞 CRLF 必红）；`counts.words` 与 `levels.json` 实收相等（**判据是两数相等，不写死词数**）；
  `words.json` 对 `levels.json` 的 ECDICT join 命中 ≥ 阈值（阈值手写字面）；补充块全部 `unaudited: true`；
  各源 `verbatim` 等级 = 裁定 4 的口径；**CI 不运行 `import_vocab.py`**（依赖外部数据/OCR），
  CI 只校验已提交 JSON 的 schema/计数/LF。
- **禁止**：ECDICT csv / engra clone / 官方 PDF 进 git；`import_vocab.py` 或
  `rapidocr-onnxruntime` 进 `requirements.txt`/镜像/运行时；**重跑覆盖 `_source_vocab.json` 的
  人工策展取证键**（`commit_evidence`/`sha256`/`verbatim_note`——换快照一律仓库外 scratch 重取证 +
  人工重新策展，P5-17 第 27 次卡面缺陷形态）；硬编码词数当断言。

### P6-3 背单词内存索引 loader（`app/seed/vocab.py`，零 SQLite 写入）【骨架】
- **依赖**：P6-1。**交付**：`load_vocab(seeds_dir)` + frozen `VocabWord` dataclass，
  运行时按 `word` join `levels/words/roots/wordroot_meaning`；band 过滤按 `seed_grade_ceiling`。
- **DoD 要点**：缺文件/空数组 → 空索引不阻塞服务（仿 `seed/bank.py`）；join 命中 ≥ 阈值（字面）；
  band 映射 6/9/16 三档**写判定规则不写词数**；**不写 SQLite**（装载后零写入断言，守 §14）；
  顶层结构非法 fail-fast，不静默空库。
- **禁止**：把词表灌进 SQLite；运行时调 OCR/网络；在本票自造复习调度。

### P6-4 课标词表灌进 recitation_items（seed import，复用背诵引擎）【骨架】
- **依赖**：P6-2 + P6-3。**交付**：家长触发的 service 函数（API 端点与前端另票）——
  按 band 选词批量入库 `recitation_items(subject='英语', prompt=word, answer=<ECDICT 中文释义>, source='seed')`；
  与错题候选词、家长手填并列；`create_item` 加 `source` 参数（默认 `'manual'` 向后兼容）。
- **DoD 要点**：同 `word` 幂等（二次调用 created=0）；seed 词与候选词**共用同一 `due_items()` 队列**；
  不新建 mistake；补充块专名无释义 → `answer` 留 null 不编造；
  **去重语义复用现网**：已存在 `(subject='英语', prompt=word)` 行——无论 manual/candidate、
  无论 active/retired——一律走 `create_item` 抛 `RecitationDuplicate` → 只报告、跳过、
  **不改 source、不覆盖 answer、不复活 retired**（与 `import_items`/`add_candidate_words` 逐字一致）。
- **裁定 5 的落地断言（本票新增，P6-2 不含）**：`miss` 与 `Miss` **两行并存**——
  seed 导入路径**不做 `lower()` 归一**，须各入一条、各排一轨；
  而候选词路径仍 `strip().lower()`。测试要同时覆盖这两条路径的大小写行为差异。
- **禁止**：把音标/词根家族/变形塞进 `answer`；在本票做前端；无家长确认的自动入库；
  把 `source` 纳入唯一键。

### 延后（各另票，不在数据层内）
背单词前端页（词卡展示音标/释义/变形/词根家族/中文助记/语源）；`dictation_sheets` 对 seed 词的复用；
seed 导入的 parent API 端点 + 首次批量导入向导；OCR 逐字比对把初中正文升级到 verbatim。

---

## 作废清单（v2.5，保留标题供追溯，勿实现）
- **P1-2b 供应商自动故障转移**：无在环云模型调用 → 互备无意义。
- **P1-2c 按 task 配 VLM/OCR 模型**：模型调用外移 → 不适用。
- **P1-3b OCR 行聚类切题预处理**：切片随视觉栈退役；改外部 agent 认红笔。
- **P1-3c 切片裁剪覆盖配图**：同上作废。
- **P1-4 系统内结构化提取（VLM）**：能力移到外部 agent + `docs/templates`。
- **P1-7c 自动排复习（模型判错即入库）**：入本一律经核对页确认，"未确认自动入库"场景消失。

---

## 依赖总览（v2.5）
- P1-0 → 全部 P1；P1-1(+P1-1b) → P1-2(mock-only)。
- **主入本链**：P1-4b（模板）+ P1-3（手填后手）→ **P1-3d（监听目录导入引擎）** → **P1-6（核对页确认入本）**。外部工具：P1-4c（千问办公 Skill，依赖 P1-4b + P1-3d）。
- **同类题链（Phase 3 提前）**：**P1-10（题库检索引擎）** → P1-5（判分器）→ **P1-11（考核闭环）**；P1-7a（复习：考核优先/重做兜底 + 双来源）依赖 P1-6 + P1-10；P1-7b（前置回溯）依赖 P1-10。
- **收尾**：P1-9（五页 UI）依赖以上；P1-9b 依赖 P1-3d；**P1-12（退役视觉栈/Provider）后置到 P1-3d + P1-10 + P1-11 实跑通过之后**。
- Phase 0 不再是入本前置（批改外移绕过识别瓶颈）；P0-2 黄金集转供 P1-5/P1-4b 回归。
- Phase2 → Phase3（增量）→ Phase5；Phase4 任意时点（孩子用起来后）。
