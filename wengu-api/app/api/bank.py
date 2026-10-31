"""P3-1 家长录题审核面：bank_drafts → 人工确认 → problem_bank（全部家长专属）。

外部 agent 转录的空白真题只落 `bank_drafts`；本模块负责审核闸门与入本：
- 必填齐全（缺 answer 拒绝）→ 防"模型编答案"：答案只能来自卷面/家长补填；
- verify 过 AST 白名单沙箱，结果写 verified / unverifiable；
  表达式非法（import/赋值/属性访问）或纯数值矛盾一律拒绝入库；
- 入库固定 `unaudited=true` / `blind_verified=false`，供 UI 透传"未经教师审核"；
- 手填直录与队列确认走同一 `normalize → check_approvable → classify_verify` 闸门。

P3-1c：已入库题可编辑/软作废（status active|voided），**不做物理删除**。
编辑合并后重跑同一套闸门；作废题退出运行时检索池，但历史 attempts/事件不改写。
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


class BankItemInfo(BaseModel):
    """家长区已入库题目视图：可见答案/verify，孩子区无此入口。"""

    id: int
    external_id: str
    topic_id: str | None
    topic_name: str | None
    subject: str
    type: str | None
    difficulty: str | None
    prompt: str
    answer: str
    acceptable: list[str]
    unordered: bool
    verify: str
    verify_status: str
    choices: list[dict[str, Any]]
    figure: str | None
    hide_choice_text: bool
    percent: bool
    status: str
    source: str
    unaudited: bool
    blind_verified: bool
    created_at: datetime
    updated_at: datetime | None


class BankItemList(BaseModel):
    items: list[BankItemInfo]
    total: int
    limit: int
    offset: int


class BankItemEditRequest(BaseModel):
    """编辑覆盖项；只合并显式提交的字段（figure 显式 null 表示清空）。"""

    prompt: str | None = Field(default=None, max_length=4000)
    answer: str | None = Field(default=None, max_length=1000)
    acceptable: list[str] | None = Field(default=None, max_length=50)
    unordered: bool | None = None
    verify: str | None = Field(default=None, max_length=4000)
    topic_id: str | None = Field(default=None, max_length=64)
    type: str | None = Field(default=None, max_length=16)
    difficulty: str | None = Field(default=None, max_length=40)
    choices: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    figure: str | None = None


class BankItemStatusResponse(BaseModel):
    problem_bank_id: int
    status: str
    updated_at: datetime | None


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


def _json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _row_raw(row: ProblemBankItem) -> dict[str, Any]:
    """已入库行 → 归一化输入；编辑时先还原再合并覆盖值。"""

    return {
        "topic_id": row.topic_id or "",
        "subject": row.subject,
        "type": row.question_type or "",
        "prompt": row.problem_text,
        "answer": row.answer,
        "acceptable": [
            item
            for item in _json_list(row.acceptable_answers_json)
            if isinstance(item, str)
        ],
        "unordered": bool(row.unordered),
        "verify": row.verify or "",
        "choices": [
            item for item in _json_list(row.choices_json) if isinstance(item, dict)
        ],
        "figure": row.figure,
        "difficulty": row.difficulty or "",
        "hide_choice_text": bool(row.hide_choice_text),
        "percent": bool(row.percent),
    }


def _apply_normalized(
    row: ProblemBankItem, normalized: dict[str, Any], verify_status: str
) -> None:
    choices = normalized.get("choices") or []
    row.subject = normalized["subject"]
    row.problem_text = normalized["prompt"]
    row.answer = normalized["answer"]
    row.acceptable_answers_json = json.dumps(
        normalized["acceptable"], ensure_ascii=False
    )
    row.unordered = normalized["unordered"]
    row.verify = normalized["verify"]
    row.verify_status = verify_status
    row.topic_id = normalized["topic_id"]
    row.question_type = normalized["type"]
    row.difficulty = normalized["difficulty"] or None
    row.choices_json = (
        json.dumps(choices, ensure_ascii=False, sort_keys=True) if choices else None
    )
    row.figure = normalized["figure"]
    row.hide_choice_text = normalized["hide_choice_text"]
    row.percent = normalized["percent"]


def _item_info(row: ProblemBankItem, topic_name: str | None) -> BankItemInfo:
    return BankItemInfo(
        id=row.id,
        external_id=row.external_id,
        topic_id=row.topic_id,
        topic_name=topic_name,
        subject=row.subject,
        type=row.question_type,
        difficulty=row.difficulty,
        prompt=row.problem_text,
        answer=row.answer,
        acceptable=[
            item
            for item in _json_list(row.acceptable_answers_json)
            if isinstance(item, str)
        ],
        unordered=bool(row.unordered),
        verify=row.verify,
        verify_status=row.verify_status,
        choices=[
            item for item in _json_list(row.choices_json) if isinstance(item, dict)
        ],
        figure=row.figure,
        hide_choice_text=bool(row.hide_choice_text),
        percent=bool(row.percent),
        status=row.status,
        source=row.source,
        unaudited=bool(row.unaudited),
        blind_verified=bool(row.blind_verified),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _topic_name(session: AsyncSession, topic_id: str | None) -> str | None:
    if not topic_id:
        return None
    return await session.scalar(
        select(KnowledgeSeed.name).where(KnowledgeSeed.id == topic_id)
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


@router.get("/api/bank/items", response_model=BankItemList)
async def list_bank_items(
    status: Literal["active", "voided", "all"] = "active",
    topic_id: str | None = Query(default=None, max_length=64),
    subject: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> BankItemList:
    """已入库题列表（家长区，含答案）；默认只看 active，按 id 倒序。"""

    conditions = []
    if status != "all":
        conditions.append(ProblemBankItem.status == status)
    if topic_id and topic_id.strip():
        conditions.append(ProblemBankItem.topic_id == topic_id.strip())
    if subject and subject.strip():
        conditions.append(ProblemBankItem.subject == subject.strip())

    total = (
        await session.execute(
            select(func.count()).select_from(ProblemBankItem).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.scalars(
            select(ProblemBankItem)
            .where(*conditions)
            .order_by(ProblemBankItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    topic_ids = {row.topic_id for row in rows if row.topic_id}
    topic_names: dict[str, str] = {}
    if topic_ids:
        topic_names = {
            topic_id: name
            for topic_id, name in (
                await session.execute(
                    select(KnowledgeSeed.id, KnowledgeSeed.name).where(
                        KnowledgeSeed.id.in_(topic_ids)
                    )
                )
            ).all()
        }
    return BankItemList(
        items=[_item_info(row, topic_names.get(row.topic_id or "")) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/api/bank/items/{item_id}", response_model=BankItemInfo)
async def update_bank_item(
    item_id: int,
    payload: BankItemEditRequest,
    session: AsyncSession = Depends(get_session),
) -> BankItemInfo:
    """编辑已入库题：合并覆盖值后重跑 normalize → check_approvable → classify_verify。

    `external_id` 不变，历史 attempts/事件与判分不回溯；verify_status 按新内容重算。
    """

    async with session.begin():
        row = await session.get(ProblemBankItem, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="题库条目不存在")

        overrides = payload.model_dump(exclude_unset=True)
        if not overrides:
            raise HTTPException(
                status_code=422,
                detail={"message": "没有可更新的字段", "code": "no_fields"},
            )
        merged = _row_raw(row)
        for key, value in overrides.items():
            if key == "figure" or value is not None:
                merged[key] = value

        normalized, errors = await _normalize_against_seed(session, merged)
        if errors or normalized is None:
            raise _gate_error("编辑字段校验未通过", "normalize_failed", errors)

        gate_errors = check_approvable(normalized)
        if gate_errors:
            raise _gate_error("编辑后必填项未通过审核", "missing_fields", gate_errors)

        try:
            verify_status, _ = classify_verify(normalized)
        except BankVerifyError as exc:
            raise _verify_error(exc) from None

        _apply_normalized(row, normalized, verify_status)
        row.updated_at = datetime.now(UTC)
        await session.flush()
        # SQLite 不保存时区：重新读回，保证响应与后续 GET 的 updated_at 序列化一致
        await session.refresh(row)
        response = _item_info(row, await _topic_name(session, row.topic_id))
    reset_bank_cache()
    return response


async def _set_item_status(
    session: AsyncSession, item_id: int, target: str
) -> BankItemStatusResponse:
    """软作废/撤销：只翻 status + updated_at，重复调用幂等（不改历史事实）。"""

    changed = False
    async with session.begin():
        row = await session.get(ProblemBankItem, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="题库条目不存在")
        if row.status != target:
            row.status = target
            row.updated_at = datetime.now(UTC)
            changed = True
            await session.flush()
            await session.refresh(row)
        response = BankItemStatusResponse(
            problem_bank_id=row.id,
            status=row.status,
            updated_at=row.updated_at,
        )
    if changed:
        reset_bank_cache()
    return response


@router.post("/api/bank/items/{item_id}/void", response_model=BankItemStatusResponse)
async def void_bank_item(
    item_id: int, session: AsyncSession = Depends(get_session)
) -> BankItemStatusResponse:
    return await _set_item_status(session, item_id, "voided")


@router.post("/api/bank/items/{item_id}/unvoid", response_model=BankItemStatusResponse)
async def unvoid_bank_item(
    item_id: int, session: AsyncSession = Depends(get_session)
) -> BankItemStatusResponse:
    return await _set_item_status(session, item_id, "active")
