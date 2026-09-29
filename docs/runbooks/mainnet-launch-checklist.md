# Mainnet launch checklist

The gate before BountyFlow touches real money. The configuration half of this page mirrors
`backend/app/core/mainnet.py` exactly: the API, the worker and every script call `mainnet_problems()` while
validating settings and refuse to start with the complete list printed, so an operator can fix everything in one
pass.

The configuration gate is machine-checked. The rest of this page is not, and that is the part that actually
decides whether launching is a good idea.

```bash
# The fastest way to see where you stand: set the mainnet values and start the API. It prints every problem.
cd backend && uv run python -m app.serve
# Refusing to start on Stellar mainnet. Fix the following:
#   - ALLOW_MAINNET must be set to true (an explicit opt-in to real funds)
#   - …
```

---

## Owner: platform engineering — configuration

Every line here is enforced by `mainnet_problems()`. The API will not start until all of them pass.

### Network and environment

- [ ] `ALLOW_MAINNET=true` — the explicit opt-in to real funds.
- [ ] `STELLAR_NETWORK=mainnet` **and** `BLOCKCHAIN_MODE=mainnet`. Both, or it is refused.
- [ ] `STELLAR_NETWORK_PASSPHRASE=Public Global Stellar Network ; September 2015`
- [ ] `APP_ENV=production`

### Endpoints and transport

- [ ] `FRONTEND_URL` is an `https://` URL.
- [ ] `PUBLIC_API_URL` is set to the API's own `https://` URL.
- [ ] `CORS_ORIGINS` lists `https://` origins only. `*` is refused in every environment because credentials are
      enabled.
- [ ] `STELLAR_HORIZON_URL` is a mainnet `https://` endpoint and does not contain `testnet`.
- [ ] `STELLAR_SOROBAN_RPC_URL` is a mainnet `https://` endpoint and does not contain `testnet`.
- [ ] `STELLAR_EXPLORER_BASE_URL` is a mainnet `https://` endpoint and does not contain `testnet`.
- [ ] `COOKIE_SECURE=true`.

### Contracts: audited deployments

Three contracts are part of the deployed surface. Each one that is configured must be listed for `mainnet` in
`deploy/audited-deployments.json` **with its audit report**. An entry without an `audit.report_url` does not
count — an id alone is not evidence of a review.

- [ ] `SOROBAN_CONTRACT_ID` is set and listed. Required; the escrow.
- [ ] `WEB_AUTH_CONTRACT_ID` is listed, if smart-wallet sign-in (SEP-45) is configured.
- [ ] `ATTESTATION_CONTRACT_ID` is listed, if attestations are configured.
- [ ] `AUDITED_DEPLOYMENTS_FILE` resolves and is valid JSON with a `mainnet` list.

