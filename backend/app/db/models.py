"""Imports every ORM model so metadata is complete (Alembic autogenerate, tests)."""

from app.messaging.models import OutboxEvent, ProcessedEvent
from app.modules.admin.models import AuditLog, UserReport
from app.modules.analytics.models import DailyMetric
from app.modules.applications.models import BountyApplication, BountyAssignment
from app.modules.assets.models import AssetOperation, RewardAsset
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, UserSession
from app.modules.bounties.models import Bounty, BountyBookmark, BountySkill, BountyTag, BountyViewDaily
from app.modules.compliance.models import (
    AccountDeletionRequest,
    DataExport,
    LegalAcceptance,
    LegalDocumentVersion,
    ScreeningEntry,
)
from app.modules.credentials.models import IssuedCredential
from app.modules.discovery.models import SavedSearch, SavedSearchMatch, SkillEdge, SkillNode
from app.modules.disputes.models import Dispute, DisputeEvidence
from app.modules.escrow.models import BountyMilestone, DisputeVote
from app.modules.feedback.models import Feedback
from app.modules.github.models import GitHubAccount, SubmissionPullRequest
from app.modules.notifications.models import EmailDelivery, Notification, NotificationPreference
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    PaymentRecord,
)
from app.modules.qa.models import BountyQAPost, BountyQAVote
from app.modules.reputation.models import CompletionAttestation
from app.modules.submissions.models import BountySubmission, SubmissionRevision
from app.modules.users.models import User, UserSkill, Wallet
from app.modules.wallets.models import PasskeyWallet, SponsoredTransaction

__all__ = [
    "AccountDeletionRequest",
    "AssetOperation",
    "AuditLog",
    "BlockchainTransaction",
    "Bounty",
    "BountyApplication",
    "BountyAssignment",
    "BountyBookmark",
    "BountyEscrow",
    "BountyMilestone",
    "BountyQAPost",
    "BountyQAVote",
    "BountySkill",
    "BountySubmission",
    "BountyTag",
    "BountyViewDaily",
    "CompletionAttestation",
    "DailyMetric",
    "DataExport",
    "Dispute",
    "DisputeEvidence",
    "DisputeVote",
    "EmailDelivery",
    "EmailVerificationToken",
    "Feedback",
    "GitHubAccount",
    "IssuedCredential",
    "LegalAcceptance",
    "LegalDocumentVersion",
    "Notification",
    "NotificationPreference",
    "OutboxEvent",
    "PasskeyWallet",
    "PasswordResetToken",
    "PaymentRecord",
    "ProcessedEvent",
    "RewardAsset",
    "SavedSearch",
    "SavedSearchMatch",
    "ScreeningEntry",
    "SkillEdge",
    "SkillNode",
    "SponsoredTransaction",
    "SubmissionPullRequest",
    "SubmissionRevision",
    "User",
    "UserReport",
    "UserSession",
    "UserSkill",
    "Wallet",
]
