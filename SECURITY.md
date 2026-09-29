# Security policy

BountyFlow moves money through a Soroban escrow contract, so reports about it are taken seriously. This page
explains how to report a vulnerability privately, what is in scope, and how the platform is protected.

BountyFlow is built and maintained by one person, not a team or a company. Reports are read and acted on, but
there is no on-call rota behind them — the timings below are intentions, not a service level.

## Supported versions

| Version | Supported |
|---|---|
| Latest commit on `main` | Yes |
| Older commits and forks | No |
| Current Testnet escrow contract `CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY` | Yes |
| Superseded contract deployments (listed under `superseded_deployments` in [`contracts/deployments/testnet.json`](contracts/deployments/testnet.json)) | No |

Fixes land on `main`. Please check that an issue still reproduces there before you report it.

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Fill in the form. This creates a private security advisory that only you and the maintainers can see.

If you cannot use private reporting, open a public issue that only asks a maintainer to get in touch. Leave out
every detail of the vulnerability.

### What to include

- The affected component: backend API or worker, frontend, escrow contract, or infrastructure configuration.
- The file, route, contract function or setting involved.
- The commit you tested and how you ran it (`make dev`, `make up`, or against Stellar Testnet).
- Step-by-step reproduction: requests, scripts, and Testnet transaction hashes if the chain is involved.
- The impact: what an attacker gains, and what they need first (anonymous, `USER`, `MODERATOR`, `ADMIN`, or the
  dispute arbiter key).
- A suggested fix, if you have one.

Never include real secret keys, seed phrases or other people's personal data. Use throwaway Testnet keypairs
funded by Friendbot.

### What to expect

- Acknowledgement usually within a few working days, sooner for anything that can move funds.
- You will be told whether the issue reproduces, kept updated while a fix is written, and consulted on
  disclosure timing before an advisory is published.
- If you would like credit, you will be named in the advisory.

This policy does not include a paid bug bounty or legal safe-harbour terms.

### Testing in good faith

- Test against your own local stack (`make dev` or `make up`), not against other people's accounts or data.
- On Stellar Testnet, use only your own keypairs, and do not interfere with escrows that belong to others.
- Do not run denial-of-service or load tests, send spam, or try social engineering.

## Scope

In scope:

- **Backend API and worker** (`backend/`): authentication, sessions, CSRF, RBAC and ownership checks, wallet
  ownership proofs, transaction preparation and verification, the outbox and Kafka consumers, email.
- **Frontend** (`frontend/`): cross-site scripting, unsafe rendering, the wallet signing flow, and anything that
  exposes secrets in the browser bundle.
- **Soroban escrow contract** (`contracts/bounty_escrow`) and its current Testnet deployment.
- **Infrastructure configuration in this repository**: `docker-compose.yml`, the Dockerfiles,
  `frontend/nginx.conf`, `infra/`, `scripts/` and `.github/workflows/`.

Out of scope:

- Third-party services and software: the Stellar network (Stellar Core, Horizon, Soroban RPC), Freighter,
  Friendbot and StellarExpert. Please report those to their maintainers.
