# Stellar & Soroban integration

## Networks

| Setting | Testnet (default) |
|---|---|
| `BLOCKCHAIN_MODE` | `testnet` (`mainnet` is reserved for a separate, audited future deployment) |
| `STELLAR_NETWORK_PASSPHRASE` | `Test SDF Network ; September 2015` |
| `STELLAR_HORIZON_URL` | `https://horizon-testnet.stellar.org` |
| `STELLAR_SOROBAN_RPC_URL` | `https://soroban-testnet.stellar.org` |
| `STELLAR_EXPLORER_BASE_URL` | `https://stellar.expert/explorer/testnet` |
| `SOROBAN_CONTRACT_ID` | `CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C` (escrow v2; new escrows are created here) |
| `SOROBAN_CONTRACT_VERSION` | `2` (the interface the backend expects; it also reads `version()` from the contract) |
| `STELLAR_NATIVE_ASSET_CONTRACT_ID` | `CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC` (native XLM SAC) |
| `STELLAR_ARBITER_ADDRESS` | `GDKMJJGPM7ZFTDG6Y74O6JA2QCMQBEJJE7Q7I5FGKI77Z67XXY2C3LU2` |
| `STELLAR_ARBITER_ADDRESSES` / `STELLAR_ARBITER_THRESHOLD` | The M-of-N arbiter set stored in each new escrow (comma-separated public keys). Empty means the single `STELLAR_ARBITER_ADDRESS`, 1 of 1. |
| `ESCROW_DEFAULT_REVIEW_WINDOW_SECONDS` | `604800` (7 days): the review window a new bounty gets unless the requester picks another |
| `ESCROW_MIN_REVIEW_WINDOW_SECONDS` / `ESCROW_MAX_REVIEW_WINDOW_SECONDS` | `86400` / `2592000` (1 to 30 days). The minimum can go down to 60 for a Testnet test stack; production refuses anything under a day, and the contract enforces its own deployment minimum. |

Escrows created on the v1 contract (`CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY`) stay on it: every
`bounty_escrows` row records its `contract_id` and `contract_version`, and each call goes to that contract. See
[smart-contracts.md](smart-contracts.md#versions-and-routing).

Settings are validated at startup. For example, `BLOCKCHAIN_MODE=testnet` with a mainnet passphrase is rejected.
There is no offline or simulated mode: every chain action is a real Stellar transaction. The active network is served at `GET /api/v1/config/public` and
shown throughout the UI.

## Wallet connection and ownership proof

The frontend uses the **Stellar Wallets Kit** (`@creit.tech/stellar-wallets-kit` 2.7): Freighter, xBull, Albedo,
LOBSTR, Hana, Rabet, Klever, OneKey, Bitget, Cactus Link, D'CENT, Scopuly, Fordefi, GHOSTSIG and MetaMask, plus
BountyFlow's own **passkey smart wallets**. WalletConnect, Ledger and Trezor are left out: they need credentials
or configuration this deployment does not carry. The kit's modules and passkey-kit are **lazy chunks**
(`lib/stellar/wallet-kit.ts`, `lib/stellar/passkey.ts`), so a visitor who never opens a wallet downloads neither.

BountyFlow draws its own picker (`WalletPickerDialog`) rather than the kit's modal: installed wallets offer
Connect, the others an install link. The choice (wallet id and address — both public) is remembered in
`localStorage` under `bf-wallet` and restored silently on the next visit. BountyFlow never asks for, receives or
stores secret keys or seed phrases.

Ownership of an address is proven before it can be used, with the proof the wallet supports. Every challenge is
issued for one user and one address, stored in Redis and consumed on the first verification attempt (`GETDEL`),
so it is single use even when verification fails. Nothing is ever submitted to the network.

| Proof | Addresses | How | Wallets |
|---|---|---|---|
| **SEP-10** challenge transaction | `G…` | A `manage_data` op sourced from the user's address with a 48-byte nonce and 5-minute time bounds, signed by a server key that holds no funds. The server checks the envelope hash, the server signature, the time bounds and the client master-key signature. | Freighter, xBull, Hana, most extensions |
| **SEP-53** signed message | `G…` | The wallet signs `sha256("Stellar Signed Message:\n" + message)`; the message names the address, the network, a random nonce and an expiry. Verified with the account's ed25519 key. | LOBSTR and any wallet that cannot be told which network to sign for |
| **SEP-45** web authentication | `C…` | The challenge is a pair of Soroban authorization entries for `web_auth_verify` on BountyFlow's web-auth contract, one signed by the server key and one for the wallet. The server merges **only** the wallet's entry into the issued challenge and verifies both by *simulating* the call: it succeeds only when the wallet's own `__check_auth` accepts the signature. | Passkey smart wallets |

`POST /wallets/challenge {public_address, method?}` issues one (the method defaults to SEP-45 for `C…`
addresses and SEP-10 otherwise); `POST /wallets/verify` answers it with `signed_challenge_xdr`, `signed_message`
or `signed_authorization_entries`, plus the `wallet_app` that signed. The wallet row records which app verified
it (`wallets.wallet_app`) and how (`wallets.proof_method`), and the wallet settings page shows both.

An address can be verified by only one account per network. `POST /wallets/{id}/primary` chooses which verified
wallet payouts go to.

### SEP-45 web authentication contract

`contracts/web_auth` is BountyFlow's deployment of the SEP-45 reference contract: one function,
`web_auth_verify(args: Map<Symbol, String>)`, which calls `require_auth` on the `account` argument, on the
server's `web_auth_domain_account` and, when present, on the client domain's account. It holds no state, no
funds and no admin.

| Item | Value |
|---|---|
| Contract ID | `CB3GXQ2BW2AHSIWUITLVBKODKPUHIK5DLEPWIIWTKLTKLA6TE24PLSZX` (`WEB_AUTH_CONTRACT_ID`) |
| Wasm hash | `be6a166a865ad89110de7aebacdc5d5f943835d8d627266f8a821d1caac54fee` |
| Upload / deploy tx | `6f1723a745e7da7c9707061fc3c6a5a8a5970126393afc5bbaaf6fd8dfe17cda` / `2fc10dc7dbc5b0836e0b16871ab358305b18e8ce7cf11033a5642109271d2e2e` |

**Why SEP-45 and not a bare WebAuthn assertion.** A smart wallet's signers can change (a passkey can be added,
replaced or expired), so checking a WebAuthn assertion against one key the server remembers proves less than the
wallet itself does. Simulating `web_auth_verify` runs the wallet's live `__check_auth`, so the proof is exactly
"whoever can authorize this wallet's transactions today", and it keeps working for a wallet that is not a passkey
wallet at all.

