use soroban_sdk::contracterror;

/// Contract error codes. The numeric values are part of the public interface
/// (off-chain clients map them) and must never be renumbered.
#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    NotFound = 1,
    AlreadyAttested = 2,
    Unauthorized = 3,
    InvalidAmount = 4,
    InvalidTimestamp = 5,
    AlreadyRevoked = 6,
    InvalidReason = 7,
    InvalidContributor = 8,
    Overflow = 9,
}
