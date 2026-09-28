//! Contract events. Every event carries a fixed name topic (the snake_case
//! struct name, added by `#[contractevent]`) followed by `bounty_id` as the
//! second topic so indexers can filter per bounty. Remaining fields form the
//! event data as a map keyed by field name.

use soroban_sdk::{contractevent, Address, BytesN};

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
