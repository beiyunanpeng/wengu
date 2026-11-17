"""P5-12 上游更新检查（纯开发者侧，手动跑；零应用改动、零新依赖、零迁移）。

    python wengu-api/scripts/check_upstream.py            # 检查上游是否动了
    python wengu-api/scripts/check_upstream.py --json     # 机器可读报告
    python wengu-api/scripts/check_upstream.py --pinned <sha>   # 快照一致性复检（自证）

只读 GET、无鉴权、无 token；对 seeds/data/ **零写入**、不落盘缓存（无状态，留痕=贴报告）。
exit 0 = 已同步（或 --pinned 复检 delta 全 0）；exit 1 = 有更新（或复检不一致）；
exit 2 = 检查失败（缺文件/缺键/网络失败/403 限流）——**绝不静默当"已同步"**。
同步永远是另一票：重导入 + 按设计文档 §19-F-1 重新取证 + 重新策展，人工决定。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

UPSTREAM_REPO = "xiaoyang111222/cn-math-taxonomy"
COMMITS_API_URL = (
    f"https://api.github.com/repos/{UPSTREAM_REPO}/commits?path=data&per_page=1"
)
RAW_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/" + UPSTREAM_REPO + "/{sha}/data/{name}.json"
)
SNAPSHOT_FILES = ("topics", "dependencies", "questions")

# 与 import_seed.py / import_questions.py 同口径（漂移由单测钉死）。
SUBJECT_BY_PREFIX = {"cnm_": "数学", "cne_": "英语", "cnp_": "物理"}
GRADE_BANDS = {"primary": range(1, 7), "junior": range(7, 10), "senior": range(10, 17)}
BAND_ORDER = ("primary", "junior", "senior")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "seeds" / "data" / "_source.json"
DEFAULT_DATA_DIR = PROJECT_ROOT / "seeds" / "data"


class CheckError(RuntimeError):
    """检查无法得出结论（缺输入/网络失败/响应非法）；调用方必须 exit 2，不猜。"""


# ---------------------------------------------------------------------------
# 纯解析/计算层：只吃数据结构，不接受任何路径参数，不联网、不写盘。
# ---------------------------------------------------------------------------


def parse_latest_commit(payload: Any) -> tuple[str, str]:
    """GitHub commits API 响应 → (最新触及 data/ 的 sha, 提交日期)。非法即报错，不猜。"""

    if not isinstance(payload, list) or not payload:
        raise CheckError("commits API 响应必须是非空数组（空数组无法判定上游状态，不猜）")
    entry = payload[0]
    if not isinstance(entry, dict) or not isinstance(entry.get("sha"), str):
        raise CheckError("commits API 响应首条缺少 sha 字符串")
    commit = entry.get("commit")
    date = None
    if isinstance(commit, dict):
        for who in ("committer", "author"):
            block = commit.get(who)
            if isinstance(block, dict) and isinstance(block.get("date"), str):
                date = block["date"]
                break
    if date is None:
        raise CheckError(f"commits API 响应缺少提交日期（sha={entry['sha']}）")
    return entry["sha"], date


def prefix_of(topic_id: str) -> str:
    head, sep, _ = topic_id.partition("_")
    return head + sep if sep else head


def band_of(grade: Any) -> str:
    for band in BAND_ORDER:
        if grade in GRADE_BANDS[band]:
            return band
    return "unknown"


def summarize_topics(topics: Any) -> dict:
    """topics 总数 / 分带 / 分科 / 未知前缀点名。上游 camelCase 与本地 snake_case 同尺
    （本函数只消费 id 与 grade，两种形态都有这两个键）。"""

    if not isinstance(topics, list):
        raise CheckError("topics.json 必须是数组")
    by_band: dict[str, int] = {b: 0 for b in BAND_ORDER}
    by_subject: dict[str, int] = {s: 0 for s in SUBJECT_BY_PREFIX.values()}
    unknown_prefixes: dict[str, int] = {}
    for topic in topics:
        if not isinstance(topic, dict) or not isinstance(topic.get("id"), str):
            raise CheckError(f"topics 条目缺少 id 字符串: {str(topic)[:120]}")
        band = band_of(topic.get("grade"))
        by_band[band] = by_band.get(band, 0) + 1
        prefix = prefix_of(topic["id"])
        subject = SUBJECT_BY_PREFIX.get(prefix)
        if subject is None:
            unknown_prefixes[prefix] = unknown_prefixes.get(prefix, 0) + 1
        else:
            by_subject[subject] += 1
    return {
        "topics_total": len(topics),
        "topics_by_band": by_band,
        "topics_by_subject": by_subject,
        "unknown_prefixes": unknown_prefixes,
    }


def summarize_dependencies(deps: Any) -> dict:
    if not isinstance(deps, list):
        raise CheckError("dependencies.json 必须是数组")
    return {"deps_total": len(deps)}


def summarize_questions(questions: Any, topics: Any) -> dict:
    """questions 总数 / 分带（按所挂 topic 的 grade，与 import_questions 同尺）/ 分科 /
    未知前缀点名。topicId（上游）与 topic_id（本地）两种键都认。"""

    if not isinstance(questions, list) or not isinstance(topics, list):
        raise CheckError("questions.json / topics.json 必须是数组")
    grades = {t["id"]: t.get("grade") for t in topics if isinstance(t, dict)}
    by_band: dict[str, int] = {b: 0 for b in BAND_ORDER}
    by_subject: dict[str, int] = {s: 0 for s in SUBJECT_BY_PREFIX.values()}
    unknown_prefixes: dict[str, int] = {}
    out_of_scope = 0
    for question in questions:
        if not isinstance(question, dict):
            raise CheckError(f"questions 条目必须是对象: {str(question)[:120]}")
        topic_id = question.get("topicId") or question.get("topic_id")
        if not isinstance(topic_id, str):
            raise CheckError(f"questions 条目缺少 topicId: {str(question)[:120]}")
        if topic_id not in grades:
            out_of_scope += 1
        band = band_of(grades.get(topic_id))
        by_band[band] = by_band.get(band, 0) + 1
        prefix = prefix_of(topic_id)
        subject = SUBJECT_BY_PREFIX.get(prefix)
        if subject is None:
            unknown_prefixes[prefix] = unknown_prefixes.get(prefix, 0) + 1
        else:
            by_subject[subject] += 1
    return {
        "questions_total": len(questions),
        "questions_by_band": by_band,
        "questions_by_subject": by_subject,
        "questions_out_of_scope": out_of_scope,
        "unknown_prefixes": unknown_prefixes,
    }


def _flatten(stats: dict, prefix: str = "") -> dict[str, int]:
    flat: dict[str, int] = {}
    for key, value in stats.items():
        if key == "unknown_prefixes":
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        else:
            flat[path] = value
    return flat


def compute_delta(local_stats: dict, upstream_stats: dict) -> dict[str, dict[str, int]]:
    """逐指标 delta = 上游 − 本地（0 = 该指标无变化）。未知前缀单独点名，不算数值 delta。"""

    local = _flatten(local_stats)
    upstream = _flatten(upstream_stats)
    return {
        key: {
            "local": local.get(key, 0),
            "upstream": upstream.get(key, 0),
            "delta": upstream.get(key, 0) - local.get(key, 0),
        }
        for key in sorted(set(local) | set(upstream))
    }


def merge_unknown_prefixes(*stats: dict) -> dict[str, int]:
    merged: dict[str, int] = {}
    for stat in stats:
        for prefix, count in stat.get("unknown_prefixes", {}).items():
            merged[prefix] = merged.get(prefix, 0) + count
    return dict(sorted(merged.items()))


# ---------------------------------------------------------------------------
# 输入读取（只读）与网络薄壳：网络层只做 GET + JSON 解码，无业务逻辑。
# ---------------------------------------------------------------------------


def load_pinned(source_path: Path) -> str:
    """从 _source.json 读 upstream_commit；缺文件/缺键/null 一律明确报错，不硬编码不猜。"""

    if not source_path.is_file():
        raise CheckError(f"找不到 {source_path}（无法读取钉死快照 upstream_commit）")
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CheckError(f"{source_path} 不是合法 JSON: {exc}") from exc
    commit = source.get("upstream_commit") if isinstance(source, dict) else None
    if not isinstance(commit, str) or not commit:
        raise CheckError(
            f"{source_path} 缺少非空 upstream_commit 键（探测失败的历史快照须先按 §19-F-1 取证钉死）"
        )
    return commit


def read_local_data(data_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in SNAPSHOT_FILES:
        path = data_dir / f"{name}.json"
        if not path.is_file():
            raise CheckError(f"找不到 {path}")
        try:
            data[name] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CheckError(f"{path} 不是合法 JSON: {exc}") from exc
    return data


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "wengu-check-upstream",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = "（403 通常为 GitHub API 限流，稍后重试；不猜、不当已同步）" if exc.code == 403 else ""
        raise CheckError(f"HTTP {exc.code} 请求 {url}{hint}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CheckError(f"网络失败，无法检查上游（不猜、不当已同步）: {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"响应不是合法 JSON: {url}: {exc}") from exc


def fetch_snapshot(sha: str) -> dict[str, Any]:
    return {
        name: fetch_json(RAW_URL_TEMPLATE.format(sha=sha, name=name))
        for name in SNAPSHOT_FILES
    }


# ---------------------------------------------------------------------------
# 报告与 CLI
# ---------------------------------------------------------------------------


def local_stats(data: dict[str, Any]) -> dict:
    topics = summarize_topics(data["topics"])
    deps = summarize_dependencies(data["dependencies"])
    questions = summarize_questions(data["questions"], data["topics"])
    # topics 与 questions 各自点名未知前缀，合并时不得互相覆盖。
    unknown = merge_unknown_prefixes(topics, questions)
    return {**topics, **deps, **questions, "unknown_prefixes": unknown}


def upstream_stats(snapshot: dict[str, Any]) -> dict:
    return local_stats(snapshot)


def build_report(
    mode: str,
    pinned: str | None,
    latest: tuple[str, str] | None,
    local: dict,
    upstream: dict | None,
) -> dict:
    delta = compute_delta(local, upstream) if upstream is not None else None
    unknown = (
        merge_unknown_prefixes(local, upstream) if upstream is not None else {}
    )
    return {
        "mode": mode,
        "pinned": pinned,
        "latest": {"sha": latest[0], "date": latest[1]} if latest else None,
        "local": local,
        "upstream": upstream,
        "delta": delta,
        "unknown_prefixes": unknown,
    }


def print_human_report(report: dict) -> None:
    print(f"wengu 上游更新检查 · {UPSTREAM_REPO}")
    if report["pinned"]:
        label = (
            "复检快照（--pinned）"
            if report["mode"] == "pinned"
            else "钉死快照（_source.json upstream_commit）"
        )
        print(f"{label}: {report['pinned']}")
    if report["latest"]:
        print(
            f"上游最新触及 data/ 的 commit: {report['latest']['sha']}"
            f"（{report['latest']['date']}）"
        )
    if report["mode"] == "synced":
        print("结论：已同步（上游最新 data/ commit == 钉死快照）。")
        return
    if report["mode"] == "pinned":
        print(f"复检模式：对比 upstream@{report['pinned']} 与仓内 seeds/data（只算不写）。")
    else:
        print("结论：上游有更新。以下为最新快照 vs 仓内数据（只算不写）：")
    print(f"{'指标':<36}{'本地':>8}{'上游':>8}{'delta':>8}")
    for key, row in report["delta"].items():
        print(f"{key:<36}{row['local']:>8}{row['upstream']:>8}{row['delta']:>+8}")
    if report["unknown_prefixes"]:
        named = "、".join(f"{p} ×{n}" for p, n in report["unknown_prefixes"].items())
        print(f"未知前缀（SUBJECT_BY_PREFIX 之外，点名上报、不引入）: {named}")
    nonzero = [k for k, row in report["delta"].items() if row["delta"] != 0]
    if report["mode"] == "pinned":
        if not nonzero and not report["unknown_prefixes"]:
            print("复检结论：快照一致，delta 全 0。")
        else:
            print(f"复检结论：快照不一致（非零 delta: {nonzero or '无'}），须人工核查。")
    print(
        "提醒：同步永远是另一票——重导入 + 按设计文档 §19-F-1 重新取证 + 重新策展，人工决定；"
        "本脚本对 seeds/data/ 零写入。"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 cn-math-taxonomy 上游是否更新（只读、零写入）")
    parser.add_argument(
        "--pinned",
        default=None,
        metavar="SHA",
        help="复检模式：对比指定上游快照与仓内数据（自证快照一致性；delta 全 0 → exit 0）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 报告")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = read_local_data(DEFAULT_DATA_DIR)
        local = local_stats(data)
        if args.pinned:
            snapshot = fetch_snapshot(args.pinned)
            upstream = upstream_stats(snapshot)
            report = build_report("pinned", args.pinned, None, local, upstream)
            consistent = all(
                row["delta"] == 0 for row in report["delta"].values()
            ) and not report["unknown_prefixes"]
            exit_code = 0 if consistent else 1
        else:
            pinned = load_pinned(DEFAULT_SOURCE)
            latest = parse_latest_commit(fetch_json(COMMITS_API_URL))
            if latest[0] == pinned:
                report = build_report("synced", pinned, latest, local, None)
                exit_code = 0
            else:
                snapshot = fetch_snapshot(latest[0])
                upstream = upstream_stats(snapshot)
                report = build_report("update", pinned, latest, local, upstream)
                exit_code = 1
    except CheckError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print_human_report(report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
