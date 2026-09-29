//! BountyFlow bounty escrow contract (interface version 2).
//!
//! One escrow per `bounty_id` (32 bytes). A requester locks
//! `reward_per_position * positions` of a Stellar Asset Contract (SAC)
//! compatible token (native XLM via its SAC), assigns contributors to
//! positions and releases one reward per paid position. A single-position
//! escrow can instead be split into milestones that are released one by one.
//!
//! An assigned contributor can record a submission on-chain (`submit_work`).
//! If the requester neither pays, asks for changes, rejects nor disputes
//! within the escrow's review window, the contributor can `claim` the payment.
//!
//! Cancellation needs either the consent of every assigned-but-unpaid
//! contributor or the deadline to have passed, and never while a review is
//! pending. Disputes are resolved by a per-escrow M-of-N arbiter set whose
//! power is limited to paying an assigned contributor (all or part of their
//! position) or removing that contributor's assignment; the rest of a split
//! position only ever returns to the requester.
//!
//! A deployment admin (set by the constructor) can replace the contract code
//! with `upgrade`. The admin has no power over escrowed funds.

#![no_std]

mod errors;
mod events;
mod storage;
mod types;

#[cfg(test)]
mod test;

use soroban_sdk::{
    contract, contractimpl, panic_with_error, token, Address, BytesN, ContractExecutable, Env, Vec,
};

pub use crate::errors::Error;
pub use crate::events::*;
pub use crate::storage::DataKey;
pub use crate::types::{
    ArbiterVote, AssignmentState, Escrow, EscrowStatus, EscrowTerms, Milestone, PayoutItem, Review,
    ReviewState, Vote,
};

/// Maximum number of positions per bounty.
pub const MAX_POSITIONS: u32 = 100;
/// Maximum number of arbiters per escrow.
pub const MAX_ARBITERS: u32 = 10;
/// Maximum number of milestones per escrow.
pub const MAX_MILESTONES: u32 = 20;
/// Maximum number of legs in one `batch_release`.
pub const MAX_BATCH: u32 = 10;
/// One day in seconds.
pub const DAY: u64 = 86_400;
/// Review window used by `create_escrow` (v1 arguments).
pub const DEFAULT_REVIEW_WINDOW: u64 = 7 * DAY;
/// Longest review window an escrow can use.
pub const MAX_REVIEW_WINDOW: u64 = 30 * DAY;
/// Lowest minimum review window a deployment can choose (for Testnet smoke
/// tests). Mainnet deployments use `DAY`.
pub const ABSOLUTE_MIN_REVIEW_WINDOW: u64 = 60;
/// Contract interface version.
pub const CONTRACT_VERSION: u32 = 2;

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

/// Funds held by the escrow that are neither paid out nor refunded.
fn unspent(escrow: &Escrow) -> Result<i128, Error> {
    sub_i128(
        sub_i128(escrow.funded_amount, escrow.paid_out_amount)?,
        escrow.refunded_amount,
    )
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
    if amount > 0 {
        token::Client::new(env, token).transfer(&env.current_contract_address(), to, &amount);
    }
}

/// Reviews are answered and claims made while the escrow still holds the
/// work's reward: `Funded`, or `CancelRequested` (a requester who wants to
/// cancel must still answer submitted work).
fn review_open(escrow: &Escrow) -> bool {
    escrow.status == EscrowStatus::Funded || escrow.status == EscrowStatus::CancelRequested
}

/// When the claim opens for `review`. A dispute resolved after the
/// submission gives the requester a full window again from the resolution.
fn claimable_at(escrow: &Escrow, review: &Review) -> u64 {
    if escrow.clock_reset_at == 0 {
        return review.claimable_at;
    }
    let after_reset = escrow.clock_reset_at.saturating_add(escrow.review_window);
    if after_reset > review.claimable_at {
        after_reset
    } else {
        review.claimable_at
    }
}

/// Outstanding value of the (single) position of a milestone escrow, or one
/// reward for a per-position escrow.
fn position_value(escrow: &Escrow) -> Result<i128, Error> {
    if escrow.milestones.is_empty() {
        return Ok(escrow.reward_per_position);
    }
    let mut total: i128 = 0;
    for milestone in escrow.milestones.iter() {
        if !milestone.paid {
            total = add_i128(total, milestone.amount)?;
        }
    }
    Ok(total)
}

