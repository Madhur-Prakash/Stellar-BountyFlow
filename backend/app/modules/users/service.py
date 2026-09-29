"""User profile, statistics, and wallet ownership use cases."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain import wallet as wallet_proof
from app.blockchain.config import get_network
from app.cache import keys
from app.cache.invalidation import invalidate_profile
from app.cache.redis import cached_json
from app.core.exceptions import Conflict, NotFound
from app.core.rbac import permissions_for
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.compliance import screening
from app.modules.users import repository as repo
from app.modules.users.models import User, Wallet, WalletVerificationStatus
from app.modules.users.schemas import (
    Me,
    Onboarding,
    ProfileUpdate,
    PublicProfile,
    PublicWallet,
    UserStats,
    WalletChallengeResponse,
    WalletOut,
    WalletVerifyRequest,
)

_CLEARABLE_FIELDS = {"avatar_url", "bio", "github_url", "portfolio_url"}


async def build_me(session: AsyncSession, user: User) -> Me:
    wallet_connected = await repo.has_verified_wallet(session, user.id)
    first_action = await repo.has_taken_first_action(session, user.id)
    profile_completed = bool(user.bio and user.skills and user.display_name)
    return Me(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        bio=user.bio,
        role=user.role,
        permissions=sorted(p.value for p in permissions_for(user)),
        skills=user.skill_names,
        interests=list(user.interests or []),
        github_url=user.github_url,
        portfolio_url=user.portfolio_url,
        wants_to_request=user.wants_to_request,
        wants_to_contribute=user.wants_to_contribute,
        onboarding=Onboarding(
            email_verified=user.email_verified_at is not None,
            profile_completed=profile_completed,
            role_selected=user.wants_to_request or user.wants_to_contribute,
            wallet_connected=wallet_connected,
            first_action_taken=first_action,
            completed=user.onboarding_completed_at is not None,
        ),
        created_at=user.created_at,
    )


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate) -> Me:
    old_username = user.username
    changes = data.model_dump(exclude_unset=True)
    new_username = changes.get("username")
    if (
        new_username
        and new_username != user.username
        and await repo.username_taken(session, new_username, exclude=user.id)
    ):
        raise Conflict("That username is already taken.", details=[{"field": "username", "message": "Taken"}])
    for field in (
        "display_name",
        "username",
        "avatar_url",
        "bio",
        "github_url",
        "portfolio_url",
        "wants_to_request",
        "wants_to_contribute",
    ):
        if field not in changes:
            continue
        value = changes[field]
        if value is None and field not in _CLEARABLE_FIELDS:
            continue  # required columns cannot be cleared
        setattr(user, field, value or None if field in _CLEARABLE_FIELDS else value)
    if "interests" in changes and changes["interests"] is not None:
        user.interests = changes["interests"]
    if "skills" in changes and changes["skills"] is not None:
        repo.set_skills(user, changes["skills"])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("That username is already taken.") from exc
    await session.refresh(user)
    await invalidate_profile(old_username, user.username)
    return await build_me(session, user)


async def complete_onboarding(session: AsyncSession, user: User) -> Me:
    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = utcnow()
        await session.commit()
    return await build_me(session, user)


async def get_public_user(session: AsyncSession, username: str) -> User:
    user = await repo.get_by_username(session, username)
    if user is None or not user.is_active:
        raise NotFound("User not found.")
    return user


async def get_stats(session: AsyncSession, username: str) -> UserStats:
    user = await get_public_user(session, username)

    async def load() -> dict[str, Any]:
        stats = await repo.compute_stats(session, user.id)
        return UserStats.model_validate(stats).model_dump(mode="json")

    return UserStats.model_validate(await cached_json(keys.user_stats(username), keys.TTL_PROFILE, load))


async def get_public_profile(session: AsyncSession, username: str) -> PublicProfile:
    user = await get_public_user(session, username)

    async def load() -> dict[str, Any]:
        wallets = await repo.verified_wallets(session, user.id)
        stats = await repo.compute_stats(session, user.id)
        profile = PublicProfile(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            bio=user.bio,
            skills=user.skill_names,
            interests=list(user.interests or []),
            github_url=user.github_url,
            portfolio_url=user.portfolio_url,
            joined_at=user.created_at,
            wallets=[PublicWallet.model_validate(w) for w in wallets],
            stats=UserStats.model_validate(stats),
        )
        return profile.model_dump(mode="json")

    return PublicProfile.model_validate(await cached_json(keys.profile(username), keys.TTL_PROFILE, load))


# --- Wallets -----------------------------------------------------------------


async def list_wallets(session: AsyncSession, user: User) -> list[WalletOut]:
    return [WalletOut.model_validate(w) for w in await repo.verified_wallets(session, user.id)]


async def create_wallet_challenge(
    user: User, address: str, method: wallet_proof.ProofMethod | None = None
) -> WalletChallengeResponse:
    challenge = await wallet_proof.issue_challenge(str(user.id), address, method)
    return WalletChallengeResponse(
        method=challenge.method,
        challenge_xdr=challenge.xdr,
        message=challenge.message,
        authorization_entries=challenge.authorization_entries,
        network_passphrase=get_network().passphrase,
        expires_at=challenge.expires_at,
    )


async def verify_wallet(session: AsyncSession, user: User, data: WalletVerifyRequest) -> WalletOut:
    """Links a wallet once the issued challenge is answered: a signed SEP-10 transaction, a SEP-53 message
    signature, or (contract accounts) a SEP-45 authorization."""
    address = wallet_proof.validate_address(data.public_address, allow_contract=True)
    network = get_network()
    method = await wallet_proof.verify_proof(
        str(user.id),
        address,
        signed_challenge_xdr=data.signed_challenge_xdr,
        signed_message=data.signed_message,
        signed_authorization_entries=data.signed_authorization_entries,
    )
    # Sanctions screening, once ownership is proven (so only the owner learns the result).
    await screening.enforce(user_id=user.id, addresses=[address], context=screening.WALLET_VERIFICATION)

    existing_owner = await session.scalar(
        select(Wallet).where(
            Wallet.public_address == address,
            Wallet.network == network.network,
            Wallet.verification_status == WalletVerificationStatus.VERIFIED,
        )
    )
    if existing_owner is not None:
        if existing_owner.user_id == user.id:
            return WalletOut.model_validate(existing_owner)
        raise Conflict("This wallet is already linked to another BountyFlow account.")

    wallet = Wallet(
        user_id=user.id,
        public_address=address,
        network=network.network,
        verification_status=WalletVerificationStatus.VERIFIED,
        verified_at=utcnow(),
        verification_note=f"{method}-signature",
        wallet_app=data.wallet_app or ("smart-wallet" if method == "sep45" else None),
        proof_method=method,
    )
    session.add(wallet)
    await session.flush()
    audit.record(
        session,
        actor_id=user.id,
        action="wallet.verified",
        entity_type="wallet",
        entity_id=wallet.id,
        metadata={
            "address": address,
            "network": network.network,
            "wallet_app": wallet.wallet_app,
            "proof": method,
        },
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.WALLET_VERIFIED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("This wallet is already linked to an account.") from exc
    await invalidate_profile(user.username)
    return WalletOut.model_validate(wallet)


async def remove_wallet(session: AsyncSession, user: User, wallet_id: uuid.UUID) -> None:
    wallet = await session.get(Wallet, wallet_id)
    if (
        wallet is None
        or wallet.user_id != user.id
        or wallet.verification_status != WalletVerificationStatus.VERIFIED
    ):
        raise NotFound("Wallet not found.")
    wallet.verification_status = WalletVerificationStatus.REVOKED
    wallet.revoked_at = utcnow()
    audit.record(
        session,
        actor_id=user.id,
        action="wallet.removed",
        entity_type="wallet",
        entity_id=wallet.id,
        metadata={"address": wallet.public_address},
        is_public=False,
    )
    await session.commit()
    await invalidate_profile(user.username)
