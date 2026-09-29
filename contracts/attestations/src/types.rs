use soroban_sdk::{contracttype, Address, BytesN, String};

/// One recorded completion: `contributor` was paid `amount` of `token` for
/// `bounty_id` by the escrow payout `payout_tx`.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Attestation {
    /// Sequential id, starting at 1.
    pub id: u64,
    /// The attester account that recorded it.
    pub attester: Address,
    pub contributor: Address,
    /// The escrow's `BytesN<32>` bounty key.
    pub bounty_id: BytesN<32>,
    pub escrow_contract: Address,
    /// Hash of the verified payout transaction.
    pub payout_tx: BytesN<32>,
    pub token: Address,
    /// Amount in the token's smallest unit (stroops for XLM).
    pub amount: i128,
    /// Close time of the payout's ledger (unix seconds).
    pub completed_at: u64,
    /// Ledger time when the attestation was recorded.
    pub attested_at: u64,
    /// Position in the contributor's list (0-based).
    pub contributor_index: u32,
    /// Set by `revoke`. A revoked attestation stays readable.
    pub revoked: bool,
    /// Ledger time of the revocation (0 while the attestation stands).
    pub revoked_at: u64,
    /// Why it was revoked (empty while the attestation stands).
    pub revocation_reason: String,
}
