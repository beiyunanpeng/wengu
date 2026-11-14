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

### P2-11 错因聚合卡（v2.7 D9；只读聚合、零新增状态）
- **现状（2026-11-14 读盘）**：`ERROR_CAUSES` 在 `services/mistakes.py:50-58`，7 键原文
  `prerequisite_gap / concept_unclear / method_missing / calculation / careless / expression / other`；
  错因两列都在 `mistake_versions`（`suggested_error_cause:80`、`confirmed_error_cause:81`），
  **取值优先级唯一入口是 `effective_labels()`（`:118-141`）**：`confirmed_by is not None` 用确认值、否则用建议值；
  `services/dashboard.py` **零处错因聚合**（grep 无命中），且 `_mistake_rows`（`:213-217`）只读根表、
  不加载 `MistakeVersion`——本票要扩到版本列，但**不得绕过 `effective_labels` 自己拼优先级**。
- 交付：`GET /api/dashboard` 新增 `error_cause_distribution: [{cause, label, count}]`——
  口径 = **在册未掌握**（`active` 且非 `is_graduated`，与 P2-13 同一把尺）按 `effective_labels().error_cause` 计数；
  **未填错因单列 `unlabeled`**（不塞进 `other`，否则会把"没标"误读成"其他原因"）；
  前端看板加一张横向条卡（与薄弱分布同风格），点击某条跳 `/mistakes?error_cause=<键>`（复用 P2-9 既有筛选）。
- DoD：造 confirmed/suggested 混合 fixture，断言计数走 `effective_labels` 优先级（改判后数字随之变、不重复计）；
  `sum(error_cause_distribution) + unlabeled == 未掌握总数`（与 P2-13 学科卡自洽）；
  `other` 与 `unlabeled` 分列断言；零新增列/零迁移；360/412 不破版；全量绿 + ruff + build。
- 禁止：引入模型/AI 归类错因（零模型红线）；把 `suggested_*` 当确认值统计；新建第三套未掌握口径；
  为聚合结果存列或建缓存表；用 `other` 兜底空值。

### P2-12 复习日历（v2.7 D9；只读投影，非自动排课）
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
     `kind` 沿用 `due_queue` 的 quiz/redo 判定，**不得另建判定**；
  ② `done` 来自 `learning_events` 按日归属（payload `completed_on` 优先、回退 `occurred_at`，
     与 `dashboard.py:160-184` / `streak.py:64-79` 同一口径）；**事件类型白名单必须是显式常量**，
     只收真实存在的 type：`attempt_correct`、`attempt_wrong`、`recitation_reviewed`、
     `pomodoro_completed`、`review_scheduled`、`mistake_labeled`、`mistake_voided`、`mistake_reactivated`
     （⚠️ 盘上**不存在** `mistake_confirmed`，测试夹具里出现过该字符串属误导，不得当事实写进实现）；
  ③ 新路由 `/review-calendar` + NAV 追加 `{to:"/review-calendar", label:"复习日历"}`
     （插在 `/schedule` 之后、`parentOnly` 三项之前；`groupNavItems`/`isNavActive` 自动生效）；
     月视图每天标「N 道计划」，点某天看清单并可跳 `/review`。
- DoD：造 3 条不同 `due_date`（含 1 条已完成、1 条逾期）断言按日归属与逾期标记正确、且不重复计；
  投影数字与 `due_queue` 在今日一致（同一把尺）；跨度 >92 天 → 422；与 `/schedule` 硬事件互不混入；
  只读——**任何写操作都不新增**；360/412 月视图不破版（CDP/真机取证截图）；全量绿 + ruff + build；**零迁移**。
- 禁止：自动排课/时间块式日程（§12 已砍）；为日历存状态列或建派生表；前端 localStorage 当数据源；
  臆造不存在的 event type；把 PIN 写操作混进只读页；用 `due_queue` 之外的第二套逾期/kind 判定。

### P2-14 主题切换（v2.7 D10；纯前端，零后端改动）
- **现状（2026-11-14 读盘）**：`main.tsx:17` 写死 `<MantineProvider defaultColorScheme="light">`，
  全仓**无 `createTheme`、无 theme 文件**；`src/print.css` 通篇硬编码浅色（`.print-shell:5-6`、
  `.print-toolbar:21-22`、`.print-sheet:73`、`@media print:251-306` 强制 `background:#fff !important`），
  两个打印页各自 import 它且路由挂在 `AppLayout` 之外（`App.tsx:28-29`）；
  `DashboardPage` 有 4 处硬编码色（`:100/:108/:111/:201`）；前端**完全没用过 localStorage**；
  `@mantine/hooks@8.3.18` 已在依赖（`package.json:15`）；后端 app-config 白名单只有 4 键
  （`runtime_config.py:225`）且 `PUT /api/config` 整挂 `require_parent`（`api/config.py:24`）。
