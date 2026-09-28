"""Shared API schemas: pagination, money, user summaries, and assets."""

from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import BaseModel, BeforeValidator, ConfigDict, HttpUrl, PlainSerializer, TypeAdapter

from app.core.money import fmt, parse_amount

# Decimal amounts are always serialized as fixed 7-decimal strings.
Money = Annotated[Decimal, PlainSerializer(fmt, return_type=str, when_used="always")]
OptionalMoney = Annotated[
    Decimal | None, PlainSerializer(lambda v: fmt(v) if v is not None else None, when_used="always")
]


def _parse_money_input(value: object) -> Decimal:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError('Amounts must be sent as decimal strings, e.g. "12.5"')
    return parse_amount(value)


# Accepts "12.5" (or an integer); floats are rejected to avoid binary rounding of money.
MoneyInput = Annotated[Decimal, BeforeValidator(_parse_money_input), PlainSerializer(fmt, return_type=str)]

_http_url = TypeAdapter(HttpUrl)


def _validate_url(value: object) -> str:
    url = str(_http_url.validate_python(value))
    if len(url) > 500:
        raise ValueError("URL is too long")
    return url


# Validated http(s) URL, stored and serialized as a plain string.
UrlStr = Annotated[str, BeforeValidator(_validate_url)]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](APIModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[Any], total: int, params: PageParams) -> Page[T]:
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=max(1, math.ceil(total / params.page_size)) if total else 0,
        )


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class UserSummary(APIModel):
    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: str | None = None


class Asset(APIModel):
    code: Literal["XLM"] = "XLM"
    issuer: None = None
    type: Literal["native"] = "native"
    contract_id: str | None = None


def native_asset() -> Asset:
    from app.blockchain.config import get_network  # local: blockchain.config depends on core modules

    return Asset(contract_id=get_network().native_asset_contract_id)


class Message(APIModel):
    message: str
