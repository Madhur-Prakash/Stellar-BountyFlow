//! Storage layout and TTL management.
//!
//! Instance storage (shares the contract instance's TTL):
//! - `DataKey::Attester` -> `Address`
//! - `DataKey::Total`    -> `u64` (ids run from 1 to `Total`)
//!
//! Persistent storage:
//! - `DataKey::Attestation(id)`                              -> `Attestation`
//! - `DataKey::Completion(bounty_id, contributor, payout_tx)` -> `u64` id
//! - `DataKey::ContributorCount(contributor)`                 -> `u32`
//! - `DataKey::ContributorEntry(contributor, index)`          -> `u64` id
//!
//! TTL policy: attestations are long-lived records, so every write extends the
//! entries it touches to `BUMP_TO` ledgers (~120 days at ~5s/ledger) whenever
//! the remaining TTL has fallen below `BUMP_THRESHOLD` (~30 days). Read-only
//! views do not bump TTL (they are simulated, not submitted). Anyone may call
//! `extend_ttl(id)` (or `stellar contract extend`) to keep an idle record live;
//! an archived entry is restorable, never deleted.

use soroban_sdk::{contracttype, Address, BytesN, Env};

use crate::errors::Error;
use crate::types::Attestation;

/// Approximate ledgers per day (5 second close time).
pub const DAY_IN_LEDGERS: u32 = 17_280;
/// Extend TTL when remaining TTL is below this many ledgers (~30 days).
pub const BUMP_THRESHOLD: u32 = 30 * DAY_IN_LEDGERS;
/// Target TTL after an extension (~120 days).
pub const BUMP_TO: u32 = 120 * DAY_IN_LEDGERS;

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DataKey {
    Attester,
    Total,
    Attestation(u64),
    Completion(BytesN<32>, Address, BytesN<32>),
    ContributorCount(Address),
    ContributorEntry(Address, u32),
}

pub fn bump_instance(env: &Env) {
    env.storage().instance().extend_ttl(BUMP_THRESHOLD, BUMP_TO);
}

fn bump(env: &Env, key: &DataKey) {
    env.storage()
        .persistent()
        .extend_ttl(key, BUMP_THRESHOLD, BUMP_TO);
}

pub fn attester(env: &Env) -> Address {
    env.storage()
        .instance()
        .get(&DataKey::Attester)
        .expect("constructed with an attester")
}

pub fn set_attester(env: &Env, attester: &Address) {
    env.storage().instance().set(&DataKey::Attester, attester);
}

pub fn total(env: &Env) -> u64 {
    env.storage().instance().get(&DataKey::Total).unwrap_or(0)
}

pub fn set_total(env: &Env, total: u64) {
    env.storage().instance().set(&DataKey::Total, &total);
}

pub fn completion_key(
    bounty_id: &BytesN<32>,
    contributor: &Address,
    payout_tx: &BytesN<32>,
) -> DataKey {
    DataKey::Completion(bounty_id.clone(), contributor.clone(), payout_tx.clone())
}

/// The id recorded for a completion, if any (no TTL change).
pub fn find_completion(env: &Env, key: &DataKey) -> Option<u64> {
    env.storage().persistent().get(key)
}

/// Read an attestation without touching its TTL (view calls).
pub fn read_attestation(env: &Env, id: u64) -> Result<Attestation, Error> {
    env.storage()
        .persistent()
        .get(&DataKey::Attestation(id))
        .ok_or(Error::NotFound)
}

/// Read an attestation as part of a state-changing call, extending its TTL.
pub fn load_attestation(env: &Env, id: u64) -> Result<Attestation, Error> {
    let attestation = read_attestation(env, id)?;
    bump(env, &DataKey::Attestation(id));
    Ok(attestation)
}

pub fn write_attestation(env: &Env, attestation: &Attestation) {
    let key = DataKey::Attestation(attestation.id);
    env.storage().persistent().set(&key, attestation);
    bump(env, &key);
}

/// Records the natural key and appends the id to the contributor's list.
pub fn index_attestation(env: &Env, attestation: &Attestation) {
    let completion = completion_key(
        &attestation.bounty_id,
        &attestation.contributor,
        &attestation.payout_tx,
    );
    env.storage().persistent().set(&completion, &attestation.id);
    bump(env, &completion);

    let entry = DataKey::ContributorEntry(
        attestation.contributor.clone(),
        attestation.contributor_index,
    );
    env.storage().persistent().set(&entry, &attestation.id);
    bump(env, &entry);

    let count = DataKey::ContributorCount(attestation.contributor.clone());
    env.storage()
        .persistent()
        .set(&count, &(attestation.contributor_index + 1));
    bump(env, &count);
}

pub fn contributor_count(env: &Env, contributor: &Address) -> u32 {
    env.storage()
        .persistent()
        .get(&DataKey::ContributorCount(contributor.clone()))
        .unwrap_or(0)
}

pub fn contributor_entry(env: &Env, contributor: &Address, index: u32) -> Option<u64> {
    env.storage()
        .persistent()
        .get(&DataKey::ContributorEntry(contributor.clone(), index))
}

/// Extends every persistent entry that belongs to one attestation.
pub fn extend_attestation(env: &Env, attestation: &Attestation) {
    bump(env, &DataKey::Attestation(attestation.id));
    bump(
        env,
        &completion_key(
            &attestation.bounty_id,
            &attestation.contributor,
            &attestation.payout_tx,
        ),
    );
    bump(
        env,
        &DataKey::ContributorEntry(
            attestation.contributor.clone(),
            attestation.contributor_index,
        ),
    );
    bump(
        env,
        &DataKey::ContributorCount(attestation.contributor.clone()),
    );
}
