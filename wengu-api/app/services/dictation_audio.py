"""P3-4b 听写音频：data/audio/ 目录扫描 + 魔数嗅探 + 卷级挂接校验。

第三方课程音频由家长手动放入 <data_dir>/audio/——绝不进 git、绝不进备份包
（设计文档 §19-G-3 定案二同一条理由：备份 zip 是"发网盘/发群"的高风险分发载体）。
本模块只做文件名合法性、魔数嗅探（mp3/m4a/wav）、列表排序截断与越界拦截；
不做上传端点、不挂 StaticFiles、不解析音频元数据（时长/进度由浏览器原生控件承担）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_AUDIO_LIST = 500
MAX_AUDIO_NAME_CHARS = 200

AUDIO_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
}

# 三种魔数（ID3/帧同步、ftyp、RIFF…WAVE）都落在前 12 字节内。
_HEADER_BYTES = 16


class AudioError(ValueError):
    """校验失败，带稳定码；API 转 422 {message, code}。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class AudioNotFound(LookupError):
    """音频文件缺失；API 转 404 稳定码（绝不 500）。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def sniff_audio(data: bytes) -> str | None:
    """只看魔数，不看扩展名/声明类型（与 mistake_images._sniff 同纪律）。"""

    if data.startswith(b"ID3"):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        return "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    return None


def validate_audio_name(name: str) -> None:
    """audio_ref 只存纯文件名：拒绝路径分隔符、控制字符与白名单外扩展名。"""

    if not name or len(name) > MAX_AUDIO_NAME_CHARS:
        raise AudioError("音频文件名长度非法", "audio_name_invalid")
    if (
        "/" in name
        or "\\" in name
        or name in {".", ".."}
        or any(ord(char) < 32 for char in name)
    ):
        raise AudioError("音频文件名只能是纯文件名", "audio_name_invalid")
    if Path(name).suffix.lower() not in AUDIO_MIME:
        raise AudioError("只接受 mp3/m4a/wav 音频", "audio_format_not_allowed")


def resolve_within_audio_dir(audio_dir: Path, name: str) -> Path:
    validate_audio_name(name)
    root = audio_dir.resolve()
    candidate = (audio_dir / name).resolve()
    if not candidate.is_relative_to(root):
        raise AudioError("音频路径越界", "audio_path_invalid")
    return candidate


def _sniff_file(path: Path) -> str | None:
    with path.open("rb") as handle:
        return sniff_audio(handle.read(_HEADER_BYTES))


@dataclass(frozen=True)
class AudioEntry:
    index: int
    name: str
    size_bytes: int


@dataclass(frozen=True)
class AudioList:
    entries: tuple[AudioEntry, ...]
    truncated: bool


def list_audio(audio_dir: Path) -> AudioList:
    """目录不存在 → 空列表（家长还没放文件是常态，不是错误）。

    只列合法音频（扩展名白名单 + 嗅探一致 + ≤64MB），按文件名排序保证确定性；
    超过 MAX_AUDIO_LIST 截断并报 truncated。
    """

    if not audio_dir.is_dir():
        return AudioList(entries=(), truncated=False)
    valid: list[tuple[str, int]] = []
    for path in sorted(audio_dir.iterdir(), key=lambda entry: entry.name):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in AUDIO_MIME:
            continue
        size = path.stat().st_size
        if size > MAX_AUDIO_BYTES:
            continue
        try:
            mime = _sniff_file(path)
        except OSError:
            continue
        if mime != AUDIO_MIME[ext]:
            continue
        valid.append((path.name, size))
    truncated = len(valid) > MAX_AUDIO_LIST
    entries = tuple(
        AudioEntry(index=index, name=name, size_bytes=size)
        for index, (name, size) in enumerate(valid[:MAX_AUDIO_LIST])
    )
    return AudioList(entries=entries, truncated=truncated)


def validate_audio_ref(audio_dir: Path, name: str) -> str:
    """挂接前校验：文件必须在 audio_dir 内、存在、≤64MB、嗅探与扩展名一致。"""

    path = resolve_within_audio_dir(audio_dir, name)
    if not path.is_file():
        raise AudioError(f"音频文件不存在：{name}", "audio_not_found")
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise AudioError("音频不能超过 64MB", "audio_too_large")
    mime = _sniff_file(path)
    if mime is None or mime != AUDIO_MIME[path.suffix.lower()]:
        raise AudioError("音频内容与扩展名不一致", "audio_sniff_mismatch")
    return name


def load_audio(audio_dir: Path, name: str) -> tuple[bytes, str]:
    """播放读取：文件被移走 → AudioNotFound（404 稳定码）；内容非法 → AudioError。"""

    path = resolve_within_audio_dir(audio_dir, name)
    if not path.is_file():
        raise AudioNotFound("音频文件已被移走或删除", "audio_file_missing")
    data = path.read_bytes()
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioError("音频不能超过 64MB", "audio_too_large")
    mime = sniff_audio(data)
    if mime is None or mime != AUDIO_MIME[path.suffix.lower()]:
        raise AudioError("音频内容与扩展名不一致", "audio_sniff_mismatch")
    return data, mime
