"""P5-12 上游更新检查脚本守卫：解析/delta 字面钉死 / 未知前缀点名 / 零写入 / 编排三态。

网络层薄壳（fetch_json/fetch_snapshot）不进单测；main 编排用 monkeypatch 在网络边界打桩。
断言一律字面钉死（设计文档 §19-L 纪律①）；变异证伪记录见交付报告。
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from scripts import check_upstream, import_questions, import_seed
from scripts.check_upstream import (
    CheckError,
    band_of,
    build_parser,
    compute_delta,
    load_pinned,
    local_stats,
    merge_unknown_prefixes,
    parse_latest_commit,
    prefix_of,
    summarize_dependencies,
    summarize_questions,
    summarize_topics,
    upstream_stats,
)

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "seeds" / "data"
PINNED_SHA = "d58785cef744341bf02d41e5568ebb953595ab18"
LATEST_PAYLOAD = [
    {
        "sha": PINNED_SHA,
        "commit": {
            "committer": {"date": "2026-10-23T12:40:17Z"},
            "author": {"date": "2026-10-23T12:40:17Z"},
        },
    }
]


@pytest.fixture(scope="module")
def repo_data() -> dict:
    return check_upstream.read_local_data(DATA_DIR)


def _project_upstream(data: dict) -> dict:
    """仓内真数据 → 上游 schema 投影（只保留 summarize 消费的键，camelCase）。"""

    return {
        "topics": [{"id": t["id"], "grade": t.get("grade")} for t in data["topics"]],
        "dependencies": [
            {"topicId": d["topic_id"], "prerequisiteId": d["prerequisite_id"]}
            for d in data["dependencies"]
        ],
        "questions": [
            {"id": q["id"], "topicId": q["topic_id"]} for q in data["questions"]
        ],
    }


# ---------------------------------------------------------------------------
# API 响应解析（纯函数）
# ---------------------------------------------------------------------------


def test_parse_latest_commit_literal() -> None:
    assert parse_latest_commit(LATEST_PAYLOAD) == (
        PINNED_SHA,
        "2026-10-23T12:40:17Z",
    )


def test_parse_latest_commit_author_date_fallback() -> None:
    payload = [{"sha": "abc123", "commit": {"author": {"date": "2026-10-24T00:00:00Z"}}}]
    assert parse_latest_commit(payload) == ("abc123", "2026-10-24T00:00:00Z")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        None,
        "not-a-list",
        [{"commit": {"committer": {"date": "2026-10-23T12:40:17Z"}}}],
        [{"sha": 123, "commit": {"committer": {"date": "2026-10-23T12:40:17Z"}}}],
        [{"sha": "abc123"}],
        [{"sha": "abc123", "commit": {"committer": {}}}],
    ],
)
def test_parse_latest_commit_rejects_malformed(payload: object) -> None:
    with pytest.raises(CheckError):
        parse_latest_commit(payload)


# ---------------------------------------------------------------------------
# 分带 / 分科 / 未知前缀（纯函数，字面钉死）
# ---------------------------------------------------------------------------


def test_prefix_of_literal() -> None:
    assert prefix_of("cnm_001") == "cnm_"
    assert prefix_of("cnl_j001") == "cnl_"
    assert prefix_of("weird") == "weird"


def test_band_of_literal() -> None:
    assert band_of(1) == "primary"
    assert band_of(6) == "primary"
    assert band_of(7) == "junior"
    assert band_of(9) == "junior"
    assert band_of(10) == "senior"
    assert band_of(16) == "senior"
    assert band_of(None) == "unknown"
    assert band_of(17) == "unknown"


def test_summarize_topics_bands_and_subjects_literal() -> None:
    topics = [
        {"id": "cnm_001", "grade": 7},
        {"id": "cne_001", "grade": 3},
        {"id": "cnp_001", "grade": 12},
        {"id": "cnm_002", "grade": None},
    ]
    assert summarize_topics(topics) == {
        "topics_total": 4,
        "topics_by_band": {"primary": 1, "junior": 1, "senior": 1, "unknown": 1},
        "topics_by_subject": {"数学": 2, "英语": 1, "物理": 1},
        "unknown_prefixes": {},
    }


def test_unknown_prefix_cnl_is_named_not_imported() -> None:
    """cnl_/cnc_ fixture 必须被点名（删检测 → 本测试红）；只报告、不进分科。"""

    topics = [
        {"id": "cnm_001", "grade": 7},
        {"id": "cnl_001", "grade": 7},
        {"id": "cnl_002", "grade": 8},
        {"id": "cnc_001", "grade": 9},
    ]
    stats = summarize_topics(topics)
    assert stats["unknown_prefixes"] == {"cnl_": 2, "cnc_": 1}
    assert stats["topics_total"] == 4
    assert stats["topics_by_subject"] == {"数学": 1, "英语": 0, "物理": 0}
    assert "语文" not in stats["topics_by_subject"]


def test_summarize_questions_both_key_styles_literal() -> None:
    topics = [{"id": "cnm_001", "grade": 7}, {"id": "cne_001", "grade": 3}]
    upstream_style = [
        {"id": "cnm_001_q1", "topicId": "cnm_001"},
        {"id": "cne_001_q1", "topicId": "cne_001"},
        {"id": "cnm_001_q2", "topicId": "cnm_999"},
    ]
    local_style = [
        {"id": "cnm_001_q1", "topic_id": "cnm_001"},
        {"id": "cne_001_q1", "topic_id": "cne_001"},
        {"id": "cnm_001_q2", "topic_id": "cnm_999"},
    ]
    expected = {
        "questions_total": 3,
        "questions_by_band": {"primary": 1, "junior": 1, "senior": 0, "unknown": 1},
        "questions_by_subject": {"数学": 2, "英语": 1, "物理": 0},
        "questions_out_of_scope": 1,
        "unknown_prefixes": {},
    }
    assert summarize_questions(upstream_style, topics) == expected
    assert summarize_questions(local_style, topics) == expected


def test_summarize_questions_unknown_prefix_named() -> None:
    topics = [{"id": "cnl_001", "grade": 7}]
    questions = [{"id": "cnl_001_q1", "topicId": "cnl_001"}]
    stats = summarize_questions(questions, topics)
    assert stats["unknown_prefixes"] == {"cnl_": 1}
    assert stats["questions_by_subject"] == {"数学": 0, "英语": 0, "物理": 0}


def test_local_stats_merges_unknown_prefixes_from_both() -> None:
    data = {
        "topics": [{"id": "cnl_001", "grade": 7}],
        "dependencies": [],
        "questions": [{"id": "cnc_001_q1", "topicId": "cnc_001"}],
    }
    stats = local_stats(data)
    assert stats["unknown_prefixes"] == {"cnl_": 1, "cnc_": 1}


def test_summarize_dependencies_literal() -> None:
    assert summarize_dependencies([{"topicId": "a", "prerequisiteId": "b"}]) == {
        "deps_total": 1
    }
    assert summarize_dependencies([]) == {"deps_total": 0}


@pytest.mark.parametrize(
    "func,args",
    [
        (summarize_topics, ({},)),
        (summarize_dependencies, ({},)),
        (summarize_questions, ([], {})),
    ],
)
def test_summarize_rejects_non_list(func: object, args: tuple) -> None:
    with pytest.raises(CheckError):
        func(*args)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# delta 计算（纯函数，字面钉死）
# ---------------------------------------------------------------------------


def test_compute_delta_literal_nonzero() -> None:
    local = summarize_topics(
        [{"id": "cnm_001", "grade": 7}, {"id": "cne_001", "grade": 3}]
    )
    upstream = summarize_topics(
        [
            {"id": "cnm_001", "grade": 7},
            {"id": "cne_001", "grade": 3},
            {"id": "cnl_001", "grade": 7},
        ]
    )
    delta = compute_delta(local, upstream)
    assert delta["topics_total"] == {"local": 2, "upstream": 3, "delta": 1}
    assert delta["topics_by_band.junior"] == {"local": 1, "upstream": 2, "delta": 1}
    assert delta["topics_by_band.primary"] == {"local": 1, "upstream": 1, "delta": 0}
    assert delta["topics_by_subject.数学"] == {"local": 1, "upstream": 1, "delta": 0}
    assert all("unknown_prefixes" not in key for key in delta)
    assert merge_unknown_prefixes(local, upstream) == {"cnl_": 1}


def test_repo_local_stats_literal_equals_source_counts(repo_data: dict) -> None:
    """纪律①：仓内真数据算出的数字字面 == 两个 source JSON 的 counts。"""

    stats = local_stats(repo_data)
    assert stats["topics_total"] == 1821
    assert stats["topics_by_band"] == {"primary": 450, "junior": 664, "senior": 707}
    assert stats["topics_by_subject"] == {"数学": 828, "英语": 724, "物理": 269}
    assert stats["deps_total"] == 2917
    assert stats["questions_total"] == 7431
    assert stats["questions_by_band"] == {
        "primary": 1800,
        "junior": 2803,
        "senior": 2828,
    }
    assert stats["questions_by_subject"] == {"数学": 3459, "英语": 2896, "物理": 1076}
    assert stats["questions_out_of_scope"] == 0
    assert merge_unknown_prefixes(stats) == {}

    source = json.loads((DATA_DIR / "_source.json").read_text(encoding="utf-8"))
    qsource = json.loads(
        (DATA_DIR / "questions_source.json").read_text(encoding="utf-8")
    )
    counts = source["counts"]
    assert stats["topics_total"] == counts["topics_imported"]
    assert stats["topics_by_band"] == counts["topics_by_band"]
    assert stats["topics_by_subject"] == counts["topics_by_subject"]
    assert stats["deps_total"] == counts["dependencies_imported"]
    qcounts = qsource["counts"]
    assert stats["questions_total"] == qcounts["questions_imported"]
    assert stats["questions_by_band"] == qcounts["questions_by_band"]
    assert stats["questions_by_subject"] == qcounts["questions_by_subject"]
    assert source["upstream_commit"] == PINNED_SHA


def test_pinned_snapshot_projection_delta_all_zero(repo_data: dict) -> None:
    """纪律①：d58785ce 快照（上游 schema 投影）vs 仓内真数据，delta 必须全 0。

    离线版自证：投影只保留 summarize 消费的键（id/grade/topicId），验证两种 schema
    同尺。在线版自证 = 实跑 `--pinned d58785ce…`（DoD，下载 raw 真快照）。
    """

    local = local_stats(repo_data)
    upstream = upstream_stats(_project_upstream(repo_data))
    delta = compute_delta(local, upstream)
    assert delta, "delta 表不得为空"
    assert all(row["delta"] == 0 for row in delta.values()), delta
    assert all(row["local"] == row["upstream"] for row in delta.values())
    assert "topics_total" in delta
    assert "questions_by_band.junior" in delta
    assert merge_unknown_prefixes(local, upstream) == {}


# ---------------------------------------------------------------------------
# pinned sha 从 _source.json 读取（tmp fixture；不硬编码）
# ---------------------------------------------------------------------------


def test_load_pinned_reads_tmp_source(tmp_path: Path) -> None:
    source = tmp_path / "_source.json"
    source.write_text(
        json.dumps({"upstream_commit": "abc123def456"}), encoding="utf-8"
    )
    assert load_pinned(source) == "abc123def456"


def test_load_pinned_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CheckError, match="找不到"):
        load_pinned(tmp_path / "nope.json")


@pytest.mark.parametrize("content", ["{}", '{"upstream_commit": null}', '{"upstream_commit": 42}', '{"upstream_commit": ""}', "not-json"])
def test_load_pinned_missing_or_invalid_key(tmp_path: Path, content: str) -> None:
    source = tmp_path / "_source.json"
    source.write_text(content, encoding="utf-8")
    with pytest.raises(CheckError):
        load_pinned(source)


# ---------------------------------------------------------------------------
# 零写入守卫 + 常量漂移守卫
# ---------------------------------------------------------------------------


def test_compute_functions_accept_no_output_path() -> None:
    """计算函数只吃数据结构：无任何 Path 参数、无 out/output/dest/write 参数名。"""

    funcs = [
        parse_latest_commit,
        prefix_of,
        band_of,
        summarize_topics,
        summarize_dependencies,
        summarize_questions,
        compute_delta,
        merge_unknown_prefixes,
        local_stats,
        upstream_stats,
    ]
    for func in funcs:
        for name, param in inspect.signature(func).parameters.items():
            assert not re.search(r"out|output|dest|write", name, re.IGNORECASE), (
                func.__name__,
                name,
            )
            assert param.annotation not in (Path, "Path"), (func.__name__, name)


def test_cli_has_no_write_path_option() -> None:
    options = [opt for action in build_parser()._actions for opt in action.option_strings]
    assert options == ["-h", "--help", "--pinned", "--json"]
    assert not any(re.search(r"out|output|dest|cache", opt) for opt in options)


def test_script_source_has_no_write_calls() -> None:
    source = Path(check_upstream.__file__).read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "write_bytes" not in source
    assert ".mkdir(" not in source
    assert re.search(r"\bopen\(", source) is None  # urlopen 不算；内置 open 一律禁


def test_constants_match_import_scripts() -> None:
    assert check_upstream.SUBJECT_BY_PREFIX == import_seed.SUBJECT_BY_PREFIX
    assert check_upstream.SUBJECT_BY_PREFIX == import_questions.SUBJECT_BY_PREFIX
    assert check_upstream.GRADE_BANDS == import_seed.GRADE_BANDS
    assert check_upstream.GRADE_BANDS == import_questions.GRADE_BANDS


# ---------------------------------------------------------------------------
# main 编排三态（网络边界 monkeypatch，不真联网）
# ---------------------------------------------------------------------------


def _fake_fetch_factory(repo_data: dict, latest_sha: str):
    projected = _project_upstream(repo_data)

    def fake_fetch(url: str) -> object:
        if url == check_upstream.COMMITS_API_URL:
            return [
                {
                    "sha": latest_sha,
                    "commit": {"committer": {"date": "2026-10-23T12:40:17Z"}},
                }
            ]
        for name in check_upstream.SNAPSHOT_FILES:
            if url == check_upstream.RAW_URL_TEMPLATE.format(sha=latest_sha, name=name):
                return projected[name]
        raise AssertionError(f"unexpected url: {url}")

    return fake_fetch


def test_main_synced_exit_0(
    monkeypatch: pytest.MonkeyPatch, repo_data: dict, capsys: pytest.CaptureFixture
) -> None:
    pinned = load_pinned(check_upstream.DEFAULT_SOURCE)
    monkeypatch.setattr(check_upstream, "fetch_json", _fake_fetch_factory(repo_data, pinned))
    assert check_upstream.main([]) == 0
    out = capsys.readouterr().out
    assert "已同步" in out
    assert pinned in out


def test_main_update_exit_1_even_when_delta_zero(
    monkeypatch: pytest.MonkeyPatch, repo_data: dict, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        check_upstream, "fetch_json", _fake_fetch_factory(repo_data, "f" * 40)
    )
    assert check_upstream.main([]) == 1
    out = capsys.readouterr().out
    assert "上游有更新" in out
    assert "1821" in out and "7431" in out and "2917" in out


def test_main_pinned_recheck_exit_0(
    monkeypatch: pytest.MonkeyPatch, repo_data: dict, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        check_upstream, "fetch_json", _fake_fetch_factory(repo_data, PINNED_SHA)
    )
    assert check_upstream.main(["--pinned", PINNED_SHA]) == 0
    out = capsys.readouterr().out
    assert "delta 全 0" in out
    for literal in ("1821", "450", "664", "707", "2917", "7431", "1800", "2803", "2828"):
        assert literal in out


def test_main_pinned_mismatch_names_cnl_exit_1(
    monkeypatch: pytest.MonkeyPatch, repo_data: dict, capsys: pytest.CaptureFixture
) -> None:
    projected = _project_upstream(repo_data)
    projected["topics"] = projected["topics"] + [{"id": "cnl_001", "grade": 7}]

    def fake_fetch(url: str) -> object:
        for name in check_upstream.SNAPSHOT_FILES:
            if url == check_upstream.RAW_URL_TEMPLATE.format(sha=PINNED_SHA, name=name):
                return projected[name]
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(check_upstream, "fetch_json", fake_fetch)
    assert check_upstream.main(["--pinned", PINNED_SHA]) == 1
    out = capsys.readouterr().out
    assert "cnl_" in out
    assert "快照不一致" in out


def test_main_network_error_exit_2_not_synced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def boom(url: str) -> object:
        raise CheckError("HTTP 403（限流）")

    monkeypatch.setattr(check_upstream, "fetch_json", boom)
    assert check_upstream.main([]) == 2
    captured = capsys.readouterr()
    assert "错误" in captured.err
    assert "已同步" not in captured.out


def test_main_missing_source_exit_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(check_upstream, "DEFAULT_SOURCE", tmp_path / "absent.json")
    assert check_upstream.main([]) == 2
    assert "找不到" in capsys.readouterr().err


def test_main_json_report_synced(
    monkeypatch: pytest.MonkeyPatch, repo_data: dict, capsys: pytest.CaptureFixture
) -> None:
    pinned = load_pinned(check_upstream.DEFAULT_SOURCE)
    monkeypatch.setattr(check_upstream, "fetch_json", _fake_fetch_factory(repo_data, pinned))
    assert check_upstream.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "synced"
    assert report["pinned"] == pinned
    assert report["latest"]["sha"] == pinned
    assert report["local"]["topics_total"] == 1821
    assert report["delta"] is None
