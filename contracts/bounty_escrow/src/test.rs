#![cfg(test)]
extern crate std;

use crate::{
    AdminChanged, ArbiterVote, AssignmentState, BatchReleased, BountyEscrow, BountyEscrowArgs,
    BountyEscrowClient, CancelConsented, CancelRequested, ChangesRequested, ContractUpgraded,
    ContributorAssigned, DisputeRaised, DisputeResolved, Error, Escrow, EscrowConfigured,
    EscrowCreated, EscrowFunded, EscrowRefunded, EscrowStatus, EscrowTerms, Milestone,
    MilestoneReleased, PaymentClaimed, PayoutItem, ResolutionVoted, Review, ReviewState,
    RewardReleased, SubmissionRejected, WorkSubmitted, DAY, DEFAULT_REVIEW_WINDOW, MAX_BATCH,
    MAX_REVIEW_WINDOW,
};
use soroban_sdk::{
    testutils::{
        Address as _, AuthorizedFunction, AuthorizedInvocation, Events as _, Ledger as _, MockAuth,
        MockAuthInvoke,
    },
    token::{StellarAssetClient, TokenClient},
    vec, Address, BytesN, Env, Event, IntoVal, Symbol, Val, Vec,
};

const REWARD: i128 = 1_000;
const START_TS: u64 = 1_000_000;
/// Two weeks: long enough for a full default review window before the deadline.
const DEADLINE: u64 = START_TS + 14 * DAY;
const MINT: i128 = 1_000_000;
/// Minimum review window of the test deployment (a Testnet-style short floor).
const MIN_WINDOW: u64 = 3_600;
/// Review window of the v2 escrows in these tests.
const WINDOW: u64 = 2 * DAY;
/// Wasm used to prove `upgrade` swaps the code (soroban-sdk's `add(u64, u64)` fixture).
const UPGRADE_WASM: &[u8] = include_bytes!("../test_fixtures/add_u64.wasm");

struct Setup<'a> {
    env: Env,
    contract_id: Address,
    client: BountyEscrowClient<'a>,
    token_id: Address,
    token: TokenClient<'a>,
    admin: Address,
    requester: Address,
    arbiter: Address,
    arbiter2: Address,
    arbiter3: Address,
    alice: Address,
    bob: Address,
    carol: Address,
}

impl<'a> Setup<'a> {
    fn new() -> Self {
        let env = Env::default();
        env.mock_all_auths();
        env.ledger().set_timestamp(START_TS);

        let admin = Address::generate(&env);
        let contract_id = env.register(
            BountyEscrow,
            BountyEscrowArgs::__constructor(&admin, &MIN_WINDOW),
        );
        let client = BountyEscrowClient::new(&env, &contract_id);

        let token_admin = Address::generate(&env);
        let sac = env.register_stellar_asset_contract_v2(token_admin);
        let token_id = sac.address();
        let token = TokenClient::new(&env, &token_id);

        let requester = Address::generate(&env);
        let arbiter = Address::generate(&env);
        let arbiter2 = Address::generate(&env);
        let arbiter3 = Address::generate(&env);
        let alice = Address::generate(&env);
        let bob = Address::generate(&env);
        let carol = Address::generate(&env);

        StellarAssetClient::new(&env, &token_id).mint(&requester, &MINT);

        Setup {
            env,
            contract_id,
            client,
            token_id,
            token,
            admin,
            requester,
            arbiter,
            arbiter2,
            arbiter3,
            alice,
            bob,
            carol,
        }
    }

    fn id(&self, n: u8) -> BytesN<32> {
        BytesN::from_array(&self.env, &[n; 32])
    }

    /// Create an escrow with `positions` and the given initial deposit.
    fn create(&self, n: u8, positions: u32, deposit: i128) -> Escrow {
        self.client.create_escrow(
            &self.requester,
            &self.id(n),
            &self.token_id,
            &REWARD,
            &positions,
            &self.arbiter,
            &DEADLINE,
            &deposit,
        )
    }

    /// Create a fully funded escrow.
    fn create_funded(&self, n: u8, positions: u32) -> Escrow {
        self.create(n, positions, REWARD * positions as i128)
    }

    fn contract_balance(&self) -> i128 {
        self.token.balance(&self.contract_id)
    }

    /// Events emitted by the escrow contract in the last invocation.
    fn own_events(&self) -> std::vec::Vec<soroban_sdk::xdr::ContractEvent> {
        self.env
            .events()
            .all()
            .filter_by_contract(&self.contract_id)
            .events()
            .to_vec()
    }

    fn xdr<E: Event>(&self, event: E) -> soroban_sdk::xdr::ContractEvent {
        event.to_xdr(&self.env, &self.contract_id)
    }

    /// v2 terms: fully funded, one arbiter, `WINDOW`, no milestones.
    fn terms(&self, positions: u32) -> EscrowTerms {
        EscrowTerms {
            reward_per_position: REWARD,
            positions,
            deadline: DEADLINE,
            initial_deposit: REWARD * positions as i128,
            arbiters: vec![&self.env, self.arbiter.clone()],
            threshold: 1,
            review_window: WINDOW,
            milestones: Vec::new(&self.env),
        }
    }

    fn create_v2(&self, n: u8, terms: &EscrowTerms) -> Escrow {
        self.client
            .create_escrow_v2(&self.requester, &self.id(n), &self.token_id, terms)
    }

    /// A funded single-position escrow split into milestones summing to REWARD.
    fn create_milestones(&self, n: u8, amounts: &[i128]) -> Escrow {
        let mut terms = self.terms(1);
        terms.milestones = Vec::from_slice(&self.env, amounts);
        self.create_v2(n, &terms)
    }

    /// A funded escrow with the three test arbiters and the given threshold.
    fn create_multisig(&self, n: u8, positions: u32, threshold: u32) -> Escrow {
        let mut terms = self.terms(positions);
        terms.arbiters = vec![
            &self.env,
            self.arbiter.clone(),
            self.arbiter2.clone(),
            self.arbiter3.clone(),
        ];
        terms.threshold = threshold;
        self.create_v2(n, &terms)
    }

    fn now(&self) -> u64 {
        self.env.ledger().timestamp()
    }

    fn set_time(&self, ts: u64) {
        self.env.ledger().set_timestamp(ts);
    }

    fn review(&self, n: u8, who: &Address) -> Option<Review> {
        self.client.review(&self.id(n), who)
    }
}

fn err<T: core::fmt::Debug>(
    r: Result<Result<T, soroban_sdk::ConversionError>, Result<Error, soroban_sdk::InvokeError>>,
) -> Error {
    match r {
        Err(Ok(e)) => e,
        other => panic!("expected contract error, got {:?}", other),
    }
}

// ---------------------------------------------------------------------------
// create_escrow
// ---------------------------------------------------------------------------

#[test]
fn version_is_two() {
    let s = Setup::new();
    assert_eq!(s.client.version(), 2);
}

#[test]
fn create_without_deposit() {
    let s = Setup::new();
    let e = s.create(1, 3, 0);
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::AwaitingFunding);
    assert_eq!(e.required_amount, 3 * REWARD);
    assert_eq!(e.funded_amount, 0);
    assert_eq!(e.positions, 3);
    assert_eq!(e.created_at, START_TS);
    assert_eq!(e.deadline, DEADLINE);
    assert_eq!(e.requester, s.requester);
    assert_eq!(e.arbiter, s.arbiter);
    assert_eq!(e.token, s.token_id);
    assert_eq!(s.client.get_escrow(&s.id(1)), e);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(s.token.balance(&s.requester), MINT);

    // Only EscrowCreated, no funding event.
    let expected = EscrowCreated {
        bounty_id: s.id(1),
        requester: s.requester.clone(),
        token: s.token_id.clone(),
        required_amount: 3 * REWARD,
        arbiter: s.arbiter.clone(),
    };
    assert_eq!(ev, std::vec![expected.to_xdr(&s.env, &s.contract_id)]);
}

