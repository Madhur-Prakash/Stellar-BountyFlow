<div align="center">

# Documentation

**Every document in this repository, indexed by what you are trying to do.**

[Readme](../README.md) · [Quick start](../README.md#quick-start) · [Architecture](architecture.md) · [API](api.md) · [Security](security.md) · [Runbooks](runbooks/README.md) · [Contributing](../CONTRIBUTING.md)

</div>

---

## Start here

| You want to | Read |
|---|---|
| Run it locally for the first time | [development.md](development.md), then [Quick start](../README.md#quick-start) |
| Understand how the pieces fit | [architecture.md](architecture.md) |
| Call the API | [api.md](api.md) |
| Know what it refuses to do | [security.md](security.md) |
| Change something and get it merged | [../CONTRIBUTING.md](../CONTRIBUTING.md) |

---

## The system

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | System overview, request lifecycle, module layout, the funding and payout sequences, and the decisions behind them |
| [api.md](api.md) | The REST contract under `/api/v1`: conventions, enums, shared shapes, every endpoint |
| [database.md](database.md) | Entity relationships, tables, concurrency, search, and the seed data |
| [kafka-events.md](kafka-events.md) | Topics, the event envelope, reliability, running without Kafka, periodic jobs |
| [design.md](design.md) | The design system: tokens, typography, motion, and what the interface refuses to do |

## Stellar and the contracts

| Document | What it covers |
|---|---|
| [blockchain.md](blockchain.md) | Networks, wallet ownership proof, the transaction lifecycle, and the real-network test |
| [smart-contracts.md](smart-contracts.md) | Testnet deployment, the escrow model, trust assumptions, how the backend calls the contract |
| [../contracts/README.md](../contracts/README.md) | The full contract interface, state machine, storage, events, error codes, build and deploy |
| [credentials.md](credentials.md) | Verifiable credentials: format, issuer DID, revocation, and how to verify one |

## Product surface

| Document | What it covers |
|---|---|
| [discovery.md](discovery.md) | Saved-search matching, the skill graph, ranking, and the offline evaluation |
| [github.md](github.md) | GitHub account proof, pull request verification, and how it interacts with the review clock |
| [user-onboarding.md](user-onboarding.md) | The onboarding form, the response workbook, and how form answers become the next phase |
| [product-roadmap.md](product-roadmap.md) | What has shipped, what is next, and the limitations as they stand today |

## Running it

| Document | What it covers |
|---|---|
| [development.md](development.md) | Prerequisites, first run, backend and frontend conventions, troubleshooting |
| [testing.md](testing.md) | The suites, isolation, Playwright scenarios, CI, and regenerating the screenshots |
| [deployment.md](deployment.md) | Images, the production checklist, mainnet, scaling |
| [runbooks/README.md](runbooks/README.md) | Twelve SRE runbooks: incidents, outages, backups, key rotation, contract upgrade, mainnet launch |
| [../backend/README.md](../backend/README.md) | The backend package on its own terms |

## Trust, law and risk

| Document | What it covers |
|---|---|
| [security.md](security.md) | Threat model, sessions, CSRF, RBAC, transaction verification, review findings |
| [compliance.md](compliance.md) | Custody posture, regulatory considerations, data protection, sanctions screening, the before-mainnet list |
| [../SECURITY.md](../SECURITY.md) | How to report a vulnerability |

---

<div align="center">

A document that describes last month's behaviour is worse than no document.
If you change behaviour, change the document in the same commit.

</div>
