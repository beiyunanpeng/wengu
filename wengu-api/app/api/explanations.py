"""P1-8 三段式讲解 API：错题订正与拍照答疑共用同一引擎。

POST 会调用模型（缓存命中除外），并写 explanation_shown 事实事件；
GET 不存在，避免纯查询页误触模型。事实事件只存元数据，不含题目/答案/讲解正文。
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.prompts.loader import PromptError
from app.providers.failover import AllProvidersFailed
from app.providers.registry import ProviderConfigError
from app.services.ai_gateway import AiGateway, get_ai_gateway
from app.services.explanation import (
    ENTRY_MISTAKE,
    MODE_GUIDE,
    ExplainContextNotFound,
    ExplainContextUnavailable,
    ExplanationQualityError,
    choose_strategy,
    default_mode,
    has_attempt,
    needs_soft_gate,
    next_hint_level,
    prompt_values,
    quality_gate,
    read_context,
    record_attempt,
    record_shown,
    resolve_mode,
    strategy_label,
)
from app.services.model_audit import DailyLimitExceeded

router = APIRouter(tags=["explanations"])

SourceKind = Literal["mistake", "problem_extraction", "ingestion_draft"]
RequestedMode = Literal["auto", "guide", "full"]
FinalMode = Literal["guide", "full"]


class ExplanationRequest(BaseModel):
    source_kind: SourceKind
    source_id: int = Field(ge=1)
    mode: RequestedMode = "auto"
    hint_level: int = Field(default=1, ge=1, le=3)
    request_id: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=100
    )


class AttemptRequest(BaseModel):
    source_kind: SourceKind
    source_id: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=100)
    mode: FinalMode = "guide"
    hint_level: int = Field(ge=1, le=3)


class ExplanationBody(BaseModel):
    focus: str
    steps: list[str]
    consolidation: str
    answer: str | None


class ExplanationMeta(BaseModel):
    provider: str
    model: str
    prompt_id: str
    prompt_version: int
    cache_hit: bool
    latency_ms: int


class ExplanationResponse(BaseModel):
    source_kind: SourceKind
    source_id: int
    entry: Literal["mistake", "question"]
    mode: FinalMode
    requested_mode: RequestedMode
    default_mode: FinalMode
    strategy: str
    strategy_label: str
    hint_level: int | None
    next_hint_level: int | None
    attempted: bool
    soft_gate: bool
    answer_shown: bool
    leak_flags: list[str]
    request_id: str
    explanation: ExplanationBody
    meta: ExplanationMeta


class AttemptResponse(BaseModel):
    source_kind: SourceKind
    source_id: int
    attempt_id: str
    recorded: bool
    attempted: bool


async def _context_or_http(
    session: AsyncSession, payload: ExplanationRequest | AttemptRequest
):
    try:
        return await read_context(session, payload.source_kind, payload.source_id)
    except ExplainContextNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ExplainContextUnavailable as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "当前内容暂不适合讲解", "reason": exc.reason},
        ) from None


@router.post("/api/explanations", response_model=ExplanationResponse)
async def create_explanation(
    payload: ExplanationRequest,
    session: AsyncSession = Depends(get_session),
    gateway: AiGateway = Depends(get_ai_gateway),
) -> ExplanationResponse:
    async with session.begin():
        context = await _context_or_http(session, payload)
        attempted = await has_attempt(session, context)

    mode = resolve_mode(context, payload.mode)
    strategy = choose_strategy(context)
    hint = payload.hint_level if mode == MODE_GUIDE else 0
    soft_gate = needs_soft_gate(context, mode=mode, attempted=attempted)
    prompt_id = "explain_guide" if mode == MODE_GUIDE else "explain_full"

    values = prompt_values(
        context,
        mode=mode,
        strategy=strategy,
        hint_level=hint,
        attempted=attempted,
    )
    values.pop("PROBLEM_TEXT", None)
    values.pop("HINT_LEVEL", None)

    try:
        explanation, meta = await gateway.solve_explain(
            context.problem_text,
            prompt_id=prompt_id,
            hint_level=hint,
            extra_values=values,
        )
        gated = quality_gate(
            explanation, mode=mode, standard_answer=context.standard_answer
        )
    except DailyLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except (PromptError, ProviderConfigError) as exc:
        raise HTTPException(
            status_code=503, detail=f"讲解模型未配置：{type(exc).__name__}"
        ) from None
    except AllProvidersFailed as exc:
        raise HTTPException(
            status_code=503 if exc.config_only else 502,
            detail=(
                f"讲解模型未配置：{exc.kind}"
                if exc.config_only
                else f"讲解模型调用失败（{exc.kind}），请稍后重试"
            ),
        ) from None
    except ExplanationQualityError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "讲解质量未达标，请重试", "reasons": list(exc.reasons)},
        ) from None
    except Exception:
        raise HTTPException(
            status_code=502, detail="讲解模型调用失败，请稍后重试"
        ) from None

    async with session.begin():
        await record_shown(
            session,
            context,
            request_id=payload.request_id,
            mode=mode,
            requested_mode=payload.mode,
            default_mode=default_mode(context),
            strategy=strategy,
            hint_level=hint if mode == MODE_GUIDE else None,
            attempted=attempted,
            soft_gate=soft_gate,
            answer_shown=gated.answer is not None,
            leak_flags=gated.leak_flags,
            meta=meta,
        )

    return ExplanationResponse(
        source_kind=payload.source_kind,
        source_id=payload.source_id,
        entry=context.entry,
        mode=mode,
        requested_mode=payload.mode,
        default_mode=default_mode(context),
        strategy=strategy,
        strategy_label=strategy_label(strategy),
        hint_level=hint if mode == MODE_GUIDE else None,
        next_hint_level=next_hint_level(mode, hint),
        attempted=attempted,
        soft_gate=soft_gate,
        answer_shown=gated.answer is not None,
        leak_flags=list(gated.leak_flags),
        request_id=payload.request_id,
        explanation=ExplanationBody(
            focus=gated.focus,
            steps=list(gated.steps),
            consolidation=gated.consolidation,
            answer=gated.answer,
        ),
        meta=ExplanationMeta(
            provider=meta.provider,
            model=meta.model,
            prompt_id=meta.prompt_id,
            prompt_version=meta.prompt_version,
            cache_hit=bool(meta.raw.get("cache_hit")),
            latency_ms=meta.latency_ms,
        ),
    )


@router.post("/api/explanations/attempts", response_model=AttemptResponse)
async def record_explanation_attempt(
    payload: AttemptRequest,
    session: AsyncSession = Depends(get_session),
) -> AttemptResponse:
    async with session.begin():
        context = await _context_or_http(session, payload)
        if context.entry != ENTRY_MISTAKE:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "拍照答疑不需要记录动手尝试",
                    "reason": "attempt_not_required",
                },
            )
        _, created = await record_attempt(
            session,
            context,
            attempt_id=payload.attempt_id,
            mode=payload.mode,
            hint_level=payload.hint_level,
        )
        attempted = await has_attempt(session, context)

    return AttemptResponse(
        source_kind=payload.source_kind,
        source_id=payload.source_id,
        attempt_id=payload.attempt_id,
        recorded=created,
        attempted=attempted,
    )