#[test]
fn create_with_partial_and_full_deposit() {
    let s = Setup::new();
    let e = s.create(1, 3, 1_500);
    let events = s.own_events();
    assert_eq!(e.status, EscrowStatus::AwaitingFunding);
    assert_eq!(e.funded_amount, 1_500);
    assert_eq!(s.contract_balance(), 1_500);
    assert_eq!(s.token.balance(&s.requester), MINT - 1_500);

    assert_eq!(events.len(), 2);
    assert_eq!(
        events[1],
        EscrowFunded {
            bounty_id: s.id(1),
            amount: 1_500,
            funded_total: 1_500
        }
        .to_xdr(&s.env, &s.contract_id)
    );

    let e2 = s.create_funded(2, 2);
    assert_eq!(e2.status, EscrowStatus::Funded);
    assert_eq!(e2.funded_amount, 2 * REWARD);
    assert_eq!(s.contract_balance(), 1_500 + 2 * REWARD);
}

#[test]
fn create_invalid_params() {
    let s = Setup::new();
    let id = s.id(1);
    let c = &s.client;
    let (r, t, a) = (&s.requester, &s.token_id, &s.arbiter);

    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &0, &1, a, &DEADLINE, &0)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &-5, &1, a, &DEADLINE, &0)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &0, a, &DEADLINE, &0)),
        Error::InvalidPositions
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &101, a, &DEADLINE, &0)),
        Error::InvalidPositions
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, r, &DEADLINE, &0)),
        Error::InvalidArbiter
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, a, &START_TS, &0)),
        Error::DeadlineInPast
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, a, &(START_TS - 1), &0)),
        Error::DeadlineInPast
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &i128::MAX, &2, a, &DEADLINE, &0)),
        Error::Overflow
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, a, &DEADLINE, &-1)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, a, &DEADLINE, &(REWARD + 1))),
        Error::Overfunded
    );
    // 100 positions is the maximum allowed.
    assert!(c
        .try_create_escrow(r, &id, t, &REWARD, &100, a, &DEADLINE, &0)
        .is_ok());
    // Duplicate id.
    assert_eq!(
        err(c.try_create_escrow(r, &id, t, &REWARD, &1, a, &DEADLINE, &0)),
        Error::AlreadyExists
    );
    assert_eq!(s.contract_balance(), 0);
}

#[test]
fn get_escrow_not_found() {
    let s = Setup::new();
    assert_eq!(err(s.client.try_get_escrow(&s.id(9))), Error::NotFound);
    assert_eq!(
        err(s.client.try_fund(&s.requester, &s.id(9), &1)),
        Error::NotFound
    );
    assert_eq!(s.client.assignment(&s.id(9), &s.alice), None);
}

// ---------------------------------------------------------------------------
// fund
// ---------------------------------------------------------------------------

#[test]
fn fund_partial_then_full_and_overfund() {
    let s = Setup::new();
    s.create(1, 3, 0);

    let e = s.client.fund(&s.requester, &s.id(1), &1_000);
    assert_eq!(e.funded_amount, 1_000);
    assert_eq!(e.status, EscrowStatus::AwaitingFunding);
    assert_eq!(
        s.own_events(),
        std::vec![EscrowFunded {
            bounty_id: s.id(1),
            amount: 1_000,
            funded_total: 1_000
        }
        .to_xdr(&s.env, &s.contract_id)]
    );

    assert_eq!(
        err(s.client.try_fund(&s.requester, &s.id(1), &2_001)),
        Error::Overfunded
    );
    assert_eq!(
        err(s.client.try_fund(&s.requester, &s.id(1), &0)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(s.client.try_fund(&s.requester, &s.id(1), &-1)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(s.client.try_fund(&s.alice, &s.id(1), &1)),
        Error::Unauthorized
    );

    let e = s.client.fund(&s.requester, &s.id(1), &2_000);
    assert_eq!(e.funded_amount, 3_000);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(s.contract_balance(), 3_000);
    assert_eq!(s.token.balance(&s.requester), MINT - 3_000);

    // Once funded, further funding is an invalid state.
    assert_eq!(
        err(s.client.try_fund(&s.requester, &s.id(1), &1)),
        Error::InvalidState
    );
}

// ---------------------------------------------------------------------------
// assign
// ---------------------------------------------------------------------------

#[test]
fn assign_rules() {
    let s = Setup::new();
    s.create(1, 2, 0);
    // Not funded yet.
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.alice)),
        Error::InvalidState
    );
    s.client.fund(&s.requester, &s.id(1), &(2 * REWARD));

    let e = s.client.assign(&s.requester, &s.id(1), &s.alice);
    let ev = s.own_events();
    assert_eq!(e.assigned_unpaid, 1);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Assigned)
    );
    assert_eq!(
        ev,
        std::vec![ContributorAssigned {
            bounty_id: s.id(1),
            contributor: s.alice.clone()
        }
        .to_xdr(&s.env, &s.contract_id)]
    );

    // Duplicate.
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.alice)),
        Error::AlreadyAssigned
    );
    // Requester cannot assign themselves.
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.requester)),
        Error::Unauthorized
    );
    // Wrong requester.
    assert_eq!(
        err(s.client.try_assign(&s.bob, &s.id(1), &s.carol)),
        Error::Unauthorized
    );

    s.client.assign(&s.requester, &s.id(1), &s.bob);
    // Positions exhausted by assignments.
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.carol)),
        Error::PositionsExhausted
    );

    // Paid contributors cannot be re-assigned.
    s.client.release(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.alice)),
        Error::AlreadyAssigned
    );
}

// ---------------------------------------------------------------------------
// release
// ---------------------------------------------------------------------------

#[test]
fn release_happy_path_assigned() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);

    let e = s.client.release(&s.requester, &s.id(1), &s.alice);
    let all_len = s.env.events().all().events().len();
    let ev = s.own_events();
    assert_eq!(e.payouts_made, 1);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.contract_balance(), REWARD);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
    assert_eq!(
        ev,
        std::vec![RewardReleased {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
            amount: REWARD
        }
        .to_xdr(&s.env, &s.contract_id)]
    );
    // Token transfer event from the SAC is also emitted.
    assert!(all_len > 1);
}

#[test]
fn release_direct_without_assignment_and_duplicate_prevented() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(s.token.balance(&s.bob), REWARD);

    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.bob)),
        Error::AlreadyPaid
    );
    assert_eq!(s.token.balance(&s.bob), REWARD);
    assert_eq!(s.contract_balance(), REWARD);
}

#[test]
fn release_positions_exhausted_by_assignments() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    // The only position is reserved for alice.
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.bob)),
        Error::PositionsExhausted
    );
    let e = s.client.release(&s.requester, &s.id(1), &s.alice);
    assert_eq!(e.status, EscrowStatus::Completed);
    // Completed escrow blocks further releases.
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.bob)),
        Error::InvalidState
    );
}

#[test]
fn release_requires_funded_state() {
    let s = Setup::new();
    s.create(1, 2, REWARD);
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.alice)),
        Error::InvalidState
    );
}

#[test]
fn release_unauthorized_wrong_requester() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s.client.try_release(&s.bob, &s.id(1), &s.alice)),
        Error::Unauthorized
    );
    assert_eq!(
        err(s.client.try_release(&s.arbiter, &s.id(1), &s.alice)),
        Error::Unauthorized
    );
    assert_eq!(s.token.balance(&s.alice), 0);
}

#[test]
fn release_blocked_while_disputed_and_cancel_requested() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.alice)),
        Error::InvalidState
    );
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.bob)),
        Error::InvalidState
    );

    s.create_funded(2, 1);
    s.client.request_cancel(&s.requester, &s.id(2));
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(2), &s.bob)),
        Error::InvalidState
    );
}

#[test]
fn multi_position_completion() {
    let s = Setup::new();
    s.create_funded(1, 3);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.assign(&s.requester, &s.id(1), &s.bob);
    s.client.release(&s.requester, &s.id(1), &s.bob);
    s.client.release(&s.requester, &s.id(1), &s.alice);
    let e = s.client.release(&s.requester, &s.id(1), &s.carol);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.payouts_made, 3);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.paid_out_amount, 3 * REWARD);
    for who in [&s.alice, &s.bob, &s.carol] {
        assert_eq!(s.token.balance(who), REWARD);
    }
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(s.token.balance(&s.requester), MINT - 3 * REWARD);
    // Completed escrow cannot be cancelled or refunded.
    assert_eq!(
        err(s.client.try_request_cancel(&s.requester, &s.id(1))),
        Error::InvalidState
    );
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::InvalidState
    );
}

