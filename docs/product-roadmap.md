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

## Next

| Theme | Items |
|---|---|
| Wallets | Stellar Wallets Kit (xBull, Albedo, Lobstr, Hana), passkey smart wallets |
| Assets | USDC and other SAC tokens; trustline checks and guidance |
| Escrow | Milestone-based releases; automatic release after a review timeout (requires a contract upgrade); multisig arbiter |
| Reputation | On-chain completion attestations; verifiable contributor credentials |
| Discovery | Saved searches with alerts; skill-graph recommendations |
| Collaboration | Threaded Q&A on bounties; GitHub PR linking and auto-verification |
| Payments | Batch payouts; fee sponsorship (fee-bump transactions) for contributors |
| Mainnet | Contract audit, multisig arbiter, compliance review, production SRE runbooks |

## Honest limitations today

- A payout requires the requester's signature, so the contract cannot force a release. Disputes and the arbiter
  cover this only when the escrow is frozen on-chain.
- A single arbiter key on Testnet.
- Native XLM only.
- Profiles and skills are self-reported and are **not** blockchain-verified. Only wallet ownership is
  cryptographically proven.
