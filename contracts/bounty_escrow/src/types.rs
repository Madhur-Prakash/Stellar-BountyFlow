use soroban_sdk::{contracttype, Address, Vec};

/// Lifecycle status of an escrow.
#[contracttype]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub enum EscrowStatus {
    AwaitingFunding = 0,
    Funded = 1,
    CancelRequested = 2,
    Disputed = 3,
    Completed = 4,
    Cancelled = 5,
}

/// Per-(bounty, contributor) assignment state. Absence of the storage key
/// means the contributor is not assigned.
#[contracttype]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub enum AssignmentState {
    Assigned = 0,
    Paid = 1,
}

/// State of a contributor's recorded submission (see `submit_work`).
#[contracttype]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub enum ReviewState {
    /// The review window is running; `claim` opens once it has passed.
    Pending = 0,
    /// The requester asked for changes in time. A new `submit_work` restarts the window.
    ChangesRequested = 1,
    /// The requester rejected the work in time. Only a dispute can move it on.
    Rejected = 2,
}

/// A contributor's recorded submission and its review clock.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Review {
    /// Milestone index under review (always 0 for an escrow without milestones).
    pub milestone: u32,
    pub submitted_at: u64,
    /// `submitted_at + review_window`. A dispute resolved later pushes the
    /// effective time to `clock_reset_at + review_window` (see `claimable_at`).
    pub claimable_at: u64,
    pub state: ReviewState,
}

/// One milestone of a single-position escrow. `paid` is also set when a
/// dispute resolution settles the position.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Milestone {
    pub amount: i128,
    pub paid: bool,
}

/// Terms of an escrow created with `create_escrow_v2`.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EscrowTerms {
    pub reward_per_position: i128,
    pub positions: u32,
    pub deadline: u64,
    pub initial_deposit: i128,
    /// M-of-N dispute arbiters (1 to `MAX_ARBITERS`, unique, never the requester).
    pub arbiters: Vec<Address>,
    /// Approvals needed to execute a dispute resolution (1 to `arbiters.len()`).
    pub threshold: u32,
    /// Seconds the requester has to answer a recorded submission.
    pub review_window: u64,
    /// Milestone amounts. Empty for a per-position escrow; otherwise
    /// `positions == 1` and the amounts add up to `reward_per_position`.
    pub milestones: Vec<i128>,
}

/// One leg of `batch_release`.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PayoutItem {
    /// Pay a whole position (every unpaid milestone on a milestone escrow).
    Position(Address),
    /// Pay one milestone to the contributor holding the position.
    Milestone(Address, u32),
}

/// An arbiter's approval of a dispute resolution, valid for one dispute round.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Vote {
    pub round: u32,
    pub contributor: Address,
    pub contributor_amount: i128,
}

/// A current-round vote, as returned by `resolution_votes`.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArbiterVote {
    pub arbiter: Address,
    pub contributor: Address,
    pub contributor_amount: i128,
}

/// On-chain escrow record for one bounty.
///
/// The first fifteen fields are the v1 layout. `arbiter` is the first entry of
/// `arbiters`, kept so v1 readers still see the escrow's arbiter.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Escrow {
    pub requester: Address,
    pub token: Address,
    pub arbiter: Address,
    pub reward_per_position: i128,
    pub positions: u32,
    pub required_amount: i128,
    pub funded_amount: i128,
    pub paid_out_amount: i128,
    pub refunded_amount: i128,
    pub payouts_made: u32,
    pub assigned_unpaid: u32,
    pub deadline: u64,
    pub status: EscrowStatus,
    pub pre_dispute_status: EscrowStatus,
    pub created_at: u64,
    // --- v2 ---
    pub arbiters: Vec<Address>,
    pub threshold: u32,
    pub review_window: u64,
    /// Reviews currently in `Pending` state. `refund` waits until it is 0.
    pub pending_reviews: u32,
    /// Incremented by every `raise_dispute`; votes of earlier rounds are void.
    pub dispute_round: u32,
    /// Ledger time the last dispute was resolved (0 = never). Every pending
    /// review gets a full window again from this moment.
    pub clock_reset_at: u64,
    pub milestones: Vec<Milestone>,
}
