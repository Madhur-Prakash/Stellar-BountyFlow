//! SEP-45 web authentication contract for contract accounts.
//!
//! BountyFlow proves that a user controls a smart-wallet address (`C…`) the same way SEP-10 proves control
//! of a `G…` account: the server issues a challenge, the wallet authorizes it and the server verifies it.
//! For a contract account "authorizing" means its `__check_auth` accepts the authorization entry for
//! `web_auth_verify`, so the wallet's own signer rules (for a passkey wallet, a WebAuthn secp256r1
//! assertion) are what is checked.
//!
//! The challenge is never submitted. The server verifies it by simulating `web_auth_verify` with the signed
//! authorization entries: the call only succeeds when both the client account and the server's signing key
//! authorized exactly these arguments (including the single-use nonce).
//!
//! Interface and behaviour follow the SEP-45 reference implementation (`stellar/sep45-reference`,
//! `contracts/web_auth`). The contract holds no state, no funds and no admin.

#![no_std]

#[cfg(test)]
mod test;

use soroban_sdk::{contract, contracterror, contractimpl, Address, Env, Map, String, Symbol};

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum WebAuthError {
    /// `account` or `web_auth_domain_account` is missing from the arguments.
    MissingArgument = 1,
}

#[contract]
pub struct WebAuthContract;

#[contractimpl]
impl WebAuthContract {
    /// Requires the authorization of the client account, the server's signing key and, when present, the
    /// client domain's signing key.
    ///
    /// Arguments (all strings): `account`, `home_domain`, `web_auth_domain`, `web_auth_domain_account`,
    /// `nonce`, and optionally `client_domain` and `client_domain_account`.
    pub fn web_auth_verify(env: Env, args: Map<Symbol, String>) -> Result<(), WebAuthError> {
        let account = args
            .get(Symbol::new(&env, "account"))
            .ok_or(WebAuthError::MissingArgument)?;
        Address::from_string(&account).require_auth();

        let server = args
            .get(Symbol::new(&env, "web_auth_domain_account"))
            .ok_or(WebAuthError::MissingArgument)?;
        Address::from_string(&server).require_auth();

        if let Some(client_domain_account) = args.get(Symbol::new(&env, "client_domain_account")) {
            Address::from_string(&client_domain_account).require_auth();
        }
        Ok(())
    }
}
