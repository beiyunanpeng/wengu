"""P3-3b 教材词表批量导入：服务端唯一的解析与校验真源。

信任边界（与外部 agent 转录不同）：词表来自家长本人，是可信来源，
因此**直接入库 + 逐行报告**，不做草稿暂存表、不走核对页确认。
但「导入即不可信输入」（AGENTS §5）的体积/行数/字段校验照抄——
家长也会手滑，畸形输入不能打到数据库。

解析契约：
- 只接受 UTF-8（可带 BOM；出现 U+FFFD 替换字符视为编码不对，整批拒绝）；
- 首个内容行含 TAB → TSV，否则 CSV（stdlib `csv`，支持引号与换行转义）；
- 首个内容行整行都是 prompt/answer/unit 表头关键字 → 跳过（至少两个关键字，
  避免把单词 "unit" 当成表头）；
- 空行与 `#` 开头的注释行跳过；
- 每行 1–3 列：prompt 必填，answer / unit 可选；多余的空尾列忽略。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.recitation import (
    RecitationDuplicate,
    RecitationInvalid,
    create_item,
)
from app.services.review_policy import MEMORY_SUBJECTS

MAX_IMPORT_BODY_BYTES = 256 * 1024
MAX_IMPORT_ROWS = 500
MAX_PROMPT_CHARS = 200
MAX_ANSWER_CHARS = 500
MAX_UNIT_CHARS = 40
HEADER_KEYWORDS = frozenset({"prompt", "answer", "unit"})


@dataclass(frozen=True, slots=True)
class ImportRow:
    line: int
    prompt: str
    answer: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class RowIssue:
    line: int
    reason: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateRow:
    line: int
    prompt: str


@dataclass(frozen=True, slots=True)
class ParsedImport:
    rows: tuple[ImportRow, ...]
    issues: tuple[RowIssue, ...]


@dataclass(frozen=True, slots=True)
class ImportReport:
    imported: int
    duplicates: tuple[DuplicateRow, ...]
    issues: tuple[RowIssue, ...]


class ImportRejected(Exception):
    """整批拒绝：编码/行数/字段超长/学科不合法（body 体积由 API 层检查）。"""

    def __init__(
        self,
        reason: str,
        *,
        line: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.line = line
        self.field = field


def _first_content_line(lines: list[str]) -> tuple[int, str] | None:
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            return index + 1, raw
    return None


def _is_header(cells: list[str]) -> bool:
    tokens = [cell.strip().lower() for cell in cells if cell.strip()]
    return len(tokens) >= 2 and all(token in HEADER_KEYWORDS for token in tokens)


def _row_from_cells(cells: list[str], line: int) -> ImportRow | RowIssue:
    trimmed = list(cells)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()

    if len(trimmed) > 3:
        return RowIssue(
            line=line,
            field="columns",
            reason="最多 3 列（prompt, answer, unit）",
        )

    prompt = trimmed[0].strip() if trimmed else ""
    if not prompt:
        return RowIssue(line=line, field="prompt", reason="prompt 不能为空")

    answer = trimmed[1].strip() if len(trimmed) > 1 else ""
    unit = trimmed[2].strip() if len(trimmed) > 2 else ""

    if len(prompt) > MAX_PROMPT_CHARS:
        raise ImportRejected(
            f"prompt 超过 {MAX_PROMPT_CHARS} 字符", line=line, field="prompt"
        )
    if len(answer) > MAX_ANSWER_CHARS:
        raise ImportRejected(
            f"answer 超过 {MAX_ANSWER_CHARS} 字符", line=line, field="answer"
        )
    if len(unit) > MAX_UNIT_CHARS:
        raise ImportRejected(
            f"unit 超过 {MAX_UNIT_CHARS} 字符", line=line, field="unit"
        )

    return ImportRow(
        line=line,
        prompt=prompt,
        answer=answer or None,
        unit=unit or None,
    )


def parse_text(text: str) -> ParsedImport:
    """把 CSV/TSV 原文解析成行；整批问题抛 `ImportRejected`，坏行收进 issues。"""

    if text.startswith("\ufeff"):
        text = text[1:]
    if "\ufffd" in text:
        raise ImportRejected(
            "文本疑似不是 UTF-8（含 U+FFFD 替换字符），"
            "请用 Excel 的“CSV UTF-8”重新导出",
            field="text",
        )

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    first = _first_content_line(lines)
    delimiter = "\t" if first is not None and "\t" in first[1] else ","

    rows: list[ImportRow] = []
    issues: list[RowIssue] = []
    header_seen = False
    previous_line = 0
    reader = csv.reader(
        io.StringIO(normalized), delimiter=delimiter, strict=True
    )
    try:
        for cells in reader:
            start_line = previous_line + 1
            previous_line = reader.line_num
            raw = lines[start_line - 1] if start_line - 1 < len(lines) else ""
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if raw.lstrip().startswith("#"):
                continue
            if not header_seen:
                header_seen = True
                if _is_header(cells):
                    continue
            row = _row_from_cells(cells, start_line)
            if isinstance(row, RowIssue):
                issues.append(row)
                continue
            if len(rows) + len(issues) >= MAX_IMPORT_ROWS:
                raise ImportRejected(
                    f"单次最多导入 {MAX_IMPORT_ROWS} 行，第 {start_line} 行已超限",
                    line=start_line,
                )
            rows.append(row)
    except csv.Error as exc:
        raise ImportRejected(
            f"CSV 解析失败：{exc}", line=previous_line + 1, field="text"
        ) from None

    return ParsedImport(rows=tuple(rows), issues=tuple(issues))


async def import_items(
    session: AsyncSession,
    *,
    subject: str,
    text: str,
) -> ImportReport:
    """逐行走既有 `create_item`；重复只报告、不更新已有行，坏行不阻断好行。"""

    subject = subject.strip()
    if subject not in MEMORY_SUBJECTS:
        raise ImportRejected(
            f"subject 必须是 {sorted(MEMORY_SUBJECTS)} 之一", field="subject"
        )

    parsed = parse_text(text)
    issues = list(parsed.issues)
    duplicates: list[DuplicateRow] = []
    imported = 0
    for row in parsed.rows:
        try:
            await create_item(
                session,
                subject=subject,
                prompt=row.prompt,
                answer=row.answer,
                unit=row.unit,
                created_by="parent",
            )
        except RecitationDuplicate:
            duplicates.append(DuplicateRow(line=row.line, prompt=row.prompt))
            continue
        except RecitationInvalid as exc:
            issues.append(RowIssue(line=row.line, reason=str(exc), field="prompt"))
            continue
        imported += 1

    issues.sort(key=lambda issue: issue.line)
    return ImportReport(
        imported=imported,
        duplicates=tuple(duplicates),
        issues=tuple(issues),
    )
