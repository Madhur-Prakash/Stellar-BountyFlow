"""Escrow v2 settings as the services use them: the configured contract version, arbiter set and review window."""

from __future__ import annotations

from dataclasses import dataclass

from app.blockchain.config import get_network
from app.core.config import get_settings


@dataclass(frozen=True)
class EscrowSettings:
    contract_id: str | None
    contract_version: int
    arbiters: tuple[str, ...]
    threshold: int
    default_review_window: int
    min_review_window: int
    max_review_window: int

    @property
    def is_v2(self) -> bool:
        return self.contract_version >= 2

    @property
    def is_multisig(self) -> bool:
        return self.threshold > 1 or len(self.arbiters) > 1


def escrow_settings() -> EscrowSettings:
    """The arbiter set is STELLAR_ARBITER_ADDRESSES with STELLAR_ARBITER_THRESHOLD approvals; without a list it is
    the single STELLAR_ARBITER_ADDRESS with a threshold of 1 (the v1 behaviour)."""
    settings = get_settings()
    network = get_network()
    arbiters = tuple(settings.stellar_arbiter_addresses) or (
        (network.arbiter_address,) if network.arbiter_address else ()
    )
    threshold = settings.stellar_arbiter_threshold if settings.stellar_arbiter_addresses else 1
    return EscrowSettings(
        contract_id=network.contract_id,
        contract_version=settings.soroban_contract_version,
        arbiters=arbiters,
        threshold=min(threshold, max(len(arbiters), 1)),
        default_review_window=settings.escrow_default_review_window_seconds,
        min_review_window=settings.escrow_min_review_window_seconds,
        max_review_window=settings.escrow_max_review_window_seconds,
    )


_detected: dict[str, int] = {}


async def contract_version() -> int:
    """Interface version of the configured contract, read once from ``version()`` and cached per contract id.

    SOROBAN_CONTRACT_VERSION is the fallback when the contract cannot be read. Reading it guards against a
    SOROBAN_CONTRACT_ID that still names the v1 deployment (v2 calls would all fail there)."""
    from app.blockchain import soroban
    from app.blockchain.soroban import ContractError
    from app.blockchain.transactions import ChainUnavailable, get_adapter
    from app.core.logging import get_logger

    config = escrow_settings()
    if not config.contract_id:
        return config.contract_version
    if config.contract_id in _detected:
        return _detected[config.contract_id]
    try:
        version = int(await get_adapter().read(soroban.version()))
    except (ContractError, ChainUnavailable, TypeError, ValueError):
        return config.contract_version
    if version != config.contract_version:
        get_logger(__name__).warning(
            "contract_version_mismatch",
            contract_id=config.contract_id,
            configured=config.contract_version,
            found=version,
        )
    _detected[config.contract_id] = version
    return version