fn all_milestones_paid(escrow: &Escrow) -> bool {
    escrow.milestones.iter().all(|m| m.paid)
}

/// Marks every open milestone paid (the position is being settled whole).
fn settle_milestones(escrow: &mut Escrow) {
    for i in 0..escrow.milestones.len() {
        let mut milestone = escrow.milestones.get_unchecked(i);
        if !milestone.paid {
            milestone.paid = true;
            escrow.milestones.set(i, milestone);
        }
    }
}

/// Removes `contributor`'s review record. With `only_milestone`, only a
/// review of that milestone is removed.
fn clear_review(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
    only_milestone: Option<u32>,
) -> Result<(), Error> {
    if let Some(review) = storage::load_review(env, bounty_id, contributor) {
        if only_milestone.is_some_and(|m| m != review.milestone) {
            return Ok(());
        }
        if review.state == ReviewState::Pending {
            escrow.pending_reviews = sub_u32(escrow.pending_reviews, 1)?;
        }
        storage::remove_review(env, bounty_id, contributor);
    }
    Ok(())
}

/// Ensures `contributor` holds a position: an assigned contributor already
/// does, an unassigned one takes a free position (the direct-pay path of
/// v1 `release`). A paid contributor can never be paid again.
fn take_position(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
) -> Result<(), Error> {
    match storage::load_assignment(env, bounty_id, contributor) {
        Some(AssignmentState::Paid) => Err(Error::AlreadyPaid),
        Some(AssignmentState::Assigned) => Ok(()),
        None => {
            if positions_taken(escrow)? >= escrow.positions {
                return Err(Error::PositionsExhausted);
            }
            escrow.assigned_unpaid = add_u32(escrow.assigned_unpaid, 1)?;
            storage::write_assignment(env, bounty_id, contributor, AssignmentState::Assigned);
            Ok(())
        }
    }
}

/// Books `amount` as paid out of the escrow.
fn book_amount(escrow: &mut Escrow, amount: i128) -> Result<(), Error> {
    let available = sub_i128(escrow.funded_amount, escrow.paid_out_amount)?;
    if available < amount {
        return Err(Error::InsufficientFunds);
    }
    escrow.paid_out_amount = add_i128(escrow.paid_out_amount, amount)?;
    Ok(())
}

/// Moves the escrow to `Completed` once every position is paid, booking any
/// unspent remainder (left by a split dispute resolution) as refunded to the
/// requester. Returns that remainder, which the caller transfers.
fn finish_if_complete(escrow: &mut Escrow) -> Result<i128, Error> {
    if escrow.payouts_made != escrow.positions {
        return Ok(0);
    }
    escrow.status = EscrowStatus::Completed;
    let leftover = unspent(escrow)?;
    escrow.refunded_amount = add_i128(escrow.refunded_amount, leftover)?;
    Ok(leftover)
}

/// Marks `contributor`'s position paid. Returns the remainder to refund.
fn complete_position(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
) -> Result<i128, Error> {
    escrow.assigned_unpaid = sub_u32(escrow.assigned_unpaid, 1)?;
    escrow.payouts_made = add_u32(escrow.payouts_made, 1)?;
    storage::write_assignment(env, bounty_id, contributor, AssignmentState::Paid);
    finish_if_complete(escrow)
}

/// Books a whole position for `contributor` (every open milestone on a
/// milestone escrow). Only state is written here; the caller persists the
/// escrow and only then transfers (checks-effects-interactions).
/// Returns `(amount, remainder_to_refund)`.
fn book_position(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
) -> Result<(i128, i128), Error> {
    take_position(env, bounty_id, escrow, contributor)?;
    let amount = position_value(escrow)?;
    book_amount(escrow, amount)?;
    settle_milestones(escrow);
    clear_review(env, bounty_id, escrow, contributor, None)?;
    let leftover = complete_position(env, bounty_id, escrow, contributor)?;
    Ok((amount, leftover))
}

