"""P3-4b 听写音频纯层：魔数嗅探、文件名/越界校验、列表排序截断、挂接与读取。

样本全部是手写字节头（不引入真实音频文件，仓库零音频样本）：
- mp3 两种合法头：ID3 标签 / MPEG 帧同步；
- m4a：ftyp box；wav：RIFF…WAVE；
- 伪装样本：扩展名 .mp3 但内容是 PNG 头，必须被拒绝（定案③）。
边界常量手写字面钉死（§19-L 纪律），不随符号漂移。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.services.dictation_audio import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_LIST,
    AudioError,
    AudioNotFound,
    list_audio,
    load_audio,
    resolve_within_audio_dir,
    sniff_audio,
    validate_audio_name,
    validate_audio_ref,
)

MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 32
MP3_SYNC = b"\xff\xfb\x90\x00" + b"\x00" * 32
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A mp42" + b"\x00" * 16
WAV = b"RIFF$\x00\x00\x00WAVEfmt " + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_boundary_constants_are_pinned_literals() -> None:
    assert MAX_AUDIO_BYTES == 67108864
    assert MAX_AUDIO_LIST == 500


def test_sniff_accepts_three_formats_with_real_byte_headers() -> None:
    assert sniff_audio(MP3_ID3) == "audio/mpeg"
    assert sniff_audio(MP3_SYNC) == "audio/mpeg"
    assert sniff_audio(M4A) == "audio/mp4"
    assert sniff_audio(WAV) == "audio/wav"


def test_sniff_rejects_disguised_and_unknown_bytes() -> None:
    assert sniff_audio(PNG) is None
    assert sniff_audio(b"") is None
    assert sniff_audio(b"\xff") is None
    assert sniff_audio(b"RIFF\x00\x00\x00\x00AVI ") is None
    assert sniff_audio(b"\x00\x00\x00\x18moov") is None


def test_validate_audio_name_accepts_plain_whitelisted_names() -> None:
    for name in ("u1.mp3", "U1.MP3", "单元一 m4a.m4a", "a.wav", "x" * 196 + ".mp3"):
        validate_audio_name(name)


def test_validate_audio_name_rejects_bad_names_with_stable_codes() -> None:
    cases = {
        "": "audio_name_invalid",
        "x" * 197 + ".mp3": "audio_name_invalid",
        "../evil.mp3": "audio_name_invalid",
        "sub/evil.mp3": "audio_name_invalid",
        "sub\\evil.mp3": "audio_name_invalid",
        ".": "audio_name_invalid",
        "..": "audio_name_invalid",
        "evil\n.mp3": "audio_name_invalid",
        "evil.txt": "audio_format_not_allowed",
        "evil": "audio_format_not_allowed",
        "evil.ogg": "audio_format_not_allowed",
    }
    for name, code in cases.items():
        with pytest.raises(AudioError) as excinfo:
            validate_audio_name(name)
        assert excinfo.value.code == code


def test_resolve_within_audio_dir_blocks_traversal(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    resolved = resolve_within_audio_dir(audio_dir, "u1.mp3")
    assert resolved == (audio_dir / "u1.mp3").resolve()
    for name in ("../outside.mp3", "..\\outside.mp3", "a/../../outside.mp3"):
        with pytest.raises(AudioError) as excinfo:
            resolve_within_audio_dir(audio_dir, name)
        assert excinfo.value.code == "audio_name_invalid"


def _write_audio(audio_dir: Path, name: str, data: bytes) -> Path:
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / name
    path.write_bytes(data)
    return path


def _oversize(path: Path) -> None:
    with path.open("r+b") as handle:
        os.truncate(handle.fileno(), 67108865)


def test_list_audio_missing_dir_is_empty_not_error(tmp_path) -> None:
    listing = list_audio(tmp_path / "audio")
    assert listing.entries == ()
    assert listing.truncated is False


def test_list_audio_sorts_and_filters_invalid_files(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    _write_audio(audio_dir, "b.wav", WAV)
    _write_audio(audio_dir, "a.mp3", MP3_ID3)
    _write_audio(audio_dir, "c.m4a", M4A)
    _write_audio(audio_dir, "notes.txt", b"hello")
    _write_audio(audio_dir, "fake.mp3", PNG)
    _write_audio(audio_dir, "fake.wav", MP3_ID3)
    _oversize(_write_audio(audio_dir, "big.mp3", MP3_ID3))
    (audio_dir / "sub.mp3").mkdir()

    listing = list_audio(audio_dir)
    assert listing.truncated is False
    assert [(entry.index, entry.name) for entry in listing.entries] == [
        (0, "a.mp3"),
        (1, "b.wav"),
        (2, "c.m4a"),
    ]
    assert listing.entries[0].size_bytes == len(MP3_ID3)


def test_list_audio_truncates_at_500_and_reports(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    for index in range(501):
        _write_audio(audio_dir, f"w{index:04d}.wav", WAV)
    listing = list_audio(audio_dir)
    assert len(listing.entries) == 500
    assert listing.truncated is True
    assert listing.entries[-1].name == "w0499.wav"


def test_list_audio_exactly_500_is_not_truncated(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    for index in range(500):
        _write_audio(audio_dir, f"w{index:04d}.wav", WAV)
    listing = list_audio(audio_dir)
    assert len(listing.entries) == 500
    assert listing.truncated is False


def test_validate_audio_ref_accepts_valid_file(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    _write_audio(audio_dir, "u1.mp3", MP3_ID3)
    assert validate_audio_ref(audio_dir, "u1.mp3") == "u1.mp3"


def test_validate_audio_ref_rejects_missing_disguised_and_oversize(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    _write_audio(audio_dir, "fake.mp3", PNG)
    _oversize(_write_audio(audio_dir, "big.wav", WAV))
    cases = {
        "gone.mp3": "audio_not_found",
        "fake.mp3": "audio_sniff_mismatch",
        "big.wav": "audio_too_large",
        "notes.txt": "audio_format_not_allowed",
    }
    for name, code in cases.items():
        with pytest.raises(AudioError) as excinfo:
            validate_audio_ref(audio_dir, name)
        assert excinfo.value.code == code


def test_load_audio_returns_bytes_and_sniffed_mime(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    _write_audio(audio_dir, "u1.m4a", M4A)
    data, mime = load_audio(audio_dir, "u1.m4a")
    assert data == M4A
    assert mime == "audio/mp4"


def test_load_audio_missing_file_raises_not_found_never_generic(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    path = _write_audio(audio_dir, "u1.wav", WAV)
    path.unlink()
    with pytest.raises(AudioNotFound) as excinfo:
        load_audio(audio_dir, "u1.wav")
    assert excinfo.value.code == "audio_file_missing"


def test_load_audio_rejects_disguised_content(tmp_path) -> None:
    audio_dir = tmp_path / "audio"
    _write_audio(audio_dir, "fake.mp3", PNG)
    with pytest.raises(AudioError) as excinfo:
        load_audio(audio_dir, "fake.mp3")
    assert excinfo.value.code == "audio_sniff_mismatch"
