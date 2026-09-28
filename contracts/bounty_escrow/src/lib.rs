//! BountyFlow bounty escrow contract.
//!
//! One escrow per `bounty_id` (32 bytes). A requester locks
//! `reward_per_position * positions` of a Stellar Asset Contract (SAC)
//! compatible token (native XLM via its SAC), assigns contributors to
//! positions and releases one reward per paid position. Cancellation needs
//! either the consent of every assigned-but-unpaid contributor or the
//! deadline to have passed. Disputes are resolved by a per-escrow arbiter
//! whose power is limited to paying an assigned contributor or removing that
//! contributor's assignment. There is no admin and no upgrade path.

#![no_std]

mod errors;
mod events;
mod storage;
mod types;

#[cfg(test)]
mod test;

use soroban_sdk::{contract, contractimpl, token, Address, BytesN, Env};

pub use crate::errors::Error;
pub use crate::events::*;
pub use crate::storage::DataKey;
pub use crate::types::{AssignmentState, Escrow, EscrowStatus};

/// Maximum number of positions per bounty.
pub const MAX_POSITIONS: u32 = 100;
/// Contract interface version.
pub const CONTRACT_VERSION: u32 = 1;

#[contract]
pub struct BountyEscrow;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

fn add_i128(a: i128, b: i128) -> Result<i128, Error> {
    a.checked_add(b).ok_or(Error::Overflow)
}

fn sub_i128(a: i128, b: i128) -> Result<i128, Error> {
    a.checked_sub(b).ok_or(Error::Overflow)
}

fn add_u32(a: u32, b: u32) -> Result<u32, Error> {
    a.checked_add(b).ok_or(Error::Overflow)
}

fn sub_u32(a: u32, b: u32) -> Result<u32, Error> {
    a.checked_sub(b).ok_or(Error::Overflow)
}

/// Positions that are either paid or currently reserved by an assignment.
fn positions_taken(escrow: &Escrow) -> Result<u32, Error> {
    add_u32(escrow.payouts_made, escrow.assigned_unpaid)
}

/// Loads the escrow and verifies `requester` is its requester.
/// `requester.require_auth()` must be called by the caller beforehand.
fn load_as_requester(
    env: &Env,
    requester: &Address,
    bounty_id: &BytesN<32>,
) -> Result<Escrow, Error> {
    let escrow = storage::load_escrow(env, bounty_id)?;
    if escrow.requester != *requester {
        return Err(Error::Unauthorized);
    }
    Ok(escrow)
}

fn transfer_out(env: &Env, token: &Address, to: &Address, amount: i128) {
    token::Client::new(env, token).transfer(&env.current_contract_address(), to, &amount);
}

