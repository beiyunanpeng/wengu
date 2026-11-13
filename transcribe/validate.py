#!/usr/bin/env python3
"""wengu 转录契约校验器 —— 纯标准库、离线、不调模型、不写 wengu 数据库。

定位：transcribe/ 可选包的「机器真源消费端」。它跑在 wengu 运行时之外，
只做三件事：

  check      校验外部 agent 产出的转录 JSON，输出批次 manifest
  selfcheck  比对「契约 / 模板 / Skill / 后端常量」是否漂移（只读，不改任何文件）
  evals      跑脱敏合成样例回归（不调模型也能验证契约与负例）

设计红线：
  - 绝不 import wengu-api 的任何模块（后端零依赖，本包也不反向依赖）
  - 后端 wengu-api/app/services/ingestion.py 的常量是运行时唯一权威
  - 本文件只读取、只报告；修 drift 由人按 ticket 改，不自动改写

用法：
  python transcribe/validate.py check data/inbox/transcribe-*.json
  python transcribe/validate.py check x.json --source-tool doubao_web --template-version 2 --manifest out.json
  python transcribe/validate.py selfcheck [--strict]
  python transcribe/validate.py evals
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
CONTRACT_PATH = PACKAGE_ROOT / "contract" / "ingestion_v1.json"
FIXTURES_DIR = PACKAGE_ROOT / "evals" / "fixtures"

BACKEND_PATH = REPO_ROOT / "wengu-api" / "app" / "services" / "ingestion.py"
TEMPLATE_PATH = REPO_ROOT / "docs" / "templates" / "doubao_transcribe_v1.md"
LEGACY_SKILL_PATH = REPO_ROOT / "docs" / "tooling" / "wengu-transcribe.md"
EVALS_REGRESSION_PATH = PACKAGE_ROOT / "evals"
ENV_EXAMPLE_PATH = REPO_ROOT / "wengu-api" / ".env.example"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# --------------------------------------------------------------------------- #
# 基础读取
# --------------------------------------------------------------------------- #

def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def read_frontmatter(path: Path) -> dict[str, Any]:
    """读 markdown frontmatter。只解析简单 key: value / [a, b] / 整数，够用即可。"""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    result: dict[str, Any] = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.split(" # ", 1)[0].strip()
        if raw.startswith("[") and raw.endswith("]"):
            value: Any = [part.strip() for part in raw[1:-1].split(",") if part.strip()]
        elif re.fullmatch(r"-?\d+", raw):
            value = int(raw)
        else:
            value = raw
        result[key.strip()] = value
    return result


def _static_number(node: ast.expr) -> Any:
    """静态求值纯数字四则表达式（如 5 * 1024 * 1024），不用 eval、不执行任何代码。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        operand = _static_number(node.operand)
        if operand is None:
            return None
        return +operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        left, right = _static_number(node.left), _static_number(node.right)
        if left is None or right is None:
            return None
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.FloorDiv) and right:
            return left // right
        if isinstance(op, ast.Pow):
            return left**right
    return None


def parse_backend_constants(path: Path = BACKEND_PATH) -> dict[str, Any]:
    """用 ast 静态解析后端模块级常量，绝不 import、绝不 eval、绝不执行后端代码。"""
    if not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {
        "FIELD_LIMITS",
        "SUPPORTED_CHANNELS",
        "MAX_ITEMS_PER_BATCH",
        "MAX_BATCH_BODY_BYTES",
        "PLACEHOLDER_MARK",
    }
    found: dict[str, Any] = {}
    for node in tree.body:
        name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value_node = node.value
        if name in wanted and value_node is not None:
            try:
                value: Any = ast.literal_eval(value_node)
            except (ValueError, SyntaxError):
                value = _static_number(value_node)
            if value is None:
                continue
            found[name] = list(value) if isinstance(value, tuple) else value
    return found


# --------------------------------------------------------------------------- #
# 转录产物校验（与后端 validate_envelope / validate_and_normalize 同语义）
# --------------------------------------------------------------------------- #

@dataclass
class ItemError:
    index: int
    field: str
    reason: str


