# Product roadmap

## Shipped (MVP)

- Bounty marketplace: search, filters, sorting, bookmarks, reports.
- Full lifecycle: draft → publish → fund (Soroban escrow) → apply → select → submit → revise → approve →
  on-chain payout, with cancellation and refunds.
- Multi-position bounties with per-position rewards and partial funding.
- Wallet ownership proof (SEP-10), Freighter signing, and independent transaction verification plus
  reconciliation.
- Disputes with evidence, moderator resolution, and a bounded on-chain arbiter.
- Notifications (in-app and email) delivered through the Kafka outbox.
- Role-aware dashboard, analytics with a documented methodology, and admin moderation with RBAC and audit logs.
- Automated end-to-end coverage on the real Stellar Testnet (Playwright + a backend Testnet lifecycle suite).

## Shipped since the MVP

**Escrow v2** (contract `CBCXG46F…3M4C`, interface version 2; escrows created on v1 `CDX6FN2M…4SFY4CY` keep
running on it, because every escrow row stores the contract it was created on):

- Milestone-based releases: a single-position bounty can be split into milestones that each pay on approval.
- Automatic release after a review timeout. The contributor records their submission on-chain, which starts a
  review window (7 days by default, 1–30). If the requester neither releases, requests changes, rejects nor
  disputes within it, the contributor can claim the payment themselves. Only an on-chain answer stops the clock.
- A multisig arbiter: an M-of-N arbiter set per escrow, with split decisions. A single arbiter is 1-of-1.
- Batch payouts: up to 10 contributors or milestones released in one atomic transaction, signed once.
- An upgradeable contract with an admin set at deployment.

**Wallets and payments:**

- Multi-wallet support through the Stellar Wallets Kit (Freighter, xBull, Albedo, LOBSTR, Hana and every other
  module that needs no extra credentials), with a wallet picker, a remembered choice, and SEP-10, SEP-53 or
  SEP-45 ownership proofs. The SDKs are lazy-loaded and stay out of the main bundle.
- Passkey smart wallets: a Soroban wallet contract secured by a WebAuthn passkey, usable for funding and as a
  payout wallet. No extension, no seed phrase, and no XLM needed to start. SEP-45 web auth contract
  `CB3GXQ2B…LSZX`.
- Fee sponsorship: the platform fee-bumps contributor-side escrow calls (including `claim`) and relays
  smart-wallet transactions, under an allow-list, a per-transaction cap, per-user daily caps and a balance floor.

**Reward assets:**

- XLM, USDC and any Stellar asset an admin adds, moved through that asset's Stellar Asset Contract. Every amount
  carries its asset, and totals are never added across assets: filters, analytics and exports are per-asset.
- Trustline checks before funding, before assignment and before every payout — including every leg of a batch,
  which is checked before the batch is signed. In-product guidance, a one-signature "Add trustline" action with
  the network fee on the platform, and a link to Circle's Testnet faucet.

**Reputation:**

- On-chain completion attestations in a dedicated registry contract (`CBXJVFUQ…Z33N`), written by the platform
  attester only after a payout is verified on-chain. One attestation per completed (bounty, contributor), so a
  batch payout produces several and a part-paid position produces none. Backfill and reconciliation jobs keep the
  database and the chain in step.
- Verifiable contributor credentials: W3C VC 2.0 with `eddsa-jcs-2022` Data Integrity proofs, a `did:web` issuer
  at `/.well-known/did.json`, `did:pkh:stellar` subjects (classic and smart wallets), a Bitstring Status List for
  revocation, and a public verification page that also re-reads the attestation from the chain.

**Discovery:**

- Saved searches with alerts: save a marketplace search (text, filters and sort) and be told when a new bounty
  matches, instantly or as a daily or weekly digest, in-app and by email, with one-click unsubscribe. Matching
  reuses the marketplace's own query builder, so alerts and search results cannot drift apart.
- Skill-graph recommendations: a normalised-PMI co-occurrence graph built from real listings and profiles,
  blended with reward, deadline and funding status, always showing which skills matched. Rewards are compared
  only within an asset. Offline precision@k evaluation: `uv run python -m app.scripts.evaluate_recommendations`.

**Collaboration:**

- Threaded Q&A on bounties: public questions, one level of replies, requester answers marked and acceptable,
  pinning, upvote-ranked sorting, edit and delete, and reporting into the existing moderation queue with
  moderator hide/unhide and an audit trail.
- GitHub account linking proved with a public gist (no OAuth app required; OAuth is optional), storing the
  numeric account id so a rename cannot re-point the link.
- Pull request verification: existence, repository, author, state and merged-at, head SHA and combined checks,
  re-checked on a schedule, on demand and by webhook. Requesters can require a merged pull request before
  approving. See [github.md](github.md), including how that requirement interacts with the review clock.

**Mainnet readiness:**

- A startup guard that refuses to run on mainnet until every requirement is met: audited contract deployments,
  a multisig arbiter with a threshold of at least 2, real signing keys, HTTPS origins, sponsor caps, and test-only
  switches off. It reports every problem at once.
- Compliance features: user data export (built by a worker, delivered by a signed expiring link), account
  deletion after a cancellable grace period with anonymisation that keeps the financial and audit record,
  sanctions screening of wallet addresses at verification, before funding and before every payout, and versioned
  terms and privacy acceptance. See [compliance.md](compliance.md).
- Operability: a protected Prometheus `/metrics` endpoint, alert rules, a Grafana dashboard, backup and restore
  scripts, and twelve SRE runbooks in [runbooks/](runbooks/README.md).

## Next

| Theme | Items |
| --- | --- |
| Mainnet | An independent contract audit — the remaining gate. `deploy/audited-deployments.json` holds no mainnet entry, so the guard refuses every contract id until a real audit report is recorded |
| Compliance | KYC/AML decisions, name (not just address) screening, geographic controls, and tax reporting (DAC7 / 1099-DA) |
| Wallets | A recovery path for passkey wallets that does not make BountyFlow custodial |
| Payments | Sponsoring a trustline's reserve, so a contributor holding no XLM can add one |
| Escrow | An on-chain pause or freeze for emergencies (the contract is permissionless by design today) |

## Honest limitations today

- A payout requires the requester's signature, so the contract cannot force a release. The review-timeout claim
  covers this only when the contributor recorded their submission on-chain; work submitted only in BountyFlow has
  no on-chain clock.
- The contract admin can replace the contract code. Keep that key offline, and use a multisig account on mainnet.
- A trustline's 0.5 XLM reserve must come from the contributor's own account; BountyFlow pays only the network
  fee.
- A lost, unsynced passkey is an unrecoverable wallet. BountyFlow deliberately holds no recovery key, because
  holding one would make it custodial.
- Sanctions screening matches addresses against a configured list. It does not screen names, and it is only as
  current as its source.
- Profiles and skills are self-reported and are **not** blockchain-verified. Only wallet ownership, completed
  work (through attestations) and linked GitHub accounts are cryptographically or externally proven.
