"""Compliance records: personal-data exports, account deletion requests, sanctions screening entries, and legal
document versions with their acceptances.

None of these rows hold money. Financial and audit records stay in their own tables and are kept (pseudonymised)
when an account is deleted; see docs/compliance.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.db.types import str_enum


class ExportStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DeletionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ScreeningSource(StrEnum):
    LIST = "LIST"  # synced from the configured sanctions list file or URL
    MANUAL = "MANUAL"  # added by an admin


class LegalDocument(StrEnum):
    TERMS = "TERMS"
    PRIVACY = "PRIVACY"


class DataExport(UUIDPrimaryKey, CreatedAt, Base):
    """A requested copy of a user's personal data. The worker builds the archive (gzip-compressed JSON) and
    stores it here until it expires; expiry clears the archive."""

    __tablename__ = "data_exports"
    __table_args__ = (
        Index("ix_data_exports_user_created", "user_id", "created_at"),
        Index("ix_data_exports_status", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ExportStatus] = mapped_column(
        str_enum(ExportStatus, "export_status"), nullable=False, default=ExportStatus.PENDING
    )
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    archive: Mapped[bytes | None] = mapped_column(LargeBinary)
    archive_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_downloaded_at: Mapped[datetime | None]


class AccountDeletionRequest(UUIDPrimaryKey, CreatedAt, Base):
    """A request to delete an account. It waits out a grace period (cancellable), then the worker anonymises the
    account once nothing blocks it (funded escrows, open disputes, unsettled work)."""

    __tablename__ = "account_deletion_requests"
    __table_args__ = (
        # At most one scheduled deletion per user.
        Index(
            "uq_account_deletion_requests_one_scheduled",
            "user_id",
            unique=True,
            postgresql_where="status = 'SCHEDULED'",
        ),
        Index("ix_account_deletion_requests_status_due", "status", "scheduled_for"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[DeletionStatus] = mapped_column(
        str_enum(DeletionStatus, "deletion_status"), nullable=False, default=DeletionStatus.SCHEDULED
    )
    reason: Mapped[str | None] = mapped_column(Text)
    scheduled_for: Mapped[datetime] = mapped_column(nullable=False)
    cancelled_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    last_attempt_at: Mapped[datetime | None]
    # Why the last attempt could not run (for example a funded escrow opened during the grace period).
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    # The pseudonymous username the account received when it was anonymised.
    pseudonym: Mapped[str | None] = mapped_column(String(30))


class ScreeningEntry(UUIDPrimaryKey, CreatedAt, Base):
    """A Stellar address that must not be used on BountyFlow. Removed entries are kept for the record."""

    __tablename__ = "screening_entries"
    __table_args__ = (
        Index(
            "uq_screening_entries_active",
            "address",
            "source",
            unique=True,
            postgresql_where="removed_at IS NULL",
        ),
        Index("ix_screening_entries_address", "address"),
    )

    address: Mapped[str] = mapped_column(String(56), nullable=False)
    source: Mapped[ScreeningSource] = mapped_column(
        str_enum(ScreeningSource, "screening_source"), nullable=False
    )
    list_name: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None]
    removed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removal_note: Mapped[str | None] = mapped_column(Text)


class LegalDocumentVersion(UUIDPrimaryKey, CreatedAt, Base):
    """A published version of the terms or the privacy notice. A version scheduled for the future can be
    withdrawn until it takes effect; versions are never deleted."""

    __tablename__ = "legal_document_versions"
    __table_args__ = (
        UniqueConstraint("document", "version", name="uq_legal_document_versions_document_version"),
        Index("ix_legal_document_versions_document_effective", "document", "effective_at"),
    )

    document: Mapped[LegalDocument] = mapped_column(str_enum(LegalDocument, "legal_document"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(nullable=False)
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    withdrawn_at: Mapped[datetime | None]
    withdrawn_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LegalAcceptance(UUIDPrimaryKey, Base):
    """A user's acceptance of one legal document version (append-only)."""

    __tablename__ = "legal_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "version_id", name="uq_legal_acceptances_user_version"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    document: Mapped[LegalDocument] = mapped_column(str_enum(LegalDocument, "legal_document"), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "prompt" | "registration"
    request_id: Mapped[str | None] = mapped_column(String(64))