@dataclass
class CheckResult:
    envelope_error: str = ""
    drafts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ItemError] = field(default_factory=list)
    dropped_unknown_fields: int = 0

    @property
    def placeholder_count(self) -> int:
        return sum(1 for d in self.drafts if d["has_placeholder"])

    @property
    def incomplete_count(self) -> int:
        return sum(1 for d in self.drafts if d["is_incomplete"])


def clean_text(value: str) -> str:
    return _CONTROL_CHARS.sub("", value).strip()


def validate_envelope(payload: Any, contract: dict[str, Any]) -> tuple[str, list[Any], str]:
    """返回 (channel, items, error)；error 非空表示整批拒绝。"""
    channels = contract["channels"]
    allowed = [channels["primary"], *channels["compat"]]
    required = contract["envelope"]["required_keys"]
    if not isinstance(payload, dict):
        return "", [], "body 必须是 JSON 对象 {channel, items}"
    for key in required:
        if key not in payload:
            return "", [], f"缺少必填键 {key}"
    channel = payload.get("channel")
    if channel not in allowed:
        return "", [], f"不支持的 channel {channel!r}（仅支持 {' / '.join(allowed)}）"
    items = payload.get("items")
    if not isinstance(items, list):
        return "", [], "items 必须是数组"
    if not items:
        return "", [], "items 为空，无可导入内容"
    max_items = contract["envelope"]["max_items"]
    if len(items) > max_items:
        return "", [], f"单批上限 {max_items} 题，当前 {len(items)} 题，请拆分"
    return channel, items, ""


def normalize_items(items: list[Any], contract: dict[str, Any]) -> CheckResult:
    result = CheckResult()
    limits: dict[str, dict[str, Any]] = contract["fields"]
    placeholder: str = contract["placeholder"]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            result.errors.append(ItemError(index, "item", "不是对象"))
            continue
        normalized: dict[str, Any] = {}
        has_error = False
        for name, spec in limits.items():
            value = item.get(name)
            if value is None:
                normalized[name] = ""
                continue
            if not isinstance(value, str):
                result.errors.append(ItemError(index, name, "必须是字符串"))
                has_error = True
                break
            value = clean_text(value)
            if len(value) > spec["max"]:
                result.errors.append(
                    ItemError(index, name, f"超长 {len(value)} > {spec['max']}，未导入")
                )
                has_error = True
                break
            normalized[name] = value
        if has_error:
            continue
        if not normalized["problem_text"]:
            result.errors.append(ItemError(index, "problem_text", "题目为空（必填）"))
            continue
        result.dropped_unknown_fields += sum(1 for key in item if key not in limits)
        all_text = "".join(normalized.values())
        result.drafts.append(
            {
                "seq": index,
                "has_placeholder": placeholder in all_text,
                "is_incomplete": not normalized["student_answer"]
                or not normalized["standard_answer"],
                "suggestion_only": bool(
                    normalized["error_cause_suggestion"] or normalized["suggested_topic_id"]
                ),
            }
        )
    return result


def check_payload(payload: Any, contract: dict[str, Any], raw_len: int = 0) -> CheckResult:
    max_bytes = contract["envelope"]["max_body_bytes"]
    if raw_len > max_bytes:
        out = CheckResult()
        out.envelope_error = f"报文 {raw_len} 字节超过 {max_bytes} 上限，请拆分"
        return out
    channel, items, error = validate_envelope(payload, contract)
    if error:
        out = CheckResult()
        out.envelope_error = error
        return out
    return normalize_items(items, contract)


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #

def cmd_check(args: argparse.Namespace) -> int:
    contract = load_contract()
    failures = 0
    for filename in args.files:
        path = Path(filename)
        if not path.exists():
            print(f"[FAIL] {filename}: 文件不存在")
            failures += 1
            continue
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[FAIL] {filename}: JSON 解析失败 {exc.msg}")
            failures += 1
            continue
        result = check_payload(payload, contract, len(raw))
        if result.envelope_error:
            print(f"[FAIL] {filename}: {result.envelope_error}")
            failures += 1
            continue
        print(
            f"[ {'PASS' if not result.errors else 'PARTIAL'} ] {filename}: "
            f"items={len(result.drafts) + len(result.errors)} "
            f"accepted={len(result.drafts)} rejected={len(result.errors)} "
            f"placeholder={result.placeholder_count} incomplete={result.incomplete_count} "
            f"unknown_fields={result.dropped_unknown_fields}"
        )
        for err in result.errors:
            print(f"        - index={err.index} field={err.field} reason={err.reason}")
        if result.incomplete_count or result.placeholder_count:
            print("        ! 含占位符或缺正答的项只能进草稿，转正须核对页人工确认")
        manifest = {
            "contract_id": contract["contract_id"],
            "contract_version": contract["version"],
            "template_version": args.template_version,
            "source_tool": args.source_tool,
            "file": path.name,
            "sha256": sha,
            "body_bytes": len(raw),
            "items": len(result.drafts) + len(result.errors),
            "accepted": len(result.drafts),
            "rejected": len(result.errors),
            "placeholder_count": result.placeholder_count,
            "incomplete_count": result.incomplete_count,
            "unknown_fields": result.dropped_unknown_fields,
            "suggestion_only_items": sum(1 for d in result.drafts if d["suggestion_only"]),
        }
        if args.manifest:
            out = Path(args.manifest)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"        manifest -> {out}")
        if result.errors:
            failures += 1
    return 1 if failures else 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    contract = load_contract()
    backend = parse_backend_constants()
    fm_template = read_frontmatter(TEMPLATE_PATH)
    fm_skill = read_frontmatter(LEGACY_SKILL_PATH)
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8") if TEMPLATE_PATH.exists() else ""
    skill_text = LEGACY_SKILL_PATH.read_text(encoding="utf-8") if LEGACY_SKILL_PATH.exists() else ""

    records: list[tuple[str, str, str]] = []

    def add(status: str, name: str, detail: str) -> None:
        records.append((status, name, detail))

    if not backend:
        add("DRIFT", "后端常量可解析", f"未能从 {BACKEND_PATH} 读取常量")
    else:
        expected_channels = {contract["channels"]["primary"], *contract["channels"]["compat"]}
        got_channels = set(backend.get("SUPPORTED_CHANNELS", []))
        add("OK" if expected_channels == got_channels else "DRIFT", "channel 集合",
            f"contract={sorted(expected_channels)} backend={sorted(got_channels)}")

        limits = backend.get("FIELD_LIMITS", {})
        c_fields = set(contract["fields"])
        b_fields = set(limits)
        add("OK" if c_fields == b_fields else "DRIFT", "字段集合",
            f"contract={len(c_fields)} 项 backend={len(b_fields)} 项 "
            f"差异={sorted(c_fields ^ b_fields) or '无'}")
        mismatch = [
            f"{k}:{contract['fields'][k]['max']}!={limits[k]}"
            for k in c_fields & b_fields
            if contract["fields"][k]["max"] != limits[k]
        ]
        add("OK" if not mismatch else "DRIFT", "字段长度上限",
            "全部一致" if not mismatch else ", ".join(mismatch))

        for key, ckey in (
            ("MAX_ITEMS_PER_BATCH", "max_items"),
            ("MAX_BATCH_BODY_BYTES", "max_body_bytes"),
        ):
            cv = contract["envelope"][ckey]
            bv = backend.get(key)
            add("OK" if cv == bv else "DRIFT", key, f"contract={cv} backend={bv}")

        add("OK" if contract["placeholder"] == backend.get("PLACEHOLDER_MARK") else "DRIFT",
            "占位符", f"contract={contract['placeholder']} backend={backend.get('PLACEHOLDER_MARK')}")

    # 模板与契约：模板 schema_fields 必须 == 契约字段 − bank_only_fields（显式规则，非忽略项）
    tmpl_fields = set(fm_template.get("schema_fields", []))
    c_fields = set(contract["fields"])
    bank_only = set(contract["template"].get("bank_only_fields", []))
    expected_tmpl_fields = c_fields - bank_only
    bank_only_valid = bank_only <= c_fields
    tmpl_fields_ok = tmpl_fields == expected_tmpl_fields and bank_only_valid
    add("OK" if tmpl_fields_ok else "DRIFT", "模板 schema_fields ↔ 契约字段",
        f"模板 {len(tmpl_fields)} 项 / 契约 {len(c_fields)} 项 − bank_only {sorted(bank_only) or '无'} "
        f"= 期望 {len(expected_tmpl_fields)} 项；差异={sorted(tmpl_fields ^ expected_tmpl_fields) or '无'}"
        + ("" if bank_only_valid else f"；bank_only 含非契约字段={sorted(bank_only - c_fields)}"))
    add("OK" if fm_template.get("version") == contract["template"]["version"] else "DRIFT",
        "模板 version", f"模板={fm_template.get('version')} 契约={contract['template']['version']}")
    add("OK" if fm_template.get("channel") == contract["channels"]["primary"] else "DRIFT",
        "模板 channel", f"模板={fm_template.get('channel')} 契约={contract['channels']['primary']}")
    add("OK" if fm_template.get("id") == contract["template"]["id"] else "DRIFT",
        "模板 id", f"模板={fm_template.get('id')} 契约={contract['template']['id']}")

    # 旧 Skill 与模板
    ref = fm_skill.get("template_ref")
    add("OK" if ref and (REPO_ROOT / str(ref)).exists() else "DRIFT", "Skill template_ref 指向",
        f"{ref}（{'存在' if ref and (REPO_ROOT / str(ref)).exists() else '不存在/未配置'}）")

    # portable Skill（真正随包分发的执行配方）与模板/契约
    portable_path = REPO_ROOT / contract["skill"]["portable_path"]
    fm_portable = read_frontmatter(portable_path)
    p_tref = fm_portable.get("template_ref")
    p_cref = fm_portable.get("contract_ref")
    p_tref_ok = bool(p_tref) and (REPO_ROOT / str(p_tref)).exists()
    add("OK" if p_tref_ok else "DRIFT", "portable Skill template_ref 指向",
        f"{p_tref}（{'存在' if p_tref_ok else '不存在/未配置'}）")
    p_cref_ok = bool(p_cref) and (REPO_ROOT / str(p_cref)).resolve() == CONTRACT_PATH.resolve()
    add("OK" if p_cref_ok else "DRIFT", "portable Skill contract_ref 指向",
        f"{p_cref}（{'指向本包契约' if p_cref_ok else '未指向 contract/ingestion_v1.json'}）")
    fm_p_template = read_frontmatter(REPO_ROOT / str(p_tref)) if p_tref else {}
    add("OK" if fm_p_template.get("id") == contract["template"]["id"] else "DRIFT",
        "portable Skill 模板 id", f"模板={fm_p_template.get('id')} 契约={contract['template']['id']}")
    add("OK" if fm_p_template.get("version") == contract["template"]["version"] else "DRIFT",
        "portable Skill 模板 version",
        f"模板={fm_p_template.get('version')} 契约={contract['template']['version']}")
    add("OK" if fm_p_template.get("channel") == contract["channels"]["primary"] else "DRIFT",
        "portable Skill 模板 channel",
        f"模板={fm_p_template.get('channel')} 契约={contract['channels']['primary']}")

    # 版本纪律回归目录：文档引用的回归目录必须存在，且不得再指向已退役的旧路径
    docs_text = template_text + "\n" + skill_text
    live_ref = "transcribe/evals/" in docs_text
    dead_ref = "evals/transcribe/" in docs_text
    regression_ok = EVALS_REGRESSION_PATH.exists() and live_ref and not dead_ref
    add("OK" if regression_ok else "DRIFT", "版本纪律回归目录",
        f"transcribe/evals/ {'存在' if EVALS_REGRESSION_PATH.exists() else '缺失'}；"
        f"文档引用 live={live_ref} dead={dead_ref}（应 live=True dead=False）")

    # inbox 路径可移植性
    env_text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8") if ENV_EXAMPLE_PATH.exists() else ""
    m = re.search(r"^WENGU_INBOX_DIR=(\S+)", env_text, re.M)
    env_default = m.group(1) if m else ""
    add("OK" if env_default == contract["inbox"]["default_path"] else "DRIFT",
        "inbox 默认路径", f".env.example={env_default} 契约={contract['inbox']['default_path']}")
    if re.search(r"[A-Za-z]:[\\/]|/d/MyProducts|/Users/", skill_text):
        add("WARN", "Skill 内硬编码个人路径",
            "docs/tooling/wengu-transcribe.md 含开发者本机绝对路径，开源后其他家长不可直接用")

    widths = max(len(name) for _, name, _ in records)
    for status, name, detail in records:
        print(f"[{status:>5}] {name:<{widths}}  {detail}")
    drift = sum(1 for s, _, _ in records if s == "DRIFT")
    warn = sum(1 for s, _, _ in records if s == "WARN")
    ok = sum(1 for s, _, _ in records if s == "OK")
    print(f"\n汇总: {ok} OK / {drift} DRIFT / {warn} WARN")
    print("说明: DRIFT 表示「文档承诺」与「代码事实」已分离；本命令只读报告，不自动修。")
    return 1 if (args.strict and drift) else 0


