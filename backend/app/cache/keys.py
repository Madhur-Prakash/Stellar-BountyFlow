"""Central cache-key strategy and TTLs.

All keys are namespaced ``bountyflow:v1:``. Marketplace list results embed a *generation* number; bumping the
generation invalidates every cached list query in O(1) without scanning keys.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

PREFIX = "bountyflow:v1"

TTL_MARKETPLACE = 45
TTL_BOUNTY_DETAIL = 45
TTL_FEATURED = 60
TTL_PROFILE = 120
TTL_PUBLIC_STATS = 60

GEN_BOUNTIES = f"{PREFIX}:gen:bounties"


def _digest(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def marketplace(generation: int, params: dict[str, Any]) -> str:
    return f"{PREFIX}:bounties:list:g{generation}:{_digest(params)}"


def featured(generation: int) -> str:
    return f"{PREFIX}:bounties:featured:g{generation}"


def bounty_detail(bounty_id: str) -> str:
    return f"{PREFIX}:bounty:{bounty_id}"


def bounty_slug(slug: str) -> str:
    return f"{PREFIX}:bounty-slug:{slug}"


def profile(username: str) -> str:
    return f"{PREFIX}:profile:{username.lower()}"


def user_stats(username: str) -> str:
    return f"{PREFIX}:profile-stats:{username.lower()}"


def public_stats() -> str:
    return f"{PREFIX}:stats:public"


def rate_limit(scope: str, identity: str, window: int) -> str:
    return f"{PREFIX}:rl:{scope}:{identity}:{window}"


def wallet_challenge(user_id: str, address: str) -> str:
    return f"{PREFIX}:wallet-challenge:{user_id}:{address}"


def tx_lock(transaction_id: str) -> str:
    return f"{PREFIX}:lock:tx:{transaction_id}"


def idempotency(scope: str, key: str) -> str:
    return f"{PREFIX}:idem:{scope}:{key}"


def worker_heartbeat(worker: str) -> str:
    return f"{PREFIX}:worker:heartbeat:{worker}"


def job_lock(job: str) -> str:
    """Distributed lock so only one worker instance runs a periodic job at a time."""
    return f"{PREFIX}:lock:job:{job}"


def bounty_views(bounty_id: str, viewer: str) -> str:
    return f"{PREFIX}:views:{bounty_id}:{viewer}"
