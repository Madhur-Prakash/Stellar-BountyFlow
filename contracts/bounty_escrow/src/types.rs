use soroban_sdk::{contracttype, Address};

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

/// On-chain escrow record for one bounty.
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
}