/// Books one milestone for `contributor`; the last one completes the position.
/// Returns `(amount, remainder_to_refund)`.
fn book_milestone(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &mut Escrow,
    contributor: &Address,
    index: u32,
) -> Result<(i128, i128), Error> {
    if index >= escrow.milestones.len() {
        return Err(Error::InvalidMilestone);
    }
    let mut milestone = escrow.milestones.get_unchecked(index);
    if milestone.paid {
        return Err(Error::MilestoneAlreadyPaid);
    }
    take_position(env, bounty_id, escrow, contributor)?;
    book_amount(escrow, milestone.amount)?;
    milestone.paid = true;
    let amount = milestone.amount;
    escrow.milestones.set(index, milestone);
    clear_review(env, bounty_id, escrow, contributor, Some(index))?;
    let leftover = if all_milestones_paid(escrow) {
        clear_review(env, bounty_id, escrow, contributor, None)?;
        complete_position(env, bounty_id, escrow, contributor)?
    } else {
        0
    };
    Ok((amount, leftover))
}

fn validate_arbiters(arbiters: &Vec<Address>, requester: &Address) -> Result<(), Error> {
    let count = arbiters.len();
    if count == 0 || count > MAX_ARBITERS {
        return Err(Error::InvalidArbiter);
    }
    for i in 0..count {
        let arbiter = arbiters.get_unchecked(i);
        if arbiter == *requester {
            return Err(Error::InvalidArbiter);
        }
        for j in (i + 1)..count {
            if arbiters.get_unchecked(j) == arbiter {
                return Err(Error::InvalidArbiter);
            }
        }
    }
    Ok(())
}

fn build_milestones(env: &Env, terms: &EscrowTerms) -> Result<Vec<Milestone>, Error> {
    let mut milestones = Vec::new(env);
    if terms.milestones.is_empty() {
        return Ok(milestones);
    }
    if terms.positions != 1 || terms.milestones.len() > MAX_MILESTONES {
        return Err(Error::InvalidMilestones);
    }
    let mut total: i128 = 0;
    for amount in terms.milestones.iter() {
        if amount <= 0 {
            return Err(Error::InvalidMilestones);
        }
        total = add_i128(total, amount)?;
        milestones.push_back(Milestone {
            amount,
            paid: false,
        });
    }
    if total != terms.reward_per_position {
        return Err(Error::InvalidMilestones);
    }
    Ok(milestones)
}

/// Current-round approvals of exactly this resolution.
fn count_approvals(
    env: &Env,
    bounty_id: &BytesN<32>,
    escrow: &Escrow,
    contributor: &Address,
    contributor_amount: i128,
) -> u32 {
    let mut approvals = 0;
    for arbiter in escrow.arbiters.iter() {
        if let Some(vote) = storage::read_vote(env, bounty_id, &arbiter) {
            if vote.round == escrow.dispute_round
                && vote.contributor == *contributor
                && vote.contributor_amount == contributor_amount
            {
                approvals += 1;
            }
        }
    }
    approvals
}

fn publish_release(
    env: &Env,
    bounty_id: &BytesN<32>,
    contributor: &Address,
    milestone: Option<u32>,
    amount: i128,
) {
    match milestone {
        Some(index) => MilestoneReleased {
            bounty_id: bounty_id.clone(),
            contributor: contributor.clone(),
            milestone: index,
            amount,
        }
        .publish(env),
        None => RewardReleased {
            bounty_id: bounty_id.clone(),
            contributor: contributor.clone(),
            amount,
        }
        .publish(env),
    }
}

fn publish_refund(env: &Env, bounty_id: &BytesN<32>, amount: i128) {
    if amount > 0 {
        EscrowRefunded {
            bounty_id: bounty_id.clone(),
            amount,
        }
        .publish(env);
    }
}