def cmd_evals(_args: argparse.Namespace) -> int:
    contract = load_contract()
    cases: list[dict[str, Any]] = []
    valid_path = FIXTURES_DIR / "valid_batch.json"
    invalid_path = FIXTURES_DIR / "invalid_cases.json"
    if not valid_path.exists() or not invalid_path.exists():
        print("[FAIL] fixtures 缺失")
        return 1
    valid = json.loads(valid_path.read_text(encoding="utf-8"))
    expect_valid = valid.pop("_expect")
    cases.append({"name": "valid_batch", "payload": valid, "expect": expect_valid})
    cases.extend(json.loads(invalid_path.read_text(encoding="utf-8")))

    passed = 0
    for case in cases:
        payload = case["payload"]
        raw_len = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        result = check_payload(payload, contract, raw_len)
        actual = {
            "envelope_rejected": bool(result.envelope_error),
            "accepted": len(result.drafts),
            "rejected": len(result.errors),
            "placeholder_count": result.placeholder_count,
            "incomplete_count": result.incomplete_count,
            "unknown_fields": result.dropped_unknown_fields,
        }
        expect: dict[str, Any] = case["expect"]
        bad = {k: (expect[k], actual.get(k)) for k in expect if actual.get(k) != expect[k]}
        if bad:
            print(f"[FAIL] {case['name']}: {bad}")
        else:
            print(f"[PASS] {case['name']}: {actual}")
            passed += 1
    print(f"\n{passed}/{len(cases)} 通过（全部为合成样例，不含任何真实作业内容）")
    return 0 if passed == len(cases) else 1


def main() -> int:
    # Windows 默认 cmd/PowerShell 控制台是 GBK：记录名/详情含 ↔ 与中文会抛 UnicodeEncodeError，
    # 打不到汇总行、退出码被 traceback 取代。入口统一重配置为 UTF-8 + replace，保证默认环境可跑。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="wengu 转录契约校验器（离线、纯标准库）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="校验转录 JSON 并输出批次 manifest")
    p_check.add_argument("files", nargs="+")
    p_check.add_argument("--source-tool", default="unknown", help="转录工具标识，写进 manifest")
    p_check.add_argument("--template-version", type=int, default=2, help="模板版本，写进 manifest")
    p_check.add_argument("--manifest", help="manifest 输出路径（不写则只打印）")
    p_check.set_defaults(func=cmd_check)

    p_self = sub.add_parser("selfcheck", help="只读比对契约/模板/Skill/后端常量是否漂移")
    p_self.add_argument("--strict", action="store_true", help="存在 DRIFT 时返回非零，供 CI 使用")
    p_self.set_defaults(func=cmd_selfcheck)

    p_evals = sub.add_parser("evals", help="跑脱敏合成样例契约回归（不调模型）")
    p_evals.set_defaults(func=cmd_evals)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
