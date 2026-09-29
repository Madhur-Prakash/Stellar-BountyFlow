//! Contract events. Every event carries a fixed name topic (the snake_case
//! struct name, added by `#[contractevent]`) followed by `bounty_id` as the
//! second topic so indexers can filter per bounty. Remaining fields form the
//! event data as a map keyed by field name. The two contract-level events
//! (`contract_upgraded`, `admin_changed`) carry only the name topic.

use soroban_sdk::{contractevent, Address, BytesN, Vec};

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EscrowCreated {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub requester: Address,
    pub token: Address,
    pub required_amount: i128,
    pub arbiter: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EscrowFunded {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub amount: i128,
    pub funded_total: i128,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContributorAssigned {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RewardReleased {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
    pub amount: i128,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelRequested {
    #[topic]
    pub bounty_id: BytesN<32>,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelConsented {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EscrowRefunded {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub amount: i128,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DisputeRaised {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub raised_by: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DisputeResolved {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
    pub paid: bool,
}

// --- v2 ---

/// Emitted by `create_escrow_v2` after `escrow_created`.
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EscrowConfigured {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub arbiters: Vec<Address>,
    pub threshold: u32,
    pub review_window: u64,
    pub milestones: u32,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkSubmitted {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
    pub milestone: u32,
    pub claimable_at: u64,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChangesRequested {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SubmissionRejected {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MilestoneReleased {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
    pub milestone: u32,
    pub amount: i128,
}

/// Emitted by `claim`, after the `reward_released` or `milestone_released`
/// event of the payment itself.
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PaymentClaimed {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub contributor: Address,
    pub milestone: u32,
    pub amount: i128,
}

/// Emitted by `batch_release` after one release event per leg.
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchReleased {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub legs: u32,
    pub total: i128,
}

/// An arbiter approved a resolution that has not reached the threshold yet.
/// The approval that reaches it emits `dispute_resolved` instead.
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolutionVoted {
    #[topic]
    pub bounty_id: BytesN<32>,
    pub arbiter: Address,
    pub contributor: Address,
    pub contributor_amount: i128,
    pub approvals: u32,
    pub threshold: u32,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractUpgraded {
    pub new_wasm_hash: BytesN<32>,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdminChanged {
    pub previous: Address,
    pub admin: Address,
}
