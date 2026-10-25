"""P1-5 题库入库闸门：verify 必填、AST 沙箱跑通且 mismatch=0 才允许入库。

外部数据是不可信输入：逐项校验长度/占位/变量类型，坏项只拒绝该项并逐条报告；
external_id 幂等，重复导入同内容跳过、内容不同报冲突。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.judge.normalize import PLACEHOLDER
from app.judge.verify_sandbox import SandboxError, verify_answer
from app.models import ProblemBankItem

router = APIRouter(tags=["problem-bank"])

MAX_IMPORT_ITEMS = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ProblemBankImportRequest(BaseModel):
    items: list[Any] = Field(min_length=1, max_length=MAX_IMPORT_ITEMS)


class _ItemIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=20)
    problem_text: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=500)
    acceptable: list[str] = Field(default_factory=list, max_length=50)
    unordered: bool = False
    verify: str = Field(min_length=1, max_length=2000)
    verify_vars: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="import", min_length=1, max_length=50)


class BankImportResult(BaseModel):
    index: int
    external_id: str | None
    status: str  # accepted | skipped | rejected
    reason: str | None = None
    problem_bank_id: int | None = None


class BankImportReport(BaseModel):
    total: int
    accepted_count: int
    skipped_count: int
    rejected_count: int
    verify_pass_rate: float | None
    results: list[BankImportResult]


class BankItemInfo(BaseModel):
    id: int
    external_id: str
    subject: str
    problem_text: str
    answer: str
    acceptable_answers: list[str]
    unordered: bool
    verify: str
    verify_vars: dict[str, Any]
    verify_status: str
    source: str
    created_at: datetime


def _validation_reason(exc: ValidationError) -> str:
    error = exc.errors()[0]
    loc = error.get("loc") or ("item",)
    return f"invalid:{loc[-1]}"


def _candidate_error(item: _ItemIn) -> str | None:
    """占位、控制字符与空值拒绝；返回稳定 reason，不含题目正文。"""

    values = [item.problem_text, item.answer, *item.acceptable]
    if any(_CONTROL_CHARS.search(value) for value in values):
        return "invalid_control_char"
    for value in (item.problem_text, item.answer):
        if not value.strip():
            return "empty_field"
        if PLACEHOLDER in value:
            return "placeholder"
    if any(PLACEHOLDER in alias for alias in item.acceptable):
        return "placeholder"
    return None


def _verify_reason(item: _ItemIn) -> str | None:
    """AST 沙箱核验；返回 None 表示 mismatch=0，可入库。"""

    try:
        outcome = verify_answer(
            item.verify,
            expected=item.answer,
            acceptable=item.acceptable,
            unordered=item.unordered,
            variables=item.verify_vars,
        )
    except SandboxError as exc:
        return f"verify_error:{exc.reason}"
    if outcome.verdict == "verified":
        return None
    if outcome.verdict == "mismatch":
        return "verify_mismatch"
    return "verify_uncertain"


def _same_content(row: ProblemBankItem, item: _ItemIn) -> bool:
    try:
        stored_acceptable = json.loads(row.acceptable_answers_json)
        stored_vars = json.loads(row.verify_vars_json)
    except json.JSONDecodeError:
        return False
    return (
        row.subject == item.subject
        and row.problem_text == item.problem_text
        and row.answer == item.answer
        and stored_acceptable == item.acceptable
        and row.unordered == item.unordered
        and row.verify == item.verify
        and stored_vars == item.verify_vars
        and row.source == item.source
    )


async def _fetch_existing(
    session: AsyncSession, external_ids: set[str]
) -> dict[str, ProblemBankItem]:
    if not external_ids:
        return {}
    rows = (
        await session.execute(
            select(ProblemBankItem).where(
                ProblemBankItem.external_id.in_(external_ids)
            )
        )
    ).scalars().all()
    return {row.external_id: row for row in rows}


@router.post("/api/problem-bank/import", response_model=BankImportReport)
async def import_problem_bank(
    payload: ProblemBankImportRequest,
    session: AsyncSession = Depends(get_session),
) -> BankImportReport:
    parsed: list[tuple[int, _ItemIn | None, str | None]] = []
    for index, raw in enumerate(payload.items):
        try:
            item = _ItemIn.model_validate(raw)
        except ValidationError as exc:
            parsed.append((index, None, _validation_reason(exc)))
            continue
        parsed.append((index, item, _candidate_error(item)))
    valid_ids = {item.external_id for _, item, _ in parsed if item is not None}
    async with session.begin():
        existing = await _fetch_existing(session, valid_ids)
        seen: dict[str, _ItemIn] = {}
        results: list[BankImportResult] = []
        accepted = skipped = rejected = verify_attempts = 0

        for index, item, error in parsed:
            raw = payload.items[index]
            raw_external_id = raw.get("external_id") if isinstance(raw, dict) else None
            external_id = (
                item.external_id
                if item is not None
                else (raw_external_id if isinstance(raw_external_id, str) else None)
            )
            if error is not None:
                rejected += 1
                results.append(
                    BankImportResult(
                        index=index,
                        external_id=external_id,
                        status="rejected",
                        reason=error,
                    )
                )
                continue

            row = existing.get(item.external_id)
            if row is not None:
                if _same_content(row, item):
                    skipped += 1
                    results.append(
                        BankImportResult(
                            index=index,
                            external_id=item.external_id,
                            status="skipped",
                            reason="duplicate",
                            problem_bank_id=row.id,
                        )
                    )
                else:
                    rejected += 1
                    results.append(
                        BankImportResult(
                            index=index,
                            external_id=item.external_id,
                            status="rejected",
                            reason="external_id_conflict",
                        )
                    )
                continue

            previous = seen.get(item.external_id)
            if previous is not None:
                if previous == item:
                    skipped += 1
                    results.append(
                        BankImportResult(
                            index=index,
                            external_id=item.external_id,
                            status="skipped",
                            reason="duplicate_in_batch",
                        )
                    )
                else:
                    rejected += 1
                    results.append(
                        BankImportResult(
                            index=index,
                            external_id=item.external_id,
                            status="rejected",
                            reason="external_id_conflict",
                        )
                    )
                continue
            seen[item.external_id] = item

            verify_attempts += 1
            verify_error = _verify_reason(item)
            if verify_error is not None:
                rejected += 1
                results.append(
                    BankImportResult(
                        index=index,
                        external_id=item.external_id,
                        status="rejected",
                        reason=verify_error,
                    )
                )
                continue

            bank = ProblemBankItem(
                external_id=item.external_id,
                subject=item.subject,
                problem_text=item.problem_text,
                answer=item.answer,
                acceptable_answers_json=json.dumps(item.acceptable, ensure_ascii=False),
                unordered=item.unordered,
                verify=item.verify,
                verify_vars_json=json.dumps(
                    item.verify_vars, ensure_ascii=False, sort_keys=True
                ),
                verify_status="verified",
                source=item.source,
                created_at=datetime.now(UTC),
            )
            session.add(bank)
            try:
                await session.flush()
            except IntegrityError:
                raise HTTPException(
                    status_code=409, detail="external_id 并发导入冲突，请重试"
                ) from None
            accepted += 1
            results.append(
                BankImportResult(
                    index=index,
                    external_id=item.external_id,
                    status="accepted",
                    problem_bank_id=bank.id,
                )
            )

    if accepted == 0 and skipped == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "没有可入库的题目（verify 必须 mismatch=0）",
                "results": [r.model_dump() for r in results],
            },
        )

    pass_rate = (
        accepted / verify_attempts if verify_attempts else None
    )
    return BankImportReport(
        total=len(payload.items),
        accepted_count=accepted,
        skipped_count=skipped,
        rejected_count=rejected,
        verify_pass_rate=pass_rate,
        results=results,
    )


@router.get("/api/problem-bank/items/{item_id}", response_model=BankItemInfo)
async def get_problem_bank_item(
    item_id: int, session: AsyncSession = Depends(get_session)
) -> BankItemInfo:
    item = await session.get(ProblemBankItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="题库条目不存在")
    return BankItemInfo(
        id=item.id,
        external_id=item.external_id,
        subject=item.subject,
        problem_text=item.problem_text,
        answer=item.answer,
        acceptable_answers=json.loads(item.acceptable_answers_json),
        unordered=item.unordered,
        verify=item.verify,
        verify_vars=json.loads(item.verify_vars_json),
        verify_status=item.verify_status,
        source=item.source,
        created_at=item.created_at,
    )
