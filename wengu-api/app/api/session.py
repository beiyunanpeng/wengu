"""P2-4 两角色会话 API：家长 PIN 解锁（仅防误入，不是公网认证）。

孩子区（导入 / 核对 / 复习考核 / 错题本 / 看板）全程免 PIN；
家长专属写操作通过 `require_parent` 依赖校验签名 cookie，未解锁一律 403。
公网暴露仍须真鉴权与用户隔离，或走 Tailscale（P5-3）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.session import (
    COOKIE_NAME,
    COOKIE_TTL,
    LOCK_SECONDS,
    PinValidationError,
    is_locked,
    issue_token,
    pin_is_set,
    register_failure,
    reset_failures,
    set_pin,
    token_valid,
    verify_pin,
)

router = APIRouter(tags=["session"])


class SessionStatus(BaseModel):
    pin_set: bool
    parent_unlocked: bool


class PinRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=64)


def _source(request: Request) -> str:
    client = request.client
    return client.host if client is not None and client.host else "unknown"


def _cookie_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def _unlocked(request: Request) -> bool:
    return token_valid(_cookie_token(request))


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="尝试次数过多，请 60 秒后再试",
        headers={"Retry-After": str(int(LOCK_SECONDS))},
    )


def _set_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(),
        max_age=int(COOKIE_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )


async def require_parent(request: Request) -> None:
    """家长专属端点的依赖：签名 cookie 无效/过期即 403（孩子区不受影响）。"""

    if not _unlocked(request):
        raise HTTPException(status_code=403, detail="家长区未解锁：请先输入家长 PIN")


@router.get("/api/session/status", response_model=SessionStatus)
async def session_status(
    request: Request, session: AsyncSession = Depends(get_session)
) -> SessionStatus:
    configured = await pin_is_set(session)
    return SessionStatus(
        pin_set=configured,
        parent_unlocked=configured and _unlocked(request),
    )


@router.post("/api/session/pin/set", response_model=SessionStatus)
async def set_parent_pin(
    payload: PinRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionStatus:
    """首次设置或已解锁后重设；成功后直接下发会话 cookie。"""

    unlocked = _unlocked(request)
    async with session.begin():
        if await pin_is_set(session) and not unlocked:
            raise HTTPException(
                status_code=403, detail="家长 PIN 已设置：请先解锁家长区再修改"
            )
        try:
            await set_pin(session, payload.pin, actor="parent", replace=True)
        except PinValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    _set_cookie(response)
    return SessionStatus(pin_set=True, parent_unlocked=True)


@router.post("/api/session/unlock", response_model=SessionStatus)
async def unlock_parent(
    payload: PinRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionStatus:
    source = _source(request)
    if is_locked(source):
        raise _too_many()
    async with session.begin():
        if not await pin_is_set(session):
            raise HTTPException(status_code=409, detail="尚未设置家长 PIN")
        matched = await verify_pin(session, payload.pin)
    if not matched:
        if register_failure(source):
            raise _too_many()
        raise HTTPException(status_code=401, detail="PIN 不正确")
    reset_failures(source)
    _set_cookie(response)
    return SessionStatus(pin_set=True, parent_unlocked=True)


@router.post("/api/session/lock", response_model=SessionStatus)
async def lock_parent(
    response: Response, session: AsyncSession = Depends(get_session)
) -> SessionStatus:
    response.delete_cookie(COOKIE_NAME, path="/")
    return SessionStatus(pin_set=await pin_is_set(session), parent_unlocked=False)
