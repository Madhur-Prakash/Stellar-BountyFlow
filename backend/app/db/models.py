"""Imports every ORM model so metadata is complete (Alembic autogenerate, tests)."""

from app.messaging.models import OutboxEvent, ProcessedEvent
from app.modules.admin.models import AuditLog, UserReport
from app.modules.analytics.models import DailyMetric
from app.modules.applications.models import BountyApplication, BountyAssignment
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, UserSession
from app.modules.bounties.models import Bounty, BountyBookmark, BountySkill, BountyTag, BountyViewDaily
from app.modules.disputes.models import Dispute, DisputeEvidence
from app.modules.notifications.models import EmailDelivery, Notification, NotificationPreference
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    PaymentRecord,
)
from app.modules.submissions.models import BountySubmission, SubmissionRevision
from app.modules.users.models import User, UserSkill, Wallet

__all__ = [
    "AuditLog",
    "BlockchainTransaction",
    "Bounty",
    "BountyApplication",
    "BountyAssignment",
    "BountyBookmark",
    "BountyEscrow",
    "BountySkill",
    "BountySubmission",
    "BountyTag",
    "BountyViewDaily",
    "DailyMetric",
    "Dispute",
    "DisputeEvidence",
    "EmailDelivery",
    "EmailVerificationToken",
    "Notification",
    "NotificationPreference",
    "OutboxEvent",
    "PasswordResetToken",
    "PaymentRecord",
    "ProcessedEvent",
    "SubmissionRevision",
    "User",
    "UserReport",
    "UserSession",
    "UserSkill",
    "Wallet",
]
