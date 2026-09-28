# Architecture

BountyFlow is a **modular monolith** with dedicated background workers. A single FastAPI service owns the HTTP API
and domain logic. A worker process runs Kafka consumers, the outbox relay and scheduled jobs. PostgreSQL is the
source of truth. Stellar Soroban holds the funds.

## System overview

```mermaid
flowchart LR
  subgraph Browser
    UI[React SPA<br/>Vite · TanStack Query]
    W[Freighter wallet]
  end
  subgraph Edge
    NGINX[nginx<br/>static + /api proxy]
  end
  subgraph Backend
    API[FastAPI API<br/>modules: auth · users · bounties · applications ·<br/>submissions · payments · disputes · notifications ·<br/>analytics · admin · dashboard]
    WK[Worker<br/>outbox relay · Kafka consumers · periodic jobs]
  end
  PG[(PostgreSQL<br/>source of truth)]
  RD[(Redis<br/>cache · rate limits · challenges · locks)]
  KF[(Kafka<br/>domain events + DLQs)]
  MP[Mailpit / SMTP]
  RPC[Soroban RPC<br/>Stellar Testnet]
  SC[[BountyEscrow<br/>Soroban contract]]
  SAC[[Native XLM<br/>Stellar Asset Contract]]

  UI -- HTTPS cookies + CSRF --> NGINX --> API
  UI <-- sign XDR --> W
  API --> PG
  API --> RD
  API -- simulate / submit / read --> RPC
  RPC --- SC --- SAC
  API -- outbox rows in same TX --> PG
  WK -- relay unpublished outbox --> KF
  KF --> WK
  WK --> PG
  WK --> MP
  WK -- verify transactions --> RPC
```

## Request lifecycle

1. `RequestContextMiddleware` assigns `X-Request-ID` and a correlation ID and binds them to the logging context
   (Logifyx structured logs). `BodySizeLimitMiddleware` rejects oversized bodies. CORS uses an allowlist.
   `SecurityHeadersMiddleware` adds CSP, `nosniff` and related headers. `CSRFMiddleware` enforces the
   double-submit token on every mutating `/api/v1` route.
2. Dependencies resolve the user from the `bf_access` JWT cookie and check that the session row is still valid.
   RBAC guards (`require_permission`, see [security.md](security.md)) run next.
3. A router calls a **service** that validates the domain rules. The service locks rows in a fixed order (bounty
   first), mutates state through the **state machine**, writes an **audit log** entry and stages **outbox events**,
   then commits once.
4. After commit, caches are invalidated. The public marketplace uses a generation counter, so a single `INCR`
   invalidates every cached query.

## Module layout (backend)

| Layer | Location | Responsibility |
|---|---|---|
| HTTP | `app/modules/*/router.py`, `app/api/*` | Validation, auth, typed responses |
| Domain | `app/modules/*/service.py`, `bounties/state_machine.py` | Business rules, transitions, events |
| Data | `app/modules/*/models.py`, `repository.py`, `migrations/` | SQLAlchemy 2.1 models, queries, Alembic |
| Chain | `app/blockchain/*` | Network config, SEP-10 wallet proof, adapters, verification, reconciliation |
| Messaging | `app/messaging/*`, `worker/*` | Event envelope, schemas, outbox, consumers, DLQ |
| Cross-cutting | `app/core/*`, `app/cache/*` | Config, security, RBAC, logging, rate limits, cache keys |

## Bounty lifecycle

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> OPEN: publish (email verified)
  DRAFT --> CANCELLED
  OPEN --> FUNDING_PENDING: funding tx submitted
  FUNDING_PENDING --> FUNDED: tx verified + escrow fully funded
  FUNDING_PENDING --> OPEN: tx failed / expired / partial
  OPEN --> CANCELLED
  OPEN --> EXPIRED: deadline passed
  FUNDED --> IN_PROGRESS: contributor accepted
  IN_PROGRESS --> UNDER_REVIEW: submission received
  UNDER_REVIEW --> IN_PROGRESS: revision requested
  UNDER_REVIEW --> COMPLETED: approved + payout verified on-chain
  UNDER_REVIEW --> FUNDED: paid, positions remain
  IN_PROGRESS --> DISPUTED
  UNDER_REVIEW --> DISPUTED
  DISPUTED --> IN_PROGRESS: resolved
  DISPUTED --> UNDER_REVIEW: resolved
  DISPUTED --> COMPLETED: arbiter paid last position
  FUNDED --> CANCEL_REQUESTED
  IN_PROGRESS --> CANCEL_REQUESTED
  EXPIRED --> CANCEL_REQUESTED
  CANCEL_REQUESTED --> CANCELLED: refund verified on-chain
  COMPLETED --> [*]
  CANCELLED --> [*]
