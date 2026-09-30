# Discovery: saved searches and skill-graph recommendations

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [API](api.md) &middot; [Database](database.md) &middot; [Roadmap](product-roadmap.md)
<!-- nav -->

Two features share this module (`backend/app/modules/discovery`): **saved searches**, which watch the marketplace
and alert their owner when a new bounty matches, and **recommendations**, which rank open bounties against what a
contributor has shown they work on.

- [Saved searches](#saved-searches)
  - [Matching](#matching)
  - [Alerts and digests](#alerts-and-digests)
  - [Unsubscribe tokens](#unsubscribe-tokens)
- [The skill graph](#the-skill-graph)
- [Ranking](#ranking)
- [Offline evaluation](#offline-evaluation)
- [Jobs, caching and settings](#jobs-caching-and-settings)

## Saved searches

A saved search stores a marketplace query exactly as the user left it: the text, every filter, and the sort
(`saved_searches.filters`, a JSONB document validated by `SavedSearchFilters`). That schema **subclasses the
marketplace's own `MarketplaceFilters`**, so a filter added to the marketplace — the asset filter, for example —
is captured by saved searches with no change here.

One field differs. A saved deadline is a **rolling window** (`deadline_within_days`) rather than the fixed
`deadline_before` / `deadline_after` pair the marketplace puts in the URL: "closing within 7 days" has to keep
meaning that next month, so the window is resolved against the current time on every use
(`SavedSearchFilters.to_marketplace(now)`). Fixed dates are rejected.

Stored filters are read back tolerantly (`from_stored`): if a value the current schema no longer accepts is
found — a retired category, say — that one field is dropped instead of the whole search failing to load.

### Matching

A saved search matches a bounty **exactly when the marketplace, given that search's filters at that moment, would
list it**. That is not a re-implementation: `match_clause()` calls the bounties repository's own
`marketplace_query()` and takes its `WHERE` clause, so search results and alerts can never drift apart.

Matching runs in the `discovery-worker` consumer on `bounty.published` and `bounty.funded`, inside the event
handler's transaction:

1. One query loads every candidate saved search, joined to its owner, excluding the bounty's own requester
   (a user is never alerted about their own bounty) and inactive accounts.
2. One **batched statement** decides which of them match. Each search's clause becomes a branch of a `UNION ALL`
   that selects `(saved_search_id, bounty_id)`, so a batch of 50 searches is decided by one round trip rather
   than a query per search. The same helper (`matching_pairs`) is reused by the digest job and by the
   "new since you last looked" counter.
3. One `INSERT … ON CONFLICT DO NOTHING` writes the match rows. The primary key `(saved_search_id, bounty_id)` is
   the deduplication: a bounty that is published and later funded matches once, and a redelivered event inserts
   nothing.
4. Instant alerts are raised for the rows that were actually inserted.

Everything — match rows, notifications and the staged email events — commits with the consumer's
processed-event marker, so the handler is idempotent and can never half-apply.

### Alerts and digests

Each saved search has a frequency (`INSTANT`, `DAILY`, `WEEKLY`, `OFF`), a pause switch, and two channels
(in-app, email). Channels are subject to the user's notification preferences: the email worker re-checks
`SAVED_SEARCH_MATCH` against `notification_preferences` at send time, so the global email switch and the per-type
switch both still apply. Choosing email on a saved search is an explicit opt-in, so it turns that type's email
preference on.

| Frequency | What happens |
|---|---|
| `INSTANT` | The match raises an in-app notification and stages a `notification.saved_search_alert` event; the email worker sends one email naming the bounty. |
| `DAILY` | The match is stored `PENDING`. The digest job sends one email a day, at `DISCOVERY_DIGEST_HOUR_UTC`. |
| `WEEKLY` | The same, on Mondays at that hour. |
| `OFF` / paused | The match is still recorded (so it counts as new) but marked `SKIPPED`: nothing is sent. |

The digest job (`worker/jobs/discovery.py`, every 5 minutes) does the whole run in one transaction and a handful
of statements: it locks the due searches (`FOR UPDATE … SKIP LOCKED`, so replicas never collide), loads every
pending match in one query, re-checks all of them with one batched `matching_pairs` call, and marks the outcome
with **two** `UPDATE`s over `(saved_search_id, bounty_id)` tuples. A bounty that stopped matching between
matching and the digest — cancelled, hidden, or edited out of the filters — is marked `SKIPPED` rather than sent.
One email and one in-app notification go to each user, covering all of their due searches.

**"N new since you last looked"** is counted in SQL, never in Python: one aggregate branch per search, unioned
into one statement, counting matches after `last_viewed_at` that the search *still* lists. Opening a saved search
in the marketplace resets it (`POST /saved-searches/{id}/viewed`).

### Unsubscribe tokens

Every alert and digest email carries a per-search unsubscribe link and a `List-Unsubscribe` header. The token is
`v1.<search id>.<user id>.<HMAC-SHA256>`, signed with a key derived from `JWT_SECRET` and a fixed purpose label
(`app/modules/discovery/tokens.py`), so it cannot be replayed as another kind of token. It does not expire,
because a link in an old email must keep working, and it can only ever turn alerts **off**, which is idempotent.
`POST /saved-searches/unsubscribe` is therefore public and CSRF-exempt; the signature is the authorisation. The
page asks for confirmation before it acts, so a link scanner opening the URL unsubscribes nobody.

## The skill graph

Nodes are **normalised** skills. Bounty skills, tags and profile skills are free text, so
`app/modules/discovery/skills.py` lower-cases and collapses whitespace, then maps the name through an alias table
on a separator-insensitive key: `JS`, `js`, `Java Script` and `javascript` are one node, and so are
`smart-contracts`, `smart_contracts` and `smart contracts`. Unknown names keep their own spelling.

A **document** is one set of skills that belong together: a listed bounty's required skills plus its tags, or one
active user's profile skills. Two skills that appear in the same document co-occur. Edge weight:

```
npmi(a, b)   = ln(p(a,b) / (p(a)·p(b))) / −ln p(a,b)        normalised PMI, in [−1, 1]
weight(a, b) = max(0, npmi(a, b)) · c(a,b) / (c(a,b) + 1)   shrunk towards 0 for rare pairs
```

Normalised PMI keeps a common pair from beating a genuinely associated one just because both skills are popular.
The shrink factor is what stops a pair seen **once** from scoring as highly as a pair seen a hundred times, which
raw PMI does. Only positive associations are kept, each node keeps its 20 strongest neighbours, and edges are
stored in both directions so a lookup is one indexed read.

The graph is rebuilt from source on a schedule (`DISCOVERY_GRAPH_REFRESH_SECONDS`, 30 minutes by default) by the
`skill-graph` worker job, written to `skill_nodes` / `skill_edges` under a Postgres advisory lock, and cached in
Redis for six hours. Readers take the Redis copy, fall back to the tables, and only compute in memory on a fresh
install before the worker's first run.

## Ranking

`GET /recommendations` ranks bounties for the signed-in user in four steps
(`app/modules/discovery/ranking.py`, all pure functions).

**1. Seeds** — what the user is into, as weighted skills. The strongest source for a skill wins:

| Source | Weight |
|---|---|
| Profile skills | 1.0 |
| Skills of bounties they completed | 0.8 |
| Skills of bounties they applied to | 0.6 |
| Skills of bounties they bookmarked | 0.4 |

A bounty's **tags** count half as much as its required skills, in the seeds and in the candidate.

**2. Candidates** — the bounties the marketplace would list (the same `match_clause`, so the marketplace filters
apply to "For you" too) that still accept applications, have an open position, are not the user's own, that they
have not applied to, and that carry at least one skill the seeds reach. That last test runs in SQL against an
expression index on the normalised skill and tag names, widened to every known spelling of the reachable skills.

**3. Proximity** — each skill a bounty asks for gets an affinity: the seed weight if the user has that skill,
otherwise the best `seed weight × edge weight × 0.7` over the user's seeds (one hop in the graph; the discount
keeps a neighbour from ever outscoring the skill itself). The bounty's proximity is the weighted mean affinity
over its skills, in [0, 1]. A bounty with no affinity at all is not recommended.

**4. Blend** — `0.60 × proximity + 0.15 × reward + 0.15 × deadline + 0.10 × funding`, ties going to the newest.

- *reward*: `log1p(amount) / log1p(best amount of the same asset)`. **Rewards are never compared across assets.**
  100 USDC and 100 XLM are different amounts of different things and BountyFlow has no price feed, so the best
  reward is tracked per **asset identifier** (`native`, `CODE:ISSUER` — two issuers' "USDC" stay apart) and the
  reward part is a bounty's rank within its own asset. Amounts are never summed across assets.
- *deadline*: `0.1 … 1.0` over a 14-day horizon; a bounty with no deadline scores 0.6, a passed one 0.
- *funding*: verified on-chain funding scores highest (1.0 funded, 0.6 partially, 0.5 pending, 0.3 unfunded).
  This reads the same escrow state the funding badge does — never a claim.

Every recommendation is returned with the reason it was chosen: the skills matched directly, and the related ones
with the user's skill each was reached through. The UI renders that as "Matches rust, soroban" or
"Related to soroban".

The ranked list is cached in Redis for 60 seconds per user. The key includes the marketplace cache generation, so
any bounty change invalidates it immediately, plus the graph version and the user's seeds.

## Offline evaluation

`app/modules/discovery/evaluation.py` scores the ranking against real behaviour, and
`uv run python -m app.scripts.evaluate_recommendations` runs it over a database (read-only):

```
uv run python -m app.scripts.evaluate_recommendations               # k = 1, 3, 5, 10; 20% held out
uv run python -m app.scripts.evaluate_recommendations --k 5 --holdout 0.3
```

For every user with applications, the most recent share (`--holdout`, at least one) is hidden. Seeds are rebuilt
from what is left — earlier applications, bookmarks and completions, and the profile — with nothing about a
held-out bounty allowed to leak in. Every bounty the user did not post and had not applied to is ranked, and the
held-out applications are the relevant items:

```
precision@k = |top k ∩ held out| / k        recall@k = |top k ∩ held out| / |held out|
hit rate@k  = share of users with at least one held-out bounty in their top k
```

The same split is scored for two baselines, so the numbers mean something: **popularity** (how many other people
applied) and **skill overlap** (required skills shared with the profile — the rule the dashboard used before).
The report is a Markdown table, one row per k and ranker, ending with the number of users evaluated and
held-out applications.

Applying to a bounty is an imperfect relevance signal: it is biased towards what the marketplace already showed
the user. Read the numbers as a comparison between rankers on one split, not as an absolute quality score.

## Jobs, caching and settings

| Job (`worker/jobs/discovery.py`) | Interval | What it does |
|---|---|---|
| `skill-graph` | `DISCOVERY_GRAPH_REFRESH_SECONDS` (1800 s) | Rebuilds the graph from bounties and profiles; stores and caches it. |
| `saved-search-digests` | 300 s | Sends the daily and weekly digests that are due, each frequency in its own transaction. |

Both take the usual Redis job lock, so only one worker replica runs each at a time.

| Setting | Default | Meaning |
|---|---|---|
| `DISCOVERY_DIGEST_HOUR_UTC` | `8` | UTC hour digests go out: daily every day, weekly on Mondays. |
| `DISCOVERY_GRAPH_REFRESH_SECONDS` | `1800` | How often the skill graph is rebuilt. |
| `DISCOVERY_DIGEST_TRIGGER_ENABLED` | `false` | Enables `POST /admin/discovery/digests/run` (admins only), which sends pending digests immediately. The route answers 404 while it is off, so it does not exist in normal deployments. It is there for operators and for the end-to-end suite. |

Redis keys: `bf:v1:discovery:skill-graph` (the graph, 6 h) and `bf:v1:discovery:recs:<user>:g<gen>:<digest>`
(a user's ranked list, 60 s).