## Passkey smart wallets

A passkey wallet is a Soroban contract account (`C…`) whose only signer is a WebAuthn **secp256r1** passkey on
the user's device. It is created from the browser with [passkey-kit](https://github.com/stellar/passkey-kit)
0.19 and the passkey-kit v1.1 wallet WASM, already uploaded on Testnet:

| Item | Value |
|---|---|
| Wallet WASM hash | `97ce047884106b1c6c3bb40b8973cc48db1c4dad95c9e20462bf2c701daa764e` (`PASSKEY_WALLET_WASM_HASH`) |
| Address derivation | `sha256(HashIDPreimage::ContractId{ networkId, fromAddress{ deployer, salt = sha256(keyId) } })` |
| Deployer | passkey-kit's canonical `sha256("kalepail")` keypair: it only salts and signs the deployment's authorization entry, never controls the wallet and never pays |

1. **Create.** The browser registers a passkey and builds a `CreateContractV2` carrier whose constructor installs
   that passkey as the wallet's only, unlimited, persistent signer. `POST /wallets/passkey` re-derives the
   address, and refuses the deployment unless it creates **exactly** that contract, from the configured WASM,
   with the registered credential id and public key, carrying exactly the deployer's authorization for that same
   call (`app/blockchain/passkey.py`). The sponsor then sources, signs, pays for and submits it.
2. **Confirm.** The wallet is `DEPLOYING` until the network confirms the transaction **and** the contract reads
   back with the expected WASM hash; only then is it `ACTIVE`. A code mismatch fails the wallet.
3. **Link.** The user verifies ownership with SEP-45 (above); the address is then an ordinary verified wallet and
   can be the payout wallet or fund a bounty.

**Signing.** A contract account cannot be a transaction source. Every call from a passkey wallet is prepared with
the sponsor as the source and the wallet's **authorization entries** address-bound (CAP-71) with a signature
expiration covering the prepare timeout. The browser signs only those entries; the API checks they are the
prepared ones (same host function, same invocation trees, same addresses and nonces, and actually signed) and
relays them: it rebuilds the envelope, re-simulates it — which runs the wallet's `__check_auth`, so a wrong
signature fails before anything reaches the network — signs it as the sponsor and submits. The relayed hash
replaces the prepared one on the transaction row, and the envelope is stored so a lost response re-sends exactly
the same transaction.