/// Shared by `create_escrow` and `create_escrow_v2`.
/// `requester.require_auth()` must be called by the caller beforehand.
fn create(
    env: &Env,
    requester: Address,
    bounty_id: BytesN<32>,
    token: Address,
    terms: EscrowTerms,
    publish_terms: bool,
) -> Result<Escrow, Error> {
    if storage::has_escrow(env, &bounty_id) {
        return Err(Error::AlreadyExists);
    }
    if terms.reward_per_position <= 0 {
        return Err(Error::InvalidAmount);
    }
    if terms.positions == 0 || terms.positions > MAX_POSITIONS {
        return Err(Error::InvalidPositions);
    }
    validate_arbiters(&terms.arbiters, &requester)?;
    if terms.threshold == 0 || terms.threshold > terms.arbiters.len() {
        return Err(Error::InvalidThreshold);
    }
    let now = env.ledger().timestamp();
    if terms.deadline <= now {
        return Err(Error::DeadlineInPast);
    }
    if terms.review_window < storage::read_min_review_window(env)
        || terms.review_window > MAX_REVIEW_WINDOW
    {
        return Err(Error::InvalidReviewWindow);
    }
    let milestones = build_milestones(env, &terms)?;
    let required_amount = terms
        .reward_per_position
        .checked_mul(terms.positions as i128)
        .ok_or(Error::Overflow)?;
    if terms.initial_deposit < 0 {
        return Err(Error::InvalidAmount);
    }
    if terms.initial_deposit > required_amount {
        return Err(Error::Overfunded);
    }

    let status = if terms.initial_deposit == required_amount {
        EscrowStatus::Funded
    } else {
        EscrowStatus::AwaitingFunding
    };
    let arbiter = terms.arbiters.get_unchecked(0);

    let escrow = Escrow {
        requester: requester.clone(),
        token: token.clone(),
        arbiter: arbiter.clone(),
        reward_per_position: terms.reward_per_position,
        positions: terms.positions,
        required_amount,
        funded_amount: terms.initial_deposit,
        paid_out_amount: 0,
        refunded_amount: 0,
        payouts_made: 0,
        assigned_unpaid: 0,
        deadline: terms.deadline,
        status,
        pre_dispute_status: status,
        created_at: now,
        arbiters: terms.arbiters.clone(),
        threshold: terms.threshold,
        review_window: terms.review_window,
        pending_reviews: 0,
        dispute_round: 0,
        clock_reset_at: 0,
        milestones,
    };
    storage::write_escrow(env, &bounty_id, &escrow);
    storage::bump_instance(env);

    if terms.initial_deposit > 0 {
        token::Client::new(env, &token).transfer(
            &requester,
            env.current_contract_address(),
            &terms.initial_deposit,
        );
    }

    EscrowCreated {
        bounty_id: bounty_id.clone(),
        requester,
        token,
        required_amount,
        arbiter,
    }
    .publish(env);
    if publish_terms {
        EscrowConfigured {
            bounty_id: bounty_id.clone(),
            arbiters: terms.arbiters,
            threshold: terms.threshold,
            review_window: terms.review_window,
            milestones: escrow.milestones.len(),
        }
        .publish(env);
    }
    if terms.initial_deposit > 0 {
        EscrowFunded {
            bounty_id,
            amount: terms.initial_deposit,
            funded_total: terms.initial_deposit,
        }
        .publish(env);
    }
    Ok(escrow)
}

