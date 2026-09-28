"""Authentication endpoints. Tokens travel only in HttpOnly cookies; a readable CSRF cookie backs the
double-submit check for mutating requests."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import NotAuthenticated, error_body
from app.core.rate_limit import client_ip, hit, rate_limit
from app.core.schemas import Message
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, decode_access_token, generate_token
from app.dependencies import CurrentUser, SessionDep
from app.modules.auth import service
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionOut,
    VerifyEmailRequest,
)
from app.modules.auth.service import IssuedTokens
from app.modules.users.schemas import Me
from app.modules.users.service import build_me

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, tokens: IssuedTokens) -> None:
    s = get_settings()

    def put(name: str, value: str, *, max_age: int, httponly: bool, path: str) -> None:
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            httponly=httponly,
            path=path,
            secure=s.cookie_secure,
            samesite=s.cookie_samesite,
            domain=s.cookie_domain,
        )

    put(ACCESS_COOKIE, tokens.access_token, max_age=s.access_token_ttl, httponly=True, path="/")
    put(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=s.refresh_token_ttl,
        httponly=True,
        path=f"{s.api_prefix}/auth",
    )
    # Readable by JavaScript on purpose: the double-submit CSRF token must be echoed in the X-CSRF-Token header.
    put(CSRF_COOKIE, generate_token(24), max_age=s.refresh_token_ttl, httponly=False, path="/")


def _clear_auth_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=s.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path=f"{s.api_prefix}/auth", domain=s.cookie_domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=s.cookie_domain)


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post(
    "/register",
    response_model=Me,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth:register", 10, 3600))],
)
async def register(data: RegisterRequest, request: Request, response: Response, session: SessionDep) -> Me:
    user, tokens = await service.register(session, data, _ua(request), client_ip(request))
    _set_auth_cookies(response, tokens)
    return await build_me(session, user)


@router.post("/login", response_model=Me, dependencies=[Depends(rate_limit("auth:login:ip", 30, 300))])
async def login(data: LoginRequest, request: Request, response: Response, session: SessionDep) -> Me:
    await hit("auth:login:email", data.email.lower(), 10, 300)
    user, tokens = await service.login(session, data.email, data.password, _ua(request), client_ip(request))
    _set_auth_cookies(response, tokens)
    return await build_me(session, user)


@router.post("/refresh", response_model=Me, dependencies=[Depends(rate_limit("auth:refresh", 120, 300))])
async def refresh(request: Request, response: Response, session: SessionDep) -> Response | Me:
    try:
        user, tokens = await service.refresh(session, request.cookies.get(REFRESH_COOKIE))
    except NotAuthenticated as exc:
        failure = JSONResponse(status_code=401, content=error_body(exc.code, exc.message, request))
        _clear_auth_cookies(failure)
        return failure
    _set_auth_cookies(response, tokens)
    return await build_me(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep) -> Response:
    session_id: uuid.UUID | None = None
    try:
        token = request.cookies.get(ACCESS_COOKIE)
        if token:
            session_id = decode_access_token(token).session_id
    except NotAuthenticated:
        session_id = None
    await service.logout(session, session_id, request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.post("/verify-email", response_model=Me, dependencies=[Depends(rate_limit("auth:verify", 30, 300))])
async def verify_email(data: VerifyEmailRequest, session: SessionDep) -> Me:
    user = await service.verify_email(session, data.token)
    return await build_me(session, user)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(user: CurrentUser, session: SessionDep) -> Response:
    await hit("auth:resend", str(user.id), 3, 900)
    await service.request_verification_email(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/forgot-password",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("auth:forgot", 10, 900))],
)
async def forgot_password(data: ForgotPasswordRequest, session: SessionDep) -> Message:
    await hit("auth:forgot:email", data.email.lower(), 3, 900)
    await service.forgot_password(session, data.email)
    return Message(message="If an account exists for that email, a password reset link has been sent.")


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("auth:reset", 10, 900))],
)
async def reset_password(data: ResetPasswordRequest, session: SessionDep) -> Response:
    await service.reset_password(session, data.token, data.password)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=Me)
async def me(user: CurrentUser, session: SessionDep) -> Me:
    return await build_me(session, user)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(request: Request, user: CurrentUser, session: SessionDep) -> list[SessionOut]:
    current = getattr(request.state, "session_id", None)
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            user_agent=s.user_agent,
            is_current=s.id == current,
        )
        for s in await service.list_sessions(session, user)
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await service.revoke_session(session, user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
