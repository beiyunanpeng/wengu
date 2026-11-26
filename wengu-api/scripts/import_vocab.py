"""P6-1 构建期编排：vendored 词表 + ECDICT + engra → seeds/vocab。

开发者本地运行，不进运行时、镜像、requirements 或 CI：
    python wengu-api/scripts/import_vocab.py --ecdict-dir ../ECDICT --engra-dir ../engra
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from scripts.vocab_extract import SeedConvertError
    from scripts.vocab_extract.build_levels import build_levels
    from scripts.vocab_extract.vocab_join import join_levels
except ModuleNotFoundError:
    from vocab_extract import SeedConvertError
    from vocab_extract.build_levels import build_levels
    from vocab_extract.vocab_join import join_levels

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "seeds" / "vocab"
VERBATIM_BY_SOURCE = {
    "ecdict": "official-repo",
    "engra": "official-repo",
    "primary": "official-repo",
    "junior": "derived-from-transcription",
    "supplement": "ocr",
    "senior": "official-pdf-verbatim",
}


def upstream_commit(src: Path, override: str | None = None) -> str | None:
    if override:
        return override
    try:
        commit = (
            subprocess.run(
                ["git", "-C", str(src), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
            or None
        )
    except OSError:
        commit = None
    if commit is None:
        print(
            f"警告：{src} 探测不到 git commit（无 .git 或非 git 仓库），upstream_commit 写 null；"
            "zip 来源请显式传 --upstream-commit <sha>，严禁按导入日期猜测。",
            file=sys.stderr,
        )
    return commit


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedConvertError(f"JSON 读取失败：{path}") from exc
    if not isinstance(value, dict):
        raise SeedConvertError(f"JSON 顶层必须是 object：{path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_vendored(out_dir: Path, source: dict) -> None:
    upstream_dir = (out_dir / "_upstream").resolve()
    for name, evidence in source["vendored"].items():
        relative = evidence["path"]
        path = (out_dir / relative).resolve()
        if path.parent != upstream_dir or path.name != name:
            raise SeedConvertError(f"vendored 路径越界或文件名不一致：{relative}")
        if not path.is_file():
            raise SeedConvertError(f"vendored 文件缺失：{relative}")
        actual_hash = sha256_file(path)
        actual_bytes = path.stat().st_size
        if actual_hash != evidence["sha256"] or actual_bytes != evidence["bytes"]:
            raise SeedConvertError(
                f"vendored sha256/bytes 不一致：{name}；"
                f"expected {evidence['sha256']}/{evidence['bytes']}，actual {actual_hash}/{actual_bytes}"
            )


def _verify_input_file(path: Path, evidence: dict) -> None:
    if not path.is_file():
        raise SeedConvertError(f"上游输入缺失：{path}")
    if sha256_file(path) != evidence["sha256"] or path.stat().st_size != evidence["bytes"]:
        raise SeedConvertError(f"上游输入 sha256/bytes 不一致：{path}")


def _verify_commit(repo: Path, expected: str, override: str | None, label: str) -> str:
    actual = upstream_commit(repo, override)
    if actual != expected:
        raise SeedConvertError(f"{label} commit 漂移：expected {expected}，actual {actual}")
    return expected


def _git_bytes(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:
        raise SeedConvertError(f"无法读取 engra git 仓库：{repo}") from exc
    if result.returncode != 0:
        raise SeedConvertError(f"engra git 命令失败：{' '.join(args)}")
    return result.stdout


def read_engra_files(repo: Path) -> dict[str, bytes]:
    listing = _git_bytes(repo, "ls-tree", "-r", "HEAD", "--", "dict/roots").decode("utf-8")
    blobs = []
    for line in listing.splitlines():
        metadata, path = line.split("\t", 1)
        _mode, kind, object_id = metadata.split()
        if kind == "blob" and path.endswith(".yml"):
            blobs.append((object_id, path))
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            input="".join(f"{object_id}\n" for object_id, _ in blobs).encode("ascii"),
            capture_output=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:
        raise SeedConvertError(f"无法读取 engra git 仓库：{repo}") from exc
    if result.returncode != 0:
        raise SeedConvertError("engra git cat-file --batch 失败")
    data = result.stdout
    position = 0
    files: dict[str, bytes] = {}
    for object_id, path in blobs:
        newline = data.index(b"\n", position)
        header = data[position:newline].decode("ascii").split()
        if len(header) != 3 or header[0] != object_id or header[1] != "blob":
            raise SeedConvertError(f"engra blob 响应异常：{path}")
        size = int(header[2])
        start = newline + 1
        files[path] = data[start : start + size]
        position = start + size + 1
    if len(files) != len(blobs):
        raise SeedConvertError("engra cat-file 未覆盖全部 roots/*.yml（含 Windows 保留名文件）")
    return files


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_engra_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()
        is_sequence_item = content.startswith("- ")
        while stack[-1][0] > indent or (
            stack[-1][0] == indent and isinstance(stack[-1][1], list) != is_sequence_item
        ):
            stack.pop()
        parent = stack[-1][1]
        if content.startswith("- ") and not re.match(r"- [A-Za-z_][\w-]*:", content):
            if not isinstance(parent, list):
                raise SeedConvertError("engra YAML 标量列表位置错误")
            parent.append(_scalar(content[2:]))
            continue
        if content.startswith("- "):
            content = content[2:]
        match = re.fullmatch(r"([A-Za-z_][\w-]*):(?:\s*(.*))?", content)
        if match is None:
            raise SeedConvertError(f"engra YAML 不支持的行：{content}")
        key, raw_value = match.group(1), match.group(2)
        is_item = is_sequence_item
        if is_item:
            if not isinstance(parent, list):
                raise SeedConvertError("engra YAML 映射列表位置错误")
            item: dict = {}
            parent.append(item)
            stack.append((indent, item))
            parent = item
        if raw_value:
            parent[key] = _scalar(raw_value)
            continue
        next_content = ""
        for following in lines[index + 1 :]:
            if following.strip() and not following.lstrip().startswith("#"):
                next_content = following.strip()
                break
        child: list | dict = [] if next_content.startswith("- ") else {}
        parent[key] = child
        stack.append((indent, child))
    return root


def _flatten_node(node: dict, root_name: str, path: tuple[str, ...]) -> list[dict]:
    word = node.get("name")
    if not isinstance(word, str) or not word:
        raise SeedConvertError("engra 节点缺 name")
    current = (*path, word)
    rows = [
        {
            "word": word,
            "root": root_name,
            "path": list(current),
            "phonetic": node.get("phonetic"),
            "mnemonic": node.get("mnemonic"),
            "meaning": node.get("meaning"),
        }
    ]
    for child in node.get("children") or []:
        rows.extend(_flatten_node(child, root_name, current))
    return rows


def _manifest_sha256(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[path]).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_roots(files: dict[str, bytes], commit: str) -> dict:
    families = []
    for path in sorted(files):
        tree = parse_engra_yaml(files[path].decode("utf-8"))
        root_name = tree.get("name")
        if not isinstance(root_name, str) or not root_name:
            raise SeedConvertError(f"engra 词根文件缺 name：{path}")
        words = _flatten_node(tree, root_name, ())
        words.sort(key=lambda row: (tuple(part.casefold() for part in row["path"]), row["path"]))
        families.append(
            {
                "root": root_name,
                "root_meaning": tree.get("meaning"),
                "tags": tree.get("tags") or [],
                "source_file": path,
                "source_sha256": hashlib.sha256(files[path]).hexdigest(),
                "words": words,
            }
        )
    families.sort(key=lambda family: (family["root"].casefold(), family["root"]))
    word_nodes = sum(len(family["words"]) for family in families)
    return {
        "meta": {
            "source": "bonaysoft/engra",
            "upstream_commit": commit,
            "license": "MIT",
            "verbatim": "official-repo",
            "count": len(families),
            "counts": {"families": len(families), "word_nodes": word_nodes},
            "source_manifest_sha256": _manifest_sha256(files),
            "note": "只保证快照 sha256 与条数一致；家族到单词的映射质量归 P6-3 复核",
        },
        "families": families,
    }


def build_wordroot(data: dict, commit: str) -> dict:
    entries = []
    for key in sorted(data, key=lambda value: (value.casefold(), value)):
        value = data[key]
        if not isinstance(value, dict):
            raise SeedConvertError(f"wordroot 条目必须是 object：{key}")
        entries.append({"key": key, **value})
    return {
        "meta": {
            "source": "skywind3000/ECDICT wordroot.txt",
            "upstream_commit": commit,
            "license": "MIT",
            "verbatim": "official-repo",
            "count": len(entries),
            "counts": {"entries": len(entries)},
        },
        "entries": entries,
    }


def _verify_source_literals(source: dict, supplement: dict, levels: dict) -> None:
    for name, expected in VERBATIM_BY_SOURCE.items():
        actual = source["sources"][name]["verbatim"]
        if actual != expected:
            raise SeedConvertError(f"{name} verbatim 漂移：expected {expected}，actual {actual}")
    if supplement.get("meta", {}).get("unaudited") is not True:
        raise SeedConvertError("补充块 meta 必须 unaudited=true")
    block_rows = [row for row in levels["words"] if row.get("block")]
    if not all(row.get("unaudited") is True for row in block_rows):
        raise SeedConvertError("补充块 levels 行必须全部 unaudited=true")


def _derived_counts(levels: dict, words: dict, roots: dict, wordroot: dict, junior: dict) -> dict:
    return {
        **levels["meta"]["counts"],
        **words["meta"]["counts"],
        "root_families": roots["meta"]["counts"]["families"],
        "root_word_nodes": roots["meta"]["counts"]["word_nodes"],
        "wordroot_entries": wordroot["meta"]["counts"]["entries"],
        "junior_rows": len(junior["words"]),
        "junior_official_word_count": junior["meta"]["official_word_count"],
        "junior_level2_marked": junior["meta"]["level2_count"],
    }


def convert(out_dir: Path, ecdict_dir: Path, engra_dir: Path, ecdict_commit: str | None, engra_commit: str | None) -> dict:
    source = _read_json(out_dir / "_source_vocab.json")
    verify_vendored(out_dir, source)
    for name, evidence in source["inputs"]["ecdict"]["files"].items():
        _verify_input_file(ecdict_dir / name, evidence)
    wordroot = _read_json(ecdict_dir / "wordroot.txt")
    ecdict_sha = _verify_commit(ecdict_dir, source["inputs"]["ecdict"]["commit"], ecdict_commit, "ECDICT")
    engra_sha = _verify_commit(engra_dir, source["inputs"]["engra"]["commit"], engra_commit, "engra")

    upstream = out_dir / "_upstream"
    primary = _read_json(upstream / "vocab-level2.json")
    junior = _read_json(upstream / "kebiao-level3-1600.json")
    senior = _read_json(upstream / "gsenior-2020-OFFICIAL.json")
    supplement = _read_json(upstream / "kebiao-junior-supplement.json")
    levels = build_levels(primary, junior, senior, supplement)
    words, unmatched, no_detail = join_levels(levels, ecdict_dir / "ecdict.csv")
    words["meta"]["upstream_commit"] = ecdict_sha

    engra_files = read_engra_files(engra_dir)
    roots = build_roots(engra_files, engra_sha)
    wordroot_doc = build_wordroot(wordroot, ecdict_sha)

    engra_evidence = source["inputs"]["engra"]
    if len(engra_files) != engra_evidence["roots_files"]:
        raise SeedConvertError("engra roots/*.yml 文件数与 _source_vocab.json 不一致")
    if roots["meta"]["source_manifest_sha256"] != engra_evidence["source_manifest_sha256"]:
        raise SeedConvertError("engra roots 清单 sha256 与 _source_vocab.json 不一致")
    wordroot_evidence = source["inputs"]["ecdict"]["files"]["wordroot.txt"]
    if len(wordroot) != wordroot_evidence["entries"]:
        raise SeedConvertError("ECDICT wordroot 条目数与 _source_vocab.json 不一致")
    primary_evidence = source["sources"]["primary"]["counts"]
    if primary["count"] != primary_evidence["words"] or len(primary["words"]) != primary_evidence["words"]:
        raise SeedConvertError("小学档 count/words 与 _source_vocab.json 实收数不一致")
    junior_evidence = source["sources"]["junior"]["counts"]
    if (
        junior["meta"]["rows"] != junior_evidence["rows"]
        or junior["meta"]["official_word_count"] != junior_evidence["official_word_count"]
        or junior["meta"]["level2_count"] != junior_evidence["level2_marked"]
        or junior["meta"]["transcript_sha256"] != source["transcript"]["sha256"]
    ):
        raise SeedConvertError("初中正文 provenance/counts 与 _source_vocab.json 不一致")
    regenerated = source["regenerated_from_transcript"]
    if source["vendored"]["kebiao-level3-1600.json"]["sha256"] != regenerated["new_vendored_sha256"]:
        raise SeedConvertError("初中重发射新 sha256 与 _source_vocab.json 不一致")

    _verify_source_literals(source, supplement, levels)
    levels_by_word = {row["word"]: row for row in levels["words"]}
    nonblock_unmatched = {word for word in unmatched if not levels_by_word[word]["block"]}
    if nonblock_unmatched:
        raise SeedConvertError(f"非 block 三档两级查找仍有缺口：{sorted(nonblock_unmatched)}")
    if no_detail != source["no_detail"]:
        raise SeedConvertError("words.json 全 null 详情集合与 _source_vocab.json.no_detail 不一致")
    counts = _derived_counts(levels, words, roots, wordroot_doc, junior)
    if counts != source["counts"]:
        raise SeedConvertError(f"counts 与 _source_vocab.json 不一致：derived={counts}")

    for name, document in (
        ("levels.json", levels),
        ("words.json", words),
        ("roots.json", roots),
        ("wordroot_meaning.json", wordroot_doc),
    ):
        _write_json(out_dir / name, document)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ecdict-dir", type=Path, required=True)
    parser.add_argument("--engra-dir", type=Path, required=True)
    parser.add_argument("--ecdict-commit", default=None)
    parser.add_argument("--engra-commit", default=None)
    args = parser.parse_args(argv)
    try:
        counts = convert(args.out, args.ecdict_dir, args.engra_dir, args.ecdict_commit, args.engra_commit)
    except (KeyError, TypeError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(counts, ensure_ascii=False, indent=1))
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
