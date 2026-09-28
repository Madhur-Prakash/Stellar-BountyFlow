//! Persistent storage layout and TTL management.
//!
//! Keys:
//! - `DataKey::Escrow(bounty_id)`                 -> `Escrow`
//! - `DataKey::Assignment(bounty_id, contributor)` -> `AssignmentState`
//!
//! TTL policy: every write, and every read performed as part of a
//! state-changing call, extends the entry's TTL to `BUMP_TO` ledgers
//! (~30 days at ~5s/ledger) whenever the remaining TTL has fallen below
//! `BUMP_THRESHOLD` (~15 days). Read-only view calls do not bump TTL
//! (they are simulated, not submitted). Anyone may additionally extend
//! TTLs off-chain via `stellar contract extend` if an escrow is idle for a
//! long time. The contract instance TTL is bumped on each state-changing
//! call as well.

use soroban_sdk::{contracttype, Address, BytesN, Env};

use crate::errors::Error;
use crate::types::{AssignmentState, Escrow};

/// Approximate ledgers per day (5 second close time).
pub const DAY_IN_LEDGERS: u32 = 17_280;
/// Extend TTL when remaining TTL is below this many ledgers (~15 days).
pub const BUMP_THRESHOLD: u32 = 15 * DAY_IN_LEDGERS;
/// Target TTL after an extension (~30 days).
pub const BUMP_TO: u32 = 30 * DAY_IN_LEDGERS;

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DataKey {
    Escrow(BytesN<32>),
    Assignment(BytesN<32>, Address),
}

pub fn bump_instance(env: &Env) {
    env.storage().instance().extend_ttl(BUMP_THRESHOLD, BUMP_TO);
}

pub fn has_escrow(env: &Env, bounty_id: &BytesN<32>) -> bool {
    env.storage()
        .persistent()
        .has(&DataKey::Escrow(bounty_id.clone()))
}

/// Read an escrow without touching its TTL (view calls).
pub fn read_escrow(env: &Env, bounty_id: &BytesN<32>) -> Result<Escrow, Error> {
    env.storage()
        .persistent()
        .get(&DataKey::Escrow(bounty_id.clone()))
        .ok_or(Error::NotFound)
}

/// Read an escrow as part of a state-changing call, extending its TTL.
pub fn load_escrow(env: &Env, bounty_id: &BytesN<32>) -> Result<Escrow, Error> {
    let key = DataKey::Escrow(bounty_id.clone());
    let escrow: Escrow = env
        .storage()
        .persistent()
        .get(&key)
        .ok_or(Error::NotFound)?;
    env.storage()
        .persistent()
        .extend_ttl(&key, BUMP_THRESHOLD, BUMP_TO);
    Ok(escrow)
}

pub fn write_escrow(env: &Env, bounty_id: &BytesN<32>, escrow: &Escrow) {
    let key = DataKey::Escrow(bounty_id.clone());
    env.storage().persistent().set(&key, escrow);
    env.storage()
        .persistent()
        .extend_ttl(&key, BUMP_THRESHOLD, BUMP_TO);
}

/// Read an assignment without touching its TTL (view calls).
pub fn read_assignment(
    env: &Env,
    bounty_id: &BytesN<32>,
    contributor: &Address,
) -> Option<AssignmentState> {
    env.storage()
        .persistent()
        .get(&DataKey::Assignment(bounty_id.clone(), contributor.clone()))
}

/// Read an assignment as part of a state-changing call, extending its TTL
/// if it exists.
pub fn load_assignment(
    env: &Env,
    bounty_id: &BytesN<32>,
    contributor: &Address,
) -> Option<AssignmentState> {
    let key = DataKey::Assignment(bounty_id.clone(), contributor.clone());
    let state: Option<AssignmentState> = env.storage().persistent().get(&key);
    if state.is_some() {
        env.storage()
            .persistent()
            .extend_ttl(&key, BUMP_THRESHOLD, BUMP_TO);
    }
    state
}

pub fn write_assignment(
    env: &Env,
    bounty_id: &BytesN<32>,
    contributor: &Address,
    state: AssignmentState,
) {
    let key = DataKey::Assignment(bounty_id.clone(), contributor.clone());
    env.storage().persistent().set(&key, &state);
    env.storage()
        .persistent()
        .extend_ttl(&key, BUMP_THRESHOLD, BUMP_TO);
}

pub fn remove_assignment(env: &Env, bounty_id: &BytesN<32>, contributor: &Address) {
    env.storage()
        .persistent()
        .remove(&DataKey::Assignment(bounty_id.clone(), contributor.clone()));
}
