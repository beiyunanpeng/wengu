"""P5-5 开源基线收口守卫：LICENSE 纯净 / provenance 字面串 / 探测不猜 / 隐私声明 / 数据未扩。

断言一律字面串钉死（设计文档 §19-L 纪律①）；变异证伪记录见交付报告。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import import_questions, import_seed

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_SHA = "d58785cef744341bf02d41e5568ebb953595ab18"
SOURCE_PATHS = ["seeds/data/_source.json", "seeds/data/questions_source.json"]
PROVENANCE_KEYS = {
    "upstream_commit",
    "upstream_commit_date",
    "upstream_author",
    "upstream_spdx",
    "code_spdx",
    "modified",
    "disclaimer",
    "snapshot_source",
    "commit_evidence",
}
IMPORTERS = [import_seed, import_questions]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _source(rel: str) -> dict:
    return json.loads(_read(rel))


@pytest.mark.unit
def test_license_is_pure_mit() -> None:
    text = _read("LICENSE")
    assert "CC BY-NC" not in text
    assert "cn-math-taxonomy" not in text
    assert "Permission is hereby granted, free of charge" in text
    assert "Copyright (c) 2026 wengu (温故) contributors" in text


@pytest.mark.unit
@pytest.mark.parametrize("rel", SOURCE_PATHS)
def test_source_provenance_literals(rel: str) -> None:
    source = _source(rel)
    assert source["upstream_commit"] == UPSTREAM_SHA
    assert source["upstream_commit_date"] == "2026-10-23T12:40:17Z"
    assert source["upstream_spdx"] == "CC-BY-NC-4.0"
    assert source["code_spdx"] == "MIT"
    assert "Aifeng" in source["upstream_author"]
    assert "xiaoyang111222" in source["upstream_author"]
    assert source["snapshot_source"] == "GitHub zip of main（无 .git），upstream_commit 由内容寻址反查钉死"
    assert source["modified"]
    assert source["disclaimer"]
    assert "未经一线教师审核" in source["disclaimer"]
    evidence = source["commit_evidence"]
    assert isinstance(evidence, list) and evidence
    assert all(isinstance(item, str) and item for item in evidence)


@pytest.mark.unit
def test_provenance_keys_identical_in_both_sources() -> None:
    keysets = [set(_source(rel)) for rel in SOURCE_PATHS]
    for keys in keysets:
        assert keys >= PROVENANCE_KEYS
    assert keysets[0] & PROVENANCE_KEYS == keysets[1] & PROVENANCE_KEYS


@pytest.mark.unit
@pytest.mark.parametrize("rel", SOURCE_PATHS)
def test_commit_evidence_pins_blobs_and_parent(rel: str) -> None:
    evidence = "\n".join(_source(rel)["commit_evidence"])
    for literal in [
        "79cd0a87c89e3575fcbac17c738882489305d676",
        "76058ca51f98bfaf6ec52aad998143d5dc40ada5",
        "28cee1a857b2a05cbb798c738212704addec4a8a",
        "cc60a25e66c45ddfa5b45118ea39162daf9fa426",
        "7dc3d6adf5ea6ad96be5c27761143fbc8060625d",
        "76db74d1394e8e2084ae21753d03a73fc937e79c",
        UPSTREAM_SHA,
        "cnl_",
    ]:
        assert literal in evidence


@pytest.mark.unit
@pytest.mark.parametrize("module", IMPORTERS, ids=["import_seed", "import_questions"])
def test_detect_without_git_returns_none_and_warns(module, tmp_path: Path, capsys) -> None:
    assert module.upstream_commit(tmp_path) is None
    stderr = capsys.readouterr().err
    assert "警告" in stderr
    assert "null" in stderr
    assert "--upstream-commit" in stderr


@pytest.mark.unit
@pytest.mark.parametrize("module", IMPORTERS, ids=["import_seed", "import_questions"])
def test_detect_override_wins_without_git(module, tmp_path: Path) -> None:
    assert module.upstream_commit(tmp_path, override=UPSTREAM_SHA) == UPSTREAM_SHA


@pytest.mark.unit
@pytest.mark.parametrize("module", IMPORTERS, ids=["import_seed", "import_questions"])
def test_write_out_null_without_git_and_override_wins(module, tmp_path: Path) -> None:
    out = tmp_path / "out"
    src = tmp_path / "src"
    src.mkdir()
    name = "_source.json" if module is import_seed else "questions_source.json"

    module.write_out(out, module.ConvertResult(), src)
    assert json.loads((out / name).read_text(encoding="utf-8"))["upstream_commit"] is None

    module.write_out(out, module.ConvertResult(), src, commit_override=UPSTREAM_SHA)
    source = json.loads((out / name).read_text(encoding="utf-8"))
    assert source["upstream_commit"] == UPSTREAM_SHA
    # 策展 provenance 键是当前快照的取证工件，脚本不自动发射（换快照须按 §19-F-1 重新策展）
    assert "commit_evidence" not in source


@pytest.mark.unit
def test_readme_clone_url_real_and_no_placeholder() -> None:
    text = _read("README.md")
    assert "<你>" not in text
    assert "git clone https://github.com/beiyunanpeng/wengu.git" in text


@pytest.mark.unit
def test_privacy_positive_and_negative_assertions() -> None:
    text = _read("PRIVACY.md")
    for literal in ["数据本土化", "外部转录", "监护人同意", "离线"]:
        assert literal in text
    assert "题目图片不进网络" not in text
    assert "完全不上云" not in text
    assert "个人信息保护法" in text
    assert "未成年人网络保护条例" in text
    assert "Tailscale" in text


@pytest.mark.unit
def test_privacy_aligns_transcribe_checklist_and_fields() -> None:
    text = _read("PRIVACY.md")
    for literal in [
        "姓名", "学校", "班级", "学号", "座位号", "家长签名", "教师评语", "EXIF",
        "裁剪", "单独同意", "境内", "本地留存", "/import", "POST /api/imports",
        "subject", "problem_text", "student_answer", "standard_answer",
        "correction_notes", "error_cause_suggestion", "suggested_topic_id",
        "source_ref", "captured_at",
    ]:
        assert literal in text


@pytest.mark.unit
def test_privacy_guide_attribution_and_internal_gate() -> None:
    text = _read("PRIVACY.md")
    assert "基础教育教学指导委员会" in text
    assert "内部硬门槛" in text
    assert "2025 年 5 月" in text
    assert "对**教师**" in text
    assert "严禁将个人信息、考试试题等敏感数据输入 AI 工具" in text
    assert "对**学生**" in text
    assert "避免将个人信息输入生成式人工智能工具" in text
    assert "对**家长**" in text
    assert "避免输入任何可能泄露个人或家庭敏感信息的内容" in text
    # 负断言：把教师侧禁令直接套到用户身上的旧表述（发文主体写成"教育部"）不得出现
    assert "教育部《中小学生成式人工智能使用指南》" not in text
    assert "另受教育部" not in text


@pytest.mark.unit
def test_readme_positioning_in_first_lines() -> None:
    head = "\n".join(_read("README.md").splitlines()[:12])
    for literal in ["本地优先", "不判真实作业", "不生成讲解", "零模型"]:
        assert literal in head
    assert "AI 学习工作台" not in head
    assert "AI learning workbench" not in head


@pytest.mark.unit
def test_seed_data_not_expanded() -> None:
    assert len(json.loads(_read("seeds/data/topics.json"))) == 664
    assert len(json.loads(_read("seeds/data/dependencies.json"))) == 1018
    assert len(json.loads(_read("seeds/data/questions.json"))) == 2803


@pytest.mark.unit
def test_license_data_and_doc_links() -> None:
    data_license = _read("LICENSE-data.md")
    assert UPSTREAM_SHA in data_license
    assert "CC BY-NC 4.0" in data_license
    assert "Aifeng" in data_license
    assert "已修改" in data_license
    assert "664" in data_license and "1018" in data_license and "2803" in data_license

    notices = _read("THIRD-PARTY-NOTICES.md")
    assert UPSTREAM_SHA in notices
    assert "Aifeng" in notices
    assert "LICENSE-data.md" in notices

    readme = _read("README.md")
    assert "LICENSE-data.md" in readme
    assert "PRIVACY.md" in readme
    assert "OSI" in readme
    assert "版本以该文件首行为准" in readme
