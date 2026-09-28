"""Regression tests for confirmed backend bugs, plus broad coverage of flows that had none (every chain action,
multi-position bounties, the lifecycle and sweep jobs, seeding). Reuses the API fixtures (Testnet configuration with
the `FakeStellarChain` test double as the chain adapter)."""

from tests.integration.api.conftest import app, chain, client_factory  # noqa: F401
