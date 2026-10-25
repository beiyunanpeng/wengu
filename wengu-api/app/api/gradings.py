"""P1-5 批改分级闸 API：创建/查询/确认/申诉。

客观题零模型（judgeAnswer），过程题才调 gateway；GET 纯查询。
Phase 0 边界表未回填：所有新单 pending，确认/申诉只追加版本与事实事件。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import GradingResult, GradingVersion, Mistake
from app.prompts.loader import PromptError
from app.providers.registry import ProviderConfigError
from app.services.ai_gateway import AiGateway, get_ai_gateway
from app.services.grading import (
    ReferenceNotFound,
    SourceNotFound,
    append_user_decision,
    get_by_source,
    get_versions,
    objective_suggestion,
    parse_acceptable,
    persist_grading,
    process_suggestion,
    read_source,
    resolve_reference,
)

router = APIRouter(tags=["gradings"])


class GradingCreateRequest(BaseModel):
    source_kind: Literal["problem_extraction", "ingestion_draft"]
    source_id: int = Field(ge=1)
    question_type: Literal["objective", "process", "open"]
    problem_bank_id: int | None = Field(default=None, ge=1)
    answer: str | None = Field(default=None, max_length=2000)
    acceptable: list[str] = Field(default_factory=list, max_length=50)
    unordered: bool = False
    samples: int = Field(default=1, ge=1, le=3)


class GradingVersionInfo(BaseModel):
    version: int
    action: str
    verdict: str
    source: str
    confidence: float | None
    reason: str | None
    provider: str | None
    model: str | None
    prompt_id: str | None
    prompt_version: int | None
    sample_verdicts: list[str]
    created_at: datetime


class GradingDetail(BaseModel):
    id: int
    source_kind: str
    source_id: int
    problem_bank_id: int | None
    question_type: str
    problem_text: str
    student_answer: str | None
    standard_answer: str | None
    acceptable_answers: list[str]
    unordered: bool
    status: str
    current_version: int
    current_verdict: str
    mistake_id: int | None = None
    mistake_status: str | None = None
    versions: list[GradingVersionInfo]
    created_at: datetime
    updated_at: datetime


class GradingCreateResponse(BaseModel):
    route: Literal["grading", "explanation"]
    duplicate: bool = False
    grading: GradingDetail | None = None


class ConfirmRequest(BaseModel):
    base_version: int = Field(ge=1)
    verdict: Literal["correct", "wrong"] | None = None
    actor: Literal["student", "parent"] = "student"


class AppealRequest(BaseModel):
    base_version: int = Field(ge=1)
    verdict: Literal["correct", "wrong"]
    actor: Literal["student", "parent"] = "student"
    reason: str | None = Field(default=None, max_length=200)


def _json_list(raw: str) -> list[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


def _naive_utc(value: datetime) -> datetime:
    """POST 的内存对象带时区、GET 从 SQLite 读回是 naive；统一成 naive UTC。"""

    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _version_info(row: GradingVersion) -> GradingVersionInfo:
    return GradingVersionInfo(
        version=row.version,
        action=row.action,
        verdict=row.verdict,
        source=row.source,
        confidence=row.confidence,
        reason=row.reason,
        provider=row.provider,
        model=row.model,
        prompt_id=row.prompt_id,
        prompt_version=row.prompt_version,
        sample_verdicts=_json_list(row.sample_verdicts_json),
        created_at=_naive_utc(row.created_at),
    )


async def _detail(session: AsyncSession, grading: GradingResult) -> GradingDetail:
    versions = await get_versions(session, grading.id)
    mistake = (
        await session.execute(
            select(Mistake).where(Mistake.source_grading_id == grading.id)
        )
    ).scalar_one_or_none()
    return GradingDetail(
        id=grading.id,
        source_kind=grading.source_kind,
        source_id=grading.source_id,
        problem_bank_id=grading.problem_bank_id,
        question_type=grading.question_type,
        problem_text=grading.problem_text,
        student_answer=grading.student_answer,
        standard_answer=grading.standard_answer,
        acceptable_answers=list(parse_acceptable(grading.acceptable_answers_json)),
        unordered=grading.unordered,
        status=grading.status,
        current_version=grading.current_version,
        current_verdict=versions[-1].verdict if versions else "uncertain",
        mistake_id=mistake.id if mistake is not None else None,
        mistake_status=mistake.status if mistake is not None else None,
        versions=[_version_info(row) for row in versions],
        created_at=_naive_utc(grading.created_at),
        updated_at=_naive_utc(grading.updated_at),
    )


def _validate_reference_shape(payload: GradingCreateRequest) -> None:
    if payload.problem_bank_id is not None and payload.answer is not None:
        raise HTTPException(status_code=422, detail="problem_bank_id 与 answer 只能二选一")
    if payload.problem_bank_id is not None and (payload.acceptable or payload.unordered):
        raise HTTPException(
            status_code=422, detail="引用 problem_bank 时不得再传 acceptable/unordered"
        )


async def _get_or_404(session: AsyncSession, grading_id: int) -> GradingResult:
    grading = await session.get(GradingResult, grading_id)
    if grading is None:
        raise HTTPException(status_code=404, detail="grading 不存在")
    return grading


@router.post("/api/gradings", response_model=GradingCreateResponse)
async def create_grading(
    payload: GradingCreateRequest,
    session: AsyncSession = Depends(get_session),
    gateway: AiGateway = Depends(get_ai_gateway),
) -> GradingCreateResponse:
    _validate_reference_shape(payload)

    async with session.begin():
        try:
            source = await read_source(session, payload.source_kind, payload.source_id)
        except SourceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

        if payload.question_type == "open":
            return GradingCreateResponse(route="explanation", grading=None)

        existing = await get_by_source(session, payload.source_kind, payload.source_id)
        if existing is not None:
            return GradingCreateResponse(
                route="grading", duplicate=True, grading=await _detail(session, existing)
            )

        try:
            reference, reference_reason = await resolve_reference(
                session,
                problem_bank_id=payload.problem_bank_id,
                answer=payload.answer,
                acceptable=payload.acceptable,
                unordered=payload.unordered,
            )
        except ReferenceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    if payload.question_type == "objective":
        suggestion = objective_suggestion(
            source, reference, reference_reason=reference_reason
        )
    else:
        try:
            suggestion = await process_suggestion(
                source,
                reference,
                gateway=gateway,
                samples=payload.samples,
                reference_reason=reference_reason,
            )
        except (ProviderConfigError, PromptError) as exc:
            raise HTTPException(
                status_code=503, detail=f"批改模型未配置：{type(exc).__name__}"
            ) from None
        except Exception:
            raise HTTPException(
                status_code=502, detail="过程题模型调用失败，请稍后重试"
            ) from None

    async with session.begin():
        grading, created = await persist_grading(
            session,
            source=source,
            question_type=payload.question_type,
            reference=reference,
            suggestion=suggestion,
        )
        return GradingCreateResponse(
            route="grading",
            duplicate=not created,
            grading=await _detail(session, grading),
        )


@router.get("/api/gradings/{grading_id}", response_model=GradingDetail)
async def get_grading(
    grading_id: int, session: AsyncSession = Depends(get_session)
) -> GradingDetail:
    async with session.begin():
        grading = await _get_or_404(session, grading_id)
        return await _detail(session, grading)


@router.post("/api/gradings/{grading_id}/confirm", response_model=GradingDetail)
async def confirm_grading(
    grading_id: int,
    payload: ConfirmRequest,
    session: AsyncSession = Depends(get_session),
) -> GradingDetail:
    async with session.begin():
        grading = await _get_or_404(session, grading_id)
        if payload.base_version != grading.current_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "版本已变化，请刷新后重试",
                    "current_version": grading.current_version,
                },
            )
        versions = await get_versions(session, grading.id)
        latest = versions[-1]
        verdict = payload.verdict or latest.verdict
        if verdict not in ("correct", "wrong"):
            raise HTTPException(status_code=422, detail="建议值为待确认，请明确选择 correct/wrong")

        try:
            await append_user_decision(
                session,
                grading,
                action="confirmed",
                verdict=verdict,  # type: ignore[arg-type]
                actor=payload.actor,
                reason="user_confirmed",
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="版本冲突，请刷新后重试") from None
        return await _detail(session, grading)


@router.post("/api/gradings/{grading_id}/appeal", response_model=GradingDetail)
async def appeal_grading(
    grading_id: int,
    payload: AppealRequest,
    session: AsyncSession = Depends(get_session),
) -> GradingDetail:
    async with session.begin():
        grading = await _get_or_404(session, grading_id)
        if payload.base_version != grading.current_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "版本已变化，请刷新后重试",
                    "current_version": grading.current_version,
                },
            )
        try:
            await append_user_decision(
                session,
                grading,
                action="appealed",
                verdict=payload.verdict,
                actor=payload.actor,
                reason=(payload.reason or "user_appeal")[:200],
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="版本冲突，请刷新后重试") from None
        return await _detail(session, grading)