```

All transitions are defined centrally in `app/modules/bounties/state_machine.py`. Clients never set a status
directly. `FUNDED`, `IN_PROGRESS` and `UNDER_REVIEW` are *derived* from live work
(`recompute_operational_status`). An approved-but-unpaid submission keeps the bounty `UNDER_REVIEW` until the
payout is verified.

## Funding and payout sequence

```mermaid
sequenceDiagram
  autonumber
  participant U as Requester (browser)
  participant F as Freighter
  participant A as API
  participant R as Soroban RPC
  participant C as BountyEscrow
  participant K as Worker

  U->>A: POST /bounties/{id}/funding/prepare {wallet}
  A->>A: validate owner, status, verified wallet
  A->>R: load account, simulate create_escrow(...)
  R-->>A: footprint + auth + resource fee
  A-->>U: PreparedTransaction (unsigned XDR, tx row SIGNATURE_REQUIRED)
  U->>F: signTransaction(xdr, passphrase)
  F-->>U: signed XDR
  U->>A: POST /transactions/{txId}/submit {signed_xdr}
  A->>A: verify hash == prepared, source == wallet, signature valid
  A->>R: sendTransaction
  A-->>U: tx SUBMITTED (bounty FUNDING_PENDING)
  A->>K: outbox TX_SUBMITTED (via Kafka)
  loop until confirmed or expired
    K->>R: getTransaction(hash)
  end
  R-->>K: SUCCESS (ledger N)
  K->>R: simulate get_escrow(bounty_id)
  R-->>K: on-chain Escrow state
  K->>A: reconcile DB escrow, bounty → FUNDED, events
  U->>A: GET /transactions/{txId} (poll)
  A-->>U: CONFIRMED + explorer link
```

Payouts, refunds, assignment locks and dispute resolutions use the same pipeline with a different contract
function (`release`, `refund`, `assign`, `resolve_dispute`, …). A payout is marked `CONFIRMED` only after
`assignment(bounty_id, contributor)` reads back as `Paid` from the contract.

## Event processing

```mermaid
flowchart LR
  S[Service transaction] -->|INSERT outbox_events| DB[(PostgreSQL)]
  DB --> RL[Outbox relay<br/>SKIP LOCKED batches]
  RL -->|acks=all, idempotent producer| T[(Kafka topics)]
  T --> N[notification-worker]
  T --> E[email-worker]
  T --> AN[analytics-worker]
  T --> BV[blockchain-verifier]
  N & E & AN & BV -->|INSERT processed_events<br/>+ effects in one TX| DB
  N & E & AN & BV -. permanent / exhausted .-> DLQ[(topic.dlq)]
```

See [kafka-events.md](kafka-events.md) for topics, envelopes and reliability guarantees.

## Key decisions

| Decision | Rationale |
|---|---|
| Modular monolith + worker | Clear domain boundaries without distributed-transaction complexity. |
| Transactional outbox | State and its events commit atomically; Kafka outages delay events but never lose them. |
| Backend builds, wallet signs | The server enforces domain rules and simulates contract calls. The wallet signs the exact prepared transaction, and the server checks the hash before submitting. Private keys never touch BountyFlow. |
| Verify from chain state | Funding and payouts are recorded from contract reads after confirmation, never from client claims. |
| Cookie auth + CSRF | HttpOnly tokens are not readable by XSS. Double-submit CSRF protects every mutation. |
| Redis only for ephemeral state | Caches, rate limits, challenges and locks. Losing Redis never corrupts financial data. |
| Real network only | The application has no simulated chain. Automated tests inject a test double that still exercises real XDR and signature verification; Playwright runs on Stellar Testnet. |
