//! Contract events. Every event carries a fixed name topic (the snake_case
//! struct name, added by `#[contractevent]`). Attestation events add the
//! contributor as the second topic (and `bounty_id` as the third on
//! `completion_attested`) so indexers can filter per contributor and bounty.
//! Remaining fields form the event data as a map keyed by field name.

use soroban_sdk::{contractevent, Address, BytesN, String};

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompletionAttested {
    #[topic]
    pub contributor: Address,
    #[topic]
    pub bounty_id: BytesN<32>,
    pub id: u64,
    pub escrow_contract: Address,
    pub payout_tx: BytesN<32>,
    pub token: Address,
    pub amount: i128,
    pub completed_at: u64,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttestationRevoked {
    #[topic]
    pub contributor: Address,
    pub id: u64,
    pub reason: String,
}

#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttesterRotated {
    pub previous: Address,
    pub attester: Address,
}