// ---------------------------------------------------------------------------
// cancel / refund
// ---------------------------------------------------------------------------

#[test]
fn refund_awaiting_funding_directly() {
    let s = Setup::new();
    s.create(1, 3, 1_200);
    let e = s.client.refund(&s.requester, &s.id(1));
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(e.refunded_amount, 1_200);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(s.token.balance(&s.requester), MINT);
    assert_eq!(
        ev,
        std::vec![EscrowRefunded {
            bounty_id: s.id(1),
            amount: 1_200
        }
        .to_xdr(&s.env, &s.contract_id)]
    );
    // Terminal.
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::InvalidState
    );
}

#[test]
fn refund_funded_requires_cancel_request() {
    let s = Setup::new();
    s.create_funded(1, 1);
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::InvalidState
    );
    let e = s.client.request_cancel(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::CancelRequested);
    assert_eq!(
        s.own_events(),
        std::vec![CancelRequested { bounty_id: s.id(1) }.to_xdr(&s.env, &s.contract_id)]
    );
    // Double request is invalid.
    assert_eq!(
        err(s.client.try_request_cancel(&s.requester, &s.id(1))),
        Error::InvalidState
    );
    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(s.token.balance(&s.requester), MINT);
}

#[test]
fn refund_blocked_with_outstanding_assignment_then_after_consent() {
    let s = Setup::new();
    s.create_funded(1, 3);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.release(&s.requester, &s.id(1), &s.bob);
    s.client.request_cancel(&s.requester, &s.id(1));

    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::AssignmentsOutstanding
    );
    // Non-assigned party cannot consent.
    assert_eq!(
        err(s.client.try_consent_cancel(&s.carol, &s.id(1))),
        Error::NotAssigned
    );
    // Paid party cannot consent either.
    assert_eq!(
        err(s.client.try_consent_cancel(&s.bob, &s.id(1))),
        Error::NotAssigned
    );

    let e = s.client.consent_cancel(&s.alice, &s.id(1));
    let ev = s.own_events();
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(s.client.assignment(&s.id(1), &s.alice), None);
    assert_eq!(
        ev,
        std::vec![CancelConsented {
            bounty_id: s.id(1),
            contributor: s.alice.clone()
        }
        .to_xdr(&s.env, &s.contract_id)]
    );

    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(e.refunded_amount, 2 * REWARD);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(s.token.balance(&s.bob), REWARD);
    assert_eq!(s.token.balance(&s.alice), 0);
    assert_eq!(s.token.balance(&s.requester), MINT - REWARD);
}

#[test]
fn consent_requires_cancel_requested() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s.client.try_consent_cancel(&s.alice, &s.id(1))),
        Error::InvalidState
    );
}

#[test]
fn refund_after_deadline_with_outstanding_assignment() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.request_cancel(&s.requester, &s.id(1));

    // Exactly at the deadline is still blocked.
    s.env.ledger().set_timestamp(DEADLINE);
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::AssignmentsOutstanding
    );

    s.env.ledger().set_timestamp(DEADLINE + 1);
    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(e.refunded_amount, 2 * REWARD);
    assert_eq!(s.token.balance(&s.requester), MINT);
    assert_eq!(s.contract_balance(), 0);
}

#[test]
fn refund_only_by_requester() {
    let s = Setup::new();
    s.create(1, 1, 500);
    assert_eq!(
        err(s.client.try_refund(&s.arbiter, &s.id(1))),
        Error::Unauthorized
    );
    assert_eq!(
        err(s.client.try_request_cancel(&s.alice, &s.id(1))),
        Error::Unauthorized
    );
}

// ---------------------------------------------------------------------------
// disputes
// ---------------------------------------------------------------------------

#[test]
fn dispute_raise_by_non_party_rejected() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s.client.try_raise_dispute(&s.carol, &s.id(1))),
        Error::Unauthorized
    );
    assert_eq!(
        err(s.client.try_raise_dispute(&s.arbiter, &s.id(1))),
        Error::Unauthorized
    );
    // A paid contributor is no longer a party.
    s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(
        err(s.client.try_raise_dispute(&s.bob, &s.id(1))),
        Error::Unauthorized
    );
}

#[test]
fn dispute_raise_state_rules() {
    let s = Setup::new();
    s.create(1, 1, 0);
    // AwaitingFunding: not disputable.
    assert_eq!(
        err(s.client.try_raise_dispute(&s.requester, &s.id(1))),
        Error::InvalidState
    );
    s.create_funded(2, 1);
    s.client.assign(&s.requester, &s.id(2), &s.alice);
    let e = s.client.raise_dispute(&s.requester, &s.id(2));
    assert_eq!(e.status, EscrowStatus::Disputed);
    assert_eq!(e.pre_dispute_status, EscrowStatus::Funded);
    assert_eq!(
        s.own_events(),
        std::vec![DisputeRaised {
            bounty_id: s.id(2),
            raised_by: s.requester.clone()
        }
        .to_xdr(&s.env, &s.contract_id)]
    );
    // Already disputed.
    assert_eq!(
        err(s.client.try_raise_dispute(&s.requester, &s.id(2))),
        Error::InvalidState
    );
    // Cancel / refund blocked while disputed.
    assert_eq!(
        err(s.client.try_request_cancel(&s.requester, &s.id(2))),
        Error::InvalidState
    );
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(2))),
        Error::InvalidState
    );
}

#[test]
fn resolve_by_non_arbiter_rejected() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    // Not disputed yet.
    assert_eq!(
        err(s
            .client
            .try_resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true)),
        Error::InvalidState
    );
    s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(
        err(s
            .client
            .try_resolve_dispute(&s.requester, &s.id(1), &s.alice, &true)),
        Error::Unauthorized
    );
    assert_eq!(
        err(s
            .client
            .try_resolve_dispute(&s.alice, &s.id(1), &s.alice, &true)),
        Error::Unauthorized
    );
    // Arbiter can only route to an assigned contributor.
    assert_eq!(
        err(s
            .client
            .try_resolve_dispute(&s.arbiter, &s.id(1), &s.arbiter, &true)),
        Error::NotAssigned
    );
    assert_eq!(
        err(s
            .client
            .try_resolve_dispute(&s.arbiter, &s.id(1), &s.carol, &true)),
        Error::NotAssigned
    );
    assert_eq!(s.token.balance(&s.arbiter), 0);
    assert_eq!(s.contract_balance(), REWARD);
}

#[test]
fn resolve_pay_contributor() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));

    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true);
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.payouts_made, 1);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.contract_balance(), REWARD);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
    assert_eq!(
        ev,
        std::vec![
            RewardReleased {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                amount: REWARD
            }
            .to_xdr(&s.env, &s.contract_id),
            DisputeResolved {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                paid: true
            }
            .to_xdr(&s.env, &s.contract_id),
        ]
    );
    // Release still works for the remaining position.
    let e = s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.contract_balance(), 0);
}

#[test]
fn resolve_pay_last_position_completes() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.request_cancel(&s.requester, &s.id(1));
    let e = s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(e.pre_dispute_status, EscrowStatus::CancelRequested);
    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.contract_balance(), 0);
}

/// SEC-05: a dispute with nobody `Assigned` could never be resolved (the
/// arbiter can only act on an assigned contributor), locking the funds forever.
#[test]
fn dispute_requires_an_assigned_contributor() {
    let s = Setup::new();
    s.create_funded(1, 2);
    assert_eq!(
        err(s.client.try_raise_dispute(&s.requester, &s.id(1))),
        Error::NotAssigned
    );
    // One position paid directly, none assigned: still nothing to resolve.
    s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(
        err(s.client.try_raise_dispute(&s.requester, &s.id(1))),
        Error::NotAssigned
    );
    // Also during a cancellation.
    s.client.request_cancel(&s.requester, &s.id(1));
    assert_eq!(
        err(s.client.try_raise_dispute(&s.requester, &s.id(1))),
        Error::NotAssigned
    );
    assert_eq!(
        s.client.get_escrow(&s.id(1)).status,
        EscrowStatus::CancelRequested
    );

    // With an assigned contributor the dispute can be raised and always resolved.
    s.create_funded(2, 1);
    s.client.assign(&s.requester, &s.id(2), &s.alice);
    s.client.raise_dispute(&s.requester, &s.id(2));
    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(2), &s.alice, &false);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.assigned_unpaid, 0);
}

/// SEC-06: an assignment is only meaningful while it blocks refunds, i.e.
/// strictly before the deadline.
#[test]
fn assign_rejected_at_or_after_deadline() {
    let s = Setup::new();
    s.create_funded(1, 3);
    s.env.ledger().set_timestamp(DEADLINE - 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.env.ledger().set_timestamp(DEADLINE);
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.bob)),
        Error::DeadlineInPast
    );
    s.env.ledger().set_timestamp(DEADLINE + 10);
    assert_eq!(
        err(s.client.try_assign(&s.requester, &s.id(1), &s.carol)),
        Error::DeadlineInPast
    );
    // A pre-deadline assignment can still be paid after the deadline.
    let e = s.client.release(&s.requester, &s.id(1), &s.alice);
    assert_eq!(e.payouts_made, 1);
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

/// Payout bookkeeping is persisted before the token transfer
/// (checks-effects-interactions) and the transfer still happens exactly once.
#[test]
fn payouts_record_state_and_move_funds_once() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));
    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(s.client.get_escrow(&s.id(1)), e);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(
        err(s.client.try_release(&s.requester, &s.id(1), &s.alice)),
        Error::AlreadyPaid
    );
    let e = s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(s.token.balance(&s.bob), REWARD);
}

#[test]
fn resolve_unassign_then_refund() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.request_cancel(&s.requester, &s.id(1));
    s.client.raise_dispute(&s.requester, &s.id(1));

    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &false);
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::CancelRequested);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.payouts_made, 0);
    assert_eq!(s.client.assignment(&s.id(1), &s.alice), None);
    assert_eq!(s.token.balance(&s.alice), 0);
    assert_eq!(
        ev,
        std::vec![DisputeResolved {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
            paid: false
        }
        .to_xdr(&s.env, &s.contract_id)]
    );

    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(s.token.balance(&s.requester), MINT);
    assert_eq!(s.contract_balance(), 0);
}

// ---------------------------------------------------------------------------
// auth
// ---------------------------------------------------------------------------

#[test]
fn auth_assign_requires_requester_signature() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        s.env.auths(),
        std::vec![(
            s.requester.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    s.contract_id.clone(),
                    Symbol::new(&s.env, "assign"),
                    (s.requester.clone(), s.id(1), s.alice.clone()).into_val(&s.env),
                )),
                sub_invocations: std::vec![],
            }
        )]
    );
}

#[test]
fn auth_fund_includes_token_transfer() {
    let s = Setup::new();
    s.create(1, 1, 0);
    s.client.fund(&s.requester, &s.id(1), &REWARD);
    assert_eq!(
        s.env.auths(),
        std::vec![(
            s.requester.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    s.contract_id.clone(),
                    Symbol::new(&s.env, "fund"),
                    (s.requester.clone(), s.id(1), REWARD).into_val(&s.env),
                )),
                sub_invocations: std::vec![AuthorizedInvocation {
                    function: AuthorizedFunction::Contract((
                        s.token_id.clone(),
                        Symbol::new(&s.env, "transfer"),
                        (s.requester.clone(), s.contract_id.clone(), REWARD).into_val(&s.env),
                    )),
                    sub_invocations: std::vec![],
                }],
            }
        )]
    );
}

#[test]
fn auth_consent_and_dispute_signers() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(s.env.auths()[0].0, s.alice);
    s.client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &false);
    assert_eq!(s.env.auths().len(), 1);
    assert_eq!(s.env.auths()[0].0, s.arbiter);
}

#[test]
fn auth_release_fails_without_requester_signature() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);

    // Only the contributor signs a release naming the requester: must fail.
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "release",
                args: (s.requester.clone(), s.id(1), s.alice.clone()).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_release(&s.requester, &s.id(1), &s.alice);
    assert!(res.is_err());
    assert_eq!(s.token.balance(&s.alice), 0);

    // With the requester's signature it succeeds.
    s.client
        .mock_auths(&[MockAuth {
            address: &s.requester,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "release",
                args: (s.requester.clone(), s.id(1), s.alice.clone()).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .release(&s.requester, &s.id(1), &s.alice);
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn auth_resolve_fails_without_arbiter_signature() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));

    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "resolve_dispute",
                args: (s.arbiter.clone(), s.id(1), s.alice.clone(), true).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true);
    assert!(res.is_err());
    assert_eq!(s.token.balance(&s.alice), 0);
    assert_eq!(s.client.get_escrow(&s.id(1)).status, EscrowStatus::Disputed);
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------

#[test]
fn escrows_are_isolated() {
    let s = Setup::new();
    s.create_funded(1, 1);
    s.create_funded(2, 1);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(s.client.assignment(&s.id(2), &s.alice), None);
    s.client.release(&s.requester, &s.id(2), &s.alice);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Assigned)
    );
    assert_eq!(
        s.client.get_escrow(&s.id(2)).status,
        EscrowStatus::Completed
    );
    assert_eq!(s.client.get_escrow(&s.id(1)).status, EscrowStatus::Funded);
    assert_eq!(s.contract_balance(), REWARD);
}

#[test]
fn insufficient_token_balance_reverts_creation() {
    let s = Setup::new();
    let poor = Address::generate(&s.env);
    let res = s.client.try_create_escrow(
        &poor,
        &s.id(1),
        &s.token_id,
        &REWARD,
        &1,
        &s.arbiter,
        &DEADLINE,
        &REWARD,
    );
    assert!(res.is_err());
    assert_eq!(err(s.client.try_get_escrow(&s.id(1))), Error::NotFound);
}

// ---------------------------------------------------------------------------
// v2: deployment, admin and upgrade
// ---------------------------------------------------------------------------

#[test]
fn constructor_sets_admin_and_min_review_window() {
    let s = Setup::new();
    assert_eq!(s.client.admin(), s.admin);
    assert_eq!(s.client.min_review_window(), MIN_WINDOW);
}

#[test]
#[should_panic]
fn constructor_rejects_min_window_below_floor() {
    let env = Env::default();
    let admin = Address::generate(&env);
    env.register(BountyEscrow, BountyEscrowArgs::__constructor(&admin, &59));
}

#[test]
#[should_panic]
fn constructor_rejects_min_window_above_default() {
    let env = Env::default();
    let admin = Address::generate(&env);
    env.register(
        BountyEscrow,
        BountyEscrowArgs::__constructor(&admin, &(DEFAULT_REVIEW_WINDOW + 1)),
    );
}

#[test]
fn upgrade_requires_admin_signature() {
    let s = Setup::new();
    let hash = s.env.deployer().upload_contract_wasm(UPGRADE_WASM);
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.requester,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "upgrade",
                args: (hash.clone(),).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_upgrade(&hash);
    assert!(res.is_err());
    // Still the escrow contract.
    assert_eq!(s.client.version(), 2);
}

#[test]
fn upgrade_by_admin_swaps_code_and_keeps_storage() {
    let s = Setup::new();
    s.create_funded(1, 1);
    let hash = s.env.deployer().upload_contract_wasm(UPGRADE_WASM);
    s.client.upgrade(&hash);
    assert_eq!(
        s.env.auths(),
        std::vec![(
            s.admin.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    s.contract_id.clone(),
                    Symbol::new(&s.env, "upgrade"),
                    (hash.clone(),).into_val(&s.env),
                )),
                sub_invocations: std::vec![],
            }
        )]
    );
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(ContractUpgraded {
            new_wasm_hash: hash.clone()
        })]
    );
    // The new code answers: the fixture's add(u64, u64).
    let sum: u64 = s.env.invoke_contract(
        &s.contract_id,
        &Symbol::new(&s.env, "add"),
        vec![&s.env, 2_u64.into_val(&s.env), 3_u64.into_val(&s.env)],
    );
    assert_eq!(sum, 5);
    // Funds stay with the contract address.
    assert_eq!(s.contract_balance(), REWARD);
}

#[test]
fn set_admin_needs_both_admins_and_moves_upgrade_rights() {
    let s = Setup::new();
    let next = Address::generate(&s.env);
    // Only the new admin signing is not enough.
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &next,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "set_admin",
                args: (next.clone(),).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_set_admin(&next);
    assert!(res.is_err());
    assert_eq!(s.client.admin(), s.admin);

    s.client.set_admin(&next);
    let signers: std::vec::Vec<Address> = s.env.auths().into_iter().map(|(a, _)| a).collect();
    assert_eq!(signers, std::vec![s.admin.clone(), next.clone()]);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(AdminChanged {
            previous: s.admin.clone(),
            admin: next.clone()
        })]
    );
    assert_eq!(s.client.admin(), next);
    // The previous admin can no longer upgrade.
    let hash = s.env.deployer().upload_contract_wasm(UPGRADE_WASM);
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.admin,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "upgrade",
                args: (hash.clone(),).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_upgrade(&hash);
    assert!(res.is_err());
}

// ---------------------------------------------------------------------------
// v2: creation
// ---------------------------------------------------------------------------

#[test]
fn create_escrow_v1_arguments_use_v2_defaults() {
    let s = Setup::new();
    let e = s.create_funded(1, 2);
    assert_eq!(e.arbiters, vec![&s.env, s.arbiter.clone()]);
    assert_eq!(e.threshold, 1);
    assert_eq!(e.review_window, DEFAULT_REVIEW_WINDOW);
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(e.dispute_round, 0);
    assert_eq!(e.clock_reset_at, 0);
    assert!(e.milestones.is_empty());
}

#[test]
fn create_escrow_v2_with_terms_and_events() {
    let s = Setup::new();
    let mut terms = s.terms(1);
    terms.arbiters = vec![
        &s.env,
        s.arbiter.clone(),
        s.arbiter2.clone(),
        s.arbiter3.clone(),
    ];
    terms.threshold = 2;
    terms.milestones = vec![&s.env, 300, 700];
    let e = s.create_v2(1, &terms);
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.arbiter, s.arbiter);
    assert_eq!(e.arbiters, terms.arbiters);
    assert_eq!(e.threshold, 2);
    assert_eq!(e.review_window, WINDOW);
    assert_eq!(
        e.milestones,
        vec![
            &s.env,
            Milestone {
                amount: 300,
                paid: false
            },
            Milestone {
                amount: 700,
                paid: false
            }
        ]
    );
    assert_eq!(s.contract_balance(), REWARD);
    assert_eq!(
        ev,
        std::vec![
            s.xdr(EscrowCreated {
                bounty_id: s.id(1),
                requester: s.requester.clone(),
                token: s.token_id.clone(),
                required_amount: REWARD,
                arbiter: s.arbiter.clone(),
            }),
            s.xdr(EscrowConfigured {
                bounty_id: s.id(1),
                arbiters: terms.arbiters.clone(),
                threshold: 2,
                review_window: WINDOW,
                milestones: 2,
            }),
            s.xdr(EscrowFunded {
                bounty_id: s.id(1),
                amount: REWARD,
                funded_total: REWARD,
            }),
        ]
    );
}

#[test]
fn create_escrow_v2_validation() {
    let s = Setup::new();
    let c = &s.client;
    let (r, t) = (&s.requester, &s.token_id);
    let check = |terms: &EscrowTerms, expected: Error| {
        assert_eq!(err(c.try_create_escrow_v2(r, &s.id(1), t, terms)), expected);
    };

    let mut bad = s.terms(1);
    bad.arbiters = Vec::new(&s.env);
    check(&bad, Error::InvalidArbiter);
    bad.arbiters = vec![&s.env, s.arbiter.clone(), s.arbiter.clone()];
    check(&bad, Error::InvalidArbiter);
    bad.arbiters = vec![&s.env, s.arbiter.clone(), s.requester.clone()];
    check(&bad, Error::InvalidArbiter);
    let mut many = Vec::new(&s.env);
    for _ in 0..11 {
        many.push_back(Address::generate(&s.env));
    }
    bad.arbiters = many;
    check(&bad, Error::InvalidArbiter);

    let mut bad = s.terms(1);
    bad.threshold = 0;
    check(&bad, Error::InvalidThreshold);
    bad.threshold = 2;
    check(&bad, Error::InvalidThreshold);

    let mut bad = s.terms(1);
    bad.review_window = MIN_WINDOW - 1;
    check(&bad, Error::InvalidReviewWindow);
    bad.review_window = MAX_REVIEW_WINDOW + 1;
    check(&bad, Error::InvalidReviewWindow);

    let mut bad = s.terms(2);
    bad.milestones = vec![&s.env, 500, 500];
    check(&bad, Error::InvalidMilestones); // milestones need a single position
    let mut bad = s.terms(1);
    bad.milestones = vec![&s.env, 500, 400];
    check(&bad, Error::InvalidMilestones); // must add up to the reward
    bad.milestones = vec![&s.env, 1_000, 0];
    check(&bad, Error::InvalidMilestones);
    bad.milestones = vec![&s.env, 1_100, -100];
    check(&bad, Error::InvalidMilestones);
    let mut too_many = Vec::new(&s.env);
    for _ in 0..21 {
        too_many.push_back(1);
    }
    bad.reward_per_position = 21;
    bad.initial_deposit = 21;
    bad.milestones = too_many;
    check(&bad, Error::InvalidMilestones);

    // Bounds are inclusive.
    let mut ok = s.terms(1);
    ok.review_window = MIN_WINDOW;
    assert!(c.try_create_escrow_v2(r, &s.id(2), t, &ok).is_ok());
    ok.review_window = MAX_REVIEW_WINDOW;
    assert!(c.try_create_escrow_v2(r, &s.id(3), t, &ok).is_ok());
    assert_eq!(s.contract_balance(), 2 * REWARD);
}

// ---------------------------------------------------------------------------
// v2: milestones
// ---------------------------------------------------------------------------

#[test]
fn milestones_release_one_by_one() {
    let s = Setup::new();
    s.create_milestones(1, &[200, 300, 500]);
    s.client.assign(&s.requester, &s.id(1), &s.alice);

    // Any order.
    let e = s
        .client
        .release_milestone(&s.requester, &s.id(1), &s.alice, &1);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(MilestoneReleased {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
            milestone: 1,
            amount: 300,
        })]
    );
    assert_eq!(e.paid_out_amount, 300);
    assert_eq!(e.payouts_made, 0);
    assert_eq!(e.assigned_unpaid, 1);
    assert!(e.milestones.get_unchecked(1).paid);
    assert_eq!(s.token.balance(&s.alice), 300);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Assigned)
    );

    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.requester, &s.id(1), &s.alice, &1)),
        Error::MilestoneAlreadyPaid
    );
    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.requester, &s.id(1), &s.alice, &3)),
        Error::InvalidMilestone
    );
    // The position is held by alice.
    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.requester, &s.id(1), &s.bob, &0)),
        Error::PositionsExhausted
    );
    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.bob, &s.id(1), &s.alice, &0)),
        Error::Unauthorized
    );

    s.client
        .release_milestone(&s.requester, &s.id(1), &s.alice, &0);
    let e = s
        .client
        .release_milestone(&s.requester, &s.id(1), &s.alice, &2);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.payouts_made, 1);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(e.refunded_amount, 0);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
}

#[test]
fn milestone_release_takes_a_free_position_and_release_pays_the_rest() {
    let s = Setup::new();
    s.create_milestones(1, &[400, 600]);
    // Unassigned contributor: the first milestone reserves the position.
    let e = s
        .client
        .release_milestone(&s.requester, &s.id(1), &s.bob, &0);
    assert_eq!(e.assigned_unpaid, 1);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.bob),
        Some(AssignmentState::Assigned)
    );
    // v1 `release` pays every open milestone at once.
    let e = s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(RewardReleased {
            bounty_id: s.id(1),
            contributor: s.bob.clone(),
            amount: 600,
        })]
    );
    assert_eq!(e.status, EscrowStatus::Completed);
    assert!(e.milestones.iter().all(|m| m.paid));
    assert_eq!(s.token.balance(&s.bob), REWARD);
}

#[test]
fn milestone_calls_on_a_per_position_escrow_fail() {
    let s = Setup::new();
    s.create_funded(1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.requester, &s.id(1), &s.alice, &0)),
        Error::InvalidMilestone
    );
    assert_eq!(
        err(s.client.try_submit_work(&s.alice, &s.id(1), &1)),
        Error::InvalidMilestone
    );
    // Not funded: milestone releases need a funded escrow.
    let mut terms = s.terms(1);
    terms.initial_deposit = 0;
    terms.milestones = vec![&s.env, 500, 500];
    s.create_v2(2, &terms);
    assert_eq!(
        err(s
            .client
            .try_release_milestone(&s.requester, &s.id(2), &s.alice, &0)),
        Error::InvalidState
    );
}

// ---------------------------------------------------------------------------
// v2: review window and claim
// ---------------------------------------------------------------------------

#[test]
fn submit_work_rules() {
    let s = Setup::new();
    let mut terms = s.terms(2);
    terms.initial_deposit = 0;
    s.create_v2(1, &terms);
    // Not funded yet.
    assert_eq!(
        err(s.client.try_submit_work(&s.alice, &s.id(1), &0)),
        Error::InvalidState
    );
    s.client.fund(&s.requester, &s.id(1), &(2 * REWARD));
    // Not assigned.
    assert_eq!(
        err(s.client.try_submit_work(&s.alice, &s.id(1), &0)),
        Error::NotAssigned
    );
    s.client.assign(&s.requester, &s.id(1), &s.alice);

    let e = s.client.submit_work(&s.alice, &s.id(1), &0);
    let ev = s.own_events();
    assert_eq!(e.pending_reviews, 1);
    assert_eq!(
        s.review(1, &s.alice),
        Some(Review {
            milestone: 0,
            submitted_at: START_TS,
            claimable_at: START_TS + WINDOW,
            state: ReviewState::Pending,
        })
    );
    assert_eq!(
        ev,
        std::vec![s.xdr(WorkSubmitted {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
            milestone: 0,
            claimable_at: START_TS + WINDOW,
        })]
    );
    // One pending submission at a time.
    assert_eq!(
        err(s.client.try_submit_work(&s.alice, &s.id(1), &0)),
        Error::ReviewPending
    );
    // Not after the deadline.
    s.client.assign(&s.requester, &s.id(1), &s.bob);
    s.set_time(DEADLINE);
    assert_eq!(
        err(s.client.try_submit_work(&s.bob, &s.id(1), &0)),
        Error::DeadlineInPast
    );
}

#[test]
fn claim_opens_exactly_when_the_window_passes() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);

    s.set_time(START_TS + WINDOW - 1);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::ReviewWindowOpen
    );
    // Nobody else can claim alice's review.
    assert_eq!(
        err(s.client.try_claim(&s.bob, &s.id(1))),
        Error::NoPendingReview
    );

    s.set_time(START_TS + WINDOW);
    let e = s.client.claim(&s.alice, &s.id(1));
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(e.paid_out_amount, REWARD);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.review(1, &s.alice), None);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
    assert_eq!(
        ev,
        std::vec![
            s.xdr(RewardReleased {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                amount: REWARD,
            }),
            s.xdr(PaymentClaimed {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                milestone: 0,
                amount: REWARD,
            }),
        ]
    );
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::InvalidState
    );
}

#[test]
fn request_changes_stops_the_clock_and_resubmission_restarts_it() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);

    s.set_time(START_TS + WINDOW - 1); // the last second of the window
    let e = s.client.request_changes(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(ChangesRequested {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
        })]
    );
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(
        s.review(1, &s.alice).unwrap().state,
        ReviewState::ChangesRequested
    );
    s.set_time(START_TS + 3 * WINDOW);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::NoPendingReview
    );
    assert_eq!(
        err(s
            .client
            .try_request_changes(&s.requester, &s.id(1), &s.alice)),
        Error::NoPendingReview
    );

    // A resubmission gets a full new window.
    let resubmitted = s.now();
    s.client.submit_work(&s.alice, &s.id(1), &0);
    assert_eq!(
        s.review(1, &s.alice).unwrap().claimable_at,
        resubmitted + WINDOW
    );
    s.set_time(resubmitted + WINDOW - 1);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::ReviewWindowOpen
    );
    s.set_time(resubmitted + WINDOW);
    s.client.claim(&s.alice, &s.id(1));
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn requester_answers_after_the_window_are_refused() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.set_time(START_TS + WINDOW);
    assert_eq!(
        err(s
            .client
            .try_request_changes(&s.requester, &s.id(1), &s.alice)),
        Error::ReviewWindowElapsed
    );
    assert_eq!(
        err(s
            .client
            .try_reject_submission(&s.requester, &s.id(1), &s.alice)),
        Error::ReviewWindowElapsed
    );
    assert_eq!(
        err(s.client.try_request_changes(&s.bob, &s.id(1), &s.alice)),
        Error::Unauthorized
    );
    // Paying is always possible, and clears the review.
    let e = s.client.release(&s.requester, &s.id(1), &s.alice);
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(s.review(1, &s.alice), None);
}

#[test]
fn rejection_stops_the_clock_for_good() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    let e = s.client.reject_submission(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(SubmissionRejected {
            bounty_id: s.id(1),
            contributor: s.alice.clone(),
        })]
    );
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(s.review(1, &s.alice).unwrap().state, ReviewState::Rejected);
    assert_eq!(
        err(s.client.try_submit_work(&s.alice, &s.id(1), &0)),
        Error::WorkRejected
    );
    s.set_time(START_TS + 2 * WINDOW);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::NoPendingReview
    );
    // The contributor is still assigned, so a dispute remains possible.
    let e = s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Disputed);
}

#[test]
fn pending_review_blocks_refund_even_after_the_deadline() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.set_time(DEADLINE - 10);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.client.request_cancel(&s.requester, &s.id(1));
    s.set_time(DEADLINE + 1);
    assert_eq!(
        err(s.client.try_refund(&s.requester, &s.id(1))),
        Error::ReviewPending
    );
    // The claim still works while a cancellation is requested.
    s.set_time(DEADLINE - 10 + WINDOW);
    let e = s.client.claim(&s.alice, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn consent_cancel_clears_the_review() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.client.request_cancel(&s.requester, &s.id(1));
    // The requester can still answer during a cancellation.
    assert!(s
        .client
        .try_request_changes(&s.requester, &s.id(1), &s.alice)
        .is_ok());
    s.client.submit_work(&s.alice, &s.id(1), &0);
    let e = s.client.consent_cancel(&s.alice, &s.id(1));
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(s.review(1, &s.alice), None);
    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(s.token.balance(&s.requester), MINT);
}

#[test]
fn claim_pays_the_submitted_milestone_only() {
    let s = Setup::new();
    s.create_milestones(1, &[250, 750]);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &1);
    // Paying the other milestone leaves the review of milestone 1 running.
    s.client
        .release_milestone(&s.requester, &s.id(1), &s.alice, &0);
    assert_eq!(s.review(1, &s.alice).unwrap().milestone, 1);
    s.set_time(START_TS + WINDOW);
    let e = s.client.claim(&s.alice, &s.id(1));
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(
        ev,
        std::vec![
            s.xdr(MilestoneReleased {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                milestone: 1,
                amount: 750,
            }),
            s.xdr(PaymentClaimed {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                milestone: 1,
                amount: 750,
            }),
        ]
    );
    // A paid milestone cannot be submitted again.
    let s2 = Setup::new();
    s2.create_milestones(1, &[250, 750]);
    s2.client.assign(&s2.requester, &s2.id(1), &s2.alice);
    s2.client
        .release_milestone(&s2.requester, &s2.id(1), &s2.alice, &0);
    assert_eq!(
        err(s2.client.try_submit_work(&s2.alice, &s2.id(1), &0)),
        Error::MilestoneAlreadyPaid
    );
    assert_eq!(
        err(s2.client.try_submit_work(&s2.alice, &s2.id(1), &2)),
        Error::InvalidMilestone
    );
}

#[test]
fn dispute_freezes_claims_and_resolution_resets_the_clock() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(2));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.assign(&s.requester, &s.id(1), &s.bob);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.client.raise_dispute(&s.requester, &s.id(1));
    s.set_time(START_TS + WINDOW);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::InvalidState
    );
    assert_eq!(
        err(s
            .client
            .try_request_changes(&s.requester, &s.id(1), &s.alice)),
        Error::InvalidState
    );
    // The dispute is about bob; alice's review keeps waiting.
    let resolved_at = START_TS + WINDOW + 100;
    s.set_time(resolved_at);
    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.bob, &false);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.clock_reset_at, resolved_at);
    assert_eq!(e.pending_reviews, 1);
    // The requester gets a full window again from the resolution.
    s.set_time(resolved_at + WINDOW - 1);
    assert_eq!(
        err(s.client.try_claim(&s.alice, &s.id(1))),
        Error::ReviewWindowOpen
    );
    assert!(s
        .client
        .try_request_changes(&s.requester, &s.id(1), &s.alice)
        .is_ok());
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.set_time(s.now() + WINDOW);
    s.client.claim(&s.alice, &s.id(1));
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn dispute_resolution_clears_the_disputed_review() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &0);
    s.client.raise_dispute(&s.alice, &s.id(1));
    let e = s
        .client
        .resolve_dispute(&s.arbiter, &s.id(1), &s.alice, &true);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(s.review(1, &s.alice), None);
}

#[test]
fn auth_review_calls_require_the_right_signers() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(1));
    s.client.assign(&s.requester, &s.id(1), &s.alice);

    // submit_work: only the contributor.
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.requester,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "submit_work",
                args: (s.alice.clone(), s.id(1), 0_u32).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_submit_work(&s.alice, &s.id(1), &0);
    assert!(res.is_err());
    s.client.submit_work(&s.alice, &s.id(1), &0);
    assert_eq!(s.env.auths()[0].0, s.alice);

    // request_changes: only the requester.
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "request_changes",
                args: (s.requester.clone(), s.id(1), s.alice.clone()).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_request_changes(&s.requester, &s.id(1), &s.alice);
    assert!(res.is_err());

    // claim: only the contributor.
    s.set_time(START_TS + WINDOW);
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.requester,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "claim",
                args: (s.alice.clone(), s.id(1)).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_claim(&s.alice, &s.id(1));
    assert!(res.is_err());
    assert_eq!(s.token.balance(&s.alice), 0);
    s.client.claim(&s.alice, &s.id(1));
    assert_eq!(s.env.auths()[0].0, s.alice);
}

// ---------------------------------------------------------------------------
// v2: multisig arbiters
// ---------------------------------------------------------------------------

#[test]
fn two_of_three_resolution_executes_on_the_second_matching_vote() {
    let s = Setup::new();
    s.create_multisig(1, 1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));

    // Outsiders and non-disputed contributors are refused.
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.requester, &s.id(1), &s.alice, &REWARD)),
        Error::Unauthorized
    );
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.arbiter, &s.id(1), &s.bob, &REWARD)),
        Error::NotAssigned
    );
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.arbiter, &s.id(1), &s.alice, &(REWARD + 1))),
        Error::InvalidResolution
    );
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.arbiter, &s.id(1), &s.alice, &-1)),
        Error::InvalidResolution
    );

    let e = s
        .client
        .vote_resolution(&s.arbiter, &s.id(1), &s.alice, &600);
    assert_eq!(e.status, EscrowStatus::Disputed);
    assert_eq!(
        s.own_events(),
        std::vec![s.xdr(ResolutionVoted {
            bounty_id: s.id(1),
            arbiter: s.arbiter.clone(),
            contributor: s.alice.clone(),
            contributor_amount: 600,
            approvals: 1,
            threshold: 2,
        })]
    );
    // A different split does not count towards the first one.
    let e = s
        .client
        .vote_resolution(&s.arbiter2, &s.id(1), &s.alice, &500);
    assert_eq!(e.status, EscrowStatus::Disputed);
    assert_eq!(
        s.client.resolution_votes(&s.id(1)),
        vec![
            &s.env,
            ArbiterVote {
                arbiter: s.arbiter.clone(),
                contributor: s.alice.clone(),
                contributor_amount: 600,
            },
            ArbiterVote {
                arbiter: s.arbiter2.clone(),
                contributor: s.alice.clone(),
                contributor_amount: 500,
            },
        ]
    );
    assert_eq!(s.token.balance(&s.alice), 0);

    // The third arbiter agrees with the first: 2 of 3, executed.
    let e = s
        .client
        .vote_resolution(&s.arbiter3, &s.id(1), &s.alice, &600);
    let ev = s.own_events();
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.paid_out_amount, 600);
    assert_eq!(e.refunded_amount, 400);
    assert_eq!(e.payouts_made, 1);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(s.token.balance(&s.alice), 600);
    assert_eq!(s.token.balance(&s.requester), MINT - 600);
    assert_eq!(s.contract_balance(), 0);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Paid)
    );
    assert_eq!(
        ev,
        std::vec![
            s.xdr(RewardReleased {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                amount: 600,
            }),
            s.xdr(DisputeResolved {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                paid: true,
            }),
            s.xdr(EscrowRefunded {
                bounty_id: s.id(1),
                amount: 400,
            }),
        ]
    );
    // Votes are spent.
    assert!(s.client.resolution_votes(&s.id(1)).is_empty());
}

#[test]
fn an_arbiter_can_change_its_vote_and_revoting_does_not_double_count() {
    let s = Setup::new();
    s.create_multisig(1, 1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.requester, &s.id(1));
    s.client.vote_resolution(&s.arbiter, &s.id(1), &s.alice, &0);
    // The same arbiter voting again is still one approval.
    let e = s.client.vote_resolution(&s.arbiter, &s.id(1), &s.alice, &0);
    assert_eq!(e.status, EscrowStatus::Disputed);
    // Changing its mind replaces the earlier vote.
    s.client
        .vote_resolution(&s.arbiter, &s.id(1), &s.alice, &REWARD);
    assert_eq!(s.client.resolution_votes(&s.id(1)).len(), 1);
    let e = s
        .client
        .vote_resolution(&s.arbiter2, &s.id(1), &s.alice, &REWARD);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn three_of_three_threshold_and_unassign_resolution() {
    let s = Setup::new();
    s.create_multisig(1, 2, 3);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.request_cancel(&s.requester, &s.id(1));
    s.client.raise_dispute(&s.requester, &s.id(1));
    s.client.vote_resolution(&s.arbiter, &s.id(1), &s.alice, &0);
    // v1 resolve_dispute counts as a vote for the whole position or nothing.
    let e = s
        .client
        .resolve_dispute(&s.arbiter2, &s.id(1), &s.alice, &false);
    assert_eq!(e.status, EscrowStatus::Disputed);
    let e = s
        .client
        .resolve_dispute(&s.arbiter3, &s.id(1), &s.alice, &false);
    assert_eq!(e.status, EscrowStatus::CancelRequested);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(s.client.assignment(&s.id(1), &s.alice), None);
    let e = s.client.refund(&s.requester, &s.id(1));
    assert_eq!(e.status, EscrowStatus::Cancelled);
    assert_eq!(s.token.balance(&s.requester), MINT);
}

#[test]
fn split_resolution_with_positions_left_keeps_the_rest_until_completion() {
    let s = Setup::new();
    s.create_v2(1, &s.terms(2));
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));
    let e = s
        .client
        .vote_resolution(&s.arbiter, &s.id(1), &s.alice, &250);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.paid_out_amount, 250);
    assert_eq!(e.refunded_amount, 0);
    assert_eq!(s.token.balance(&s.alice), 250);
    // The second position is paid in full; the escrow completes and the
    // remainder of the split position goes back to the requester.
    let e = s.client.release(&s.requester, &s.id(1), &s.bob);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(e.refunded_amount, 750);
    assert_eq!(
        s.own_events(),
        std::vec![
            s.xdr(RewardReleased {
                bounty_id: s.id(1),
                contributor: s.bob.clone(),
                amount: REWARD,
            }),
            s.xdr(EscrowRefunded {
                bounty_id: s.id(1),
                amount: 750,
            }),
        ]
    );
    assert_eq!(s.token.balance(&s.requester), MINT - 2 * REWARD + 750);
    assert_eq!(s.contract_balance(), 0);
}

#[test]
fn milestone_dispute_split_settles_every_open_milestone() {
    let s = Setup::new();
    let mut terms = s.terms(1);
    terms.milestones = vec![&s.env, 400, 600];
    terms.arbiters = vec![&s.env, s.arbiter.clone(), s.arbiter2.clone()];
    terms.threshold = 2;
    s.create_v2(1, &terms);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client
        .release_milestone(&s.requester, &s.id(1), &s.alice, &0);
    s.client.raise_dispute(&s.alice, &s.id(1));
    // Only the open 600 can be awarded.
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.arbiter, &s.id(1), &s.alice, &601)),
        Error::InvalidResolution
    );
    s.client
        .vote_resolution(&s.arbiter, &s.id(1), &s.alice, &300);
    let e = s
        .client
        .vote_resolution(&s.arbiter2, &s.id(1), &s.alice, &300);
    assert_eq!(e.status, EscrowStatus::Completed);
    assert!(e.milestones.iter().all(|m| m.paid));
    assert_eq!(e.paid_out_amount, 700);
    assert_eq!(e.refunded_amount, 300);
    assert_eq!(s.token.balance(&s.alice), 700);
    assert_eq!(s.contract_balance(), 0);
}

#[test]
fn votes_require_a_disputed_escrow_and_the_arbiter_signature() {
    let s = Setup::new();
    s.create_multisig(1, 1, 2);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    assert_eq!(
        err(s
            .client
            .try_vote_resolution(&s.arbiter, &s.id(1), &s.alice, &REWARD)),
        Error::InvalidState
    );
    s.client.raise_dispute(&s.alice, &s.id(1));
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "vote_resolution",
                args: (s.arbiter.clone(), s.id(1), s.alice.clone(), REWARD).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_vote_resolution(&s.arbiter, &s.id(1), &s.alice, &REWARD);
    assert!(res.is_err());
    assert!(s.client.resolution_votes(&s.id(1)).is_empty());
    s.client
        .vote_resolution(&s.arbiter2, &s.id(1), &s.alice, &REWARD);
    assert_eq!(s.env.auths().len(), 1);
    assert_eq!(s.env.auths()[0].0, s.arbiter2);
}

// ---------------------------------------------------------------------------
// v2: batch release
// ---------------------------------------------------------------------------

#[test]
fn batch_release_pays_every_leg_in_one_call() {
    let s = Setup::new();
    s.create_funded(1, 3);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.assign(&s.requester, &s.id(1), &s.bob);
    let items = vec![
        &s.env,
        PayoutItem::Position(s.alice.clone()),
        PayoutItem::Position(s.bob.clone()),
    ];
    let e = s.client.batch_release(&s.requester, &s.id(1), &items);
    let ev = s.own_events();
    // One signature for the whole batch.
    assert_eq!(s.env.auths().len(), 1);
    assert_eq!(s.env.auths()[0].0, s.requester);
    assert_eq!(e.status, EscrowStatus::Funded);
    assert_eq!(e.payouts_made, 2);
    assert_eq!(e.assigned_unpaid, 0);
    assert_eq!(e.paid_out_amount, 2 * REWARD);
    assert_eq!(s.token.balance(&s.alice), REWARD);
    assert_eq!(s.token.balance(&s.bob), REWARD);
    assert_eq!(
        ev,
        std::vec![
            s.xdr(RewardReleased {
                bounty_id: s.id(1),
                contributor: s.alice.clone(),
                amount: REWARD,
            }),
            s.xdr(RewardReleased {
                bounty_id: s.id(1),
                contributor: s.bob.clone(),
                amount: REWARD,
            }),
            s.xdr(BatchReleased {
                bounty_id: s.id(1),
                legs: 2,
                total: 2 * REWARD,
            }),
        ]
    );
}

#[test]
fn batch_release_is_atomic() {
    let s = Setup::new();
    s.create_funded(1, 3);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.assign(&s.requester, &s.id(1), &s.bob);
    s.client.release(&s.requester, &s.id(1), &s.carol);
    let before = s.client.get_escrow(&s.id(1));
    // The last leg fails (carol is already paid): nothing may move.
    let items = vec![
        &s.env,
        PayoutItem::Position(s.alice.clone()),
        PayoutItem::Position(s.bob.clone()),
        PayoutItem::Position(s.carol.clone()),
    ];
    assert_eq!(
        err(s.client.try_batch_release(&s.requester, &s.id(1), &items)),
        Error::AlreadyPaid
    );
    assert_eq!(s.client.get_escrow(&s.id(1)), before);
    assert_eq!(s.token.balance(&s.alice), 0);
    assert_eq!(s.token.balance(&s.bob), 0);
    assert_eq!(
        s.client.assignment(&s.id(1), &s.alice),
        Some(AssignmentState::Assigned)
    );
    // The same contributor twice fails on the second leg.
    let twice = vec![
        &s.env,
        PayoutItem::Position(s.alice.clone()),
        PayoutItem::Position(s.alice.clone()),
    ];
    assert_eq!(
        err(s.client.try_batch_release(&s.requester, &s.id(1), &twice)),
        Error::AlreadyPaid
    );
    assert_eq!(s.token.balance(&s.alice), 0);
    assert_eq!(s.client.get_escrow(&s.id(1)), before);
}

#[test]
fn batch_release_limits_and_state() {
    let s = Setup::new();
    s.create_funded(1, 1);
    assert_eq!(
        err(s
            .client
            .try_batch_release(&s.requester, &s.id(1), &Vec::new(&s.env))),
        Error::InvalidBatch
    );
    let mut too_many = Vec::new(&s.env);
    for _ in 0..(MAX_BATCH + 1) {
        too_many.push_back(PayoutItem::Position(Address::generate(&s.env)));
    }
    assert_eq!(
        err(s
            .client
            .try_batch_release(&s.requester, &s.id(1), &too_many)),
        Error::InvalidBatch
    );
    let one = vec![&s.env, PayoutItem::Position(s.alice.clone())];
    assert_eq!(
        err(s.client.try_batch_release(&s.bob, &s.id(1), &one)),
        Error::Unauthorized
    );
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.raise_dispute(&s.alice, &s.id(1));
    assert_eq!(
        err(s.client.try_batch_release(&s.requester, &s.id(1), &one)),
        Error::InvalidState
    );
}

#[test]
fn batch_release_of_milestones() {
    let s = Setup::new();
    s.create_milestones(1, &[100, 200, 700]);
    s.client.assign(&s.requester, &s.id(1), &s.alice);
    s.client.submit_work(&s.alice, &s.id(1), &1);
    let items = vec![
        &s.env,
        PayoutItem::Milestone(s.alice.clone(), 0),
        PayoutItem::Milestone(s.alice.clone(), 1),
    ];
    let e = s.client.batch_release(&s.requester, &s.id(1), &items);
    assert_eq!(e.paid_out_amount, 300);
    assert_eq!(e.pending_reviews, 0);
    assert_eq!(s.review(1, &s.alice), None);
    assert_eq!(s.token.balance(&s.alice), 300);
    assert_eq!(e.status, EscrowStatus::Funded);
    // Mixing in a milestone that is already paid fails as a whole.
    let items = vec![
        &s.env,
        PayoutItem::Milestone(s.alice.clone(), 2),
        PayoutItem::Milestone(s.alice.clone(), 0),
    ];
    assert_eq!(
        err(s.client.try_batch_release(&s.requester, &s.id(1), &items)),
        Error::MilestoneAlreadyPaid
    );
    assert_eq!(s.token.balance(&s.alice), 300);
    let e = s.client.batch_release(
        &s.requester,
        &s.id(1),
        &vec![&s.env, PayoutItem::Position(s.alice.clone())],
    );
    assert_eq!(e.status, EscrowStatus::Completed);
    assert_eq!(s.token.balance(&s.alice), REWARD);
}

#[test]
fn batch_release_auth_covers_only_the_requester() {
    let s = Setup::new();
    s.create_funded(1, 2);
    let items: Vec<PayoutItem> = vec![
        &s.env,
        PayoutItem::Position(s.alice.clone()),
        PayoutItem::Position(s.bob.clone()),
    ];
    s.client.batch_release(&s.requester, &s.id(1), &items);
    let args: Vec<Val> = (s.requester.clone(), s.id(1), items.clone()).into_val(&s.env);
    assert_eq!(
        s.env.auths(),
        std::vec![(
            s.requester.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    s.contract_id.clone(),
                    Symbol::new(&s.env, "batch_release"),
                    args,
                )),
                sub_invocations: std::vec![],
            }
        )]
    );
}
