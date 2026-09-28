"""Column type helpers."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enums as VARCHAR + CHECK constraint (portable and cheap to migrate, unlike native PG enums)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )
