use soroban_sdk::contracterror;

/// Contract error codes. The numeric values are part of the public interface
/// (off-chain clients map them) and must never be renumbered.
#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    NotFound = 1,
    AlreadyExists = 2,
    InvalidAmount = 3,
    InvalidPositions = 4,
    InvalidState = 5,
    Unauthorized = 6,
    AlreadyPaid = 7,
    AlreadyAssigned = 8,
    NotAssigned = 9,
    PositionsExhausted = 10,
    InsufficientFunds = 11,
    Overfunded = 12,
    DeadlineInPast = 13,
    AssignmentsOutstanding = 14,
    Overflow = 15,
    InvalidArbiter = 16,
}
