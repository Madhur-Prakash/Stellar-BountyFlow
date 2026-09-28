# Stellar & Soroban integration

## Networks

| Setting | Testnet (default) |
|---|---|
| `BLOCKCHAIN_MODE` | `testnet` (`mainnet` is reserved for a separate, audited future deployment) |
| `STELLAR_NETWORK_PASSPHRASE` | `Test SDF Network ; September 2015` |
| `STELLAR_HORIZON_URL` | `https://horizon-testnet.stellar.org` |
| `STELLAR_SOROBAN_RPC_URL` | `https://soroban-testnet.stellar.org` |
| `STELLAR_EXPLORER_BASE_URL` | `https://stellar.expert/explorer/testnet` |
| `SOROBAN_CONTRACT_ID` | `CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY` |
| `STELLAR_NATIVE_ASSET_CONTRACT_ID` | `CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC` (native XLM SAC) |
| `STELLAR_ARBITER_ADDRESS` | `GDKMJJGPM7ZFTDG6Y74O6JA2QCMQBEJJE7Q7I5FGKI77Z67XXY2C3LU2` |

Settings are validated at startup. For example, `BLOCKCHAIN_MODE=testnet` with a mainnet passphrase is rejected.
There is no offline or simulated mode: every chain action is a real Stellar transaction. The active network is served at `GET /api/v1/config/public` and
shown throughout the UI.

## Wallet connection and ownership proof

The frontend uses **Freighter** (`@stellar/freighter-api`). BountyFlow never asks for, receives or stores secret
keys or seed phrases.

Ownership of an address is proven with a **SEP-10 challenge transaction**:

1. `POST /wallets/challenge {public_address}`: the server builds a challenge (a `manage_data` op sourced from the
   user's address, a 48-byte random nonce and 5-minute time bounds) and signs it with a server key that holds no
   funds. The challenge is stored in Redis, bound to the user and the address.
2. The wallet signs the challenge. It is **never submitted** to the network.
3. `POST /wallets/verify`: the server consumes the challenge (single use, `GETDEL`), checks that the envelope hash
   matches, then verifies the server signature, the client master-key signature and the time bounds with the
   Stellar SDK's SEP-10 verifier.

An address can be verified by only one account per network.

## Transaction lifecycle

```
prepare ──► SIGNATURE_REQUIRED ──sign in wallet──► submit ──► SUBMITTED ──verify──► CONFIRMED
                 │                                   │                  └──────────► FAILED / EXPIRED
                 └──(5 min timeout)──► EXPIRED        └─(rejected by network)──► FAILED
```

1. **Prepare** (`POST /bounties/{id}/chain/prepare` or the `funding/` and `payouts/` aliases). The server validates
   domain rules and the caller's *verified* wallet, builds an `InvokeHostFunction` with that wallet as the source
   account, **simulates** it (so contract errors surface before signing), assembles footprint, auth and resource
   fees, and records a `blockchain_transactions` row with the transaction hash.
2. **Sign.** Freighter signs the exact XDR.
3. **Submit** (`POST /transactions/{id}/submit`). The server checks that the signed envelope's hash equals the
   prepared hash (signatures do not change the hash), that its source is the expected wallet, and that a valid
   signature from that key is present. It then calls `sendTransaction`. `PENDING` and `DUPLICATE` mean submitted;
   `TRY_AGAIN_LATER` is surfaced as retryable; `ERROR` result codes are decoded (`txBAD_SEQ`,
   `txINSUFFICIENT_BALANCE`, `txTOO_LATE`, …).
4. **Verify.** The worker's `blockchain-verifier` (triggered by an outbox event), a periodic sweep and client polls
   all call the idempotent `verify_transaction`. It uses `getTransaction` and treats `NOT_FOUND` as pending until
   expiry plus a grace period.
5. **Reconcile.** After `SUCCESS`, the server reads `get_escrow` (and `assignment` for payouts) from the contract
   and overwrites the DB escrow view with chain truth. Only then do bounty and payment states advance.

**Submission is not success.** A bounty is labelled funded only when the escrow reads `Funded` on-chain. A payout
is `CONFIRMED` only when the contract reports the contributor as `Paid`.

### Chain actions

| Action | Contract function | Who signs | Effect after verification |
|---|---|---|---|
| `FUND` | `create_escrow` / `fund` | Requester | Escrow funded → bounty `FUNDED` |
| `ASSIGN` | `assign` | Requester | Contributor locked on-chain (protects their reward from refunds) |
| `PAYOUT` | `release` | Requester | Payment `CONFIRMED`, assignment completed, bounty `COMPLETED` when all positions are paid |
| `REQUEST_CANCEL` | `request_cancel` | Requester | Escrow `CancelRequested` |
| `CONSENT_CANCEL` | `consent_cancel` | Assigned contributor | On-chain assignment released |
| `REFUND` | `refund` | Requester | Escrow `Cancelled`, bounty `CANCELLED` |
| `RAISE_DISPUTE` | `raise_dispute` | Requester or assigned contributor | Escrow frozen (`Disputed`) |
| `RESOLVE_DISPUTE` | `resolve_dispute` | Arbiter wallet (moderator) | Pays the contributor or releases their claim |

### Error handling

| Situation | Behaviour |
|---|---|
| Wallet account missing on the network | `422 account_not_found`, with Friendbot guidance on Testnet |
| Insufficient balance / missing trustline | Simulation error, mapped to a clear message |
| Contract rule violation | `422 contract_rejected`, with the contract error name (e.g. `AlreadyPaid`) |
| User rejects in wallet | Handled client-side; the prepared tx expires harmlessly |
| Tampered or foreign signed XDR | `422 signature_invalid` |
| Expired before signing or inclusion | Tx `EXPIRED`, bounty/payment reverted, re-prepare needed |
| Sequence conflict | `txBAD_SEQ`, the user is asked to retry |
| RPC timeout / outage | `502 blockchain_error`; verification retried by the worker |
| Duplicate submission | Idempotent: returns the existing tx |

## Automated tests without a network

The application only contains the real Stellar adapter. Automated tests inject a test double
(`backend/tests/support/fake_chain.py`) through `set_adapter`. It builds **real** transaction envelopes that the
tests sign with real keypairs, so the backend's actual signature verification runs. It then executes the calls
against an in-memory model of the escrow contract (`tests/support/escrow_model.py`). The real-network path is
covered by `make test-testnet` and by the Playwright suite, which runs on Stellar Testnet.

## Explorer

`TransactionExplorer` in the UI links to `{STELLAR_EXPLORER_BASE_URL}/tx/{hash}` for real network transactions
only. Contract and account links use the same base URL.

## Real-network test

`make test-testnet` (`backend/tests/contract/test_testnet_flow.py`) runs the complete lifecycle on Stellar Testnet
with Friendbot-funded throwaway keypairs standing in for browser wallets: fund, apply, accept, submit, revise,
approve, pay out, verify, and reject a duplicate payout.
