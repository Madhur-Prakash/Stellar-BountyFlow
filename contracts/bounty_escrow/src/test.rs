#![cfg(test)]
extern crate std;

use crate::{
    AssignmentState, BountyEscrow, BountyEscrowClient, CancelConsented, CancelRequested,
    ContributorAssigned, DisputeRaised, DisputeResolved, Error, Escrow, EscrowCreated,
    EscrowFunded, EscrowRefunded, EscrowStatus, RewardReleased,
};
use soroban_sdk::{
    testutils::{
        Address as _, AuthorizedFunction, AuthorizedInvocation, Events as _, Ledger as _, MockAuth,
        MockAuthInvoke,
    },
    token::{StellarAssetClient, TokenClient},
    Address, BytesN, Env, Event, IntoVal, Symbol,
};

const REWARD: i128 = 1_000;
const START_TS: u64 = 1_000_000;
const DEADLINE: u64 = START_TS + 86_400;
const MINT: i128 = 1_000_000;

struct Setup<'a> {
    env: Env,
    contract_id: Address,
    client: BountyEscrowClient<'a>,
    token_id: Address,
    token: TokenClient<'a>,
    requester: Address,
    arbiter: Address,
    alice: Address,
    bob: Address,
    carol: Address,
}

impl<'a> Setup<'a> {
    fn new() -> Self {
        let env = Env::default();
        env.mock_all_auths();
        env.ledger().set_timestamp(START_TS);

        let contract_id = env.register(BountyEscrow, ());
        let client = BountyEscrowClient::new(&env, &contract_id);

        let token_admin = Address::generate(&env);
        let sac = env.register_stellar_asset_contract_v2(token_admin);
        let token_id = sac.address();
        let token = TokenClient::new(&env, &token_id);

        let requester = Address::generate(&env);
        let arbiter = Address::generate(&env);
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
            requester,
            arbiter,
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
fn version_is_one() {
    let s = Setup::new();
    assert_eq!(s.client.version(), 1);
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
