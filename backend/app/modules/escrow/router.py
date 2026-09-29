"""Escrow v2 endpoints: escrow settings, bounty milestones and the dispute arbiter panel.

The v2 chain actions themselves go through ``POST /bounties/{id}/chain/prepare`` (payments router) with the
actions MILESTONE_PAYOUT, BATCH_PAYOUT, SUBMIT_WORK, REQUEST_CHANGES, REJECT_SUBMISSION, CLAIM and DISPUTE_VOTE.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.blockchain import soroban
from app.dependencies import CurrentUser, OptionalUser, SessionDep
from app.modules.escrow import arbitration
from app.modules.escrow import milestones as milestone_service
from app.modules.escrow.config import contract_version, escrow_settings
from app.modules.escrow.schemas import ArbitrationOut, EscrowConfigOut, MilestoneOut, MilestonesUpdate

router = APIRouter(tags=["escrow"])


@router.get("/escrow/config", response_model=EscrowConfigOut)
async def config() -> EscrowConfigOut:
    s = escrow_settings()
    return EscrowConfigOut(
        contract_id=s.contract_id,
        contract_version=await contract_version(),
        default_review_window_seconds=s.default_review_window,
        min_review_window_seconds=s.min_review_window,
        max_review_window_seconds=s.max_review_window,
        arbiter_addresses=list(s.arbiters),
        arbiter_threshold=s.threshold,
        max_batch=soroban.MAX_BATCH,
    )


@router.get("/bounties/{bounty_id}/milestones", response_model=list[MilestoneOut])
async def list_milestones(
    bounty_id: uuid.UUID, session: SessionDep, viewer: OptionalUser
) -> list[MilestoneOut]:
    return await milestone_service.get(session, bounty_id, viewer)


@router.put("/bounties/{bounty_id}/milestones", response_model=list[MilestoneOut])
async def replace_milestones(
    bounty_id: uuid.UUID, data: MilestonesUpdate, session: SessionDep, user: CurrentUser
) -> list[MilestoneOut]:
    return await milestone_service.update(session, user, bounty_id, data.milestones)


@router.get("/disputes/{dispute_id}/arbitration", response_model=ArbitrationOut)
async def dispute_arbitration(
    dispute_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ArbitrationOut:
    return await arbitration.arbitration(session, user, dispute_id)
