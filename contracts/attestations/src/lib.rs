//! BountyFlow completion attestations contract.
//!
//! A public registry in which the platform's attester account records that a
//! contributor completed a bounty: who was paid, for which escrow `bounty_id`,
//! by which escrow contract and payout transaction, how much of which token,
//! and when. BountyFlow writes an attestation only after it has verified the
//! payout on-chain (the escrow reports the contributor as `Paid`).
//!
//! There is at most one attestation per (bounty, contributor, payout), so a
//! retried submission can never record a completion twice. Only the attester
//! can attest, revoke (with a reason) or hand the role to a new key.
//! Attestations are never deleted: a revoked one stays readable with its
//! reason. Nothing here holds or moves funds.

#![no_std]

mod errors;
mod events;
mod storage;
mod types;

#[cfg(test)]
mod test;

use soroban_sdk::{contract, contractimpl, Address, BytesN, Env, String, Vec};

pub use crate::errors::Error;
pub use crate::events::*;
pub use crate::storage::DataKey;
pub use crate::types::Attestation;

/// Contract interface version.
pub const CONTRACT_VERSION: u32 = 1;
/// Maximum number of attestations returned by one `list_by_contributor` call.
pub const MAX_PAGE: u32 = 50;
/// Maximum revocation reason length in bytes.
pub const MAX_REASON_LEN: u32 = 200;

#[contract]
pub struct CompletionAttestations;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Verifies `caller` is the current attester.
/// `caller.require_auth()` must be called by the caller beforehand.
fn require_attester(env: &Env, caller: &Address) -> Result<(), Error> {
    if storage::attester(env) != *caller {
        return Err(Error::Unauthorized);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

#[contractimpl]
impl CompletionAttestations {
    /// Deploys the registry with its attester account.
    pub fn __constructor(env: Env, attester: Address) {
        storage::set_attester(&env, &attester);
        storage::set_total(&env, 0);
        storage::bump_instance(&env);
    }

    /// Record that `contributor` was paid `amount` of `token` for `bounty_id`
    /// by the payout transaction `payout_tx` of `escrow_contract`.
    #[allow(clippy::too_many_arguments)]
    pub fn attest(
        env: Env,
        attester: Address,
        contributor: Address,
        bounty_id: BytesN<32>,
        escrow_contract: Address,
        payout_tx: BytesN<32>,
        token: Address,
        amount: i128,
        completed_at: u64,
    ) -> Result<Attestation, Error> {
        attester.require_auth();
        require_attester(&env, &attester)?;

        if contributor == attester {
            return Err(Error::InvalidContributor);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let now = env.ledger().timestamp();
        if completed_at == 0 || completed_at > now {
            return Err(Error::InvalidTimestamp);
        }
        let completion = storage::completion_key(&bounty_id, &contributor, &payout_tx);
        if storage::find_completion(&env, &completion).is_some() {
            return Err(Error::AlreadyAttested);
        }

        let id = storage::total(&env).checked_add(1).ok_or(Error::Overflow)?;
        let contributor_index = storage::contributor_count(&env, &contributor);
        contributor_index.checked_add(1).ok_or(Error::Overflow)?;

        let attestation = Attestation {
            id,
            attester,
            contributor: contributor.clone(),
            bounty_id: bounty_id.clone(),
            escrow_contract: escrow_contract.clone(),
            payout_tx: payout_tx.clone(),
            token: token.clone(),
            amount,
            completed_at,
            attested_at: now,
            contributor_index,
            revoked: false,
            revoked_at: 0,
            revocation_reason: String::from_str(&env, ""),
        };
        storage::write_attestation(&env, &attestation);
        storage::index_attestation(&env, &attestation);
        storage::set_total(&env, id);
        storage::bump_instance(&env);

        CompletionAttested {
            contributor,
            bounty_id,
            id,
            escrow_contract,
            payout_tx,
            token,
            amount,
            completed_at,
        }
        .publish(&env);
        Ok(attestation)
    }

    /// Withdraw an attestation. It stays readable, with the reason.
    pub fn revoke(
        env: Env,
        attester: Address,
        id: u64,
        reason: String,
    ) -> Result<Attestation, Error> {
        attester.require_auth();
        require_attester(&env, &attester)?;
        if reason.is_empty() || reason.len() > MAX_REASON_LEN {
            return Err(Error::InvalidReason);
        }
        let mut attestation = storage::load_attestation(&env, id)?;
        if attestation.revoked {
            return Err(Error::AlreadyRevoked);
        }
        attestation.revoked = true;
        attestation.revoked_at = env.ledger().timestamp();
        attestation.revocation_reason = reason.clone();
        storage::write_attestation(&env, &attestation);
        storage::bump_instance(&env);

        AttestationRevoked {
            contributor: attestation.contributor.clone(),
            id,
            reason,
        }
        .publish(&env);
        Ok(attestation)
    }

    /// Hand the attester role to `new_attester` (key rotation). Existing
    /// attestations keep the attester that recorded them.
    pub fn set_attester(env: Env, attester: Address, new_attester: Address) -> Result<(), Error> {
        attester.require_auth();
        require_attester(&env, &attester)?;
        storage::set_attester(&env, &new_attester);
        storage::bump_instance(&env);

        AttesterRotated {
            previous: attester,
            attester: new_attester,
        }
        .publish(&env);
        Ok(())
    }

    /// Extend the TTL of every entry that belongs to attestation `id`. Anyone
    /// may call it; it changes no data.
    pub fn extend_ttl(env: Env, id: u64) -> Result<(), Error> {
        let attestation = storage::read_attestation(&env, id)?;
        storage::extend_attestation(&env, &attestation);
        storage::bump_instance(&env);
        Ok(())
    }

    /// Read an attestation by id.
    pub fn get(env: Env, id: u64) -> Result<Attestation, Error> {
        storage::read_attestation(&env, id)
    }

    /// The attestation recorded for (bounty, contributor, payout), if any.
    pub fn find(
        env: Env,
        bounty_id: BytesN<32>,
        contributor: Address,
        payout_tx: BytesN<32>,
    ) -> Option<Attestation> {
        let key = storage::completion_key(&bounty_id, &contributor, &payout_tx);
        let id = storage::find_completion(&env, &key)?;
        storage::read_attestation(&env, id).ok()
    }

    /// A contributor's attestations, oldest first: at most `MAX_PAGE` entries
    /// starting at position `start`.
    pub fn list_by_contributor(
        env: Env,
        contributor: Address,
        start: u32,
        limit: u32,
    ) -> Vec<Attestation> {
        let mut page = Vec::new(&env);
        let count = storage::contributor_count(&env, &contributor);
        let end = start.saturating_add(limit.min(MAX_PAGE)).min(count);
        let mut index = start;
        while index < end {
            if let Some(id) = storage::contributor_entry(&env, &contributor, index) {
                if let Ok(attestation) = storage::read_attestation(&env, id) {
                    page.push_back(attestation);
                }
            }
            index += 1;
        }
        page
    }

    /// Number of attestations recorded for a contributor (revoked included).
    pub fn count_by_contributor(env: Env, contributor: Address) -> u32 {
        storage::contributor_count(&env, &contributor)
    }

    /// Number of attestations recorded (the highest id).
    pub fn total(env: Env) -> u64 {
        storage::total(&env)
    }

    /// The current attester account.
    pub fn attester(env: Env) -> Address {
        storage::attester(&env)
    }

    /// Contract interface version.
    pub fn version(_env: Env) -> u32 {
        CONTRACT_VERSION
    }
}
