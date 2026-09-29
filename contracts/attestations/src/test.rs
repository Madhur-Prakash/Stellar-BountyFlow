#![cfg(test)]
extern crate std;

use crate::storage::{BUMP_TO, DAY_IN_LEDGERS};
use crate::{
    Attestation, AttestationRevoked, AttesterRotated, CompletionAttestations,
    CompletionAttestationsClient, CompletionAttested, DataKey, Error, MAX_PAGE, MAX_REASON_LEN,
};
use soroban_sdk::{
    testutils::{
        storage::Persistent as _, Address as _, Events as _, Ledger as _, MockAuth, MockAuthInvoke,
    },
    Address, BytesN, Env, Event, IntoVal, String,
};

const START_TS: u64 = 1_790_000_000;
const COMPLETED_AT: u64 = START_TS - 600;
const AMOUNT: i128 = 255_000_000;

struct Setup<'a> {
    env: Env,
    contract_id: Address,
    client: CompletionAttestationsClient<'a>,
    attester: Address,
    escrow: Address,
    token: Address,
    alice: Address,
    bob: Address,
}

impl<'a> Setup<'a> {
    fn new() -> Self {
        let env = Env::default();
        env.mock_all_auths();
        env.ledger().set_timestamp(START_TS);
        env.ledger().set_sequence_number(1_000);

        let attester = Address::generate(&env);
        let contract_id = env.register(CompletionAttestations, (attester.clone(),));
        let client = CompletionAttestationsClient::new(&env, &contract_id);

        Setup {
            client,
            contract_id,
            attester,
            escrow: Address::generate(&env),
            token: Address::generate(&env),
            alice: Address::generate(&env),
            bob: Address::generate(&env),
            env,
        }
    }

    fn bytes(&self, n: u8) -> BytesN<32> {
        BytesN::from_array(&self.env, &[n; 32])
    }

    /// Attest a completion of bounty `bounty` paid by payout `payout`.
    fn attest(&self, contributor: &Address, bounty: u8, payout: u8) -> Attestation {
        self.client.attest(
            &self.attester,
            contributor,
            &self.bytes(bounty),
            &self.escrow,
            &self.bytes(payout),
            &self.token,
            &AMOUNT,
            &COMPLETED_AT,
        )
    }

    fn reason(&self, text: &str) -> String {
        String::from_str(&self.env, text)
    }

    /// Events emitted by the attestation contract in the last invocation.
    fn own_events(&self) -> std::vec::Vec<soroban_sdk::xdr::ContractEvent> {
        self.env
            .events()
            .all()
            .filter_by_contract(&self.contract_id)
            .events()
            .to_vec()
    }