Escrow payouts to a `C…` address and funding from one need nothing special from the contract: it takes an
`Address`, and the SAC moves the asset without a trustline.

## Fee sponsorship

A platform sponsor account (`STELLAR_SPONSOR_SECRET`, Testnet public key
`GA2H4I5DEBKXY6AERRHVXO2YL2FDIQTJK7K65577H724EANX4TBQ4BGQ`) pays network fees so a contributor never needs XLM
to be paid. Two mechanisms, both recorded in `sponsored_transactions`:

- **Fee bump** — the user's signed transaction is wrapped in a `FeeBumpTransaction` sourced by the sponsor. The
  inner transaction is untouched, so the hash BountyFlow tracks does not change, and both hashes find it on RPC
  and Horizon. A fee bump's result is decoded from the *inner* result, so a contract failure still reads as
  `txFAILED`.
- **Relay** — smart-wallet calls and passkey-wallet deployments, as described above.

Policy, checked again at submission and failing closed (`app/blockchain/sponsorship.py`):

| Check | Rule |
|---|---|
| Enabled | `STELLAR_SPONSOR_SECRET` is set. Everything below is off without it, including passkey wallets. |
| Contract | The configured escrow contract, the escrow's own `contract_id` (escrows still on v1), or `SPONSOR_ALLOWED_CONTRACTS`. |
| Function | `SPONSOR_ALLOWED_FUNCTIONS`: `consent_cancel`, `raise_dispute`, `submit_work`, `claim` — the contributor-side calls of escrow v2. Requester-side calls (`release`, `release_milestone`, `batch_release`, `refund`, `create_escrow`) are never sponsored. |
| Caller | Not the bounty's requester. Smart wallets are exempt: they can only transact through the sponsor at all. |
| Trustlines | `change_trust` to an asset in `SPONSOR_ALLOWED_ASSETS`. |
| Fee | At most `SPONSOR_MAX_FEE_STROOPS`. |
| Daily cap | Per user and UTC day: `SPONSOR_DAILY_TX_LIMIT` transactions and `SPONSOR_DAILY_FEE_LIMIT_STROOPS`, counted from `sponsored_transactions` under a per-user advisory lock. |
| Balance | Above `SPONSOR_MIN_BALANCE_XLM`; the admin console warns below `SPONSOR_LOW_BALANCE_XLM`. |

A refused fee bump never blocks the action: the user simply pays their own fee. A refused **relay** does stop the
action, because a smart wallet has no other way to transact, and the API says so.

`PreparedTransaction.summary.fee_sponsored` tells the UI to show "Network fee paid by BountyFlow" instead of the
fee estimate; `BlockchainTransaction.fee_sponsored` says it afterwards. `GET /admin/sponsorship` returns the
sponsor balance, today's spend and the recent sponsored transactions for the admin overview card.

## Reward assets

A bounty is paid in one **reward asset**. Every amount BountyFlow stores carries its asset identifier:
`native` for XLM, or `CODE:ISSUER` for a classic Stellar asset (`USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`).
Escrows move every asset the same way, through its **Stellar Asset Contract** (SAC): the token interface the
escrow contract already calls for XLM.

The **registry** (`reward_assets`, one row per network) decides what a bounty may be created in:

| Column | Meaning |
|---|---|
| `identifier` | `native`, or `CODE:ISSUER` |
| `contract_id` | The asset's SAC address. **Derived** from the asset and the network passphrase (`Asset.contract_id`), never taken from a client |
| `contract_status` | `DEPLOYED` once the SAC exists on the network, else `NOT_DEPLOYED` |
| `symbol`, `decimals` | Read from the contract (`symbol()`, `decimals()`); only 7 decimals, Stellar's own precision, is accepted |
| `issuer_flags` | The issuer account's `auth_*` flags, read from Horizon |
| `is_enabled` | Whether new bounties may pick it. Disabling never touches money already in an escrow |

XLM and Circle's Testnet USDC are enabled out of the box (the `0006_assets` migration inserts them for both
networks). An admin adds another asset by code and issuer, or by the contract id of its SAC, at
`/admin/assets`; the backend derives the SAC address, verifies the contract answers the token interface with 7
decimals, reads the issuer's flags, and refuses a contract that is not that asset's own SAC. Every classic asset
has exactly one SAC per network and **anyone may deploy it**, so when it is missing the asset stays disabled
until an admin signs the deployment (`POST /admin/assets/{id}/deploy/prepare`, `create_stellar_asset_contract`)
— the same prepare → sign → verify pipeline as every other transaction, confirmed only once the contract
instance reads back from the network.

