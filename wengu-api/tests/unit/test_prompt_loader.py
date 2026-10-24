from __future__ import annotations

import pytest
from app.prompts.loader import PromptError, load_prompts


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


@pytest.mark.unit
def test_load_prompts_reads_frontmatter_and_renders(tmp_path) -> None:
    _write(
        tmp_path / "extract.md",
        "---\nid: extract_problem\nversion: 3\n---\n题目：{{PROBLEM}}\n作答：{{ANSWER}}\n",
    )
    _write(tmp_path / "README.md", "# not a prompt\n")

    prompts = load_prompts(tmp_path)

    assert set(prompts) == {"extract_problem"}
    prompt = prompts["extract_problem"]
    assert prompt.version == 3
    assert prompt.render(PROBLEM="1+1", ANSWER="2").endswith("作答：2")
    with pytest.raises(PromptError, match="missing token ANSWER"):
        prompt.render(PROBLEM="1+1")


@pytest.mark.unit
def test_load_prompts_rejects_duplicates_and_bad_metadata(tmp_path) -> None:
    _write(tmp_path / "a.md", "---\nid: same\nversion: 1\n---\nbody\n")
    _write(tmp_path / "b.md", "---\nid: same\nversion: 2\n---\nbody\n")
    with pytest.raises(PromptError, match="duplicate prompt id same"):
        load_prompts(tmp_path)

    for name, text in {
        "missing_id.md": "---\nversion: 1\n---\nbody\n",
        "missing_version.md": "---\nid: x\n---\nbody\n",
        "bad_version.md": "---\nid: x\nversion: 0\n---\nbody\n",
        "empty_body.md": "---\nid: x\nversion: 1\n---\n   \n",
    }.items():
        directory = tmp_path / name
        directory.mkdir()
        _write(directory / name, text)
        with pytest.raises(PromptError):
            load_prompts(directory)

    with pytest.raises(PromptError, match="prompt directory not found"):
        load_prompts(tmp_path / "missing-dir")
