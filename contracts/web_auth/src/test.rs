#![cfg(test)]
extern crate std;

use crate::{WebAuthContract, WebAuthContractClient, WebAuthError};
use soroban_sdk::{
    testutils::{Address as _, AuthorizedFunction, AuthorizedInvocation, MockAuth, MockAuthInvoke},
    Address, Env, IntoVal, Map, String, Symbol,
};

struct Setup<'a> {
    env: Env,
    contract_id: Address,
    client: WebAuthContractClient<'a>,
    account: Address,
    server: Address,
}

fn setup<'a>() -> Setup<'a> {
    let env = Env::default();
    let contract_id = env.register(WebAuthContract, ());
    let client = WebAuthContractClient::new(&env, &contract_id);
    let account = Address::generate(&env);
    let server = Address::generate(&env);
    Setup {
        env,
        contract_id,
        client,
        account,
        server,
    }
}

fn args(env: &Env, pairs: &[(&str, &Address)], extra: &[(&str, &str)]) -> Map<Symbol, String> {
    let mut map = Map::new(env);
    for (key, address) in pairs {
        map.set(Symbol::new(env, key), address.to_string());
    }
    for (key, value) in extra {
        map.set(Symbol::new(env, key), String::from_str(env, value));
    }
    map
}

fn challenge_args(s: &Setup) -> Map<Symbol, String> {
    args(
        &s.env,
        &[
            ("account", &s.account),
            ("web_auth_domain_account", &s.server),
        ],
        &[
            ("home_domain", "bountyflow.local"),
            ("web_auth_domain", "api.bountyflow.local"),
            ("nonce", "b7b1c0e6f1a54d7e"),
        ],
    )
}

#[test]
fn requires_the_account_and_the_server() {
    let s = setup();
    s.env.mock_all_auths();
    let map = challenge_args(&s);
    s.client.web_auth_verify(&map);

    let expected = AuthorizedInvocation {
        function: AuthorizedFunction::Contract((
            s.contract_id.clone(),
            Symbol::new(&s.env, "web_auth_verify"),
            (map.clone(),).into_val(&s.env),
        )),
        sub_invocations: std::vec![],
    };
    let auths = s.env.auths();
    assert_eq!(auths.len(), 2);
    assert!(auths.contains(&(s.account.clone(), expected.clone())));
    assert!(auths.contains(&(s.server.clone(), expected)));
}

#[test]
fn requires_the_client_domain_account_when_present() {
    let s = setup();
    s.env.mock_all_auths();
    let client_domain = Address::generate(&s.env);
    let map = args(
        &s.env,
        &[
            ("account", &s.account),
            ("web_auth_domain_account", &s.server),
            ("client_domain_account", &client_domain),
        ],
        &[("nonce", "n"), ("client_domain", "wallet.example")],
    );
    s.client.web_auth_verify(&map);
    let signers: std::vec::Vec<Address> = s.env.auths().into_iter().map(|(a, _)| a).collect();
    assert_eq!(signers.len(), 3);
    assert!(signers.contains(&client_domain));
}

#[test]
fn fails_without_the_account_signature() {
    let s = setup();
    let map = challenge_args(&s);
    // Only the server authorizes: the account's require_auth must fail.
    s.env.mock_auths(&[MockAuth {
        address: &s.server,
        invoke: &MockAuthInvoke {
            contract: &s.contract_id,
            fn_name: "web_auth_verify",
            args: (map.clone(),).into_val(&s.env),
            sub_invokes: &[],
        },
    }]);
    assert!(s.client.try_web_auth_verify(&map).is_err());
}

#[test]
fn fails_without_the_server_signature() {
    let s = setup();
    let map = challenge_args(&s);
    s.env.mock_auths(&[MockAuth {
        address: &s.account,
        invoke: &MockAuthInvoke {
            contract: &s.contract_id,
            fn_name: "web_auth_verify",
            args: (map.clone(),).into_val(&s.env),
            sub_invokes: &[],
        },
    }]);
    assert!(s.client.try_web_auth_verify(&map).is_err());
}

#[test]
fn missing_arguments_are_rejected() {
    let s = setup();
    s.env.mock_all_auths();
    let no_account = args(&s.env, &[("web_auth_domain_account", &s.server)], &[]);
    assert_eq!(
        s.client.try_web_auth_verify(&no_account),
        Err(Ok(WebAuthError::MissingArgument))
    );
    let no_server = args(&s.env, &[("account", &s.account)], &[]);
    assert_eq!(
        s.client.try_web_auth_verify(&no_server),
        Err(Ok(WebAuthError::MissingArgument))
    );
}
