"""P5-17 行尾根治守卫：全仓文本 LF，例外有且仅有 topics_junior.tsv（CRLF）。

三层断言（卡面只写 HEAD blob 一层；实测 .gitattributes 生效后 git add 会把 CRLF
归一成 LF、index==HEAD，只查 blob 抓不到「塞 CRLF 并 add」，故加查工作区字节层）：
1. HEAD blob：tracked 文本文件 CRLF 计数为 0，例外白名单式钉死；
2. 工作区字节：同一清单同一把尺（P5-16 外部转换事故就是工作区先脏）；
3. 生成侧源码：两个 import 脚本不再出现 write_text(（防回退）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# 字面串白名单（§19-L 纪律①）：新增 CRLF 文件必须显式进例外才放行
CRLF_EXCEPTIONS = {"docs/templates/topics_junior.tsv"}

REQUIRED_GITATTRIBUTES_RULES = (
    "* text=auto eol=lf",
    "docs/templates/topics_junior.tsv -text",
    "*.ps1 text eol=lf",
    "*.png binary",
    "*.jpg binary",
    "*.gif binary",
    "*.ico binary",
)


def _git(*args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        input=stdin,
        capture_output=True,
        check=True,
    ).stdout


def _head_blobs() -> dict[str, bytes]:
    names = [
        n.decode("utf-8")
        for n in _git("ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
        if n
    ]
    out = _git("cat-file", "--batch", stdin="".join(f"HEAD:{n}\n" for n in names).encode("utf-8"))
    blobs: dict[str, bytes] = {}
    pos = 0
    for name in names:
        nl = out.index(b"\n", pos)
        size = int(out[pos:nl].split()[2])
        blobs[name] = out[nl + 1 : nl + 1 + size]
        pos = nl + 1 + size + 1  # batch 协议每条内容后跟一个 LF
    return blobs


def _is_binary(blob: bytes) -> bool:
    return b"\x00" in blob[:8000]


def test_gitattributes_key_rules() -> None:
    text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert set(REQUIRED_GITATTRIBUTES_RULES) <= set(rules)
    assert all("*.tsv" not in ln for ln in rules)  # 例外必须显式路径，防新 TSV 误继承
    # eol=crlf 只控工作区、add 仍把 blob 归一成 LF（本票实测踩中），例外只能用 -text
    assert all("eol=crlf" not in ln for ln in rules)


def test_head_text_blobs_have_no_crlf() -> None:
    blobs = _head_blobs()
    offenders = {
        name
        for name, blob in blobs.items()
        if not _is_binary(blob) and b"\r\n" in blob
    }
    # 集合相等双向钉死：多一个 CRLF 文件红；TSV 被 LF 化（例外落空）也红
    assert offenders == CRLF_EXCEPTIONS


def test_worktree_text_files_have_no_crlf() -> None:
    blobs = _head_blobs()
    offenders = set()
    for name, blob in blobs.items():
        if _is_binary(blob):
            continue
        if b"\r\n" in (REPO_ROOT / name).read_bytes():
            offenders.add(name)
    assert offenders == CRLF_EXCEPTIONS


def test_import_scripts_avoid_write_text() -> None:
    for rel in (
        "wengu-api/scripts/import_seed.py",
        "wengu-api/scripts/import_questions.py",
    ):
        assert "write_text(" not in (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_text_writers_pin_explicit_newline() -> None:
    """P5-17 折入：只禁 write_text 挡不住 newline 取值回退——把取值本身钉死。"""
    for rel in (
        "wengu-api/scripts/import_seed.py",
        "wengu-api/scripts/import_questions.py",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'newline="\\n"' in text, rel
        assert 'newline="\\r\\n"' not in text, rel
    export = (REPO_ROOT / "wengu-api/scripts/export_topics_junior.py").read_text(encoding="utf-8")
    assert 'newline="\\r\\n"' in export  # P5-10 定案：TSV 生成侧钉死 CRLF
