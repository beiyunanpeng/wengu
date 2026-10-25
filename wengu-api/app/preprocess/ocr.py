"""本地 OCR 薄封装：RapidOCR（onnxruntime 后端），不联网、不调 VLM。

模型随 wheel 分发、首次使用懒加载；换引擎（如 PaddleOCR）只需提供
同样实现了 detect_lines 的类——slicer 只依赖 TextLine 结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MIN_REC_SCORE = 0.4  # 低于此置信度的行视为噪声丢弃（确定性过滤）


@dataclass(frozen=True)
class TextLine:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2（像素，相对原图）
    text: str
    score: float

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


class OcrEngine(Protocol):
    def detect_lines(self, image_path: Path) -> list[TextLine]: ...


class RapidOcrEngine:
    """RapidOCR det+rec 一次调用；引擎实例进程内单例懒加载（模型加载约秒级）。"""

    def __init__(self) -> None:
        self._engine = None

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def detect_lines(self, image_path: Path) -> list[TextLine]:
        result, _elapse = self._ensure()(str(image_path))
        if not result:
            return []
        lines: list[TextLine] = []
        for quad, text, score in result:
            xs = [int(p[0]) for p in quad]
            ys = [int(p[1]) for p in quad]
            if float(score) < MIN_REC_SCORE:
                continue
            lines.append(
                TextLine(
                    box=(min(xs), min(ys), max(xs), max(ys)),
                    text=str(text),
                    score=float(score),
                )
            )
        return lines


_engine: RapidOcrEngine | None = None


def get_ocr_engine() -> RapidOcrEngine:
    global _engine
    if _engine is None:
        _engine = RapidOcrEngine()
    return _engine
