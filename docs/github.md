# GitHub integration

BountyFlow links a GitHub account to a BountyFlow account, and verifies the pull requests a contributor attaches
to a submission. It reads **only public data** from the GitHub REST API, never writes to GitHub, and never asks
for repository access.

- [What it is for](#what-it-is-for)
- [Linking an account](#linking-an-account)
- [Pull request verification](#pull-request-verification)
- [Re-checks: schedule, on demand, webhook](#re-checks-schedule-on-demand-webhook)
- [Merged pull requests and the review clock](#merged-pull-requests-and-the-review-clock)
- [Rate limits, caching and outages](#rate-limits-caching-and-outages)
- [Configuration](#configuration)
- [Testing without GitHub](#testing-without-github)

## What it is for

| Question | Answered by |
|---|---|
| Is this GitHub account really this BountyFlow user's? | A one-time challenge published in a public gist, or OAuth |
| Does the pull request exist, and is it in the bounty's repository? | `GET /repos/{owner}/{repo}/pulls/{number}` |
| Did the contributor open it? | The PR author's numeric id vs. the linked account's id |
| Is it open, merged or closed, and do its checks pass? | The same call plus check runs and commit statuses on the head SHA |

## Linking an account

**Gist proof** is the route that always works, with no OAuth app and no secrets:

1. `POST /github/account/challenge {login}` issues `bountyflow:<username>:<16 random bytes>`, stored in Redis for
   30 minutes under the signed-in user's id, bound to the claimed login. Rate limited to 10 per 15 minutes.
2. The user saves that text in a **public gist** as `bountyflow-verification.txt`.
3. `POST /github/account/verify-gist {gist_url}` fetches the gist through the API and links the account only if
   - the gist's **owner login** equals the claimed login (anonymous gists are refused), and
   - one of its files **contains the exact challenge**.
4. The challenge is consumed on success, so the same gist cannot be replayed. The verified **numeric GitHub id**
   is stored alongside the login, so a later GitHub rename never silently re-points the link.

A GitHub account can be linked to only one BountyFlow account (409 `github_account_taken`), enforced by a unique
constraint on `github_accounts.github_id`. Unlinking is immediate (`DELETE /github/account`).

**OAuth** is offered as well when `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set: a single-use `state`
bound to the user, the code exchanged server-side, the access token used once to read `/user` and then dropped —
it is never stored. `GET /github/config` tells the UI whether to show the button.

The verified account is shown on the public profile (`GET /users/{username}/github`), where it replaces the
self-entered `github_url` link.

## Pull request verification

A submission can link up to five pull request URLs (`https://github.com/{owner}/{repo}/pull/{number}`; tabs such
as `/files` are accepted and the URL is canonicalised and lower-cased). For each one BountyFlow records a
verification snapshot:

| Verdict | Meaning |
|---|---|
| `VERIFIED` | Exists, in the bounty's repository (when it names one), opened by the contributor's verified account |
| `NOT_FOUND` | GitHub answers 404 — it may be private, deleted, or the URL is wrong |
| `REPO_MISMATCH` | Opened against another repository |
| `AUTHOR_MISMATCH` | Opened by a different GitHub account |
| `AUTHOR_NOT_LINKED` | The contributor has not linked a verified GitHub account |
| `UNAVAILABLE` | GitHub could not be reached yet; nothing has been verified |
| `PENDING` | Linked, not checked yet |

Alongside the verdict, the snapshot holds `state` (`OPEN` / `CLOSED` / `MERGED`) with `merged_at`, the head SHA,
and the **combined checks** of that SHA: check runs and legacy commit statuses folded into one result — any
failure fails, otherwise anything unfinished is pending, otherwise success, and `NONE` when the commit has no
checks at all. GitHub reports a combined status state of `pending` for a commit with no statuses, which is why
only a non-zero `total_count` is counted.

A repository that was **renamed or transferred** still matches: when the names differ, the bounty repository's
numeric id is fetched once and compared with the PR's base repository id.

Linking or unlinking a GitHub account re-derives the authorship verdict of the contributor's already-checked
pull requests from the stored author id, without calling GitHub.

## Re-checks: schedule, on demand, webhook

* **Scheduled** — the worker job `github-pr-recheck` runs every 30 seconds and picks only rows that are due:
  5 minutes apart with a `GITHUB_TOKEN`, 20 minutes without, 6 hours for a 404, with exponential backoff (2
  minutes doubling to a 6-hour cap) after a failure. A pull request stops being re-checked once it is merged or
  closed, or its submission is approved or rejected.
* **On demand** — "Check again" on the pull request card (`POST /submissions/{id}/pull-requests/recheck`), open
  to the contributor, the requester and staff, rate limited to 20 per 5 minutes per user, with a 20-second
  cooldown per pull request so repeated clicks do not spend GitHub requests.
* **Webhook** — `POST /api/v1/github/webhook`, off unless `GITHUB_WEBHOOK_SECRET` is set (404 while empty). Every
  delivery must carry a valid `X-Hub-Signature-256` (see [security.md](security.md#github-webhook)). The payload
  is used **only to decide which rows to mark due**; the state itself always comes from the REST API afterwards.

Every check runs outside a database transaction: the plan is read in one joined query, the transaction ends, the
GitHub calls happen, and then a single new transaction locks the rows (`SELECT … FOR UPDATE`, in id order),
writes the snapshots, stages `submission.pull_request_updated` for a pull request that has just become merged or
closed, and commits once. Re-running a check writes the same state and stages no duplicate event.

## Merged pull requests and the review clock

A requester can set **"Require a merged pull request from the contributor"** on a bounty. The flag can only be
set or changed while the bounty is a draft or open and unfunded — the same rule as the reward — so nobody can
add the requirement after work has started. It also requires the bounty's repository (when it has one) to be on
GitHub.

While the requirement is unmet, **approval** is refused with 409 `merged_pr_required` and a message naming the
precise problem, for example:

> This bounty requires a merged pull request from the contributor. stellar/js-stellar-sdk#1747 is still open.

**This never blocks answering.** That matters because of the escrow contract's review window (see
[smart-contracts.md](smart-contracts.md)): once a contributor records their work on chain, a clock runs, and if
the requester neither pays nor answers before it expires, the contributor can `claim` the reward themselves.

The rule BountyFlow implements is: **an unmet pull request requirement is a reason to answer, not a reason to
stay silent.**

* The contract is the only authority over the clock. Nothing BountyFlow refuses off-chain stops it, and
  BountyFlow deliberately offers no way to pause it off-chain.
* Requesting changes and rejecting are **never** gated by the pull request requirement. While the clock runs,
  those answers are signed on-chain (`request_changes` / `reject_submission`), which is exactly what stops it.
* So when approval is blocked *and* the clock is running, the 409 says so explicitly, and the error details carry
  `onchain_review_pending` and `claimable_at`:

  > … This work is recorded on-chain and its review clock is still running until 06 Oct 2026, 11:20 UTC: staying
  > silent does not hold the reward — once the window passes the contributor can claim it. Request changes or
  > reject on-chain with your wallet to stop the clock.

* The submission review UI shows the same warning above the review buttons, next to the on-chain "Request
  revision" and "Reject" actions, and the contributor's view of the same submission says the requester cannot
  approve until the pull request is merged.

The requirement therefore protects the requester from approving unmerged work, and the review window protects
the contributor from a requester who simply stops replying. Neither one can be used to freeze the other.

## Rate limits, caching and outages

* Unauthenticated: 60 requests an hour per IP. With `GITHUB_TOKEN`: 5,000. The token is only ever sent to the
  configured API host.
* Every response is cached in Redis in a reduced shape with its `ETag`. A fresh entry is served without a
  request; a stale one is revalidated with `If-None-Match`, and a 304 costs no body.
* When the limit is exhausted (or GitHub sends `Retry-After`), a shared backoff key makes **every** caller wait
  until the reset instead of spending more requests. Cached data is still served while backing off.
* A pull request that has never been checked shows `UNAVAILABLE` with the reason; one that has been checked keeps
  its last snapshot, and the card says when it was last checked. Verification never fails a review request.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `GITHUB_TOKEN` | empty | Raises the API rate limit to 5,000/hour. Only public data is read, so a fine-grained token with no permissions is enough. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | empty | Enables "Connect with GitHub". Gist verification works without them. |
| `GITHUB_WEBHOOK_SECRET` | empty | Enables the webhook endpoint (404 while empty). |
| `GITHUB_API_URL`, `GITHUB_OAUTH_URL` | github.com | For GitHub Enterprise. |
| `GITHUB_TIMEOUT_SECONDS` | `10` | Per-request timeout. |
| `GITHUB_FIXTURE_TRANSPORT` | `false` | Test mode only; refused when `APP_ENV` is staging or production. |

## Testing without GitHub

The verification rules are tested against **recorded real GitHub responses** in
`backend/tests/fixtures/github`, captured from public pull requests:

| Fixture | What it covers |
|---|---|
| `stellar/js-stellar-sdk#1744` | Merged, by `Ryang-21`, 18 passing check runs |
| `stellar/js-stellar-sdk#1747` | Open, same author |
| `stellar/js-stellar-sdk#1739` | Open, from a fork, another author → `AUTHOR_MISMATCH` |
| `stellar/js-stellar-sdk#1716` | Closed without merging |
| `stellar/js-stellar-base#978` | Merged in another repository → `REPO_MISMATCH` |
| `…/pulls/999999` | GitHub's real 404 body |

They are replayed through an injectable `httpx` transport (`app/modules/github/transport.py`), so unit and
integration tests exercise the real client, cache, backoff and verification code without a network call. The
end-to-end suite turns on `GITHUB_FIXTURE_TRANSPORT`, which serves the same fixtures, and registers the gist it
needs in Redis — no test ever depends on a real person's gist.
