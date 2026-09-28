"""Explicit network configuration for every blockchain operation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class NetworkConfig:
    mode: str  # testnet | mainnet
    network: str  # label stored on rows: testnet | mainnet
    passphrase: str
    horizon_url: str
    soroban_rpc_url: str
    explorer_base_url: str
    contract_id: str | None
    native_asset_contract_id: str | None
    arbiter_address: str | None
    base_fee: int
    tx_timeout_seconds: int
    confirmation_timeout: int
    rpc_timeout_seconds: float

    @property
    def is_configured(self) -> bool:
        return bool(self.contract_id and self.native_asset_contract_id)

    def tx_url(self, tx_hash: str | None) -> str | None:
        if not tx_hash:
            return None
        return f"{self.explorer_base_url.rstrip('/')}/tx/{tx_hash}"

    def account_url(self, address: str) -> str:
        return f"{self.explorer_base_url.rstrip('/')}/account/{address}"

    def contract_url(self) -> str | None:
        if not self.contract_id:
            return None
        return f"{self.explorer_base_url.rstrip('/')}/contract/{self.contract_id}"


def build_network_config(settings: Settings) -> NetworkConfig:
    return NetworkConfig(
        mode=settings.blockchain_mode,
        network=settings.network_label,
        passphrase=settings.stellar_network_passphrase,
        horizon_url=settings.stellar_horizon_url,
        soroban_rpc_url=settings.stellar_soroban_rpc_url,
        explorer_base_url=settings.stellar_explorer_base_url,
        contract_id=settings.soroban_contract_id,
        native_asset_contract_id=settings.stellar_native_asset_contract_id,
        arbiter_address=settings.stellar_arbiter_address,
        base_fee=settings.stellar_base_fee,
        tx_timeout_seconds=settings.stellar_tx_timeout_seconds,
        confirmation_timeout=settings.blockchain_confirmation_timeout,
        rpc_timeout_seconds=settings.blockchain_rpc_timeout_seconds,
    )


@lru_cache
def get_network() -> NetworkConfig:
    return build_network_config(get_settings())
