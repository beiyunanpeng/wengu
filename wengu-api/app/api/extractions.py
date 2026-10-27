"""P1-4 结构化提取端点：切题子图逐题 VLM 精读 + 整页兜底 + 提取质量前置闸门。

显式触发（Phase 0 闸门内不做自动链）；纯查询 GET 零模型调用。
幂等：已有当前来源结果的题直接跳过，force 仅重跑并替换成功项；
失败项保留旧结果，重试只补缺失，不重复计费。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models import PhotoCapture, PhotoCaptureItem, ProblemExtraction
from app.prompts.loader import PromptError
from app.providers.base import CallMeta
from app.providers.failover import (
    CONFIG,
    QUOTA,
    AllProvidersFailed,
    classify_provider_error,
)
from app.providers.registry import ProviderConfigError
from app.services.ai_gateway import AiGateway, get_ai_gateway
from app.services.extraction import (
    EXTRACT_PROMPT_ID,
    SOURCE_SLICE,
    SOURCE_WHOLE_PAGE,
    ExtractionRejected,
    GateDecision,
    apply_extraction_gate,
)
from app.services.model_audit import DailyLimitExceeded

router = APIRouter(tags=["extractions"])
WHOLE_PAGE_SEQ = 1


class ExtractionAttemptInfo(BaseModel):
    provider: str
    status: str
    error_kind: str | None
    latency_ms: int


class ExtractionErrorItem(BaseModel):
    seq: int
    reason: str
    kind: str
    attempts: list[ExtractionAttemptInfo] = Field(default_factory=list)


class ExtractionInfo(BaseModel):
    id: int
    seq: int
    item_id: int | None
    source_kind: Literal["slice", "whole_page"]
    image_path: str
    problem_text: str
    student_answer: str | None
    confidence: float | None
    problem_complete: bool | None
    gate_status: Literal["ready_for_grading", "manual_review", "figure_dependent"]
    review_reasons: list[str]
    figure_keywords: list[str]
    prompt_id: str
    prompt_version: int
    provider: str
    model: str
    created_at: datetime


class ExtractionBatch(BaseModel):
    capture_id: int
    source_kind: Literal["slice", "whole_page"]
    total: int
    extracted_count: int
    skipped_count: int
    failed_count: int
    results: list[ExtractionInfo]
    errors: list[ExtractionErrorItem]


class _Target:
    __slots__ = ("abs_path", "item_id", "rel_path", "seq")

    def __init__(
        self, *, seq: int, item_id: int | None, rel_path: str, abs_path: Path
    ) -> None:
        self.seq = seq
        self.item_id = item_id
        self.rel_path = rel_path
        self.abs_path = abs_path


def _targets(
    capture: PhotoCapture, items: list[PhotoCaptureItem], uploads_dir: Path
) -> tuple[str, list[_Target]]:
    if items:
        return SOURCE_SLICE, [
            _Target(
                seq=item.seq,
                item_id=item.id,
                rel_path=item.stored_path,
                abs_path=uploads_dir / item.stored_path,
            )
            for item in items
        ]
    return SOURCE_WHOLE_PAGE, [
        _Target(
            seq=WHOLE_PAGE_SEQ,
            item_id=None,
            rel_path=capture.stored_path,
            abs_path=uploads_dir / capture.stored_path,
        )
    ]


def _row_info(row: ProblemExtraction) -> ExtractionInfo:
    return ExtractionInfo(
        id=row.id,
        seq=row.seq,
        item_id=row.photo_capture_item_id,
        source_kind=row.source_kind,
        image_path=row.image_path,
        problem_text=row.problem_text,
        student_answer=row.student_answer,
        confidence=row.confidence,
        problem_complete=row.problem_complete,
        gate_status=row.gate_status,
        review_reasons=json.loads(row.review_reasons_json),
        figure_keywords=json.loads(row.figure_keywords_json),
        prompt_id=row.prompt_id,
        prompt_version=row.prompt_version,
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
    )


async def _fetch_existing(
    session: AsyncSession, capture_id: int, source_kind: str
) -> list[ProblemExtraction]:
    rows = (
        await session.execute(
            select(ProblemExtraction)
            .where(
                ProblemExtraction.photo_capture_id == capture_id,
                ProblemExtraction.source_kind == source_kind,
            )
            .order_by(ProblemExtraction.seq)
        )
    ).scalars().all()
    return list(rows)


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "image_missing"
    if isinstance(exc, ExtractionRejected):
        return exc.reason
    text = str(exc).strip()[:200]
    return text or type(exc).__name__


def _error_info(
    exc: Exception,
) -> tuple[str, str, list[ExtractionAttemptInfo]]:
    """(reason, kind, attempts)；错误分类只来自 provider/gateway 边界。"""

    if isinstance(exc, AllProvidersFailed):
        return (
            _error_reason(exc),
            exc.kind,
            [
                ExtractionAttemptInfo(
                    provider=attempt.provider,
                    status=attempt.status,
                    error_kind=attempt.error_kind,
                    latency_ms=attempt.latency_ms,
                )
                for attempt in exc.attempts
            ],
        )
    if isinstance(exc, DailyLimitExceeded):
        return _error_reason(exc), QUOTA, []
    if isinstance(exc, PromptError):
        return _error_reason(exc), CONFIG, []
    return _error_reason(exc), classify_provider_error(exc), []


@router.post("/api/captures/{capture_id}/extract", response_model=ExtractionBatch)
async def extract_capture(
    capture_id: int,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    gateway: AiGateway = Depends(get_ai_gateway),
) -> ExtractionBatch:
    async with session.begin():
        capture = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.id == capture_id)
            )
        ).scalar_one_or_none()
        if capture is None:
            raise HTTPException(status_code=404, detail="capture 不存在")
        items = list(
            (
                await session.execute(
                    select(PhotoCaptureItem)
                    .where(PhotoCaptureItem.photo_capture_id == capture_id)
                    .order_by(PhotoCaptureItem.seq)
                )
            ).scalars().all()
        )
        source_kind, targets = _targets(
            capture,
            items,
            get_settings().uploads_dir,  # type: ignore[arg-type]
        )
        existing = await _fetch_existing(session, capture_id, source_kind)

    existing_seqs = {row.seq for row in existing}
    to_run = [t for t in targets if force or t.seq not in existing_seqs]

    successes: list[tuple[_Target, GateDecision, CallMeta]] = []
    failures: list[tuple[int, Exception]] = []
    for target in to_run:
        if not target.abs_path.is_file():
            failures.append((target.seq, FileNotFoundError(str(target.abs_path))))
            continue
        try:
            extracted, meta = await gateway.extract_problem(
                str(target.abs_path), prompt_id=EXTRACT_PROMPT_ID
            )
            decision = apply_extraction_gate(extracted, source_kind=source_kind)
        except Exception as exc:  # 单题失败不拖垮整批；错误摘要不含题目正文
            failures.append((target.seq, exc))
            continue
        successes.append((target, decision, meta))

    failure_infos = [(seq, *_error_info(exc)) for seq, exc in failures]

    if successes:
        now = datetime.now(UTC)
        success_seqs = {target.seq for target, _, _ in successes}
        try:
            async with session.begin():
                replace = [row for row in existing if row.seq in success_seqs]
                stale = (
                    await _fetch_existing(session, capture_id, SOURCE_WHOLE_PAGE)
                    if source_kind == SOURCE_SLICE
                    else []
                )
                for row in replace + stale:
                    await session.delete(row)
                if replace or stale:
                    await session.flush()
                for target, decision, meta in successes:
                    session.add(
                        ProblemExtraction(
                            photo_capture_id=capture_id,
                            photo_capture_item_id=target.item_id,
                            seq=target.seq,
                            source_kind=source_kind,
                            image_path=target.rel_path,
                            problem_text=decision.problem_text,
                            student_answer=decision.student_answer,
                            confidence=decision.confidence,
                            problem_complete=decision.problem_complete,
                            gate_status=decision.gate_status,
                            review_reasons_json=json.dumps(
                                list(decision.review_reasons), ensure_ascii=False
                            ),
                            figure_keywords_json=json.dumps(
                                list(decision.figure_keywords), ensure_ascii=False
                            ),
                            prompt_id=meta.prompt_id or EXTRACT_PROMPT_ID,
                            prompt_version=meta.prompt_version,
                            provider=meta.provider,
                            model=meta.model,
                            created_at=now,
                        )
                    )
        except IntegrityError:
            raise HTTPException(
                status_code=409, detail="该 capture 的提取已在进行或已完成，请刷新后重试"
            ) from None
    else:
        all_missing = bool(failures) and len(failures) == len(targets) and all(
            isinstance(exc, FileNotFoundError) for _, exc in failures
        )
        if all_missing and not existing:
            raise HTTPException(status_code=410, detail="图片文件缺失，无法提取")
        config_failure = bool(failures) and all(
            isinstance(exc, ProviderConfigError | PromptError)
            or (isinstance(exc, AllProvidersFailed) and exc.config_only)
            for _, exc in failures
        )
        if not existing and failures:
            raise HTTPException(
                status_code=503 if config_failure else 502,
                detail={
                    "message": "提取失败，未产生任何结果",
                    "errors": [
                        {
                            "seq": seq,
                            "reason": reason,
                            "kind": kind,
                            "attempts": [attempt.model_dump() for attempt in attempts],
                        }
                        for seq, reason, kind, attempts in failure_infos
                    ],
                },
            )

    rows = await _fetch_existing(session, capture_id, source_kind)
    errors = [
        ExtractionErrorItem(
            seq=seq,
            reason=reason,
            kind=kind,
            attempts=attempts,
        )
        for seq, reason, kind, attempts in failure_infos
    ]
    return ExtractionBatch(
        capture_id=capture_id,
        source_kind=source_kind,
        total=len(targets),
        extracted_count=len(successes),
        skipped_count=len(targets) - len(to_run),
        failed_count=len(errors),
        results=[_row_info(r) for r in rows],
        errors=errors,
    )


@router.get("/api/captures/{capture_id}/extractions", response_model=ExtractionBatch)
async def list_extractions(
    capture_id: int, session: AsyncSession = Depends(get_session)
) -> ExtractionBatch:
    async with session.begin():
        capture = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.id == capture_id)
            )
        ).scalar_one_or_none()
        if capture is None:
            raise HTTPException(status_code=404, detail="capture 不存在")
        items = list(
            (
                await session.execute(
                    select(PhotoCaptureItem)
                    .where(PhotoCaptureItem.photo_capture_id == capture_id)
                    .order_by(PhotoCaptureItem.seq)
                )
            ).scalars().all()
        )
        source_kind, targets = _targets(
            capture,
            items,
            get_settings().uploads_dir,  # type: ignore[arg-type]
        )
        rows = await _fetch_existing(session, capture_id, source_kind)
    return ExtractionBatch(
        capture_id=capture_id,
        source_kind=source_kind,
        total=len(targets),
        extracted_count=len(rows),
        skipped_count=0,
        failed_count=0,
        results=[_row_info(r) for r in rows],
        errors=[],
    )