Each entry looks like this (the shape is described in the file's own `_readme`):

```json
{
  "contract": "bounty_escrow v2",
  "contract_id": "C…",
  "wasm_hash": "…",
  "deployed_at": "2026-…",
  "deploy_tx": "…",
  "audit": {
    "firm": "…",
    "report_url": "https://…",
    "report_sha256": "…",
    "completed_at": "2026-…",
    "commit": "…"
  }
}
```

The `testnet` list in that file is a record only — the guard never consults it, and its entries carry
`"audit": null`. Only the `mainnet` list gates startup.

Escrows created on an older escrow contract keep serving on it (`bounty_escrows.contract_id`). The guard checks
the configured id for **new** escrows and leaves per-escrow ids alone — see
[contract-upgrade.md](contract-upgrade.md).

### Arbiters

- [ ] `STELLAR_ARBITER_THRESHOLD >= 2`. A single key must never decide a dispute.
- [ ] `STELLAR_ARBITER_ADDRESSES` lists at least `STELLAR_ARBITER_THRESHOLD` **distinct** signers.
- [ ] The keys were generated in the ceremony in [secret-rotation.md](secret-rotation.md), on separate machines,
      by separate holders, with only public keys recorded.
- [ ] A 2-of-N dispute vote was rehearsed on Testnet with the real holders and their real devices.

### Secrets

All five must hold a real value. The three Stellar seeds must be 56 characters starting with `S`; the others
must be at least 32 characters. None may contain `change-me`, `changeme`, `replace`, `dev-only`, `example` or
`insecure`.

- [ ] `JWT_SECRET` — session tokens and data-export download links.
- [ ] `WALLET_CHALLENGE_SIGNING_SECRET` — wallet ownership challenges (a Stellar seed that never holds funds).
- [ ] `STELLAR_SPONSOR_SECRET` — sponsored network fees.
- [ ] `STELLAR_ATTESTER_SECRET` — on-chain completion attestations.
- [ ] `CREDENTIAL_ISSUER_SECRET` — verifiable credentials.
- [ ] `METRICS_TOKEN` — at least 24 random characters.
- [ ] `DATABASE_URL` does not carry a development password (`bountyflow-local-dev-password`, or `:bountyflow@`).

### Fee sponsorship caps

The sponsor spends real XLM, so the caps must be deliberate rather than the development defaults.

- [ ] `SPONSOR_DAILY_TX_LIMIT > 0` and `SPONSOR_DAILY_FEE_LIMIT_STROOPS > 0`. To switch sponsorship off, leave
      `STELLAR_SPONSOR_SECRET` empty instead of zeroing the caps.
- [ ] `SPONSOR_MIN_BALANCE_XLM > 0` — the floor at which sponsoring stops.
- [ ] `SPONSOR_LOW_BALANCE_XLM > SPONSOR_MIN_BALANCE_XLM` — so it warns before it stops.

### Operations that must not run against real accounts

- [ ] `SEED_ON_STARTUP=false`.
- [ ] `GITHUB_FIXTURE_TRANSPORT=false` — it serves recorded GitHub responses.
- [ ] `DISCOVERY_DIGEST_TRIGGER_ENABLED=false` — it sends digests on demand.
- [ ] `ESCROW_MIN_REVIEW_WINDOW_SECONDS >= 86400` (one day).
- [ ] `SANCTIONS_SCREENING_ENABLED=true`.
- [ ] `SANCTIONS_LIST_PATH` or `SANCTIONS_LIST_URL` points at a real sanctions list.

> `.env.example` does not currently document `ALLOW_MAINNET`, `PUBLIC_API_URL`, `AUDITED_DEPLOYMENTS_FILE`,
> `METRICS_TOKEN` or the `SANCTIONS_*` settings. They exist in `app/core/config.py` and are enforced here.
> Add them to `.env.example` before launch so nobody has to read the source to find them.

---

## Owner: security and contracts

- [ ] The escrow contract audit is **complete**, the report is final, and the deployed wasm hash matches the
      audited build. Record the report URL and its sha256 in `deploy/audited-deployments.json`.
- [ ] The audit covers the SEC-05, SEC-06 and SEC-12 fixes listed in [`docs/security.md`](../security.md).
      Those were fixed in the contract source and need a redeploy to take effect.
- [ ] The SEP-45 web-auth contract and the attestation registry are audited too, if they are configured.
- [ ] The escrow contract **admin key** is in a hardware wallet or a multisig account with a quorum of at least
      2. Holders, custody and recovery are recorded in [secret-rotation.md](secret-rotation.md).
- [ ] An `upgrade` has been rehearsed end to end on Testnet with the real key holders
      ([contract-upgrade.md](contract-upgrade.md)).
- [ ] Nobody can sign an upgrade alone, and it is written down who can.
- [ ] `/api/docs` and `/api/openapi.json` are disabled or behind staff authentication (a recommendation in
      `docs/security.md`, not enforced by the guard).
- [ ] `TRUSTED_PROXY_HOPS` matches the real proxy topology, so client-supplied `X-Forwarded-For` cannot be
      trusted for rate limits.
- [ ] TLS and HSTS are in front of nginx or the API.
- [ ] `pip-audit` and `cargo audit` pass on the release commit.

## Owner: treasury and finance

- [ ] The fee sponsor account is funded on mainnet, well above `SPONSOR_LOW_BALANCE_XLM`, from treasury.
- [ ] `SPONSOR_MAX_FEE_STROOPS`, `SPONSOR_DAILY_TX_LIMIT`, `SPONSOR_DAILY_FEE_LIMIT_STROOPS`,
      `SPONSOR_LOW_BALANCE_XLM` and `SPONSOR_MIN_BALANCE_XLM` have each been **reviewed for real-money volumes**,
      not copied from `.env.example`. Write down the expected daily spend at the launch volume and check the
      caps allow it with headroom.
- [ ] Someone owns topping the sponsor account up, and `BountyFlowSponsorBalanceLow` reaches them.
- [ ] `SPONSOR_ALLOWED_ASSETS` and `SPONSOR_ALLOWED_CONTRACTS` list only what should be sponsored on mainnet.
- [ ] The arbiter accounts are funded with the minimum reserve so they can sign.

## Owner: data and infrastructure

- [ ] **Fresh databases.** Testnet data is never migrated to mainnet. Start from an empty database and
      `alembic upgrade head`.
- [ ] Managed PostgreSQL with backups, managed Redis, and Kafka with replication factor at least 3.
- [ ] `scripts/backup-db.sh` (or the managed equivalent) runs on a schedule, writes offsite, and prunes.
- [ ] WAL archiving or the managed PITR equivalent is on, with a known retention window.
- [ ] A **restore has been tested**, not just configured: one full pass of [restore-drill.md](restore-drill.md),
      with the measured RTO and RPO recorded.
- [ ] `RUN_MIGRATIONS_ON_STARTUP` is set deliberately; the release procedure in
      [deploy-rollback.md](deploy-rollback.md) is agreed.
- [ ] `LOG_JSON=true` and stdout ships to the log platform.
- [ ] Load-balancer liveness points at `/health/live` and readiness at `/health/ready`.
- [ ] Images are tagged by commit sha, and the currently deployed sha is recorded somewhere readable during an
      incident.

## Owner: on-call and observability

- [ ] Prometheus scrapes `/metrics` with `METRICS_TOKEN` and the target is `UP`
      ([`deploy/prometheus/prometheus.yml`](../../deploy/prometheus/prometheus.yml)).
- [ ] [`deploy/prometheus/alerts.yml`](../../deploy/prometheus/alerts.yml) is loaded and
      `promtool check rules` passes.
- [ ] **Alerting is wired to a real pager.** `severity: page` reaches a human at 03:00; this has been tested
      with a deliberate test alert.
- [ ] The Grafana dashboard is provisioned and its panels have data.
- [ ] The "who to page" table in [README.md](README.md) is filled in, with no blanks.
- [ ] The on-call rota exists, and everyone on it has every item in the access table in
      [on-call.md](on-call.md).
- [ ] A **rollback has been rehearsed** on staging: deploy, then roll back to the previous sha, and confirm the
      gates in [deploy-rollback.md](deploy-rollback.md).
- [ ] The log alerts from `docs/security.md` are configured: `foreign_escrow_detected`, `escrow_id_rotated`,
      `confirmed_transaction_on_foreign_escrow`, `payout_not_reflected_on_chain`, `outbox_event_dead_lettered`,
      `rate_limit_unavailable`, `refresh_token_reuse_detected`.

## Owner: compliance and legal

- [ ] The compliance review ([../compliance.md](../compliance.md)) is **signed off**, with the reviewer and the
      date recorded. Its own "before mainnet" list has the items that are not enforceable in configuration —
      the legal opinion per market, the KYC decision, the DPIA and the retention schedule.

- [ ] The sanctions list source is real, reachable, and refreshing: `bountyflow_sanctions_list_configured` is 1,
      `bountyflow_sanctions_list_error` is 0, and `bountyflow_sanctions_list_age_seconds` is under
      `SANCTIONS_LIST_REFRESH_SECONDS`.
- [ ] Terms and privacy **versions are published** and recorded in `legal_document_versions`, and acceptance is
      being written to `legal_acceptances`.
- [ ] The data export flow works end to end on the mainnet deployment: request, build, download,
      and the link expires after `DATA_EXPORT_TTL_HOURS`.
- [ ] The account deletion flow works, and `ACCOUNT_DELETION_GRACE_DAYS` matches what the privacy policy says.
- [ ] Someone owns `BountyFlowDataExportsFailing` and `BountyFlowAccountDeletionsOverdue`. Both have a
      regulatory clock.
- [ ] Support has wording for a blocked wallet. The user-facing message never says why; the reason is staff-only.

## Owner: product

- [ ] The launch volume is understood well enough to sanity-check the sponsor caps and the rate limits.
- [ ] Support knows what "funds stuck in escrow" means and that it is a SEV1 they escalate immediately.
- [ ] Users are told, in the product, that escrow is on-chain, that a dispute needs an arbiter quorum, and that
      a claim becomes possible after the review window.
- [ ] A rollback that ends in user-visible data loss has an agreed comms plan
      ([incident-response.md](incident-response.md)).

---

## Final gate

Do not launch with any box unticked. If one is going to be waived, write down who waived it, why, and when it
will be closed — in the launch record, not in a chat message.

```bash
# Last check, with the real mainnet .env in place. Silence means every configuration gate passed.
cd backend && uv run python -c "
from app.core.config import get_settings
from app.core.mainnet import format_problems, mainnet_problems
p = mainnet_problems(get_settings())
print(format_problems(p) if p else 'mainnet configuration gate: pass')
"
```

Then, on the deployed stack:

```bash
curl -s https://<api host>/health/ready | jq
curl -s https://<api host>/api/v1/config/public | jq '{network, network_passphrase, blockchain_mode, contract_id}'
curl -s -H "Authorization: Bearer $METRICS_TOKEN" https://<api host>/metrics | grep bountyflow_build_info
```

`network_passphrase` must read `Public Global Stellar Network ; September 2015` and `blockchain_mode` must read
`mainnet`. If either does not, stop.
