"""Authentication request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.schemas import APIModel
from app.modules.users.schemas import normalize_username


def _check_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    if value.strip() != value or not value.strip():
        raise ValueError("Password must not start or end with whitespace")
    classes = sum(
        [
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(not c.isalnum() for c in value),
        ]
    )
    if classes < 2:
        raise ValueError("Use a mix of letters, numbers, or symbols")
    return value


class RegisterRequest(APIModel):
    email: EmailStr
    password: str
    username: str
    display_name: str = Field(min_length=1, max_length=80)

    _pw = field_validator("password")(classmethod(lambda cls, v: _check_password(v)))
    _un = field_validator("username")(classmethod(lambda cls, v: normalize_username(v)))

    @field_validator("display_name")
    @classmethod
    def _dn(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Display name is required")
        return v


class LoginRequest(APIModel):
    # Lookup only: strict EmailStr validation would reject existing accounts on special-use domains
    # (for example accounts on reserved domains such as `*.test`) before the credential check.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(APIModel):
    token: str = Field(min_length=10, max_length=200)


class ForgotPasswordRequest(APIModel):
    email: str = Field(min_length=3, max_length=320)  # lookup only; the response is generic either way


class ResetPasswordRequest(APIModel):
    token: str = Field(min_length=10, max_length=200)
    password: str

    _pw = field_validator("password")(classmethod(lambda cls, v: _check_password(v)))


class SessionOut(APIModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime | None
    user_agent: str | None
    is_current: bool


class VerifiedResponse(APIModel):
    verified: bool = True