/// Shared by `request_changes` and `reject_submission`.
fn answer_review(
    env: &Env,
    requester: &Address,
    bounty_id: &BytesN<32>,
    contributor: &Address,
    answer: ReviewState,
) -> Result<Escrow, Error> {
    requester.require_auth();
    let mut escrow = load_as_requester(env, requester, bounty_id)?;
    if !review_open(&escrow) {
        return Err(Error::InvalidState);
    }
    let mut review = storage::load_review(env, bounty_id, contributor)
        .filter(|r| r.state == ReviewState::Pending)
        .ok_or(Error::NoPendingReview)?;
    // Once the window has passed the contributor has earned the claim; only
    // paying (or a dispute) remains open to the requester.
    if env.ledger().timestamp() >= claimable_at(&escrow, &review) {
        return Err(Error::ReviewWindowElapsed);
    }
    review.state = answer;
    escrow.pending_reviews = sub_u32(escrow.pending_reviews, 1)?;
    storage::write_review(env, bounty_id, contributor, &review);
    storage::write_escrow(env, bounty_id, &escrow);
    storage::bump_instance(env);
    Ok(escrow)
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

#[contractimpl]
impl BountyEscrow {
    /// Deployment: sets the admin (who can upgrade the code) and the shortest
    /// review window escrows on this deployment may use.
    pub fn __constructor(env: Env, admin: Address, min_review_window: u64) {
        if !(ABSOLUTE_MIN_REVIEW_WINDOW..=DEFAULT_REVIEW_WINDOW).contains(&min_review_window) {
            panic_with_error!(&env, Error::InvalidReviewWindow);
        }
        storage::write_admin(&env, &admin);
        storage::write_min_review_window(&env, min_review_window);
        storage::bump_instance(&env);
    }

    /// Create a new escrow for `bounty_id`, optionally depositing funds.
    /// v1 arguments: one arbiter, the default review window, no milestones.
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
        let terms = EscrowTerms {
            reward_per_position,
            positions,
            deadline,
            initial_deposit,
            arbiters: Vec::from_array(&env, [arbiter]),
            threshold: 1,
            review_window: DEFAULT_REVIEW_WINDOW,
            milestones: Vec::new(&env),
        };
        create(&env, requester, bounty_id, token, terms, false)
    }

    /// Create a new escrow with an arbiter set, a review window and optional
    /// milestones, optionally depositing funds.
    pub fn create_escrow_v2(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        token: Address,
        terms: EscrowTerms,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        create(&env, requester, bounty_id, token, terms, true)
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
    /// pre-assigned, or paid directly if a free position remains. On a
    /// milestone escrow this pays every milestone that is still open.
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
        let (amount, leftover) = book_position(&env, &bounty_id, &mut escrow, &contributor)?;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        transfer_out(&env, &escrow.token, &contributor, amount);
        transfer_out(&env, &escrow.token, &requester, leftover);

        publish_release(&env, &bounty_id, &contributor, None, amount);
        publish_refund(&env, &bounty_id, leftover);
        Ok(escrow)
    }

    /// Pay one milestone to `contributor`, who holds (or takes) the escrow's
    /// single position. The last milestone completes the position.
    pub fn release_milestone(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
        milestone: u32,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        let (amount, leftover) =
            book_milestone(&env, &bounty_id, &mut escrow, &contributor, milestone)?;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        transfer_out(&env, &escrow.token, &contributor, amount);
        transfer_out(&env, &escrow.token, &requester, leftover);

        publish_release(&env, &bounty_id, &contributor, Some(milestone), amount);
        publish_refund(&env, &bounty_id, leftover);
        Ok(escrow)
    }

    /// Pay several positions and/or milestones in one call. Every leg is
    /// checked and booked before any funds move; if one leg fails the whole
    /// call fails and nothing is paid.
    pub fn batch_release(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        items: Vec<PayoutItem>,
    ) -> Result<Escrow, Error> {
        requester.require_auth();
        let mut escrow = load_as_requester(&env, &requester, &bounty_id)?;
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        if items.is_empty() || items.len() > MAX_BATCH {
            return Err(Error::InvalidBatch);
        }
        let mut amounts: Vec<i128> = Vec::new(&env);
        let mut total: i128 = 0;
        let mut leftover: i128 = 0;
        for item in items.iter() {
            let (amount, rest) = match &item {
                PayoutItem::Position(contributor) => {
                    book_position(&env, &bounty_id, &mut escrow, contributor)?
                }
                PayoutItem::Milestone(contributor, index) => {
                    book_milestone(&env, &bounty_id, &mut escrow, contributor, *index)?
                }
            };
            amounts.push_back(amount);
            total = add_i128(total, amount)?;
            leftover = add_i128(leftover, rest)?;
        }
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        for (i, item) in items.iter().enumerate() {
            let amount = amounts.get_unchecked(i as u32);
            match &item {
                PayoutItem::Position(contributor) => {
                    transfer_out(&env, &escrow.token, contributor, amount);
                    publish_release(&env, &bounty_id, contributor, None, amount);
                }
                PayoutItem::Milestone(contributor, index) => {
                    transfer_out(&env, &escrow.token, contributor, amount);
                    publish_release(&env, &bounty_id, contributor, Some(*index), amount);
                }
            }
        }
        transfer_out(&env, &escrow.token, &requester, leftover);

        BatchReleased {
            bounty_id: bounty_id.clone(),
            legs: items.len(),
            total,
        }
        .publish(&env);
        publish_refund(&env, &bounty_id, leftover);
        Ok(escrow)
    }

    /// An assigned contributor records a submission (of `milestone`, 0 on an
    /// escrow without milestones) and starts the review window.
    pub fn submit_work(
        env: Env,
        contributor: Address,
        bounty_id: BytesN<32>,
        milestone: u32,
    ) -> Result<Escrow, Error> {
        contributor.require_auth();
        let mut escrow = storage::load_escrow(&env, &bounty_id)?;
        if !review_open(&escrow) {
            return Err(Error::InvalidState);
        }
        let now = env.ledger().timestamp();
        // Same reasoning as SEC-06: after the deadline the requester may refund.
        if now >= escrow.deadline {
            return Err(Error::DeadlineInPast);
        }
        if storage::load_assignment(&env, &bounty_id, &contributor)
            != Some(AssignmentState::Assigned)
        {
            return Err(Error::NotAssigned);
        }
        if escrow.milestones.is_empty() {
            if milestone != 0 {
                return Err(Error::InvalidMilestone);
            }
        } else {
            if milestone >= escrow.milestones.len() {
                return Err(Error::InvalidMilestone);
            }
            if escrow.milestones.get_unchecked(milestone).paid {
                return Err(Error::MilestoneAlreadyPaid);
            }
        }
        match storage::load_review(&env, &bounty_id, &contributor).map(|r| r.state) {
            Some(ReviewState::Pending) => return Err(Error::ReviewPending),
            Some(ReviewState::Rejected) => return Err(Error::WorkRejected),
            Some(ReviewState::ChangesRequested) | None => {}
        }
        let claimable_at = now
            .checked_add(escrow.review_window)
            .ok_or(Error::Overflow)?;
        let review = Review {
            milestone,
            submitted_at: now,
            claimable_at,
            state: ReviewState::Pending,
        };
        escrow.pending_reviews = add_u32(escrow.pending_reviews, 1)?;
        storage::write_review(&env, &bounty_id, &contributor, &review);
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        WorkSubmitted {
            bounty_id,
            contributor,
            milestone,
            claimable_at,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Requester asks for changes to a pending submission before its window
    /// passes. The clock stops; the next `submit_work` starts a full window.
    pub fn request_changes(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
    ) -> Result<Escrow, Error> {
        let escrow = answer_review(
            &env,
            &requester,
            &bounty_id,
            &contributor,
            ReviewState::ChangesRequested,
        )?;
        ChangesRequested {
            bounty_id,
            contributor,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// Requester rejects a pending submission before its window passes. The
    /// contributor stays assigned and can only move on through a dispute (or
    /// by consenting to a cancellation).
    pub fn reject_submission(
        env: Env,
        requester: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
    ) -> Result<Escrow, Error> {
        let escrow = answer_review(
            &env,
            &requester,
            &bounty_id,
            &contributor,
            ReviewState::Rejected,
        )?;
        SubmissionRejected {
            bounty_id,
            contributor,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// After an unanswered review window, the contributor pays themselves
    /// the submitted work: their position, or the submitted milestone.
    pub fn claim(env: Env, contributor: Address, bounty_id: BytesN<32>) -> Result<Escrow, Error> {
        contributor.require_auth();
        let mut escrow = storage::load_escrow(&env, &bounty_id)?;
        if !review_open(&escrow) {
            return Err(Error::InvalidState);
        }
        let review = storage::load_review(&env, &bounty_id, &contributor)
            .filter(|r| r.state == ReviewState::Pending)
            .ok_or(Error::NoPendingReview)?;
        if env.ledger().timestamp() < claimable_at(&escrow, &review) {
            return Err(Error::ReviewWindowOpen);
        }
        let milestone = if escrow.milestones.is_empty() {
            None
        } else {
            Some(review.milestone)
        };
        let (amount, leftover) = match milestone {
            None => book_position(&env, &bounty_id, &mut escrow, &contributor)?,
            Some(index) => book_milestone(&env, &bounty_id, &mut escrow, &contributor, index)?,
        };
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);
        transfer_out(&env, &escrow.token, &contributor, amount);
        transfer_out(&env, &escrow.token, &escrow.requester, leftover);

        publish_release(&env, &bounty_id, &contributor, milestone, amount);
        PaymentClaimed {
            bounty_id: bounty_id.clone(),
            contributor,
            milestone: review.milestone,
            amount,
        }
        .publish(&env);
        publish_refund(&env, &bounty_id, leftover);
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
    /// position (and any recorded submission).
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
        clear_review(&env, &bounty_id, &mut escrow, &contributor, None)?;
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
        // Submitted work must be answered (or claimed) first, even after the deadline.
        if escrow.pending_reviews != 0 {
            return Err(Error::ReviewPending);
        }
        let amount = unspent(&escrow)?;
        escrow.refunded_amount = add_i128(escrow.refunded_amount, amount)?;
        escrow.status = EscrowStatus::Cancelled;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        transfer_out(&env, &escrow.token, &requester, amount);

        EscrowRefunded { bounty_id, amount }.publish(&env);
        Ok(escrow)
    }

    /// Requester or an assigned contributor escalates to the arbiters. Claims
    /// wait while the escrow is disputed.
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
        // Security (SEC-05): `Disputed` can only be left through a resolution
        // for an `Assigned` contributor. Without one the escrow (and every
        // remaining position's funds) would be locked forever.
        if escrow.assigned_unpaid == 0 {
            return Err(Error::NotAssigned);
        }
        escrow.pre_dispute_status = escrow.status;
        escrow.status = EscrowStatus::Disputed;
        escrow.dispute_round = add_u32(escrow.dispute_round, 1)?;
        storage::write_escrow(&env, &bounty_id, &escrow);
        storage::bump_instance(&env);

        DisputeRaised {
            bounty_id,
            raised_by: caller,
        }
        .publish(&env);
        Ok(escrow)
    }

    /// v1 resolution: one arbiter approves paying the contributor's whole
    /// position (`pay_contributor`) or removing their assignment. With a
    /// threshold of 1 it executes at once, as in v1.
    pub fn resolve_dispute(
        env: Env,
        arbiter: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
        pay_contributor: bool,
    ) -> Result<Escrow, Error> {
        arbiter.require_auth();
        let escrow = storage::load_escrow(&env, &bounty_id)?;
        let contributor_amount = if pay_contributor {
            position_value(&escrow)?
        } else {
            0
        };
        Self::vote(&env, arbiter, bounty_id, contributor, contributor_amount)
    }

    /// An arbiter approves a resolution for one assigned contributor: pay
    /// them `contributor_amount` (up to their whole position) and return the
    /// rest of the position to the requester, or remove their assignment
    /// (`contributor_amount == 0`). It executes once `threshold` arbiters
    /// approved exactly the same resolution in the current dispute round.
    pub fn vote_resolution(
        env: Env,
        arbiter: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
        contributor_amount: i128,
    ) -> Result<Escrow, Error> {
        arbiter.require_auth();
        Self::vote(&env, arbiter, bounty_id, contributor, contributor_amount)
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

    /// Read a contributor's recorded submission (`None` = nothing recorded).
    pub fn review(env: Env, bounty_id: BytesN<32>, contributor: Address) -> Option<Review> {
        storage::read_review(&env, &bounty_id, &contributor)
    }

    /// Approvals recorded in the current dispute round.
    pub fn resolution_votes(env: Env, bounty_id: BytesN<32>) -> Result<Vec<ArbiterVote>, Error> {
        let escrow = storage::read_escrow(&env, &bounty_id)?;
        let mut votes = Vec::new(&env);
        for arbiter in escrow.arbiters.iter() {
            if let Some(vote) = storage::read_vote(&env, &bounty_id, &arbiter) {
                if vote.round == escrow.dispute_round {
                    votes.push_back(ArbiterVote {
                        arbiter,
                        contributor: vote.contributor,
                        contributor_amount: vote.contributor_amount,
                    });
                }
            }
        }
        Ok(votes)
    }

    /// The deployment admin.
    pub fn admin(env: Env) -> Address {
        storage::read_admin(&env)
    }

    /// Shortest review window escrows on this deployment may use (seconds).
    pub fn min_review_window(env: Env) -> u64 {
        storage::read_min_review_window(&env)
    }

    /// Hand the admin role to `new_admin`. Both the current and the new admin sign.
    pub fn set_admin(env: Env, new_admin: Address) {
        let previous = storage::read_admin(&env);
        previous.require_auth();
        new_admin.require_auth();
        storage::write_admin(&env, &new_admin);
        storage::bump_instance(&env);
        AdminChanged {
            previous,
            admin: new_admin,
        }
        .publish(&env);
    }

    /// Replace the contract code with an uploaded wasm. Escrow storage is kept.
    pub fn upgrade(env: Env, new_wasm_hash: BytesN<32>) {
        storage::read_admin(&env).require_auth();
        storage::bump_instance(&env);
        ContractUpgraded {
            new_wasm_hash: new_wasm_hash.clone(),
        }
        .publish(&env);
        env.deployer()
            .update_current_contract(ContractExecutable::Wasm(new_wasm_hash));
    }

    /// Contract interface version.
    pub fn version(_env: Env) -> u32 {
        CONTRACT_VERSION
    }
}

impl BountyEscrow {
    /// Records `arbiter`'s approval and executes the resolution once it has
    /// `threshold` approvals. `arbiter.require_auth()` is called by the caller.
    fn vote(
        env: &Env,
        arbiter: Address,
        bounty_id: BytesN<32>,
        contributor: Address,
        contributor_amount: i128,
    ) -> Result<Escrow, Error> {
        let mut escrow = storage::load_escrow(env, &bounty_id)?;
        if !escrow.arbiters.contains(&arbiter) {
            return Err(Error::Unauthorized);
        }
        if escrow.status != EscrowStatus::Disputed {
            return Err(Error::InvalidState);
        }
        if storage::load_assignment(env, &bounty_id, &contributor)
            != Some(AssignmentState::Assigned)
        {
            return Err(Error::NotAssigned);
        }
        if contributor_amount < 0 || contributor_amount > position_value(&escrow)? {
            return Err(Error::InvalidResolution);
        }
        storage::write_vote(
            env,
            &bounty_id,
            &arbiter,
            &Vote {
                round: escrow.dispute_round,
                contributor: contributor.clone(),
                contributor_amount,
            },
        );
        let approvals = count_approvals(env, &bounty_id, &escrow, &contributor, contributor_amount);
        if approvals < escrow.threshold {
            storage::bump_instance(env);
            ResolutionVoted {
                bounty_id,
                arbiter,
                contributor,
                contributor_amount,
                approvals,
                threshold: escrow.threshold,
            }
            .publish(env);
            return Ok(escrow);
        }

        // Threshold reached: execute. Votes are spent.
        for member in escrow.arbiters.iter() {
            storage::remove_vote(env, &bounty_id, &member);
        }
        clear_review(env, &bounty_id, &mut escrow, &contributor, None)?;
        let paid = contributor_amount > 0;
        let leftover = if paid {
            book_amount(&mut escrow, contributor_amount)?;
            settle_milestones(&mut escrow);
            complete_position(env, &bounty_id, &mut escrow, &contributor)?
        } else {
            storage::remove_assignment(env, &bounty_id, &contributor);
            escrow.assigned_unpaid = sub_u32(escrow.assigned_unpaid, 1)?;
            0
        };
        // Pending reviews of other contributors get a full window from now.
        escrow.clock_reset_at = env.ledger().timestamp();
        if escrow.status != EscrowStatus::Completed {
            escrow.status = escrow.pre_dispute_status;
        }
        storage::write_escrow(env, &bounty_id, &escrow);
        storage::bump_instance(env);
        transfer_out(env, &escrow.token, &contributor, contributor_amount);
        transfer_out(env, &escrow.token, &escrow.requester, leftover);

        if paid {
            publish_release(env, &bounty_id, &contributor, None, contributor_amount);
        }
        DisputeResolved {
            bounty_id: bounty_id.clone(),
            contributor,
            paid,
        }
        .publish(env);
        publish_refund(env, &bounty_id, leftover);
        Ok(escrow)
    }
}
