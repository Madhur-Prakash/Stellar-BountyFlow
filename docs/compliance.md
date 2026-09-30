# Compliance review

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Security](security.md) &middot; [Onboarding](user-onboarding.md) &middot; [Roadmap](product-roadmap.md)
<!-- nav -->

This is an honest review of BountyFlow's compliance posture, written for whoever operates BountyFlow and for
the lawyers it is taken to. BountyFlow is maintained by one person, so every control described here is one that
a single operator can actually run. It records what the product does today on Stellar **Testnet**, what changes when real money moves, and
what must be true before a mainnet launch.

**This is not legal advice.** Everything under "considerations" is a question to take to counsel in each
market, not a conclusion. BountyFlow has not been through a regulatory assessment, and nothing here should be
read as one.

- [Custody posture](#custody-posture)
- [What we hold](#what-we-hold)
- [KYC, AML and money transmission](#kyc-aml-and-money-transmission)
- [Sanctions screening](#sanctions-screening)
- [Data protection](#data-protection)
- [Tax reporting](#tax-reporting)
- [Terms and privacy versioning](#terms-and-privacy-versioning)
- [Records retention](#records-retention)
- [Consumer-protection risks we accept and disclose](#consumer-protection-risks-we-accept-and-disclose)
- [Before mainnet](#before-mainnet)

## Custody posture

**BountyFlow is non-custodial.** It never holds, controls or can move user funds.

| Fact | Where it is enforced |
|---|---|
| The server holds no user private key, and cannot sign for a user | The browser wallet signs; `app/blockchain/transactions.py` only builds and submits |
| Funds sit in the escrow contract, not in a platform account | `contracts/bounty_escrow`; the platform is not a party to the escrow |
| The server cannot release funds | `release` / `refund` require the requester's signature; the contract enforces it |
| The arbiter cannot take funds | `resolve_dispute` can only pay the assigned contributor or release their claim — never an arbitrary address |
| There is no admin withdrawal path | No entrypoint transfers escrowed funds to an address the caller chooses |
| Amounts and destinations are derived server-side and verified on-chain | `payments/service.py` (prepare → sign → submit → verify) |

Three qualifications, stated plainly because they are the places the "non-custodial" label is doing work:

1. **The escrow contract's admin key can replace the contract's code** (escrow v2 has `upgrade`). That key
   cannot move funds directly, but new code could. It is therefore a custody-adjacent power and must be held
   in a hardware wallet or a multisig Stellar account, with the ceremony in
   [docs/runbooks/secret-rotation.md](runbooks/secret-rotation.md).
2. **The arbiter key set decides disputed escrows.** On mainnet it is M-of-N with a threshold of at least 2
   (the configuration guard refuses anything less). Its power is bounded by the contract, but it is real.
3. **The platform pays network fees** for some contributor actions (see [fee sponsorship](#fee-sponsorship)).
   That is a payment *by* the platform, not custody of a user's money, but it is a flow of platform funds and
   is capped and audited as such.

## What we hold

The data inventory, because every later section depends on it. "Personal data" is used in the GDPR sense.

| Category | Tables | Contains | Source |
|---|---|---|---|
| Identity | `users`, `user_sessions`, `email_verification_tokens`, `password_reset_tokens` | Email, display name, username, password hash, IP and user agent per session | The user |
| Profile | `users`, `user_skills` | Bio, links, skills, interests, avatar URL | The user |
| Wallet links | `wallets`, `passkey_wallets` | Stellar addresses (`G…`), smart-wallet contract addresses (`C…`), WebAuthn credential ids | The user, proven by signature |
| Third-party identity | `github_accounts`, `submission_pull_requests` | GitHub login, numeric id, avatar, PR metadata and verification snapshots | GitHub's public API |
| Marketplace content | `bounties`, `bounty_milestones`, `bounty_applications`, `bounty_submissions`, `submission_revisions`, `bounty_qa_posts` | Free text written by users | The user |
| Financial | `bounty_escrows`, `blockchain_transactions`, `payment_records`, `sponsored_transactions` | Amounts, addresses, transaction hashes, ledger sequences | The chain, verified |
| Reputation | `completion_attestations`, `verifiable_credentials` | Addresses, amounts, completion facts, signed credential documents | Derived from verified payouts |
| Disputes | `disputes`, `dispute_evidence`, `dispute_votes` | Free text, evidence URLs, arbiter decisions | The parties and moderators |
| Communications | `notifications`, `email_deliveries`, `notification_preferences` | Titles, messages, recipient addresses | Generated |
| Discovery | `saved_searches`, `saved_search_matches` | Search filters, alert settings | The user |
| Governance | `audit_logs`, `outbox_events`, `legal_acceptances`, `screening_entries` | Who did what and when | Generated |

**On-chain data is different in kind.** Addresses, amounts, transaction hashes and attestations on Stellar are
public, permanent and outside anyone's control, including ours. No erasure right can reach them. We say this in
the privacy notice and in the export archive itself, rather than implying a deletion we cannot perform.

## KYC, AML and money transmission

BountyFlow performs **no KYC today**. Accounts need a verified email; wallets are proven by signature. There is
no identity verification, no source-of-funds check and no transaction monitoring beyond sanctions screening.

That is defensible for a non-custodial Testnet product and is the first thing to revisit for mainnet.

### Considerations to take to counsel

These are questions, not positions.

**United States.** The pivotal question is whether BountyFlow is a money transmitter under the BSA. FinCEN's
2019 guidance on convertible virtual currency treats a person who only provides software, and never accepts and
transmits value, as not a money transmitter (the "anonymizing software provider" and multisig-provider
discussions are the closest analogies). Our position would be that the escrow contract, not BountyFlow, holds
and moves value, and that we never have total independent control. Points to test with counsel:

- does the arbiter's bounded power over a *disputed* escrow amount to control?
- does the contract admin key's `upgrade` power amount to control?
- does paying network fees for users change the analysis?
- state-level money transmitter licensing, which does not always follow FinCEN, and New York's BitLicense in
  particular.

**European Union.** MiCA regulates crypto-asset service providers. Whether a non-custodial escrow front end is
"providing custody and administration" or "operating a trading platform" is the question; the exclusion for
fully decentralised services without an intermediary is narrow, and we are not obviously inside it. The
transfer-of-funds regulation (the "travel rule", Regulation 2023/1113) applies to CASPs, so the answer above
decides whether it applies to us. AMLD5/6 obligations follow the same classification.

**United Kingdom.** The FCA's cryptoasset registration regime, and whether the escrow flow is a regulated
activity or a technology service.

**Elsewhere.** Singapore (PSA), Japan (PSA), UAE (VARA) and Switzerland (FINMA) each classify non-custodial
escrow differently. Any market we accept users from needs its own answer.

**Cross-cutting questions for counsel**

1. Does BountyFlow ever have "control" of funds as each regime defines it? The three qualifications in
   [Custody posture](#custody-posture) are the pressure points.
2. Does a bounty reward make the contributor a worker, a contractor or neither, and does that pull in employment
   or payroll rules in the contributor's country?
3. If KYC becomes required, at what threshold — per payout, per cumulative volume, or on every account?
4. Are there markets we should geoblock until we have an answer?

### What we would need for KYC, if the answer is that we need it

Nothing in the current schema does identity verification. A KYC programme would need at minimum: an identity
provider integration, a verification state on `users`, a risk score, per-user and per-period transaction
thresholds, an SAR/STR filing workflow, a named compliance officer, and a retention schedule for identity
documents that is separate from everything else in this document. None of that exists. It is a project, not a
setting.

## Sanctions screening

Screening **is implemented** and runs on every path where identity is established or money moves.

### Where it runs

| Point | Code | What is screened |
|---|---|---|
| Wallet verification (SEP-10, SEP-53, SEP-45) | `users/service.verify_wallet` | The address being linked |
| Passkey smart-wallet deployment | `wallets/service.create_passkey_wallet` | The new contract address, before the platform pays for it |
| Every prepared chain action | `payments/service.prepare_action` | The signing wallet, the account the action pays or binds, and **every leg of a batch payout** |

The chain-action hook covers all fourteen actions, including `PAYOUT`, `MILESTONE_PAYOUT`, `BATCH_PAYOUT`,
`CLAIM` (where the contributor pays themselves, so the claim itself is the screening moment), `DISPUTE_VOTE` and
`RESOLVE_DISPUTE`. A batch payout settles atomically, so one sanctioned leg blocks the whole batch — the legs
are screened before anything is signed, not after.

Both address forms are screened: account ids (`G…`) and contract addresses (`C…`). A passkey smart wallet is a
contract account that receives money exactly like an account id does, so excluding it would be a hole.

### How it works

- A provider interface (`ScreeningProvider`) with a default `DenylistProvider` that matches against
  `screening_entries`. A commercial screening API can replace it with `set_provider` and no other change.
- Entries come from two places: admins add them by hand with a reason, and the worker's
  `sanctions-list-refresh` job syncs a configured list from `SANCTIONS_LIST_PATH` or `SANCTIONS_LIST_URL`. The
  parser recognises the OFAC SDN export's `Digital Currency Address - XLM` remarks, a JSON array, or one
  address per line. OFAC has not published XLM addresses at the time of writing; the loader is ready for when
  it does, and works with any list a compliance vendor provides.
- The sync **fails static**: an unreadable source, or a list that comes back empty when it previously had
  entries, keeps the entries already in place and raises the error to the admin console and to
  `bountyflow_sanctions_list_error`.
- A match blocks the action with a neutral message that never says why. Staff see the matching entry and its
  reason in the admin console, at `/admin/screening`.
- **Every decision is audited**, cleared as well as blocked, in its own transaction — so a blocked attempt is
  on the record even though the action it gated was rolled back.

### Limits, stated honestly

- It is an **address denylist, not name screening**. It cannot match a person to a sanctioned party by name,
  date of birth or country. That is a different product and would need a vendor.
- There is **no geographic control**: no IP geoblocking, no jurisdiction attestation at sign-up.
- A sanctioned party who uses a fresh address is not detected. Address screening catches known addresses only.
- It screens what BountyFlow prepares. The escrow contract is permissionless, so anyone can call it directly
  and bypass the platform entirely. Chain analytics, not screening, would be the answer to that.

Screening decisions are deliberately **excluded from data exports** (`AuditLog.action NOT LIKE 'screening.%'`).
Disclosing that a person matched a sanctions list can amount to tipping off, which is an offence in several
regimes. Whether an individual decision must be disclosed on request is a question for counsel, case by case.

## Data protection

### Lawful basis (GDPR Article 6)

The basis we would assert for each purpose. To be confirmed with counsel and then mirrored in the privacy
notice.

| Purpose | Data | Basis |
|---|---|---|
| Running the account and the marketplace | Identity, profile, marketplace content | Contract (6(1)(b)) |
| Transactional email (verification, reset, payout confirmations) | Email address | Contract (6(1)(b)) |
| Optional notification email | Email address, preferences | Contract, with per-type opt-out |
| Financial and audit records | Escrows, transactions, payments, audit log | Legal obligation (6(1)(c)) and legitimate interests (6(1)(f)) |
| Sanctions screening | Wallet addresses | Legal obligation (6(1)(c)), or legitimate interests where no obligation is established |
| Security, abuse prevention, rate limiting | IP address, user agent | Legitimate interests (6(1)(f)) |
| Reputation attestations and credentials | Completion facts, addresses | Contract (6(1)(b)); publication is user-initiated |

We process no special-category data and do no profiling with legal effects. The skill-graph recommendations are
content ranking, not a decision about a person.

**Transfers.** Any transfer outside the EEA or UK needs its own assessment once hosting and sub-processors are
chosen. Nothing here depends on a particular region, but nothing here documents one either.

### Subject rights, and what is implemented

| Right | Status | How |
|---|---|---|
| Access and portability | **Implemented** | `POST /privacy/exports` → a worker builds a JSON archive; email and in-app notice; a signed link that expires |
| Erasure | **Implemented, with the retained set below** | `POST /privacy/deletion` → grace period, cancellable, then anonymisation |
| Rectification | **Implemented** | Profile editing |
| Restriction and objection | **Partly** | Notification preferences and account deletion; no general "pause processing" state |
| Not being subject to automated decisions | Not applicable | No automated decisions with legal effect |

**The export archive** covers profile, sessions, wallets (classic and passkey), bounties, milestones, escrows,
bookmarks, applications, assignments, submissions with their revisions and linked pull requests with the
verification snapshot each was judged on, payments received and made, blockchain transactions, sponsored fees,
disputes, reports filed, completion attestations, issued credentials with their signed documents, saved
searches, Q&A posts and votes, the linked GitHub account, notifications, email log, legal acceptances, previous
privacy requests, and the audit entries about the user. Each section is a single query with its joins.

**Deletion** is refused while anything is unsettled: a funded escrow, an active bounty, an open dispute, an
active assignment, an unsettled payout, a submitted transaction awaiting confirmation, or an attestation still
settling on-chain. The user is told which, with a link.

After the grace period, anonymisation **erases** the email, name, username, profile, skills, sessions, tokens,
notifications, bookmarks, saved searches, GitHub link, WebAuthn credential identifiers, application texts and
the text of unpaid submissions; Q&A posts are soft-deleted the way the Q&A module already does it, so threads
keep their shape; issued credentials are revoked and their documents cleared. It **keeps**, under a stable
pseudonym (`deleted-<hash>`), the bounties, escrows, payment records, blockchain transactions, wallet addresses,
approved (paid) work, disputes and the audit log.

The user row itself is kept, pseudonymised, so every foreign key still resolves. That is a deliberate choice:
the alternative is either cascading deletes that destroy the other party's financial records, or orphaned rows.

**Is pseudonymised data still personal data?** Under GDPR, yes — pseudonymisation is a security measure, not
erasure. Our position is that retention of the financial set is required by accounting and anti-money-laundering
law and therefore falls under Article 17(3)(b) and (e). Counsel should confirm the retention periods per market,
and whether the residual set can be reduced further.

## Tax reporting

BountyFlow does **no tax reporting and issues no tax forms**. Users see their own payment history and can
export it. Questions for counsel:

- Does paying a contributor through a non-custodial escrow create a US 1099-NEC or 1099-MISC obligation for the
  requester, for BountyFlow, or for neither? The requester is the payer; BountyFlow is not in the payment path.
- Does the forthcoming 1099-DA regime for digital asset brokers reach a non-custodial marketplace? The broker
  definition turns on whether we effect transfers on behalf of others.
- Do EU DAC7 platform reporting obligations apply? DAC7 covers platforms that facilitate "relevant activities"
  including personal services for consideration. This is the most likely to bite, and it needs an answer before
  EU users are onboarded at scale.
- Do requesters have withholding obligations in the contributor's country?
- What should the product tell users? Today the terms say each party is responsible for their own taxes. If
  DAC7 or 1099-DA applies, we would need to collect tax residence and taxpayer identification numbers, which
  the schema does not do.

Practically: if any of these apply, we need a `tax_profiles` table, a reporting export, and a retention rule —
none of which exists.

## Terms and privacy versioning

**Implemented.** Versions of the terms and the privacy notice are records, not a date in a footer.

- Staff publish a version with a short summary of what changed and a date it takes effect
  (`legal_document_versions`). A version dated in the future is announced in the workspace ahead of time and
  can be withdrawn until it takes effect.
- Once a version is in effect, the workspace is **gated** until the user accepts it. Acceptance is recorded per
  user per version, with the request id (`legal_acceptances`).
- Signing up is acceptance of the versions in effect at that moment; the worker records that explicitly with
  `source="registration"`, so there is no gap between the registration checkbox and the acceptance record.
- Migration `0011` records the versions already published on the site as the baseline (`2026-09`), so existing
  accounts are not asked to re-accept something that has not changed.

What this gives us: for any user, at any time, we can say which version of each document they agreed to and
when. That is the question that actually gets asked in a dispute.

## Records retention

| Record | Retained | Why |
|---|---|---|
| Financial: escrows, transactions, payment records, sponsored fees | Indefinitely, pseudonymised after deletion | Accounting and AML record-keeping (commonly 5–7 years; confirm per market) |
| Audit log | Indefinitely, append-only | Reconstructing what happened; never updated or deleted by the application |
| Legal acceptances | Indefinitely | Proving which terms applied |
| Screening decisions | Indefinitely | Demonstrating the control operated |
| Marketplace content on paid work | Indefinitely | Evidence of what was delivered and paid for |
| Marketplace content on unpaid work | Cleared at deletion | No countervailing obligation |
| Identity and profile | Until deletion | No obligation to keep it |
| Sessions, tokens | Until expiry or deletion | Security |
| Email log | Until deletion; recipient replaced with the pseudonym | Delivery troubleshooting |
| Data export archives | `DATA_EXPORT_TTL_HOURS` (default 7 days), then the archive is deleted | It is a copy of everything; the shorter it lives the better |
| Notifications, saved searches, bookmarks | Until deletion | No obligation to keep them |

The retention periods above are **engineering defaults, not a legal retention schedule**. Counsel should set the
real periods per market, and then the defaults should be changed to match.

## Consumer-protection risks we accept and disclose

Three things about this product can cost a user money in ways they may not expect. All three are stated here,
and all three belong in the terms in plain language.

### Passkey wallets cannot be recovered

A passkey smart wallet is controlled by a WebAuthn credential on the user's device. BountyFlow never holds it
and cannot reconstruct it.

**If the passkey is lost and was not synced to the user's platform keychain, the wallet and everything in it are
gone permanently.** There is no seed phrase, no reset, no support path. Not "difficult to recover" —
unrecoverable.

Whether a user is protected depends on something most users have never thought about: whether their passkey is
a synced credential (iCloud Keychain, Google Password Manager, a password manager) or device-bound (a security
key, or a platform that stores it locally). We cannot detect which, and the difference is total.

This is a real consumer-protection issue, not a footnote. What we do about it:

- the wallet setup flow states it before the passkey is created, not after;
- we recommend adding a second signer or a classic wallet for anyone holding meaningful value;
- payouts can be directed to a classic wallet instead.

What we do **not** do: claim any recovery capability we do not have. A "recovery" feature that depends on the
platform's keychain sync is the platform's feature, not ours, and we should not describe it as ours.

### Fee sponsorship

The platform pays Stellar network fees for some contributor actions (`consent_cancel`, `raise_dispute`,
`submit_work`, `claim`) and for passkey wallet deployment, through a sponsor account whose key is
`STELLAR_SPONSOR_SECRET`. Contributors can therefore act without holding XLM, which removes a real barrier.

Three things follow, and all are handled:

- **It is the platform's money.** Every sponsored transaction is recorded in `sponsored_transactions` with the
  fee charged, and the balance is on the dashboard (`bountyflow_sponsor_balance_xlm`).
- **It is abusable.** The controls are an allowlist of contracts and functions, a maximum fee per transaction
  (`SPONSOR_MAX_FEE_STROOPS`), per-user daily transaction and fee caps (`SPONSOR_DAILY_TX_LIMIT`,
  `SPONSOR_DAILY_FEE_LIMIT_STROOPS`), and a balance floor below which sponsoring stops entirely
  (`SPONSOR_MIN_BALANCE_XLM`). The mainnet guard refuses to start with any of these unset or zero.
- **It switches off cleanly.** With no sponsor key, sponsorship is off and the UI says so.

It is not a payment to the user and not a fee they owe; it is the platform absorbing a cost. Whether it has any
tax or regulatory character is one of the questions for counsel above.

### Verifiable credentials contain personal data, publicly verifiable

An issued credential is a signed JSON document stating that a named subject completed specific bounties for
specific amounts. It is designed to be downloaded, kept and shown to third parties, and to be verifiable by
anyone without contacting us.

That is the point of the format, and it is also the compliance problem:

- **Copies leave our control.** Once a user downloads a credential or sends it to someone, we cannot recall it.
  Erasure cannot reach those copies, and we say so rather than implying otherwise.
- **Revocation status is public.** The Bitstring Status List at `GET /credentials/status/revocation` is a
  public document that says, for each status index, whether that credential is revoked. It contains no names —
  it is a compressed bitstring — but it is a public statement about a credential we issued to a person.
- **"Revoked" is not "deleted".** Revoking flips the bit so every conforming verifier now rejects the
  credential. It does not remove the document from anyone's device. When an account is deleted we do both
  things we can do: revoke every standing credential, and clear our own copy of the signed document and the
  subject identifier. The status index is kept, because the status list is positional and reusing or removing
  an index would silently change the status of a different credential.
- **The subject identifier is a `did:web` derived from the account.** After deletion it resolves to the
  pseudonym.

The question for counsel: does issuing a credential the user then controls make the user the controller of
those copies, and is revocation plus clearing our copy an adequate answer to an erasure request? Our position
is that it is the most that is technically possible, and that the user is told this before a credential is
issued.

## Before mainnet

The blocking list. [docs/runbooks/mainnet-launch-checklist.md](runbooks/mainnet-launch-checklist.md) is the
operational version; this is the compliance half.

**Enforced by the configuration guard** (`app/core/mainnet.py` — the API refuses to start otherwise):

1. `ALLOW_MAINNET=true` and `APP_ENV=production`, with the mainnet passphrase and mainnet endpoints.
2. Every configured contract listed in `deploy/audited-deployments.json` **with its audit report**: the escrow
   contract, and the SEP-45 web-auth and attestation contracts when those features are on. An id without an
   audit does not count.
3. A multisig arbiter: at least two distinct signers and a threshold of at least 2.
4. All five signing keys set to real values — `JWT_SECRET`, `WALLET_CHALLENGE_SIGNING_SECRET`,
   `STELLAR_SPONSOR_SECRET`, `STELLAR_ATTESTER_SECRET`, `CREDENTIAL_ISSUER_SECRET` — plus `METRICS_TOKEN`.
5. HTTPS frontend, API and CORS origins, and `COOKIE_SECURE=true`.
6. Sanctions screening on, with a list source configured.
7. Sponsor caps and balance floor set to deliberate values.
8. Seeding off, `GITHUB_FIXTURE_TRANSPORT` off, the digest trigger off, and a review window of at least a day.

**Not enforceable in code — decisions and sign-offs:**

9. **A legal opinion per launch market** on money transmission and licensing, answering the questions in
   [KYC, AML and money transmission](#kyc-aml-and-money-transmission). This is the long pole.
10. **A decision on KYC**: none, threshold-based, or universal — and if any, the programme built before launch,
    not after.
11. **A decision on geographic restrictions**, and the mechanism if there are any.
12. **A named person accountable for compliance**, and for GDPR a decision on whether a DPO is required.
13. **A DPIA** covering the financial data, the sanctions screening and the public credentials.
14. **The retention schedule** in [Records retention](#records-retention) confirmed and the defaults changed to
    match.
15. **Terms and privacy notice rewritten for real money** and published as a new version through the versioning
    flow, covering at minimum: non-custodial posture, passkey irrecoverability, fee sponsorship, credential
    publication and revocation, and dispute arbitration.
16. **Sub-processors and transfers** documented, with DPAs in place.
17. **A tax position** on DAC7 and 1099-DA, and the schema changes if either applies.
18. **An independent security audit of the contracts**, which is also gate 2 above.
19. **A complaints and support path** that a regulator would recognise, including how a user escalates a
    dispute outcome.
20. **A restore drill completed** and recorded ([docs/runbooks/restore-drill.md](runbooks/restore-drill.md)) —
    losing financial records is a compliance failure, not only an availability one.

**Known gaps we are choosing to carry into that conversation:** no name screening, no geographic controls, no
KYC, no tax reporting, no transaction monitoring beyond address screening, and no recovery for passkey wallets.
Each is defensible for a non-custodial product; none is invisible to a regulator.