- Social engineering, phishing and physical attacks.
- Volumetric denial of service.
- Attacks that need a compromised host, database or browser wallet (outside the
  [threat model](docs/security.md#threat-model)).
- Accepted risks and documented limitations in [docs/security.md](docs/security.md) (for example SEC-14 to SEC-19
  and the mainnet recommendations), unless you show a way to make them worse.
- Local development defaults in `.env.example`, such as `COOKIE_SECURE=false`, which the API already refuses in
  staging and production.

## Security model

A summary of the controls in the code. The full design, threat model and review findings are in
[docs/security.md](docs/security.md).

- **Passwords.** Argon2id (`t=3`, 64 MiB, `p=2`, 16-byte salt), hashed on a dedicated thread pool so logins do
  not stall the API. Login is timing-safe for unknown emails.
- **Sessions.** A 15-minute JWT access token (HMAC only, pinned algorithms) and an opaque refresh token, both in
  HttpOnly cookies. Only hashes of refresh tokens are stored. The refresh token rotates on every use, and
  presenting an old one revokes the session (reuse detection). Permissions come from the database role, not the
  token.
- **CSRF.** Double-submit cookie: every `POST`, `PUT`, `PATCH` and `DELETE` must send `X-CSRF-Token` matching the
  `bf_csrf` cookie, compared in constant time. A test enumerates every mutating route.
- **Authorization.** RBAC with `USER`, `MODERATOR` and `ADMIN` roles and one permission matrix
  (`backend/app/core/rbac.py`), plus ownership checks in services. Tests fail CI when a new route is not classified
  as public, authenticated or staff.
- **Rate limits.** Redis fixed-window limits on authentication, wallet, content-creation and chain endpoints. The
  client IP only trusts the configured number of proxy hops in `X-Forwarded-For`.
- **Wallet ownership.** A wallet is linked only after it signs a SEP-10 style challenge. The challenge is bound
  to the account and address, single use, never submitted, and fails closed without Redis. One verified account
  per address.
- **Non-custodial.** The platform never asks for, receives or stores users' secret keys or seed phrases. The
  server builds and simulates each transaction; the user signs it in Freighter. Before submitting, the server
  checks the envelope's hash, source account, signature and network against what it prepared.
- **Escrow.** Funds are held by the Soroban contract, which has no admin key, no upgrade path and no function that
  sends funds to an arbitrary address. The dispute arbiter can act only on disputed escrows. Arithmetic is
  checked and each address is paid at most once per escrow. The backend trusts an on-chain escrow only if its
  terms match the escrow BountyFlow prepared.
- **Input handling.** Pydantic validation on every body and query, a 1 MiB body limit, money as decimal strings,
  http/https-only URL fields, ORM bound parameters, and markdown that is never rendered to HTML on the server.
- **Headers and CORS.** `nosniff`, `X-Frame-Options: DENY`, a restrictive API Content Security Policy, HSTS when
  secure cookies are on, and an explicit CORS allowlist (`*` is refused at startup).
- **Logging.** Structured logs through Logifyx. Sensitive field names (passwords, tokens, cookies, secrets,
  signed XDR, …) are replaced with `[REDACTED]` before any handler sees them, and email bodies are never logged.
- **Production configuration.** In staging and production the API refuses to start with a weak or placeholder
  `JWT_SECRET`, `COOKIE_SECURE=false`, or a missing `SOROBAN_CONTRACT_ID` or `WALLET_CHALLENGE_SIGNING_SECRET`.

## Stellar Testnet

The deployment runs on **Stellar Testnet** (`BLOCKCHAIN_MODE=testnet`, the default). Testnet XLM has no monetary
value. Do not use mainnet keys or real funds with it. Mainnet is reserved for a separate deployment, and
[docs/security.md](docs/security.md#known-limitations-and-recommendations-for-mainnet) lists what has to happen
first, including an independent audit of the escrow contract.

## Handling secrets

- **Never commit `.env` files.** `.gitignore` excludes `.env` and `.env.*`, except the two templates.
- Start from the templates: [`.env.example`](.env.example) for the backend and Docker Compose, and
  [`frontend/.env.example`](frontend/.env.example) for the frontend. `make env` (also run by `make install`)
  creates `.env` with a fresh `JWT_SECRET` and never overwrites an existing file.
- Values marked `REPLACE` in `.env.example` are placeholders. The API rejects them in production.
- Every `VITE_` variable is embedded in the browser bundle and is public. Never put a secret in one.
- Stellar deployer and arbiter secret keys stay in the local Stellar CLI key store. The deploy scripts write only
  public data to `contracts/deployments/testnet.json`.
- If a secret is ever committed, rotate it straight away. Removing it from the history is not enough.