- 交付：`createTheme` + `useMantineColorScheme`，头部加浅色/深色切换按钮（孩子区与家长区都可见，
  解锁与否都能切）；偏好存 **localStorage（Mantine 内置 storage key）**——理由写进代码注释：
  主题是**每设备的呈现偏好、不是学习数据**，因此不进 app-config（那会被 PIN 挡住，孩子改不了自己设备外观），
  也不进数据库；把 `DashboardPage` 4 处硬编码色改为 Mantine 语义色 / `var(--mantine-color-*)`；
  **打印豁免**：`.print-shell` 与 `@media print` 在深色下仍保持浅色底，打印页工具栏若用 Mantine 组件需固定 light。
- DoD：切换后刷新保持、且**不触发任何数据请求**（网络断言或取证）；深色下桌面 + 360/412 三档取证截图
  （文字对比度、掌握度曲线、徽标、表格）；打印预览仍白底（截图取证）；localStorage 中**只有主题键**
  （断言不含任何题目/学习数据）；`npm run lint`/`test`/`build` 绿；**后端零改动**。
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
- **P3-4 听力+默写**：默写=卷面批改后走转录导入；听力"教材音频+TTS"+组卷。禁：口语 ASR。
- **P3-5 语文客观并入**：字音/病句/默写并入转录；作文/阅读理解只走外部讲解不进本。
  **前置已交付（P3-8，2026-10-31）**：家长可自建语文章级 seed（`cnl_`）、语文题可挂
  `topic_id`、语文错题可挂主考点，到期考核 `quiz` 闭环已实跑；本票只剩题库内容接入。
- **P3-6 信奥独立流**：卡壳→外部引导→"待重做清单"（复用转录）；需要时手动组卷（C++ 题库检索）；C++ 技能图谱 seed。禁：判题 infra、自动排复习。
- **P3-7 长期计划**：覆盖型（seed 图谱+掌握度自适应）+ 积累型（streak）；家长与 AI（外部）共创、AI 生成后审核。

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
- **P5-5 开源基线**：LICENSE + 中英 README（一行安装）+ 隐私声明（数据不出户；**v2.5 后无任何云转录/云推理，题目图片不进网络**——旧表述"云转录仅送题目图"已作废）+ CHANGELOG + `.env.example`；合规点名《个人信息保护法》《未成年人网络保护条例》；**第三方数据 License 署名 + NC 声明**强制。
  **现状（2026-11-02 审计）**：LICENSE / 中文 README / CHANGELOG / `wengu-api/.env.example` / 第三方署名 / 合规点名 **已在盘上**；**英文 README 与独立隐私声明文档仍缺**（本票未完结）。
  - **v2.8 扩卡（§19-F，2026-11-12 确认）**：
    ① README 前三行定位改"本地优先的错题复习工作台（AI 转录为可选外挂）"，明写不判真实作业、不生成讲解、零模型内核；
    ② 克隆地址 `<你>/wengu.git` 改真实地址 `beiyunanpeng/wengu`；
    ③ 新增独立 `PRIVACY.md`：数据本土化、外部转录上云字段清单与擦除指引、监护人告知与单独同意文案、离线 `/import` 路径；
       **修正旧句"题目图片不进网络"**——内核零模型，但可选外部转录会把擦除 PII 后的卷面送境内第三方 AI（见 `transcribe/README.md` §0）；
    ④ CC BY-NC §3(a)(1) 全项：原作者姓名、版权声明、许可通知、免责声明、原始 URI、"已修改（转换初中子集）"标注、
       `upstream_commit` 钉死为具体 SHA；补 SPDX；表述为 **"MIT 代码 + CC BY-NC 数据"分层**（整体不称 OSI 开源）；
       核对 LICENSE 使 GitHub API `license` 不再为 `NOASSERTION`；
    ⑤ 仓库 `description` / `topics` / `homepage`、首个 GitHub Release（说明可复用 `tag-v0.6.0.txt`）、开启 Discussions；
    ⑥ DoD：陌生人 5 分钟内从 README 完成合规判断并装起来；克隆地址可直接复制；隐私声明与 transcribe checklist 口径一致；
       CC 署名可人工核对；GitHub 识别 MIT；Release 可下载。
    ⑦ 禁：声称"完全不上云"；隐瞒外部转录；删除历史条目。
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