`STELLAR_NATIVE_ASSET_CONTRACT_ID` is now optional: the native SAC id is derived from the network passphrase,
and a configured value that does not match it is rejected at startup.

## Trustlines

A Stellar account can only hold a classic asset it has a **trustline** for, and the trustline locks 0.5 XLM of
the account's reserve. A SAC transfer to a `G…` address without one fails, so BountyFlow checks before it lets
anything be signed (`app/modules/assets/checks.py`, reading Horizon through `app/blockchain/horizon.py`):

| Before | Checked | Refusal |
|---|---|---|
| Funding | The requester's wallet holds the asset, with enough spendable balance for the deposit | `422 trustline_missing` / `trustline_unauthorized` / `insufficient_balance` |
| Accepting an applicant, and `ASSIGN` | The contributor's payout wallet can receive the asset | `422 trustline_missing`, naming them: "Kai's wallet can't receive USDC yet. They need to add a USDC trustline." |
| `PAYOUT`, `MILESTONE_PAYOUT`, `CLAIM`, a paying `DISPUTE_VOTE` / `RESOLVE_DISPUTE` | The destination can receive the asset | as above (a claim is worded for the contributor themselves) |
| `BATCH_PAYOUT` | **Every leg**, before the batch is signed — it pays all of them atomically, so one missing trustline fails the whole transaction | `422 trustline_missing`, naming the wallet to drop from the batch |
| Refund | The requester's wallet can still receive the asset | `422 trustline_missing` |

Contract addresses (`C…`, passkey smart wallets) hold SAC balances in contract storage and need **no**
trustline; XLM needs none either. When Horizon cannot be reached the state is `UNKNOWN` and nothing is blocked:
the simulation and the contract still refuse whatever cannot succeed, so an outage only costs the friendlier
message.

A blocked contributor is notified (`payment.trustline_required` → "Add a USDC trustline"), at most once per
bounty and stage every six hours. The UI shows the state as a tag wherever it matters: on an applicant's card
for the requester, and per wallet under **Profile → Assets and trustlines**, where **Add USDC trustline**
builds a `changeTrust`, the wallet signs it through `lib/stellar/wallet.ts`, and the backend submits it and
confirms it only once the trustline reads back from Horizon. Fee sponsorship covers that transaction's network
fee when the asset is in `SPONSOR_ALLOWED_ASSETS`; the 0.5 XLM reserve is a protocol rule and must come from
the account itself. Testnet USDC for testing comes from [Circle's faucet](https://faucet.circle.com), linked
from the same panel.

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
| `RESOLVE_DISPUTE` | `resolve_dispute` | Arbiter wallet (moderator) | Pays the contributor or releases their claim (1-of-1 arbiter set) |

Escrow v2 adds these actions. They need an escrow on the v2 contract; on a v1 escrow the API answers
`409 invalid_state_transition` ("This bounty's escrow was created on the v1 contract, which has no ...").

| Action | Contract function | Who signs | Effect after verification |
|---|---|---|---|
| `MILESTONE_PAYOUT` | `release_milestone` | Requester | The approved milestone's payment `CONFIRMED`, the milestone `PAID`; the bounty completes with the last one |
| `BATCH_PAYOUT` | `batch_release` | Requester | Every selected payment `CONFIRMED`, but only once every leg reads paid on-chain (all or none) |
| `SUBMIT_WORK` | `submit_work` | Assigned contributor | The submission's review clock runs on-chain (`onchain_state = PENDING`, `claimable_at` set) |
| `REQUEST_CHANGES` | `request_changes` | Requester | Clock stopped; the submission moves to `REVISION_REQUESTED` with the requester's feedback |
| `REJECT_SUBMISSION` | `reject_submission` | Requester | Clock stopped; the submission is `REJECTED`, the contributor stays assigned (a dispute is the way forward) |
| `CLAIM` | `claim` | Contributor | After an unanswered window: the submission is approved and paid, payment `CONFIRMED` |
| `DISPUTE_VOTE` | `vote_resolution` | An arbiter wallet of the escrow (moderator or admin) | The approval is recorded; the vote that reaches the threshold executes the recorded decision (release, refund or split) |

While a submission's clock runs on-chain, a revision request or a rejection must be signed (`REQUEST_CHANGES`,
`REJECT_SUBMISSION`): the off-chain endpoints answer `409 onchain_review_pending`, because an unsigned answer would
not stop the contributor's claim. The worker's `review-clock` job marks submissions whose window has passed and
notifies the contributor that they can claim.

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
