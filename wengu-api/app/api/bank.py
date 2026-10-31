"""P3-1 家长录题审核面：bank_drafts → 人工确认 → problem_bank（全部家长专属）。

外部 agent 转录的空白真题只落 `bank_drafts`；本模块负责审核闸门与入本：
- 必填齐全（缺 answer 拒绝）→ 防"模型编答案"：答案只能来自卷面/家长补填；
- verify 过 AST 白名单沙箱，结果写 verified / unverifiable；
  表达式非法（import/赋值/属性访问）或纯数值矛盾一律拒绝入库；
- 入库固定 `unaudited=true` / `blind_verified=false`，供 UI 透传"未经教师审核"；
- 手填直录与队列确认走同一 `normalize → check_approvable → classify_verify` 闸门。

家长题是动态数据，只写 SQLite `problem_bank`，绝不写 seed JSON（seed 只读）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.database import get_session
from app.models import BankDraft, ImportBatch, KnowledgeSeed, ProblemBankItem
from app.services.bank import reset_bank_cache
from app.services.bank_import import (
    BankVerifyError,
    check_approvable,
    classify_verify,
    normalize_bank_item,
)
from app.services.ingestion import ItemError

router = APIRouter(tags=["bank"], dependencies=[Depends(require_parent)])

VERIFY_REASON_MESSAGES = {
    "verify_mismatch": "verify 计算结果与标准答案矛盾，拒绝入库；请核对答案或表达式",
}


class BankDraftInfo(BaseModel):
    id: int
    batch_id: int
    filename: str | None
    seq: int
    status: str
    has_placeholder: bool
    created_at: datetime
    topic_id: str
    topic_name: str | None
    subject: str
    type: str
    difficulty: str
    prompt: str
    answer: str
    acceptable: list[str]
    unordered: bool
    verify: str
    choices: list[dict[str, Any]]
    figure: str | None
    source_ref: str


class BankDraftList(BaseModel):
    items: list[BankDraftInfo]
    total: int
    limit: int
    offset: int


class BankDraftApproveRequest(BaseModel):
    """审核页覆盖项；只合并显式提交且非 None 的字段。"""

    prompt: str | None = Field(default=None, max_length=4000)
    answer: str | None = Field(default=None, max_length=1000)
    acceptable: list[str] | None = Field(default=None, max_length=50)
    unordered: bool | None = None
    verify: str | None = Field(default=None, max_length=4000)
    topic_id: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=400)
    choices: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    figure: str | None = None
    hide_choice_text: bool | None = None
    percent: bool | None = None


class BankApproveResponse(BaseModel):
    draft_id: int
    status: str
    problem_bank_id: int
    verify_status: str


class BankRejectResponse(BaseModel):
    draft_id: int
    status: str


class BankManualItemRequest(BaseModel):
    """家长手填直录（无外部 agent 时的兜底入口），字段同草稿契约。"""

    topic_id: str = Field(max_length=64)
    type: str = Field(default="numeric", max_length=16)
    difficulty: str = Field(default="", max_length=40)
    prompt: str = Field(max_length=4000)
    answer: str = Field(default="", max_length=1000)
    acceptable: list[str] = Field(default_factory=list, max_length=50)
    unordered: bool = False
    verify: str = Field(default="", max_length=4000)
    choices: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    figure: str | None = None
    source_ref: str = Field(default="", max_length=400)
    hide_choice_text: bool = False
    percent: bool = False


class BankItemCreated(BaseModel):
    problem_bank_id: int
    external_id: str
    verify_status: str


def _errors_payload(errors: list[ItemError]) -> list[dict[str, Any]]:
    return [asdict(item) for item in errors]


def _gate_error(message: str, code: str, errors: list[ItemError]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": message, "code": code, "errors": _errors_payload(errors)},
    )


def _verify_error(exc: BankVerifyError) -> HTTPException:
    message = VERIFY_REASON_MESSAGES.get(
        exc.reason, "verify 表达式未通过安全沙箱（禁止 import/赋值/属性访问）"
    )
    return HTTPException(
        status_code=422, detail={"message": message, "code": exc.reason}
    )


def _load_draft_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def _normalize_against_seed(
    session: AsyncSession, raw: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[ItemError]]:
    """用 knowledge_seed 中的学科回填 subject；topic 不存在即进 errors。"""

    topic_id = raw.get("topic_id")
    topics: dict[str, str] = {}
    if isinstance(topic_id, str) and topic_id.strip():
        seed = await session.get(KnowledgeSeed, topic_id.strip())
        if seed is not None:
            topics[seed.id] = seed.subject
    return normalize_bank_item(0, raw, topics)


def _build_bank_item(
    normalized: dict[str, Any],
    *,
    external_id: str,
    source: str,
    verify_status: str,
) -> ProblemBankItem:
    choices = normalized.get("choices") or []
    return ProblemBankItem(
        external_id=external_id,
        subject=normalized["subject"],
        problem_text=normalized["prompt"],
        answer=normalized["answer"],
        acceptable_answers_json=json.dumps(
            normalized["acceptable"], ensure_ascii=False
        ),
        unordered=normalized["unordered"],
        verify=normalized["verify"],
        verify_vars_json="{}",
        verify_status=verify_status,
        source=source,
        created_at=datetime.now(UTC),
        topic_id=normalized["topic_id"],
        question_type=normalized["type"],
        difficulty=normalized["difficulty"] or None,
        choices_json=(
            json.dumps(choices, ensure_ascii=False, sort_keys=True) if choices else None
        ),
        figure=normalized["figure"],
        hide_choice_text=normalized["hide_choice_text"],
        percent=normalized["percent"],
        unaudited=True,
        blind_verified=False,
    )


@router.get("/api/bank/drafts", response_model=BankDraftList)
async def list_bank_drafts(
    status: Literal["draft", "approved", "rejected", "all"] = "draft",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> BankDraftList:
    conditions = [] if status == "all" else [BankDraft.status == status]
    total = (
        await session.execute(
            select(func.count()).select_from(BankDraft).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BankDraft, ImportBatch.filename)
            .join(ImportBatch, ImportBatch.id == BankDraft.import_batch_id)
            .where(*conditions)
            .order_by(BankDraft.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    parsed = [(draft, filename, _load_draft_json(draft.normalized_json)) for draft, filename in rows]
    topic_ids = {
        data.get("topic_id")
        for _, _, data in parsed
        if isinstance(data.get("topic_id"), str) and data.get("topic_id")
    }
    topic_names: dict[str, str] = {}
    if topic_ids:
        topic_rows = (
            await session.execute(
                select(KnowledgeSeed.id, KnowledgeSeed.name).where(
                    KnowledgeSeed.id.in_(topic_ids)
                )
            )
        ).all()
        topic_names = {topic_id: name for topic_id, name in topic_rows}

    return BankDraftList(
        items=[
            BankDraftInfo(
                id=draft.id,
                batch_id=draft.import_batch_id,
                filename=filename,
                seq=draft.seq,
                status=draft.status,
                has_placeholder=draft.has_placeholder,
                created_at=draft.created_at,
                topic_id=str(data.get("topic_id") or ""),
                topic_name=topic_names.get(str(data.get("topic_id") or "")),
                subject=str(data.get("subject") or ""),
                type=str(data.get("type") or ""),
                difficulty=str(data.get("difficulty") or ""),
                prompt=str(data.get("prompt") or ""),
                answer=str(data.get("answer") or ""),
                acceptable=[
                    item for item in data.get("acceptable", []) if isinstance(item, str)
                ],
                unordered=data.get("unordered") is True,
                verify=str(data.get("verify") or ""),
                choices=[
                    item for item in data.get("choices", []) if isinstance(item, dict)
                ],
                figure=(
                    data.get("figure") if isinstance(data.get("figure"), str) else None
                ),
                source_ref=str(data.get("source_ref") or ""),
            )
            for draft, filename, data in parsed
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/api/bank/drafts/{draft_id}/approve", response_model=BankApproveResponse
)
async def approve_bank_draft(
    draft_id: int,
    payload: BankDraftApproveRequest,
    session: AsyncSession = Depends(get_session),
) -> BankApproveResponse:
    """审核通过：覆盖项合并 → 必填闸门 → verify 沙箱 → 写 problem_bank。"""

    async with session.begin():
        draft = await session.get(BankDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="录题草稿不存在")
        if draft.status != "draft":
            raise HTTPException(
                status_code=409, detail=f"草稿已是 {draft.status}，不能重复审核"
            )

        stored = _load_draft_json(draft.normalized_json)
        if not stored:
            raise HTTPException(status_code=409, detail="草稿数据损坏，请重新导入")
        overrides = {
            key: value
            for key, value in payload.model_dump(exclude_unset=True).items()
            if value is not None
        }
        merged = {**stored, **overrides}

        normalized, errors = await _normalize_against_seed(session, merged)
        if errors or normalized is None:
            raise _gate_error("录题字段校验未通过", "normalize_failed", errors)

        gate_errors = check_approvable(normalized)
        if gate_errors:
            raise _gate_error("录题必填项未通过审核", "missing_fields", gate_errors)

        try:
            verify_status, _ = classify_verify(normalized)
        except BankVerifyError as exc:
            raise _verify_error(exc) from None

        item = _build_bank_item(
            normalized,
            external_id=f"bank_draft_{draft.id}",
            source="agent_bank",
            verify_status=verify_status,
        )
        session.add(item)
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="该草稿已入库，请刷新") from None

        draft.status = "approved"
        await session.flush()
        response = BankApproveResponse(
            draft_id=draft.id,
            status=draft.status,
            problem_bank_id=item.id,
            verify_status=verify_status,
        )
    reset_bank_cache()
    return response


@router.post("/api/bank/drafts/{draft_id}/reject", response_model=BankRejectResponse)
async def reject_bank_draft(
    draft_id: int, session: AsyncSession = Depends(get_session)
) -> BankRejectResponse:
    async with session.begin():
        draft = await session.get(BankDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="录题草稿不存在")
        if draft.status != "draft":
            raise HTTPException(
                status_code=409, detail=f"草稿已是 {draft.status}，不能重复审核"
            )
        draft.status = "rejected"
        await session.flush()
        return BankRejectResponse(draft_id=draft.id, status=draft.status)


@router.post("/api/bank/items", response_model=BankItemCreated, status_code=201)
async def create_bank_item(
    payload: BankManualItemRequest,
    session: AsyncSession = Depends(get_session),
) -> BankItemCreated:
    """家长手填直录：与队列确认共用同一闸门，不绕过 verify 沙箱。"""

    async with session.begin():
        normalized, errors = await _normalize_against_seed(
            session, payload.model_dump()
        )
        if errors or normalized is None:
            raise _gate_error("录题字段校验未通过", "normalize_failed", errors)

        gate_errors = check_approvable(normalized)
        if gate_errors:
            raise _gate_error("录题必填项未通过审核", "missing_fields", gate_errors)

        try:
            verify_status, _ = classify_verify(normalized)
        except BankVerifyError as exc:
            raise _verify_error(exc) from None

        external_id = f"manual_{uuid.uuid4().hex}"
        item = _build_bank_item(
            normalized,
            external_id=external_id,
            source="parent_manual",
            verify_status=verify_status,
        )
        session.add(item)
        await session.flush()
        response = BankItemCreated(
            problem_bank_id=item.id,
            external_id=external_id,
            verify_status=verify_status,
        )
    reset_bank_cache()
    return response