/// Books one reward for `contributor`: marks the assignment Paid and updates
/// counters (and the Completed status). The caller is responsible for the
/// position accounting of `assigned_unpaid`, for persisting the escrow and
/// only then for the token transfer (checks-effects-interactions: all state is
/// written before any external call).
fn book_payout(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
) -> Result<(), Error> {
    let available = sub_i128(escrow.funded_amount, escrow.paid_out_amount)?;
    if available < escrow.reward_per_position {
        return Err(Error::InsufficientFunds);
    }
    escrow.paid_out_amount = add_i128(escrow.paid_out_amount, escrow.reward_per_position)?;
    escrow.payouts_made = add_u32(escrow.payouts_made, 1)?;
    if escrow.payouts_made == escrow.positions {
        escrow.status = EscrowStatus::Completed;
    }
    storage::write_assignment(env, bounty_id, contributor, AssignmentState::Paid);
    Ok(())
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

#[contractimpl]
impl BountyEscrow {
    /// Create a new escrow for `bounty_id`, optionally depositing funds.
    #[allow(clippy::too_many_arguments)]
    pub fn create_escrow(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        token: Address,
        reward_per_position: i128,
        positions: u32,
        arbiter: Address,
        deadline: u64,
        initial_deposit: i128,
    ) -> Result<Escrow, Error> {
        requester.require_auth();

        if storage::has_escrow(&env, &bounty_id) {
            return Err(Error::AlreadyExists);
        }
        if reward_per_position <= 0 {
            return Err(Error::InvalidAmount);
        }
        if positions == 0 || positions > MAX_POSITIONS {
            return Err(Error::InvalidPositions);
        }
        if arbiter == requester {
            return Err(Error::InvalidArbiter);
        }
        let now = env.ledger().timestamp();
        if deadline <= now {
            return Err(Error::DeadlineInPast);
        }
        let required_amount = reward_per_position
            .checked_mul(positions as i128)
            .ok_or(Error::Overflow)?;
        if initial_deposit < 0 {
            return Err(Error::InvalidAmount);
        }
        if initial_deposit > required_amount {
            return Err(Error::Overfunded);
        }

        let status = if initial_deposit == required_amount {
            EscrowStatus::Funded
        } else {
            EscrowStatus::AwaitingFunding
        };

        let escrow = Escrow {
            requester: requester.clone(),
            token: token.clone(),
            arbiter: arbiter.clone(),
            reward_per_position,
            positions,
            required_amount,
            funded_amount: initial_deposit,
            paid_out_amount: 0,
            refunded_amount: 0,
            payouts_made: 0,
            assigned_unpaid: 0,
            deadline,
            status,
            pre_dispute_status: status,
            created_at: now,
        };
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        if initial_deposit > 0 {
            token::Client::new(&env, &token).transfer(
                &requester,
                env.current_contract_address(),
                &initial_deposit,
            );
        }

        EscrowCreated {
            bounty_id: bounty_id.clone(),
            requester,
            token,
            required_amount,
            arbiter,
        }
        .publish(&env);
        if initial_deposit > 0 {
            EscrowFunded {
                bounty_id,
                amount: initial_deposit,
                funded_total: initial_deposit,
            }
            .publish(&env);
        }

        Ok(escrow)
    }

    /// Add funds to an escrow that is still awaiting full funding.
    pub fn fund(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        amount: i128,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::AwaitingFunding {
            return Err(Error::InvalidState);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let new_total = add_i128(escrow.funded_amount, amount)?;
        if new_total > escrow.required_amount {
            return Err(Error::Overfunded);
        }
        escrow.funded_amount = new_total;
        if new_total == escrow.required_amount {
            escrow.status = EscrowStatus::Funded;
        }
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        token::Client::new(&env, &escrow.token).transfer(
            &requester,
            env.current_contract_address(),
            &amount,
        );

        EscrowFunded {
            bounty_id,
            amount,
            funded_total: new_total,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Reserve a position for `contributor`.
    pub fn assign(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        // Security (SEC-06): after the deadline the requester may refund despite
        // outstanding assignments, so a late assignment would protect nothing.
        if env.ledger().timestamp() >= escrow.deadline {
            return Err(Error::DeadlineInPast);
        }
        if contributor == escrow.requester {
            return Err(Error::Unauthorized);
        }
        if storage::load_assignment(&env, &bounty_id, &contributor).is_some() {
            return Err(Error::AlreadyAssigned);
        }
        if positions_taken(&escrow)? >= escrow.positions {
            return Err(Error::PositionsExhausted);
        }
        escrow.assigned_unpaid = add_u32(escrow.assigned_unpaid, 1)?;
        storage::write_assignment(&env, &bounty_id, &contributor, AssignmentState::Assigned);
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        ContributorAssigned {
            bounty_id,
            contributor,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Pay one position's reward to `contributor`. The contributor may be
    /// pre-assigned, or paid directly if a free position remains.
    pub fn release(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        match storage::load_assignment(&env, &bounty_id, &contributor) {
            Some(AssignmentState::Paid) => return Err(Error::AlreadyPaid),
            Some(AssignmentState::Assigned) => {
                escrow.assigned_unpaid = sub_u32(escrow.assigned_unpaid, 1)?;
            }
            None => {
                if positions_taken(&escrow)? >= escrow.positions {
                    return Err(Error::PositionsExhausted);
                }
            }
        }
        book_payout(&env, &bounty_id, &mut escrow, &contributor)?;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        transfer_out(
            &env,
            &escrow.token,
            &contributor,
            escrow.reward_per_position,
        );

        RewardReleased {
            bounty_id,
            contributor,
            amount: escrow.reward_per_position,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Requester asks to cancel. Assigned contributors must consent (or the
    /// deadline must pass) before the requester can refund.
    pub fn request_cancel(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::AwaitingFunding && escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        escrow.status = EscrowStatus::CancelRequested;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        CancelRequested { bounty_id }.publish(&env);
        Ok(escrow)
    }

    /// An assigned contributor consents to cancellation, giving up their
    /// position.
    pub fn consent_cancel(
        env: Env,
        contributor: Address,
        bounty_id: BytesN<32>,
    ) -> Result<Escrow, Error> {
        contributor.require_auth();
        let mut escrow = storage::load_escrow(&env, &bounty_id)?;
        if escrow.status != EscrowStatus::CancelRequested {
            return Err(Error::InvalidState);
        }
        if storage::load_assignment(&env, &bounty_id, &contributor)
            != Some(AssignmentState::Assigned)
        {
            return Err(Error::NotAssigned);
        }
        storage::remove_assignment(&env, &bounty_id, &contributor);
        escrow.assigned_unpaid = sub_u32(escrow.assigned_unpaid, 1)?;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        CancelConsented {
            bounty_id,
            contributor,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Return all unspent funds to the requester and close the escrow.
    pub fn refund(env: Env, requester: Address, bounty_id: BytesN<32>) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::AwaitingFunding
            && escrow.status != EscrowStatus::CancelRequested
        {
            return Err(Error::InvalidState);
        }
        if escrow.assigned_unpaid != 0 && env.ledger().timestamp() <= escrow.deadline {
            return Err(Error::AssignmentsOutstanding);
        }
        let amount = sub_i128(
            sub_i128(escrow.funded_amount, escrow.paid_out_amount)?,
            escrow.refunded_amount,
        )?;
        escrow.refunded_amount = add_i128(escrow.refunded_amount, amount)?;
        escrow.status = EscrowStatus::Cancelled;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        if amount > 0 {
            transfer_out(&env, &escrow.token, &requester, amount);
        }

        EscrowRefunded { bounty_id, amount }.publish(&env);
        Ok(escrow)
    }

    /// Requester or an assigned contributor escalates to the arbiter.
    pub fn raise_dispute(
        env: Env,
        caller: Address,
        bounty_id: BytesN<32>,
    ) -> Result<Escrow, Error> {
        caller.require_auth();
        let mut escrow = storage::load_escrow(&env, &bounty_id)?;
        let is_party = caller == escrow.requester
            || storage::load_assignment(&env, &bounty_id, &caller)
                == Some(AssignmentState::Assigned);
        if !is_party {
            return Err(Error::Unauthorized);
        }
        if escrow.status != EscrowStatus::Funded && escrow.status != EscrowStatus::CancelRequested {
            return Err(Error::InvalidState);
        }
        // Security (SEC-05): `Disputed` can only be left through
        // `resolve_dispute` for an `Assigned` contributor. Without one the
        // escrow (and every remaining position's funds) would be locked forever.
        if escrow.assigned_unpaid == 0 {
            return Err(Error::NotAssigned);
        }
        escrow.pre_dispute_status = escrow.status;
        escrow.status = EscrowStatus::Disputed;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        DisputeRaised {
            bounty_id,
            raised_by: caller,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Arbiter resolves a dispute for one assigned contributor: either pays
    /// them one reward, or removes their assignment. The arbiter can never
    /// send funds anywhere else.
    pub fn resolve_dispute(
        env: Env,
        arbiter: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
        pay_contributor: bool,
    ) -> Result<Escrow, Error> {
        arbiter.require_auth();
        let mut escrow = storage::load_escrow(&env, &bounty_id)?;
        if escrow.arbiter != arbiter {
            return Err(Error::Unauthorized);
        }
        if escrow.status != EscrowStatus::Disputed {
            return Err(Error::InvalidState);
        }
        if storage::load_assignment(&env, &bounty_id, &contributor)
            != Some(AssignmentState::Assigned)
        {
            return Err(Error::NotAssigned);
        }
        escrow.assigned_unpaid = sub_u32(escrow.assigned_unpaid, 1)?;
        if pay_contributor {
            book_payout(&env, &bounty_id, &mut escrow, &contributor)?;
        } else {
            storage::remove_assignment(&env, &bounty_id, &contributor);
        }
        escrow.status = if escrow.payouts_made == escrow.positions {
            EscrowStatus::Completed
        } else {
            escrow.pre_dispute_status
        };
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        if pay_contributor {
            transfer_out(
                &env,
                &escrow.token,
                &contributor,
                escrow.reward_per_position,
            );
        }

        if pay_contributor {
            RewardReleased {
                bounty_id: bounty_id.clone(),
                contributor: contributor.clone(),
                amount: escrow.reward_per_position,
            }
            .publish(&env);
        }
        DisputeResolved {
            bounty_id,
            contributor,
            paid: pay_contributor,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Read an escrow.
    pub fn get_escrow(env: Env, bounty_id: BytesN<32>) -> Result<Escrow, Error> {
        storage::read_escrow(&env, &bounty_id)
    }

    /// Read a contributor's assignment state for a bounty (`None` = not assigned).
    pub fn assignment(
        env: Env,
        bounty_id: BytesN<32>,
        contributor: Address,
    ) -> Option<AssignmentState> {
        storage::read_assignment(&env, &bounty_id, &contributor)
    }

    /// Contract interface version.
    pub fn version(_env: Env) -> u32 {
        CONTRACT_VERSION
    }
}
