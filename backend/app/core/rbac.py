"""Role-based access control.

Two layers protect every resource:

1. **Permissions (RBAC)** — what a *role* may do platform-wide (e.g. moderate any bounty, read audit logs).
   Routes declare them with ``Annotated[User, Depends(require_permission(Permission.X))]`` (see app.dependencies);
   the matrix below is the single source of truth and is exposed to the frontend on ``/auth/me`` so UI gating
   never diverges from the API.
2. **Ownership / relationship checks** — enforced in domain services (a requester manages *their* bounty, an
   assigned contributor submits to *their* assignment). Holding a permission never bypasses the smart contract:
   on-chain authorization is enforced independently by the escrow contract.

Requester and contributor are *capabilities* every active user has, not roles.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.exceptions import Forbidden
from app.modules.users.models import Role, User


class Permission(StrEnum):
    # Marketplace participation (every active user)
    BOUNTY_CREATE = "bounty:create"
    APPLICATION_CREATE = "application:create"
    DISPUTE_RAISE = "dispute:raise"
    REPORT_CREATE = "report:create"
    WALLET_MANAGE = "wallet:manage"

    # Moderation
    BOUNTY_MODERATE = "bounty:moderate"  # hide / unhide / force-cancel any bounty
    BOUNTY_FEATURE = "bounty:feature"
    BOUNTY_VIEW_ALL = "bounty:view_all"  # drafts, hidden and unlisted bounties
    APPLICATION_VIEW_ALL = "application:view_all"
    SUBMISSION_VIEW_ALL = "submission:view_all"
    DISPUTE_VIEW_ALL = "dispute:view_all"
    DISPUTE_RESOLVE = "dispute:resolve"
    REPORT_REVIEW = "report:review"
    FEEDBACK_REVIEW = "feedback:review"  # read the product feedback queue and mark notes handled
    USER_VIEW_ALL = "user:view_all"
    TRANSACTION_VIEW_ALL = "transaction:view_all"
    AUDIT_READ = "audit:read"
    ANALYTICS_PLATFORM = "analytics:platform"
    SYSTEM_HEALTH = "system:health"

    # Administration
    USER_MANAGE = "user:manage"  # suspend / reactivate accounts
    USER_ASSIGN_ROLE = "user:assign_role"
    ASSET_MANAGE = "asset:manage"  # add, enable/disable and deploy reward assets


_USER: frozenset[Permission] = frozenset(
    {
        Permission.BOUNTY_CREATE,
        Permission.APPLICATION_CREATE,
        Permission.DISPUTE_RAISE,
        Permission.REPORT_CREATE,
        Permission.WALLET_MANAGE,
    }
)

_MODERATOR: frozenset[Permission] = _USER | frozenset(
    {
        Permission.BOUNTY_MODERATE,
        Permission.BOUNTY_FEATURE,
        Permission.BOUNTY_VIEW_ALL,
        Permission.APPLICATION_VIEW_ALL,
        Permission.SUBMISSION_VIEW_ALL,
        Permission.DISPUTE_VIEW_ALL,
        Permission.DISPUTE_RESOLVE,
        Permission.REPORT_REVIEW,
        Permission.FEEDBACK_REVIEW,
        Permission.USER_VIEW_ALL,
        Permission.TRANSACTION_VIEW_ALL,
        Permission.AUDIT_READ,
        Permission.ANALYTICS_PLATFORM,
        Permission.SYSTEM_HEALTH,
    }
)

_ADMIN: frozenset[Permission] = _MODERATOR | frozenset(
    {
        Permission.USER_MANAGE,
        Permission.USER_ASSIGN_ROLE,
        Permission.ASSET_MANAGE,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: _USER,
    Role.MODERATOR: _MODERATOR,
    Role.ADMIN: _ADMIN,
}


def permissions_for(user: User | None) -> frozenset[Permission]:
    if user is None or not user.is_active:
        return frozenset()
    return ROLE_PERMISSIONS.get(user.role, frozenset())


def has_permission(user: User | None, permission: Permission) -> bool:
    return permission in permissions_for(user)


def ensure_permission(user: User | None, permission: Permission, message: str | None = None) -> None:
    if not has_permission(user, permission):
        raise Forbidden(
            message or "You do not have permission to perform this action.",
            details={"required_permission": permission.value},
        )


def can_assign_role(actor: User, target: User, new_role: Role) -> bool:
    """Admins may change roles, but never their own (prevents accidental self-lockout / escalation loops)."""
    return has_permission(actor, Permission.USER_ASSIGN_ROLE) and actor.id != target.id and new_role in Role