    fn ttl(&self, key: &DataKey) -> u32 {
        self.env.as_contract(&self.contract_id, || {
            self.env.storage().persistent().get_ttl(key)
        })
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
// Construction and views
// ---------------------------------------------------------------------------

#[test]
fn version_is_one() {
    let s = Setup::new();
    assert_eq!(s.client.version(), 1);
}

#[test]
fn constructor_sets_attester_and_empty_registry() {
    let s = Setup::new();
    assert_eq!(s.client.attester(), s.attester);
    assert_eq!(s.client.total(), 0);
    assert_eq!(s.client.count_by_contributor(&s.alice), 0);
    assert_eq!(s.client.list_by_contributor(&s.alice, &0, &10).len(), 0);
    assert_eq!(err(s.client.try_get(&1)), Error::NotFound);
    assert_eq!(
        s.client.find(&s.bytes(1), &s.alice, &s.bytes(2)),
        None::<Attestation>
    );
}

// ---------------------------------------------------------------------------
// attest
// ---------------------------------------------------------------------------

#[test]
fn attest_records_the_completion_and_emits_an_event() {
    let s = Setup::new();
    let a = s.attest(&s.alice, 1, 2);
    let events = s.own_events();

    assert_eq!(a.id, 1);
    assert_eq!(a.attester, s.attester);
    assert_eq!(a.contributor, s.alice);
    assert_eq!(a.bounty_id, s.bytes(1));
    assert_eq!(a.escrow_contract, s.escrow);
    assert_eq!(a.payout_tx, s.bytes(2));
    assert_eq!(a.token, s.token);
    assert_eq!(a.amount, AMOUNT);
    assert_eq!(a.completed_at, COMPLETED_AT);
    assert_eq!(a.attested_at, START_TS);
    assert_eq!(a.contributor_index, 0);
    assert!(!a.revoked);
    assert_eq!(a.revoked_at, 0);
    assert_eq!(a.revocation_reason, s.reason(""));

    assert_eq!(s.client.get(&1), a);
    assert_eq!(
        s.client.find(&s.bytes(1), &s.alice, &s.bytes(2)),
        Some(a.clone())
    );
    assert_eq!(s.client.total(), 1);
    assert_eq!(s.client.count_by_contributor(&s.alice), 1);

    let expected = CompletionAttested {
        contributor: s.alice.clone(),
        bounty_id: s.bytes(1),
        id: 1,
        escrow_contract: s.escrow.clone(),
        payout_tx: s.bytes(2),
        token: s.token.clone(),
        amount: AMOUNT,
        completed_at: COMPLETED_AT,
    };
    assert_eq!(events, std::vec![expected.to_xdr(&s.env, &s.contract_id)]);
}

#[test]
fn one_attestation_per_bounty_contributor_and_payout() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    let c = &s.client;

    // The exact same completion again (a retried submission) is refused.
    assert_eq!(
        err(c.try_attest(
            &s.attester,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT
        )),
        Error::AlreadyAttested
    );
    // Even with other amounts or tokens: the natural key is what counts.
    assert_eq!(
        err(c.try_attest(
            &s.attester,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.bob,
            &1,
            &COMPLETED_AT
        )),
        Error::AlreadyAttested
    );
    assert_eq!(c.total(), 1);

    // A different payout of the same bounty (a later milestone), another bounty, or another contributor are new.
    assert_eq!(s.attest(&s.alice, 1, 3).id, 2);
    assert_eq!(s.attest(&s.alice, 4, 2).id, 3);
    assert_eq!(s.attest(&s.bob, 1, 2).id, 4);
    assert_eq!(c.total(), 4);
    assert_eq!(c.count_by_contributor(&s.alice), 3);
    assert_eq!(c.count_by_contributor(&s.bob), 1);
}

#[test]
fn attest_validates_its_input() {
    let s = Setup::new();
    let c = &s.client;
    let (a, e, t) = (&s.attester, &s.escrow, &s.token);
    let (b, p) = (s.bytes(1), s.bytes(2));

    assert_eq!(
        err(c.try_attest(a, &s.alice, &b, e, &p, t, &0, &COMPLETED_AT)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(c.try_attest(a, &s.alice, &b, e, &p, t, &-1, &COMPLETED_AT)),
        Error::InvalidAmount
    );
    assert_eq!(
        err(c.try_attest(a, &s.alice, &b, e, &p, t, &AMOUNT, &0)),
        Error::InvalidTimestamp
    );
    assert_eq!(
        err(c.try_attest(a, &s.alice, &b, e, &p, t, &AMOUNT, &(START_TS + 1))),
        Error::InvalidTimestamp
    );
    // The attester can never attest itself.
    assert_eq!(
        err(c.try_attest(a, a, &b, e, &p, t, &AMOUNT, &COMPLETED_AT)),
        Error::InvalidContributor
    );
    // A completion at the current ledger time is fine.
    assert!(c
        .try_attest(a, &s.alice, &b, e, &p, t, &AMOUNT, &START_TS)
        .is_ok());
    assert_eq!(c.total(), 1);
}

#[test]
fn attest_by_another_account_is_unauthorized() {
    let s = Setup::new();
    assert_eq!(
        err(s.client.try_attest(
            &s.bob,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT
        )),
        Error::Unauthorized
    );
    assert_eq!(s.client.total(), 0);
}

#[test]
fn auth_attest_requires_the_attester_signature() {
    let s = Setup::new();
    let args = (
        s.attester.clone(),
        s.alice.clone(),
        s.bytes(1),
        s.escrow.clone(),
        s.bytes(2),
        s.token.clone(),
        AMOUNT,
        COMPLETED_AT,
    );

    // The contributor signs an attest call that names the attester: it must fail.
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "attest",
                args: args.clone().into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_attest(
            &s.attester,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT,
        );
    assert!(res.is_err());
    assert_eq!(s.client.total(), 0);

    // With the attester's signature it succeeds.
    s.client
        .mock_auths(&[MockAuth {
            address: &s.attester,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "attest",
                args: args.into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .attest(
            &s.attester,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT,
        );
    assert_eq!(s.client.total(), 1);
}

// ---------------------------------------------------------------------------
// revoke
// ---------------------------------------------------------------------------

#[test]
fn revoke_keeps_the_record_with_its_reason() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    s.env.ledger().set_timestamp(START_TS + 50);

    let reason = s.reason("Payout reversed by dispute review");
    let revoked = s.client.revoke(&s.attester, &1, &reason);
    let events = s.own_events();

    assert!(revoked.revoked);
    assert_eq!(revoked.revocation_reason, reason);
    assert_eq!(revoked.revoked_at, START_TS + 50);
    assert_eq!(s.client.get(&1), revoked);
    // Still counted and still found: attestations are never deleted.
    assert_eq!(s.client.count_by_contributor(&s.alice), 1);
    assert_eq!(
        s.client.find(&s.bytes(1), &s.alice, &s.bytes(2)),
        Some(revoked)
    );

    let expected = AttestationRevoked {
        contributor: s.alice.clone(),
        id: 1,
        reason: reason.clone(),
    };
    assert_eq!(events, std::vec![expected.to_xdr(&s.env, &s.contract_id)]);

    // A revoked completion cannot be attested again under the same key.
    assert_eq!(
        err(s.client.try_attest(
            &s.attester,
            &s.alice,
            &s.bytes(1),
            &s.escrow,
            &s.bytes(2),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT
        )),
        Error::AlreadyAttested
    );
}

#[test]
fn revoke_rules() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    let c = &s.client;
    let ok = s.reason("Recorded for the wrong contributor");

    assert_eq!(err(c.try_revoke(&s.attester, &9, &ok)), Error::NotFound);
    assert_eq!(err(c.try_revoke(&s.bob, &1, &ok)), Error::Unauthorized);
    assert_eq!(
        err(c.try_revoke(&s.attester, &1, &s.reason(""))),
        Error::InvalidReason
    );
    let too_long = std::string::String::from("x").repeat(MAX_REASON_LEN as usize + 1);
    assert_eq!(
        err(c.try_revoke(&s.attester, &1, &s.reason(&too_long))),
        Error::InvalidReason
    );
    let longest = std::string::String::from("x").repeat(MAX_REASON_LEN as usize);
    assert!(c.try_revoke(&s.attester, &1, &s.reason(&longest)).is_ok());
    assert_eq!(
        err(c.try_revoke(&s.attester, &1, &ok)),
        Error::AlreadyRevoked
    );
}

#[test]
fn auth_revoke_requires_the_attester_signature() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    let reason = s.reason("Recorded by mistake");
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &s.alice,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "revoke",
                args: (s.attester.clone(), 1u64, reason.clone()).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_revoke(&s.attester, &1, &reason);
    assert!(res.is_err());
    assert!(!s.client.get(&1).revoked);
}

// ---------------------------------------------------------------------------
// Attester rotation
// ---------------------------------------------------------------------------

#[test]
fn set_attester_hands_over_the_role() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    let next = Address::generate(&s.env);

    s.client.set_attester(&s.attester, &next);
    let events = s.own_events();
    assert_eq!(s.client.attester(), next);
    assert_eq!(
        events,
        std::vec![AttesterRotated {
            previous: s.attester.clone(),
            attester: next.clone(),
        }
        .to_xdr(&s.env, &s.contract_id)]
    );

    // The previous key can no longer attest, revoke or rotate.
    assert_eq!(
        err(s.client.try_attest(
            &s.attester,
            &s.alice,
            &s.bytes(5),
            &s.escrow,
            &s.bytes(6),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT
        )),
        Error::Unauthorized
    );
    assert_eq!(
        err(s.client.try_revoke(&s.attester, &1, &s.reason("no"))),
        Error::Unauthorized
    );
    assert_eq!(
        err(s.client.try_set_attester(&s.attester, &s.attester)),
        Error::Unauthorized
    );

    // The new key can. Older attestations keep the attester that recorded them.
    let a = s.client.attest(
        &next,
        &s.alice,
        &s.bytes(5),
        &s.escrow,
        &s.bytes(6),
        &s.token,
        &AMOUNT,
        &COMPLETED_AT,
    );
    assert_eq!(a.attester, next);
    assert_eq!(s.client.get(&1).attester, s.attester);
    assert!(s
        .client
        .try_revoke(&next, &1, &s.reason("Rotated key clean-up"))
        .is_ok());
}

#[test]
fn auth_set_attester_requires_the_attester_signature() {
    let s = Setup::new();
    let next = Address::generate(&s.env);
    let res = s
        .client
        .mock_auths(&[MockAuth {
            address: &next,
            invoke: &MockAuthInvoke {
                contract: &s.contract_id,
                fn_name: "set_attester",
                args: (s.attester.clone(), next.clone()).into_val(&s.env),
                sub_invokes: &[],
            },
        }])
        .try_set_attester(&s.attester, &next);
    assert!(res.is_err());
    assert_eq!(s.client.attester(), s.attester);
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

#[test]
fn list_by_contributor_pages_oldest_first() {
    let s = Setup::new();
    for n in 0..7u8 {
        s.attest(&s.alice, n, 100 + n);
        s.attest(&s.bob, n, 200 + n);
    }
    let c = &s.client;
    assert_eq!(c.count_by_contributor(&s.alice), 7);

    let first = c.list_by_contributor(&s.alice, &0, &3);
    assert_eq!(first.len(), 3);
    let ids: std::vec::Vec<u64> = first.iter().map(|a| a.id).collect();
    assert_eq!(ids, std::vec![1, 3, 5]);
    for (i, a) in first.iter().enumerate() {
        assert_eq!(a.contributor, s.alice);
        assert_eq!(a.contributor_index, i as u32);
    }

    let last = c.list_by_contributor(&s.alice, &6, &3);
    assert_eq!(last.len(), 1);
    assert_eq!(last.get(0).unwrap().id, 13);
    assert_eq!(c.list_by_contributor(&s.alice, &7, &3).len(), 0);
    assert_eq!(c.list_by_contributor(&s.alice, &0, &0).len(), 0);
    assert_eq!(
        c.list_by_contributor(&s.alice, &u32::MAX, &u32::MAX).len(),
        0
    );
    assert_eq!(c.list_by_contributor(&s.bob, &0, &100).len(), 7);
}

#[test]
fn list_by_contributor_caps_the_page_size() {
    let s = Setup::new();
    for n in 0..(MAX_PAGE + 5) {
        let b = (n % 256) as u8;
        let p = (n / 256) as u8;
        s.client.attest(
            &s.attester,
            &s.alice,
            &BytesN::from_array(&s.env, &[b; 32]),
            &s.escrow,
            &BytesN::from_array(&s.env, &[p; 32]),
            &s.token,
            &AMOUNT,
            &COMPLETED_AT,
        );
    }
    assert_eq!(
        s.client.list_by_contributor(&s.alice, &0, &1_000).len(),
        MAX_PAGE
    );
    assert_eq!(
        s.client
            .list_by_contributor(&s.alice, &MAX_PAGE, &1_000)
            .len(),
        5
    );
}

// ---------------------------------------------------------------------------
// TTL
// ---------------------------------------------------------------------------

#[test]
fn writes_extend_ttl_and_extend_ttl_renews_idle_records() {
    let s = Setup::new();
    let a = s.attest(&s.alice, 1, 2);
    let keys = [
        DataKey::Attestation(a.id),
        DataKey::Completion(
            a.bounty_id.clone(),
            a.contributor.clone(),
            a.payout_tx.clone(),
        ),
        DataKey::ContributorEntry(a.contributor.clone(), 0),
        DataKey::ContributorCount(a.contributor.clone()),
    ];
    for key in &keys {
        assert_eq!(s.ttl(key), BUMP_TO);
    }

    // 100 days later the remaining TTL (~20 days) is below the threshold: anyone may renew it.
    let seq = s.env.ledger().sequence();
    s.env
        .ledger()
        .set_sequence_number(seq + 100 * DAY_IN_LEDGERS);
    for key in &keys {
        assert_eq!(s.ttl(key), BUMP_TO - 100 * DAY_IN_LEDGERS);
    }
    s.client.extend_ttl(&a.id);
    for key in &keys {
        assert_eq!(s.ttl(key), BUMP_TO);
    }
    assert_eq!(err(s.client.try_extend_ttl(&42)), Error::NotFound);
}

#[test]
fn revocation_also_extends_the_record() {
    let s = Setup::new();
    s.attest(&s.alice, 1, 2);
    let seq = s.env.ledger().sequence();
    s.env
        .ledger()
        .set_sequence_number(seq + 95 * DAY_IN_LEDGERS);
    s.client
        .revoke(&s.attester, &1, &s.reason("Recorded by mistake"));
    assert_eq!(s.ttl(&DataKey::Attestation(1)), BUMP_TO);
}
