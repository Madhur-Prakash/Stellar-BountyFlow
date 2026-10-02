"""Issued W3C verifiable credentials. The signed document is stored as issued; revocation only sets its bit in
the public Bitstring Status List (``status_index``) and never changes the document."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.db.types import str_enum


class CredentialKind(StrEnum):
    COMPLETION = "COMPLETION"  # one attested completion
    SUMMARY = "SUMMARY"  # every attested completion at issue time


class IssuedCredential(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_verifiable_credentials"
    __table_args__ = (
        Index("ix_bountyflow_verifiable_credentials_user_kind", "user_id", "kind"),
        # The export reads a user's standing credentials; anonymisation revokes exactly those.
        Index(
            "ix_bountyflow_verifiable_credentials_user_standing",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        # At most one standing completion credential per attestation (re-issuing returns it).
        Index(
            "uq_bountyflow_verifiable_credentials_active_completion",
            "attestation_id",
            unique=True,
            postgresql_where=text("kind = 'COMPLETION' AND revoked_at IS NULL"),
        ),
        # The public revocation status list is built from one issuer's revoked indexes.
        Index(
            "ix_bountyflow_verifiable_credentials_revoked",
            "issuer_did",
            "status_index",
            postgresql_where=text("revoked_at IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bountyflow_users.id", ondelete="RESTRICT"))
    kind: Mapped[CredentialKind] = mapped_column(str_enum(CredentialKind, "credential_kind"), nullable=False)
    attestation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_completion_attestations.id", ondelete="RESTRICT")
    )
    # Attestation row ids a summary covers (a completion credential covers only ``attestation_id``).
    attestation_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject_did: Mapped[str] = mapped_column(String(120), nullable=False)
    issuer_did: Mapped[str] = mapped_column(String(200), nullable=False)
    status_index: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None]
    revocation_reason: Mapped[str | None] = mapped_column(String(200))
