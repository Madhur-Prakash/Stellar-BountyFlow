"""RBAC permission matrix: USER < MODERATOR < ADMIN, inactive users hold nothing, role assignment rules."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import Forbidden
from app.core.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    can_assign_role,
    ensure_permission,
    has_permission,
    permissions_for,
)
from app.modules.users.models import Role, User

PARTICIPATION = {
    Permission.BOUNTY_CREATE,
    Permission.APPLICATION_CREATE,
    Permission.DISPUTE_RAISE,
    Permission.REPORT_CREATE,
    Permission.WALLET_MANAGE,
}
MODERATION = {
    Permission.BOUNTY_MODERATE,
    Permission.BOUNTY_FEATURE,
    Permission.BOUNTY_VIEW_ALL,
    Permission.APPLICATION_VIEW_ALL,
    Permission.SUBMISSION_VIEW_ALL,
    Permission.DISPUTE_VIEW_ALL,
    Permission.DISPUTE_RESOLVE,
    Permission.REPORT_REVIEW,
    Permission.USER_VIEW_ALL,
    Permission.TRANSACTION_VIEW_ALL,
    Permission.AUDIT_READ,
    Permission.ANALYTICS_PLATFORM,
    Permission.SYSTEM_HEALTH,
}
ADMINISTRATION = {Permission.USER_MANAGE, Permission.USER_ASSIGN_ROLE}


def make_user(role: Role, *, active: bool = True) -> User:
    return User(id=uuid.uuid4(), role=role, is_active=active, username=f"u{uuid.uuid4().hex[:6]}")


def test_user_has_participation_only() -> None:
    perms = permissions_for(make_user(Role.USER))
    assert perms == PARTICIPATION
    assert not perms & MODERATION
    assert not perms & ADMINISTRATION


def test_moderator_has_moderation_but_not_administration() -> None:
    perms = permissions_for(make_user(Role.MODERATOR))
    assert perms == PARTICIPATION | MODERATION
    assert Permission.USER_MANAGE not in perms
    assert Permission.USER_ASSIGN_ROLE not in perms


def test_admin_has_every_permission() -> None:
    assert permissions_for(make_user(Role.ADMIN)) == set(Permission)


def test_roles_are_strictly_nested() -> None:
    assert ROLE_PERMISSIONS[Role.USER] < ROLE_PERMISSIONS[Role.MODERATOR] < ROLE_PERMISSIONS[Role.ADMIN]


@pytest.mark.parametrize("role", list(Role))
def test_inactive_users_have_no_permissions(role: Role) -> None:
    user = make_user(role, active=False)
    assert permissions_for(user) == frozenset()
    assert not has_permission(user, Permission.BOUNTY_CREATE)


def test_anonymous_has_no_permissions() -> None:
    assert permissions_for(None) == frozenset()


def test_ensure_permission_raises_forbidden_with_required_permission() -> None:
    with pytest.raises(Forbidden) as excinfo:
        ensure_permission(make_user(Role.MODERATOR), Permission.USER_MANAGE)
    assert excinfo.value.details == {"required_permission": "user:manage"}
    ensure_permission(make_user(Role.ADMIN), Permission.USER_MANAGE)


def test_role_assignment_rules() -> None:
    admin, other_admin = make_user(Role.ADMIN), make_user(Role.ADMIN)
    moderator, user = make_user(Role.MODERATOR), make_user(Role.USER)
    assert can_assign_role(admin, user, Role.MODERATOR)
    assert can_assign_role(admin, other_admin, Role.USER)
    assert not can_assign_role(admin, admin, Role.USER)  # never your own role
    assert not can_assign_role(moderator, user, Role.MODERATOR)
    assert not can_assign_role(user, user, Role.ADMIN)
    assert not can_assign_role(make_user(Role.ADMIN, active=False), user, Role.MODERATOR)
