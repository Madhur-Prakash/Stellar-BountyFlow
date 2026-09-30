"""Deterministic, idempotent development seed.

    uv run python -m app.scripts.seed          # or: make seed
    SEED_ON_STARTUP=true                       # run automatically on every API start

Every record has a stable key (username, `metadata.seed_key` for bounties, a `seed:` UUID for everything else).
Existing records are left untouched and only missing ones are created, so running the seed repeatedly is safe.

Accounts, bounties and applications are created through the real domain services, so they always obey the bounty
state machine: users and profiles, open and draft bounties, and pending applications. The lighter rows the
services have no create-and-forget entry point for — questions and answers, bookmarks, saved searches, product
feedback, announcements — are written directly with deterministic identifiers, which is what makes a second run
a no-op.

No chain history is ever fabricated — funding, assignment and payouts only happen when a real wallet signs a
real Stellar transaction. Nothing here writes an escrow, a payment, a blockchain transaction or an attestation,
and no seeded bounty ever gets past `open`.

Seeded users are ordinary accounts: each has a real email address and a password (`SEED_USER_PASSWORD`, default
`BountyFlow!2026`) and signs in through the normal login form. The emails use the reserved `.test` domain, so no
message can ever reach a real inbox by accident. `make seed` prints the sign-in details for the primary
accounts. Seeding is refused outside development/test.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import close_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.runtime import run_async
from app.core.security import hash_password, utcnow
from app.db.session import dispose_engine, get_sessionmaker
from app.modules.applications import service as application_service
from app.modules.applications.schemas import ApplicationCreate
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyBookmark, Category, Difficulty
from app.modules.bounties.schemas import BountyCreate
from app.modules.discovery.models import AlertFrequency, SavedSearch
from app.modules.discovery.saved_searches import next_digest_time
from app.modules.discovery.schemas import SavedSearchFilters
from app.modules.feedback.models import Feedback, FeedbackKind, FeedbackStatus
from app.modules.notifications.models import Notification, NotificationPreference, NotificationType
from app.modules.qa.models import BountyQAPost, BountyQAVote
from app.modules.users.models import Role, User, UserSkill

logger = get_logger(__name__)

SEED_NAMESPACE = uuid.UUID("6f0c7a4e-1b2d-4c3e-9f5a-8b7c6d5e4f30")


@dataclass(frozen=True)
class SeedUser:
    username: str
    display_name: str
    role: Role
    bio: str
    skills: list[str]
    interests: list[str]
    requester: bool = False
    contributor: bool = False
    github: str | None = None

    @property
    def email(self) -> str:
        return f"{self.username.replace('-', '.')}@bountyflow.test"


# Usernames used by earlier versions of the seed. An existing account under one of these is renamed in place, so
# its bounties, applications and history are kept.
LEGACY_USERNAMES: dict[str, str] = {
    "ada-okafor": "demo-requester",
    "kai-tanaka": "demo-contributor",
    "morgan-reyes": "demo-admin",
    "priya-nair": "demo-moderator",
    "river-chen": "river-dev",
    "mira-kovac": "mira-design",
    "sol-adeyemi": "sol-sec",
}
# Email domain of accounts created by earlier seeds; those accounts get their current address and password.
LEGACY_EMAIL_DOMAIN = "@demo.bountyflow.local"

# The accounts `make seed` prints in full and the README documents: one of every role, plus the two sides of the
# marketplace. Everyone else exists to make the listings, queues and profiles look like a working site.
PRIMARY_USERNAMES: tuple[str, ...] = (
    "ada-okafor",
    "nova-labs",
    "kai-tanaka",
    "river-chen",
    "mira-kovac",
    "sol-adeyemi",
    "priya-nair",
    "morgan-reyes",
)

USERS: list[SeedUser] = [
    SeedUser(
        "ada-okafor",
        "Ada Okafor",
        Role.USER,
        "Founder of a small payments startup. Posts well-scoped bounties with clear acceptance criteria.",
        ["product", "rust", "stellar"],
        ["development", "security"],
        requester=True,
    ),
    SeedUser(
        "kai-tanaka",
        "Kai Tanaka",
        Role.USER,
        "Full-stack developer focused on React, TypeScript and Soroban smart contracts.",
        ["react", "typescript", "rust", "soroban", "tailwind"],
        ["development", "design"],
        contributor=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "morgan-reyes",
        "Morgan Reyes",
        Role.ADMIN,
        "Runs platform operations: user support, moderation escalations, and releases.",
        ["operations"],
        ["community"],
    ),
    SeedUser(
        "priya-nair",
        "Priya Nair",
        Role.MODERATOR,
        "Community moderator. Reviews reports and disputes, and keeps listings accurate.",
        ["community", "documentation"],
        ["community"],
    ),
    SeedUser(
        "nova-labs",
        "Nova Labs",
        Role.USER,
        "Open-source tooling studio building developer infrastructure for Stellar.",
        ["rust", "devops"],
        ["development", "documentation"],
        requester=True,
    ),
    SeedUser(
        "river-chen",
        "River Chen",
        Role.USER,
        "Backend engineer. Python, Go, and distributed systems.",
        ["python", "go", "postgresql", "kafka"],
        ["development", "research"],
        contributor=True,
    ),
    SeedUser(
        "mira-kovac",
        "Mira Kovač",
        Role.USER,
        "Product designer specialising in fintech onboarding flows.",
        ["figma", "ui design", "ux research"],
        ["design"],
        contributor=True,
    ),
    SeedUser(
        "sol-adeyemi",
        "Sol Adeyemi",
        Role.USER,
        "Security researcher. Smart-contract audits and web app pentests.",
        ["security", "rust", "soroban"],
        ["security", "bug_bounty"],
        contributor=True,
    ),
    # --- Requesters ---------------------------------------------------------------------------------------
    SeedUser(
        "helio-collective",
        "Helio Collective",
        Role.USER,
        "Anchor operator moving money between Lagos, Accra and Abidjan. We post the integration work we "
        "cannot staff internally, usually SEP flows and agent tooling.",
        ["anchor", "sep-24", "sep-31", "python"],
        ["development", "research"],
        requester=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "aurora-ledger",
        "Aurora Ledger",
        Role.USER,
        "We build treasury software for companies that hold digital assets on their balance sheet. Multisig "
        "policy, reconciliation and the reports an auditor will actually accept.",
        ["typescript", "postgresql", "accounting"],
        ["development", "security"],
        requester=True,
    ),
    SeedUser(
        "fatima-el-amrani",
        "Fatima El Amrani",
        Role.USER,
        "Product lead at a Casablanca remittance app. I write the specs, run the user interviews, and post "
        "the work my two engineers do not have time for.",
        ["product", "ux research", "arabic"],
        ["design", "research"],
        requester=True,
    ),
    SeedUser(
        "lucas-ferreira",
        "Lucas Ferreira",
        Role.USER,
        "Building payroll for remote teams out of Florianópolis. Most of what I post is the unglamorous "
        "middle of a payout: batching, retries, reconciliation.",
        ["typescript", "node", "payments"],
        ["development"],
        requester=True,
    ),
    SeedUser(
        "anneke-visser",
        "Anneke Visser",
        Role.USER,
        "Grants lead at a small open-source foundation. I fund the maintenance work nobody volunteers for: "
        "accessibility, translations, migration guides.",
        ["grants", "documentation", "community"],
        ["community", "documentation"],
        requester=True,
    ),
    SeedUser(
        "hiroshi-endo",
        "Hiroshi Endō",
        Role.USER,
        "Engineering manager at a Tokyo exchange. I post the pieces that sit outside our core matching "
        "engine, and I review every submission myself.",
        ["go", "market data", "operations"],
        ["development", "security"],
        requester=True,
    ),
    SeedUser(
        "dilnoza-usmanova",
        "Dilnoza Usmanova",
        Role.USER,
        "Remittance product manager in Tashkent. Our users send money home over patchy mobile data, so I "
        "care a lot about small payload sizes and clear error copy.",
        ["product", "localization", "ux research"],
        ["design", "research"],
        requester=True,
    ),
    SeedUser(
        "noor-rahman",
        "Noor Rahman",
        Role.USER,
        "Technology lead at a microfinance non-profit in Dhaka. Field officers use our app on cheap Android "
        "phones with no signal half the day, which shapes everything I post here.",
        ["android", "offline sync", "python"],
        ["development", "research"],
        requester=True,
    ),
    SeedUser(
        "theo-lambert",
        "Théo Lambert",
        Role.USER,
        "Developer relations at a wallet company in Lyon. I commission sample apps, migration guides and "
        "the talks I do not have time to write myself.",
        ["developer relations", "typescript", "writing"],
        ["documentation", "community"],
        requester=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "zanele-mthembu",
        "Zanele Mthembu",
        Role.USER,
        "Payments operations in Johannesburg. I run the settlement desk, so the bugs I post are the ones "
        "that cost my team an afternoon of manual matching.",
        ["operations", "reconciliation", "sql"],
        ["development"],
        requester=True,
    ),
    SeedUser(
        "arun-ramaswamy",
        "Arun Ramaswamy",
        Role.USER,
        "CTO of a B2B invoicing platform in Chennai. Small team, long backlog. I post the well-bounded "
        "pieces and keep the fuzzy ones in-house.",
        ["python", "api design", "postgresql"],
        ["development", "security"],
        requester=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "ines-moreau",
        "Inès Moreau",
        Role.USER,
        "Design lead. I look after a shared component library for three product teams, and I take on "
        "design-system work elsewhere when the brief is honest about its constraints.",
        ["figma", "design systems", "css", "accessibility"],
        ["design"],
        requester=True,
        contributor=True,
    ),
    SeedUser(
        "piotr-kaczmarek",
        "Piotr Kaczmarek",
        Role.USER,
        "Platform engineer in Kraków running the clusters three products deploy to. I post the deep "
        "infrastructure work my team keeps postponing.",
        ["kubernetes", "terraform", "postgresql"],
        ["development"],
        requester=True,
    ),
    SeedUser(
        "kwame-asante",
        "Kwame Asante",
        Role.USER,
        "I build mobile money bridges in Accra and take integration contracts when my own roadmap is quiet. "
        "Both sides of this marketplace, depending on the month.",
        ["api integration", "mobile money", "python", "go"],
        ["development", "community"],
        requester=True,
        contributor=True,
    ),
    SeedUser(
        "siti-rahayu",
        "Siti Rahayu",
        Role.USER,
        "Product designer in Jakarta. I run identity and verification flows for a lending app, and I take "
        "outside work on anything involving documents, cameras and nervous users.",
        ["figma", "ui design", "identity", "prototyping"],
        ["design", "research"],
        requester=True,
        contributor=True,
    ),
    SeedUser(
        "matias-ovalle",
        "Matías Ovalle",
        Role.USER,
        "Contract Rust engineer in Buenos Aires. I post indexing work for my own tooling and pick up "
        "Soroban contracts when the scope is written down properly.",
        ["rust", "soroban", "indexing", "postgresql"],
        ["development", "research"],
        requester=True,
        contributor=True,
    ),
    SeedUser(
        "grace-wanjiru",
        "Grace Wanjiru",
        Role.USER,
        "Engineer in Nairobi. I run notification infrastructure for a savings app and freelance on anything "
        "that has to work over SMS.",
        ["python", "twilio", "sms", "celery"],
        ["development"],
        requester=True,
        contributor=True,
    ),
    # --- Contributors -------------------------------------------------------------------------------------
    SeedUser(
        "yusuf-bello",
        "Yusuf Bello",
        Role.USER,
        "Rust engineer in Kano. I write Soroban contracts and the test harnesses that keep them honest. I "
        "will always ask about the upgrade path before I start.",
        ["rust", "soroban", "wasm", "testing"],
        ["development", "security"],
        contributor=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "elena-petrova",
        "Elena Petrova",
        Role.USER,
        "Protocol engineer, mostly Go and gRPC. Ten years on systems where a dropped message costs someone "
        "real money, so I over-index on retries and idempotency.",
        ["go", "grpc", "protobuf", "distributed systems"],
        ["development", "research"],
        contributor=True,
    ),
    SeedUser(
        "mateo-silva",
        "Mateo Silva",
        Role.USER,
        "Front-end developer in Valparaíso. React and CSS, and a stubborn interest in making forms behave "
        "on a bad connection.",
        ["react", "typescript", "css", "forms"],
        ["development", "design"],
        contributor=True,
    ),
    SeedUser(
        "aiko-matsumoto",
        "Aiko Matsumoto",
        Role.USER,
        "Accessibility engineer. I test with VoiceOver and NVDA daily and file the bugs nobody else sees. "
        "Happy to do the boring audit as well as the fix.",
        ["accessibility", "aria", "react", "testing"],
        ["development", "design"],
        contributor=True,
    ),
    SeedUser(
        "daniel-okonkwo",
        "Daniel Okonkwo",
        Role.USER,
        "Backend developer in Enugu. FastAPI, Postgres, and a long history of untangling other people's "
        "pagination.",
        ["python", "fastapi", "postgresql", "sqlalchemy"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "sana-qureshi",
        "Sana Qureshi",
        Role.USER,
        "Data engineer in Lahore. Pipelines, warehouse models and the kind of reporting that survives an "
        "audit. I like briefs that come with a sample of the real data.",
        ["python", "dbt", "airflow", "sql"],
        ["research", "development"],
        contributor=True,
    ),
    SeedUser(
        "linh-nguyen",
        "Linh Nguyễn",
        Role.USER,
        "Mobile developer in Da Nang. React Native day to day, native Android when it matters. I ship on "
        "devices two generations behind the ones designers use.",
        ["react native", "android", "typescript", "mobile"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "oscar-lindqvist",
        "Oscar Lindqvist",
        Role.USER,
        "Site reliability engineer in Gothenburg. Prometheus, Grafana, Terraform. I would rather delete an "
        "alert than add one nobody acts on.",
        ["prometheus", "grafana", "terraform", "devops"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "amara-diallo",
        "Amara Diallo",
        Role.USER,
        "Technical writer in Dakar, working in French and English. I read the code before I write about it, "
        "and I test every command I publish.",
        ["technical writing", "documentation", "french"],
        ["documentation"],
        contributor=True,
    ),
    SeedUser(
        "ravi-deshmukh",
        "Ravi Deshmukh",
        Role.USER,
        "Test automation engineer in Pune. Playwright, CI pipelines, and hunting the flake that only fails "
        "on Tuesdays.",
        ["playwright", "testing", "typescript", "ci"],
        ["development", "bug_bounty"],
        contributor=True,
    ),
    SeedUser(
        "nina-schneider",
        "Nina Schneider",
        Role.USER,
        "Application security consultant in Berlin. Threat models, code review and the occasional very "
        "boring report that saves someone a very bad week.",
        ["security", "threat modelling", "appsec", "python"],
        ["security", "bug_bounty"],
        contributor=True,
    ),
    SeedUser(
        "tobias-berg",
        "Tobias Berg",
        Role.USER,
        "Systems programmer in Trondheim. Rust and WebAssembly, benchmarking as a habit rather than an "
        "afterthought.",
        ["rust", "wasm", "benchmarking", "systems"],
        ["development", "research"],
        contributor=True,
    ),
    SeedUser(
        "carmen-ortiz",
        "Carmen Ortiz",
        Role.USER,
        "Product designer in Guadalajara. I work in the messy part of a product — error states, empty "
        "states, and what happens when the money does not arrive.",
        ["figma", "ui design", "interaction design"],
        ["design"],
        contributor=True,
    ),
    SeedUser(
        "wei-zhang",
        "Wei Zhang",
        Role.USER,
        "Distributed systems engineer. Event streams, exactly-once fictions, and the operational reality "
        "underneath them. Kafka since 0.9.",
        ["kafka", "go", "java", "distributed systems"],
        ["development", "research"],
        contributor=True,
    ),
    SeedUser(
        "gabriel-mensah",
        "Gabriel Mensah",
        Role.USER,
        "Integration engineer in Kumasi. I have connected six mobile money providers and can tell you which "
        "of their sandboxes actually work.",
        ["api integration", "python", "mobile money", "webhooks"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "isabela-rocha",
        "Isabela Rocha",
        Role.USER,
        "Localization engineer in Porto Alegre. I set up the extraction pipeline, then argue with everyone "
        "about plural rules. Portuguese and Spanish natively.",
        ["i18n", "react", "localization", "typescript"],
        ["development", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "omar-haddad",
        "Omar Haddad",
        Role.USER,
        "Platform engineer in Beirut. Kubernetes, Helm, and deployment strategies that do not require "
        "everyone to be awake.",
        ["kubernetes", "helm", "devops", "argocd"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "freya-nilsen",
        "Freya Nilsen",
        Role.USER,
        "Front-end performance specialist in Aarhus. Bundle budgets, Core Web Vitals, and removing the "
        "third analytics script.",
        ["performance", "react", "web vitals", "typescript"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "karan-mehta",
        "Karan Mehta",
        Role.USER,
        "Smart contract developer in Ahmedabad. Soroban and Rust, with a preference for contracts small "
        "enough to hold in your head.",
        ["soroban", "rust", "smart contracts", "testing"],
        ["development", "security"],
        contributor=True,
        github="https://github.com/stellar",
    ),
    SeedUser(
        "hana-suzuki",
        "Hana Suzuki",
        Role.USER,
        "UX researcher in Osaka. Moderated interviews, diary studies, and reports short enough that people "
        "read them.",
        ["ux research", "interviews", "usability testing"],
        ["design", "research"],
        contributor=True,
    ),
    SeedUser(
        "emeka-nwosu",
        "Emeka Nwosu",
        Role.USER,
        "API designer in Lagos. OpenAPI, versioning strategies, and talking teams out of their fourth "
        "bespoke error format.",
        ["api design", "openapi", "graphql", "python"],
        ["development", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "lior-ben-ami",
        "Lior Ben-Ami",
        Role.USER,
        "Applied cryptographer in Haifa. Key management, signing schemes, and reviewing the places where "
        "people quietly reinvent them.",
        ["cryptography", "key management", "security", "rust"],
        ["security", "research"],
        contributor=True,
    ),
    SeedUser(
        "marta-kowalska",
        "Marta Kowalska",
        Role.USER,
        "Data visualisation developer in Wrocław. D3 and SVG, and a strong opinion about how many colours a "
        "chart needs.",
        ["d3", "data visualization", "svg", "typescript"],
        ["design", "development"],
        contributor=True,
    ),
    SeedUser(
        "ahmed-farouk",
        "Ahmed Farouk",
        Role.USER,
        "Backend engineer in Alexandria. Go services, gRPC boundaries, and load tests before the launch "
        "rather than after it.",
        ["go", "grpc", "backend", "load testing"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "sofia-marchetti",
        "Sofia Marchetti",
        Role.USER,
        "Developer experience engineer in Bologna. I rewrite getting-started guides until a stranger can "
        "finish them in fifteen minutes.",
        ["developer experience", "documentation", "typescript"],
        ["documentation", "development"],
        contributor=True,
    ),
    SeedUser(
        "tariq-benali",
        "Tariq Benali",
        Role.USER,
        "Backend developer in Algiers. Python, Celery, and long-running jobs that need to survive a "
        "restart. Works in French, Arabic and English.",
        ["python", "celery", "redis", "postgresql"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "mei-lin-koh",
        "Mei-Lin Koh",
        Role.USER,
        "Compliance engineer in Singapore. I sit between the regulation and the codebase and translate in "
        "both directions.",
        ["compliance", "kyc", "regtech", "python"],
        ["security", "research"],
        contributor=True,
    ),
    SeedUser(
        "pablo-navarro",
        "Pablo Navarro",
        Role.USER,
        "Creative developer in Valencia. WebGL, Three.js and motion work, with an eye on the frame budget "
        "of a mid-range laptop.",
        ["webgl", "three.js", "animation", "typescript"],
        ["design", "development"],
        contributor=True,
    ),
    SeedUser(
        "zara-iqbal",
        "Zara Iqbal",
        Role.USER,
        "Accessibility auditor in Manchester. WCAG 2.2 reports written for developers, with the failing "
        "selector and the fix, not just the criterion number.",
        ["accessibility", "wcag", "auditing", "html"],
        ["design", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "ana-melo",
        "Ana Melo",
        Role.USER,
        "Reliability engineer in Lisbon. Incident response, Postgres tuning, and writing the runbook while "
        "the incident is still fresh.",
        ["postgresql", "sre", "incident response", "observability"],
        ["development", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "jonas-weber",
        "Jonas Weber",
        Role.USER,
        "Full-stack developer in Hamburg. TypeScript on both ends, and an unreasonable amount of time spent "
        "on PDF rendering.",
        ["typescript", "node", "react", "pdf"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "leila-haddadi",
        "Leila Haddadi",
        Role.USER,
        "Front-end developer in Tunis working mostly in Arabic and French interfaces. Right-to-left layout "
        "is my specialist subject, unfortunately.",
        ["react", "css", "rtl", "i18n"],
        ["development", "design"],
        contributor=True,
    ),
    SeedUser(
        "daniela-vargas",
        "Daniela Vargas",
        Role.USER,
        "Content designer in Bogotá. I rewrite the sentences people read when something has gone wrong, in "
        "Spanish and English.",
        ["content design", "ux writing", "spanish"],
        ["design", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "samuel-adeniyi",
        "Samuel Adeniyi",
        Role.USER,
        "Community organiser in Ibadan. I run a monthly builders' meetup and teach the first wallet "
        "workshop most attendees ever sit through.",
        ["community", "teaching", "events"],
        ["community", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "natalia-sokolova",
        "Natalia Sokolova",
        Role.USER,
        "Video producer and educator in Tbilisi. Short technical explainers, scripted and edited by the "
        "same person so the timing works.",
        ["video", "editing", "scriptwriting", "teaching"],
        ["community", "documentation"],
        contributor=True,
    ),
    SeedUser(
        "arjun-pillai",
        "Arjun Pillai",
        Role.USER,
        "Database engineer in Kochi. Query plans, index strategy, and migrations that do not lock the table "
        "for nine minutes.",
        ["postgresql", "performance", "sql", "migrations"],
        ["development", "research"],
        contributor=True,
    ),
    SeedUser(
        "maya-goldberg",
        "Maya Goldberg",
        Role.USER,
        "Front-end engineer in Tel Aviv. Component libraries, design tokens, and keeping two dozen "
        "developers from forking the button.",
        ["react", "design systems", "typescript", "storybook"],
        ["development", "design"],
        contributor=True,
    ),
    SeedUser(
        "felipe-cardozo",
        "Felipe Cardozo",
        Role.USER,
        "Payments integration engineer in Asunción. I have written the same reconciliation job four times "
        "for four different processors and learned something each time.",
        ["python", "payments", "reconciliation", "postgresql"],
        ["development"],
        contributor=True,
    ),
    SeedUser(
        "aminata-traore",
        "Aminata Traoré",
        Role.USER,
        "Field research lead in Bamako. I test products with people who have one bar of signal and a shared "
        "phone, and report what actually happened.",
        ["field research", "ux research", "french"],
        ["research", "community"],
        contributor=True,
    ),
]


@dataclass(frozen=True)
class SeedApplication:
    """One application, written by one person. Cover letters are individual on purpose: a queue where every
    note is the same sentence with the name swapped tells a reviewer nothing."""

    username: str
    cover: str
    experience: str = ""


@dataclass(frozen=True)
class SeedBounty:
    key: str
    requester: str
    title: str
    short: str
    description: str
    category: Category
    difficulty: Difficulty
    reward: str
    skills: list[str]
    tags: list[str]
    positions: int = 1
    days_to_apply: int = 14
    days_to_complete: int = 30
    # Target stage: draft | open (anything beyond open requires real on-chain funding by a wallet)
    stage: str = "open"
    applicants: list[SeedApplication] = field(default_factory=list)
    acceptance: str = ""


# Shown in the featured rail on the marketplace.
FEATURED_KEYS: frozenset[str] = frozenset(
    {
        "wallet-connect-flow",
        "soroban-audit",
        "fee-research",
        "sep24-deposit-ui",
        "multisig-policy-editor",
        "orderbook-stream-client",
        "accessibility-audit-wcag",
    }
)


def _desc(summary: str, bullets: list[str]) -> str:
    items = "\n".join(f"- {b}" for b in bullets)
    return f"## Context\n\n{summary}\n\n## Scope\n\n{items}\n\n## Notes\n\nPlease ask questions in your application."


BOUNTIES: list[SeedBounty] = [
    SeedBounty(
        "wallet-connect-flow",
        "ada-okafor",
        "Build a Freighter wallet connection flow in React",
        "Implement a polished connect / disconnect / network-mismatch flow for Freighter in our dashboard.",
        _desc(
            "Our dashboard needs a first-class wallet experience.",
            [
                "Connect and disconnect",
                "Detect wrong network",
                "Accessible modal with keyboard support",
                "Unit tests with React Testing Library",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "250",
        ["react", "typescript", "stellar"],
        ["frontend", "wallet"],
        stage="open",
        applicants=[
            SeedApplication(
                "kai-tanaka",
                "I have built this exact flow twice and the part everyone gets wrong is the network mismatch: "
                "Freighter reports the network asynchronously and the modal has to survive the user switching "
                "networks while it is open. I would handle that with a subscription rather than a one-off read.",
                "Two production dashboards with Freighter and xBull, both with the connect flow behind a "
                "provider-agnostic interface.",
            ),
            SeedApplication(
                "mateo-silva",
                "Interested, mostly for the accessibility half. I would build the modal on a focus-trap "
                "primitive rather than hand-rolling it, and cover the keyboard path in the tests rather than "
                "only the happy click path.",
            ),
            SeedApplication(
                "maya-goldberg",
                "We shipped something close to this in our component library last year. I would like to know "
                "whether you want the connect button as a reusable component or wired into the dashboard "
                "directly, because that changes how I would structure the state.",
                "Maintain a 40-component React library used by four teams; wrote its dialog and focus "
                "management primitives.",
            ),
        ],
        acceptance="All states handled; tests pass in CI; reviewed by our team.",
    ),
    SeedBounty(
        "soroban-audit",
        "nova-labs",
        "Security review of a Soroban token vesting contract",
        "Review our vesting contract for authorization, arithmetic and upgrade-path issues.",
        _desc(
            "A ~600 line Soroban contract that releases tokens on a schedule.",
            [
                "Manual review of auth and storage",
                "Report with severity ratings",
                "Suggested fixes as a patch",
            ],
        ),
        Category.SECURITY,
        Difficulty.EXPERT,
        "1200",
        ["rust", "soroban", "security"],
        ["audit", "smart-contracts"],
        stage="open",
        applicants=[
            SeedApplication(
                "sol-adeyemi",
                "Vesting contracts fail in two places: the cliff arithmetic on the first release, and whoever "
                "can call the admin functions after an upgrade. I would spend most of the time on those and "
                "give you a written finding for each public function either way.",
                "Eleven Soroban audits, four of them on vesting or escrow schedules.",
            ),
            SeedApplication(
                "yusuf-bello",
                "Available from next week. I would want the storage layout documented before I start — half "
                "the bugs I find in this class of contract come from a key collision between two instance "
                "entries nobody meant to share.",
            ),
            SeedApplication(
                "lior-ben-ami",
                "I review signing and authorisation for a living and vesting schedules are a good match. My "
                "reports come with a proof-of-concept test for every finding above informational severity.",
                "Cryptographic review for two custody products and a signing service.",
            ),
            SeedApplication(
                "karan-mehta",
                "I have written a vesting contract on Soroban, which mostly means I know where I cut corners. "
                "I would check the release maths against a property test rather than by reading it.",
            ),
            SeedApplication(
                "nina-schneider",
                "My Rust is decent rather than expert, so I would frame this as a threat model plus a manual "
                "review rather than a deep formal audit. Say so if that is not what you need.",
            ),
        ],
        acceptance="Written report covering every public function.",
    ),
    SeedBounty(
        "fix-pagination-bug",
        "ada-okafor",
        "Fix off-by-one pagination bug in transactions API",
        "Our /transactions endpoint skips one record between pages. Find and fix it with a regression test.",
        _desc(
            "Reported by several users on large accounts.",
            ["Reproduce with a failing test", "Fix cursor handling", "Add regression coverage"],
        ),
        Category.BUG_BOUNTY,
        Difficulty.BEGINNER,
        "80",
        ["python", "postgresql"],
        ["bug", "api"],
        stage="open",
        applicants=[
            SeedApplication(
                "river-chen",
                "This is almost always a keyset cursor compared with a strict inequality on a non-unique sort "
                "column. I would reproduce it with a fixture that has two rows sharing a timestamp, then fix "
                "the cursor to include the id as a tiebreaker.",
            ),
            SeedApplication(
                "daniel-okonkwo",
                "Happy to take this. Could you say whether the endpoint uses offset or a cursor? If it is "
                "offset with a non-deterministic order the fix is a different shape, and I would rather tell "
                "you that up front than surprise you in the pull request.",
            ),
        ],
    ),
    SeedBounty(
        "onboarding-redesign",
        "ada-okafor",
        "Redesign the contributor onboarding checklist",
        "Design a friendlier first-run checklist for contributors, from profile to first application.",
        _desc(
            "Current onboarding has a high drop-off.",
            ["Figma flows for desktop and mobile", "Empty states", "Hand-off specs with tokens"],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "400",
        ["figma", "ui design", "ux research"],
        ["design", "onboarding"],
        stage="open",
        applicants=[
            SeedApplication(
                "mira-kovac",
                "I would want to see where the drop-off actually is before redrawing anything — if people "
                "leave at the wallet step, a prettier checklist will not save it. Can you share the funnel? "
                "Otherwise I am ready to start on the flows next Monday.",
                "Redesigned onboarding for two fintech products; the second cut abandonment by a third.",
            ),
            SeedApplication(
                "carmen-ortiz",
                "The empty states are the interesting part of this brief. A contributor with no applications "
                "yet is the person most likely to leave, and that screen is usually an afterthought. I would "
                "start there and work backwards.",
            ),
        ],
    ),
    SeedBounty(
        "kafka-consumer-docs",
        "nova-labs",
        "Write a guide to idempotent Kafka consumers in Python",
        "A practical tutorial covering at-least-once delivery, idempotency keys and dead-letter topics.",
        _desc("For our developer docs site.", ["2,000–3,000 words", "Runnable code samples", "Diagrams"]),
        Category.DOCUMENTATION,
        Difficulty.INTERMEDIATE,
        "150",
        ["python", "kafka"],
        ["docs", "tutorial"],
        stage="open",
        applicants=[
            SeedApplication(
                "river-chen",
                "I run consumers like this in production and have the war stories to make the examples real. "
                "I would include the case people always miss: the consumer that commits before the side "
                "effect completes.",
            ),
            SeedApplication(
                "wei-zhang",
                "I would rather write this as one worked example that grows than four disconnected snippets. "
                "Start with a naive consumer, break it deliberately, then fix it. Tell me if you want the "
                "diagrams in Mermaid or as images.",
                "Eight years on Kafka, including a migration of 200 consumers to idempotent writes.",
            ),
            SeedApplication(
                "amara-diallo",
                "I would pair with one of your engineers for an hour to get the details right, then write and "
                "test every command myself. I can deliver in English and French if the French is useful.",
            ),
        ],
    ),
    SeedBounty(
        "fee-research",
        "nova-labs",
        "Research: Soroban resource fees for escrow-style contracts",
        "Measure and document resource fees for common escrow operations on Testnet.",
        _desc(
            "We want data-driven guidance for contract authors.",
            ["Benchmark create/fund/release", "Compare storage strategies", "Publish a short report"],
        ),
        Category.RESEARCH,
        Difficulty.ADVANCED,
        "300",
        ["soroban", "rust"],
        ["research", "fees"],
        applicants=[
            SeedApplication(
                "kai-tanaka",
                "I would measure instance storage against persistent storage for the same escrow, because "
                "that is the decision most authors get wrong and it is worth a real number rather than an "
                "opinion.",
            ),
            SeedApplication(
                "sol-adeyemi",
                "Benchmarking is only useful if it is repeatable, so I would ship the harness alongside the "
                "report and pin the protocol version it was run against.",
            ),
            SeedApplication(
                "tobias-berg",
                "I benchmark for a living. I would run each operation across a range of ledger entry sizes "
                "rather than a single case, and publish the raw numbers next to the summary so you can "
                "re-derive the conclusions.",
                "Maintain a benchmark suite for a WebAssembly runtime.",
            ),
            SeedApplication(
                "matias-ovalle",
                "I have a Testnet harness for my indexer that would get this most of the way there. Happy to "
                "put the report under your name and keep the harness open source.",
            ),
        ],
    ),
    SeedBounty(
        "community-workshop",
        "ada-okafor",
        "Host a beginner workshop on Stellar wallets",
        "Run a 60-minute online workshop introducing wallets, testnet accounts and Friendbot.",
        _desc(
            "For a university blockchain club.",
            ["Slides", "A live walkthrough", "Recording shared afterwards"],
        ),
        Category.COMMUNITY,
        Difficulty.BEGINNER,
        "120",
        ["community", "documentation"],
        ["education", "workshop"],
        positions=2,
        applicants=[
            SeedApplication(
                "priya-nair",
                "I have run this session for two student groups already. The thing that decides whether it "
                "works is whether everyone gets a funded testnet account in the first ten minutes, so I would "
                "send a setup link the day before.",
            ),
            SeedApplication(
                "samuel-adeniyi",
                "I teach this monthly at our meetup in Ibadan, usually to about thirty people who have never "
                "installed a wallet. I would bring the handout we use and adapt it to your club.",
                "Eighteen months of monthly workshops; roughly 400 people through them.",
            ),
        ],
    ),
    SeedBounty(
        "i18n-support",
        "nova-labs",
        "Add internationalisation support to the explorer UI",
        "Introduce i18n with extraction tooling and ship Spanish and Portuguese translations.",
        _desc(
            "Many of our users are in LATAM.",
            ["i18n framework setup", "String extraction", "Two complete locales"],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "350",
        ["react", "typescript"],
        ["i18n", "frontend"],
        applicants=[
            SeedApplication(
                "isabela-rocha",
                "Portuguese is my first language and I have done the extraction half of this four times. The "
                "part to agree on before starting is whether you want translator-friendly message IDs or "
                "source-text keys, because switching later is painful.",
                "Set up i18n pipelines for three React products, two of them with continuous translation.",
            ),
            SeedApplication(
                "kai-tanaka",
                "I can do the framework and extraction work but I would not be the right person for the "
                "Spanish and Portuguese copy itself. Worth splitting into two positions if you agree.",
            ),
            SeedApplication(
                "daniela-vargas",
                "I would take the Spanish locale. Machine translation gets the nouns right and the tone "
                "wrong, and a wallet explorer is exactly where a stiff translation makes people distrust the "
                "product.",
            ),
        ],
    ),
    SeedBounty(
        "grafana-dashboards",
        "nova-labs",
        "Create Grafana dashboards for a FastAPI service",
        "Build latency, error-rate and saturation dashboards from Prometheus metrics.",
        _desc("Service already exports metrics.", ["Three dashboards", "Alert rules", "Short README"]),
        Category.OTHER,
        Difficulty.BEGINNER,
        "90",
        ["devops", "python"],
        ["observability"],
        applicants=[
            SeedApplication(
                "oscar-lindqvist",
                "I would build these as provisioned JSON in your repository rather than clicked together in "
                "the UI, so they survive a Grafana rebuild. Three alert rules maximum — more than that and "
                "nobody reads them.",
                "Own the observability stack for a platform team of thirty.",
            ),
        ],
    ),
    SeedBounty(
        "draft-mobile-app",
        "ada-okafor",
        "Prototype a mobile wallet companion app",
        "Draft: exploring a React Native companion app for bounty notifications.",
        _desc("Still scoping this one.", ["Notifications", "Deep links into bounties"]),
        Category.DEVELOPMENT,
        Difficulty.ADVANCED,
        "600",
        ["react", "typescript"],
        ["mobile"],
        stage="draft",
    ),
    # --- Ada Okafor ---------------------------------------------------------------------------------------
    SeedBounty(
        "ledger-export-csv",
        "ada-okafor",
        "Add a CSV export to the transactions table",
        "Let an account owner download their transaction history as CSV, with the same filters the table has.",
        _desc(
            "Support gets this request every week and currently answers it by running a query by hand.",
            [
                "Export respects the active filters and date range",
                "Streamed response, not built in memory (some accounts have 200k rows)",
                "Amounts written at full precision, never rounded for display",
                "A short note in the UI about what the file contains",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.BEGINNER,
        "110",
        ["python", "fastapi", "postgresql"],
        ["export", "api"],
        days_to_apply=10,
        days_to_complete=24,
        applicants=[
            SeedApplication(
                "daniel-okonkwo",
                "Streaming is the whole job here. I would use a server-side cursor and yield rows as they "
                "come, so a 200k-row account does not take the process down with it.",
                "Built a streaming export for a ledger product with roughly the same row counts.",
            ),
            SeedApplication(
                "tariq-benali",
                "One question before I commit: do you want the export generated synchronously, or queued with "
                "an email when it is ready? For 200k rows I would lean towards the queue, and I would build "
                "it on the Celery setup you already have.",
            ),
        ],
        acceptance="A filtered export downloads within a few seconds and the amounts reconcile against the API.",
    ),
    SeedBounty(
        "webhook-retry-queue",
        "ada-okafor",
        "Build a webhook delivery service with exponential backoff",
        "Outbound webhooks currently fire once and are lost if the customer endpoint is down. Make them durable.",
        _desc(
            "Two customers missed settlement callbacks during their own maintenance window and we had no way "
            "to replay them.",
            [
                "Durable queue with at-least-once delivery",
                "Exponential backoff with jitter, capped at 24 hours",
                "Per-endpoint circuit breaking so one dead customer does not block the rest",
                "Signed payloads and a replay endpoint for support",
                "A dead-letter view an operator can actually read",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.ADVANCED,
        "520",
        ["python", "redis", "celery", "api design"],
        ["webhooks", "reliability"],
        days_to_apply=21,
        days_to_complete=45,
        applicants=[
            SeedApplication(
                "tariq-benali",
                "I have built this twice on Celery and the part that bites is ordering: customers assume "
                "callbacks arrive in sequence and they will not once you add retries. I would either document "
                "that loudly or add a per-endpoint serial lane. Which do you want?",
                "Two webhook delivery services, one handling about 4 million events a day.",
            ),
            SeedApplication(
                "elena-petrova",
                "Per-endpoint circuit breaking is the detail most implementations skip and then regret. I "
                "would key the breaker on the endpoint host, not the customer, because several of your "
                "customers will be behind the same gateway.",
            ),
            SeedApplication(
                "gabriel-mensah",
                "I am on the receiving end of webhooks like these all day, which gives me strong opinions "
                "about the signature scheme and the replay endpoint. I would use a timestamped HMAC with a "
                "tolerance window rather than a bare body signature.",
            ),
            SeedApplication(
                "wei-zhang",
                "Interested. I would want to know your delivery volume and how long you are willing to retain "
                "failed deliveries, because that decides whether this is a Redis job or needs a real log.",
            ),
        ],
        acceptance="A customer endpoint can be down for six hours and lose nothing once it recovers.",
    ),
    SeedBounty(
        "topup-threat-model",
        "ada-okafor",
        "Threat model our card top-up to XLM conversion flow",
        "Write a structured threat model for the path from a card charge to a settled on-ledger balance.",
        _desc(
            "We are adding card top-ups and want the threat model written before the code, not after the "
            "incident.",
            [
                "Data flow diagram of the whole path, including the processor callback",
                "STRIDE pass over each trust boundary",
                "Concrete abuse cases: chargeback after withdrawal, double callback, partial capture",
                "Ranked mitigations with an owner and a rough cost for each",
            ],
        ),
        Category.SECURITY,
        Difficulty.ADVANCED,
        "900",
        ["security", "threat modelling", "payments"],
        ["security", "payments"],
        days_to_apply=18,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "nina-schneider",
                "Chargeback-after-withdrawal is the one that will hurt you, and it is a product decision "
                "dressed up as a security one. I would run a two-hour session with whoever owns the refund "
                "policy before writing anything.",
                "Threat models for four payment products, two of them card-to-crypto.",
            ),
            SeedApplication(
                "mei-lin-koh",
                "I would add the regulatory angle alongside the technical one — the controls you need for a "
                "card top-up are partly decided for you, and it is cheaper to know that now.",
            ),
            SeedApplication(
                "lior-ben-ami",
                "Happy to take the cryptographic half seriously: callback authentication, idempotency key "
                "derivation, and how you prove to yourself later that a given charge produced a given "
                "payment.",
            ),
        ],
        acceptance="Every trust boundary has at least one documented abuse case and a ranked mitigation.",
    ),
    SeedBounty(
        "refund-duplicate-rows",
        "ada-okafor",
        "Duplicate refund rows appear when a payout retries",
        "A retried payout sometimes writes two refund records for one reversal. Find the race and close it.",
        _desc(
            "Happens roughly once a week under load. Both rows have the same external reference, so the "
            "reconciliation job flags the account and someone fixes it by hand.",
            [
                "Reproduce it with a concurrent test, not by staring at the code",
                "Fix it with a constraint as well as application logic",
                "Backfill script for the duplicates already in the table",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.INTERMEDIATE,
        "220",
        ["python", "postgresql", "concurrency"],
        ["bug", "payments"],
        days_to_apply=9,
        days_to_complete=21,
        applicants=[
            SeedApplication(
                "felipe-cardozo",
                "I have fixed this exact bug at two processors. It is almost always a read-then-write with no "
                "lock, and the correct fix is a unique index on the external reference plus an upsert. The "
                "backfill is the fiddly part because you have to decide which of the two rows is canonical.",
                "Four reconciliation systems, all of which had this bug at some point.",
            ),
            SeedApplication(
                "arjun-pillai",
                "Happy to take this from the database side. A partial unique index scoped to non-voided "
                "refunds would stop it dead, and I would write the backfill as a single statement rather than "
                "a loop.",
            ),
            SeedApplication(
                "river-chen",
                "I would want to see the retry path first. If the retry is triggered by a queue redelivery "
                "rather than in-process, the fix belongs at the consumer and not in the refund code.",
            ),
        ],
    ),
    # --- Nova Labs ----------------------------------------------------------------------------------------
    SeedBounty(
        "cli-shell-completions",
        "nova-labs",
        "Add shell completions to our CLI for bash, zsh and fish",
        "Generate and ship completions for the three shells, including dynamic completion of network names.",
        _desc(
            "Our CLI has 30 subcommands and no completions, which makes it feel worse than it is.",
            [
                "Static completions generated from the command tree",
                "Dynamic completion for network and account arguments",
                "Install instructions per shell, including Homebrew",
                "A test that fails when a new subcommand is added without completions",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.BEGINNER,
        "95",
        ["rust", "cli", "shell"],
        ["cli", "developer-experience"],
        days_to_apply=12,
        days_to_complete=25,
    ),
    SeedBounty(
        "horizon-backoff-client",
        "nova-labs",
        "Add adaptive rate-limit backoff to our Horizon client",
        "Our client hammers Horizon and gets throttled. Add adaptive backoff that reads the rate-limit headers.",
        _desc(
            "We currently retry on a fixed 500ms delay, which makes throttling worse rather than better.",
            [
                "Read the remaining-quota headers and slow down before hitting zero",
                "Exponential backoff with jitter once throttled",
                "Per-host budgets so one endpoint cannot starve another",
                "Metrics for throttled requests and time spent waiting",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "300",
        ["rust", "http", "reliability"],
        ["client", "rate-limiting"],
        days_to_apply=15,
        days_to_complete=32,
        applicants=[
            SeedApplication(
                "tobias-berg",
                "Reading the quota headers and pacing before you hit zero is the right call and it is not "
                "much code. The interesting decision is what the client does when the budget is exhausted — "
                "block, or fail fast and let the caller decide? I would make it configurable and default to "
                "failing fast.",
            ),
            SeedApplication(
                "elena-petrova",
                "I would model this as a token bucket refilled from the response headers rather than a "
                "sleep-on-429 loop. It behaves much better when you have several concurrent callers.",
                "Wrote the rate limiting layer for a gRPC gateway handling several thousand requests a second.",
            ),
            SeedApplication(
                "ahmed-farouk",
                "Interested. I would want the metrics to distinguish time spent waiting on our own budget "
                "from time spent waiting on a server 429, because they mean completely different things when "
                "you are debugging at 3am.",
            ),
        ],
    ),
    SeedBounty(
        "faucet-abuse-review",
        "nova-labs",
        "Review our testnet faucet for abuse and drain vectors",
        "Our public faucet is being drained by scripts. Review the controls and propose ones that survive.",
        _desc(
            "The faucet funds testnet accounts for workshops. Someone is farming it into a handful of "
            "addresses and the daily budget is gone by lunchtime.",
            [
                "Review the existing controls, including the captcha and the per-IP limit",
                "Identify what an attacker with 500 residential IPs can still do",
                "Propose controls that do not require an account to use the faucet",
                "Say clearly which proposals trade usability for safety, and by how much",
            ],
        ),
        Category.SECURITY,
        Difficulty.ADVANCED,
        "700",
        ["security", "abuse prevention", "rate limiting"],
        ["security", "abuse"],
        days_to_apply=16,
        days_to_complete=35,
        applicants=[
            SeedApplication(
                "nina-schneider",
                "Per-IP limits are decoration once someone has a residential proxy pool. The honest answers "
                "are proof of work, a much smaller per-request grant, or an account requirement, and each one "
                "costs you something at a workshop. I will write up all three with the cost attached.",
            ),
            SeedApplication(
                "sol-adeyemi",
                "I would start by measuring: pull the last month of grants and cluster the destinations. You "
                "probably have twenty addresses taking most of the budget, and knowing their shape decides "
                "which control is worth building.",
            ),
        ],
        acceptance="A written review with at least three proposed controls, each with its usability cost.",
    ),
    SeedBounty(
        "sdk-v3-migration-guide",
        "nova-labs",
        "Write the v2 to v3 migration guide for our SDK",
        "A migration guide developers can follow end to end, with every breaking change and a codemod where possible.",
        _desc(
            "v3 renamed half the transaction builder API and changed error handling. The changelog exists but "
            "nobody can plan a migration from it.",
            [
                "Every breaking change with a before and after snippet",
                "A recommended migration order for a large codebase",
                "A codemod for the mechanical renames",
                "A short section on what we deliberately did not change and why",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.INTERMEDIATE,
        "180",
        ["technical writing", "typescript", "documentation"],
        ["docs", "migration"],
        days_to_apply=13,
        days_to_complete=28,
        applicants=[
            SeedApplication(
                "sofia-marchetti",
                "I would migrate a real project against v3 while writing this, and the guide would be the "
                "notes from doing it. Guides written from the changelog alone always miss the two changes "
                "that actually cost a day.",
                "Wrote the migration guide for a major version of a widely used HTTP client.",
            ),
            SeedApplication(
                "amara-diallo",
                "Available now. I would want a list of the three largest open-source consumers of v2 so I can "
                "check the recommended migration order against something real.",
            ),
            SeedApplication(
                "emeka-nwosu",
                "The section on what you did not change is the one I would spend the most time on. That is "
                "where a reader decides whether to trust the rest of the document.",
            ),
        ],
    ),
    SeedBounty(
        "wasm-size-research",
        "nova-labs",
        "Research: what actually drives Soroban contract WASM size",
        "Draft: measure which Rust patterns inflate compiled contract size, and by how much.",
        _desc(
            "Still scoping. We keep telling contract authors to avoid certain patterns without numbers to "
            "back it up.",
            [
                "A corpus of small contracts isolating one pattern each",
                "Size measured before and after optimisation passes",
                "A ranked list of what costs the most bytes",
            ],
        ),
        Category.RESEARCH,
        Difficulty.EXPERT,
        "850",
        ["rust", "wasm", "soroban", "benchmarking"],
        ["research", "performance"],
        days_to_apply=25,
        days_to_complete=60,
        stage="draft",
    ),
    # --- Helio Collective ---------------------------------------------------------------------------------
    SeedBounty(
        "sep24-deposit-ui",
        "helio-collective",
        "Build the interactive SEP-24 deposit flow for our anchor",
        "Implement the hosted deposit screens an anchor serves during an interactive SEP-24 withdrawal or deposit.",
        _desc(
            "Our wallet partners hand the user to us for the deposit step. Right now they see an unstyled "
            "form and about a third of them do not come back.",
            [
                "Hosted screens for amount, method selection, bank reference and confirmation",
                "Polling status page that survives the user closing and reopening the tab",
                "Works on a 360px screen, because almost everyone arrives on a phone",
                "English and French, with the copy in message files rather than the markup",
                "Handles the three failure modes: expired session, amount out of range, method unavailable",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.ADVANCED,
        "900",
        ["react", "typescript", "sep-24", "i18n"],
        ["anchor", "frontend", "payments"],
        days_to_apply=20,
        days_to_complete=50,
        applicants=[
            SeedApplication(
                "mateo-silva",
                "The status page surviving a closed tab is the requirement that shapes the whole build — it "
                "means the session token has to be resumable from the URL and the polling has to be "
                "idempotent. I would design around that first and make the screens fit it.",
                "Built two hosted payment flows, both of which had to survive being resumed hours later.",
            ),
            SeedApplication(
                "leila-haddadi",
                "French and English with the copy externalised is straightforward, but I would push for the "
                "message files to be set up so a third language can be added without touching components. "
                "You will want Arabic eventually.",
            ),
            SeedApplication(
                "kai-tanaka",
                "I have implemented the wallet side of SEP-24 and would like to build the anchor side for "
                "once. The expired-session case is the one wallets handle worst, so I would make that screen "
                "unambiguous.",
            ),
            SeedApplication(
                "linh-nguyen",
                "Most of your users arrive on a phone, so I would build this mobile-first and test on a "
                "device with 3GB of RAM rather than in a resized desktop window. Happy to record the test "
                "runs.",
            ),
        ],
        acceptance="A wallet can complete a deposit end to end on a phone, and resume it after closing the tab.",
    ),
    SeedBounty(
        "ussd-balance-check",
        "helio-collective",
        "Build a USSD balance and last-transactions service",
        "A USSD menu that lets an agent check a balance and the last five transactions without a smartphone.",
        _desc(
            "Our agents in smaller markets work on feature phones. They currently call the support line to "
            "check a balance, which costs us about forty calls a day.",
            [
                "USSD session handling with our aggregator's callback format",
                "Menu: balance, last five transactions, back",
                "Session timeout and resume behaviour that matches what agents expect",
                "Strict response size limits — 182 characters per screen",
                "Audit log of every lookup, with the agent identity",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "450",
        ["python", "ussd", "telephony", "api integration"],
        ["agents", "telephony"],
        days_to_apply=17,
        days_to_complete=38,
        applicants=[
            SeedApplication(
                "gabriel-mensah",
                "I have built USSD menus against three aggregators and they all disagree about how a session "
                "ends. Tell me which aggregator you are on and I will tell you whether the resume behaviour "
                "you want is even possible on their platform.",
                "Three USSD services in Ghana and Nigeria, two still running.",
            ),
            SeedApplication(
                "kwame-asante",
                "182 characters is the whole design constraint and it is easy to blow it once you add "
                "currency symbols and dates. I would write the formatter first, with a test that fails on any "
                "over-length screen.",
            ),
            SeedApplication(
                "grace-wanjiru",
                "This is close to what I do daily. My one suggestion: log the lookups to a separate table "
                "from your normal audit trail, because the volume from USSD will dwarf everything else.",
            ),
        ],
    ),
    SeedBounty(
        "help-centre-yoruba-hausa",
        "helio-collective",
        "Translate the payout help centre into Yoruba and Hausa",
        "Translate 42 help-centre articles about receiving and cashing out a payout, keeping the money terms exact.",
        _desc(
            "Our agents explain these articles verbally because the English is a barrier. We want them "
            "readable directly.",
            [
                "42 articles, roughly 18,000 words in total",
                "A glossary agreed before translation for the money terms",
                "Screenshots re-captured with the translated interface where one exists",
                "Native speaker review, ideally someone who has worked with agents",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.BEGINNER,
        "140",
        ["translation", "documentation", "yoruba", "hausa"],
        ["localization", "support"],
        positions=2,
        days_to_apply=22,
        days_to_complete=45,
        applicants=[
            SeedApplication(
                "samuel-adeniyi",
                "I can take the Yoruba half. The glossary is the right call — there is no settled Yoruba term "
                "for several of these and agents have invented their own, so I would start by asking them "
                "what they already say rather than inventing something new.",
            ),
        ],
    ),
    SeedBounty(
        "agent-liquidity-report",
        "helio-collective",
        "Research: where our agent network runs out of float",
        "Analyse a year of agent cash-out data and identify where and when float runs dry.",
        _desc(
            "Agents run out of cash at predictable times and we compensate by guessing. We would like the "
            "guess replaced with a model.",
            [
                "Clean and describe the dataset — it is messier than we would like",
                "Identify the patterns by location, day of week and time of month",
                "Quantify the revenue lost to a dry agent",
                "A short recommendation on rebalancing, with the assumptions written down",
            ],
        ),
        Category.RESEARCH,
        Difficulty.INTERMEDIATE,
        "380",
        ["data analysis", "python", "sql"],
        ["research", "operations"],
        days_to_apply=19,
        days_to_complete=42,
        applicants=[
            SeedApplication(
                "sana-qureshi",
                "The dataset being messy is the honest part of this brief and I appreciate it. I would spend "
                "the first week on profiling and send you a note about what is unusable before doing any "
                "modelling, so we do not build a conclusion on a broken column.",
                "Built the analytics warehouse for a mobile money operator with 9,000 agents.",
            ),
            SeedApplication(
                "aminata-traore",
                "I would pair the data with about ten agent interviews. The numbers will tell you when the "
                "float runs out; the agents will tell you why, and it is usually something the data cannot "
                "see, like a market day two towns over.",
            ),
            SeedApplication(
                "marta-kowalska",
                "Interested in the presentation half. A rebalancing recommendation lands much better as a "
                "small interactive map than as a table, and I would build that alongside the written report.",
            ),
        ],
    ),
    # --- Aurora Ledger ------------------------------------------------------------------------------------
    SeedBounty(
        "multisig-policy-editor",
        "aurora-ledger",
        "Build a visual editor for multisig signing policies",
        "A UI for composing signer weights and thresholds that makes an unsafe policy obviously unsafe.",
        _desc(
            "Our customers configure signers in a JSON textarea. Two of them have locked themselves out this "
            "year.",
            [
                "Visual composition of signers, weights and the three thresholds",
                "Live validation: warn before a policy makes the account unrecoverable",
                "Simulation — show which signer combinations can perform which operation",
                "A diff view before submitting a change",
                "The editor must never submit a transaction itself; it produces an XDR for the wallet to sign",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.EXPERT,
        "1800",
        ["react", "typescript", "stellar", "ux research"],
        ["multisig", "frontend", "treasury"],
        days_to_apply=28,
        days_to_complete=70,
        applicants=[
            SeedApplication(
                "kai-tanaka",
                "The simulation is the part that earns the fee. Enumerating signer subsets is exponential in "
                "theory but fine in practice at your sizes, and showing 'these three people together can "
                "empty the account' is what stops the lockout. I would build that before the visual editor.",
                "Built a transaction builder UI that produced XDR for an external signer, same constraint.",
            ),
            SeedApplication(
                "maya-goldberg",
                "I would want a designer alongside me for this. A weight-and-threshold model is genuinely "
                "hard to make legible and I do not think I would get there on my own with only engineering "
                "judgement.",
            ),
            SeedApplication(
                "lior-ben-ami",
                "I would like to take the validation rules specifically. The set of policies that are "
                "technically valid but operationally fatal is larger than people expect, and enumerating them "
                "properly is a cryptography-adjacent job rather than a UI one.",
            ),
            SeedApplication(
                "matias-ovalle",
                "Available in three weeks. One thing to settle first: do you need to support signers that are "
                "contract accounts? That changes the model enough that I would not want to discover it "
                "halfway through.",
            ),
            SeedApplication(
                "mateo-silva",
                "The diff view before submitting is underrated in this brief. Most lockouts I have read about "
                "were someone changing one number and not realising what it implied. I would make that screen "
                "the centrepiece.",
            ),
            SeedApplication(
                "ines-moreau",
                "I would come at this from the design side and work with whoever takes the engineering. The "
                "hard problem is representing a threshold visually without making it look like a permission "
                "checkbox, which is what everyone reaches for first.",
            ),
        ],
        acceptance="A customer cannot save a policy that locks them out without an explicit, typed confirmation.",
    ),
    SeedBounty(
        "treasury-dashboard-charts",
        "aurora-ledger",
        "Design the treasury dashboard's balance and flow charts",
        "Design a small set of charts that answer what changed, where the money went, and what is scheduled.",
        _desc(
            "Our dashboard currently shows one line chart and a table. Customers export to a spreadsheet, "
            "which tells us the dashboard is not doing its job.",
            [
                "Three to five chart types, each answering a stated question",
                "Rules for colour, so twelve assets do not become twelve competing hues",
                "Behaviour at the awkward sizes: one asset, forty assets, no data yet",
                "Light and dark, both specified rather than one derived from the other",
            ],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "420",
        ["figma", "data visualization", "ui design"],
        ["design", "charts"],
        days_to_apply=14,
        days_to_complete=34,
        applicants=[
            SeedApplication(
                "marta-kowalska",
                "Forty assets is where every treasury dashboard falls over. The answer is almost always "
                "grouping into a top-n plus an aggregated remainder, with colour reserved for the ones the "
                "customer has pinned. I would specify that rule explicitly rather than leaving it to "
                "implementation.",
                "Built the charting layer for two financial dashboards, one of them multi-asset.",
            ),
            SeedApplication(
                "carmen-ortiz",
                "I would start by writing down the five questions a treasurer opens this page to answer, get "
                "you to agree with the list, then design backwards from it. Otherwise we end up with pretty "
                "charts nobody uses.",
            ),
            SeedApplication(
                "mira-kovac",
                "The no-data-yet state is worth as much attention as the loaded one for a product people "
                "evaluate before they fund anything. I would treat it as a first-class screen.",
            ),
        ],
    ),
    SeedBounty(
        "csv-import-reconciler",
        "aurora-ledger",
        "Build a bank statement importer that suggests matches",
        "Import a bank CSV and propose matches against on-ledger movements, with a human confirming each one.",
        _desc(
            "Reconciliation is manual and takes our customers a day a month. We want to get that to an hour.",
            [
                "Column mapping for arbitrary bank CSV layouts, saved per bank",
                "Matching on amount, date window and reference, with a confidence score",
                "A review queue where a human confirms, rejects or splits a proposed match",
                "Nothing is written to the ledger automatically — every match is confirmed by a person",
                "Idempotent re-import: uploading the same file twice changes nothing",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "380",
        ["typescript", "node", "postgresql", "reconciliation"],
        ["reconciliation", "import"],
        days_to_apply=16,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "felipe-cardozo",
                "The confidence score is where these projects succeed or fail. If it is tuned so that 90% of "
                "matches are obvious, people trust the queue; if it is noisy they go back to the spreadsheet. "
                "I would build the scorer against a month of your real statements before touching the UI.",
                "Wrote reconciliation for four processors; the last one cut a two-day close to three hours.",
            ),
            SeedApplication(
                "jonas-weber",
                "Idempotent re-import is easy to say and fiddly to do, because banks reissue statements with "
                "the same rows and different ids. I would hash the normalised row rather than trusting any "
                "identifier the bank gives you.",
            ),
            SeedApplication(
                "sana-qureshi",
                "I would take the column mapping seriously — every bank exports a different shape and a saved "
                "mapping per bank is the difference between this being used and abandoned.",
            ),
        ],
    ),
    SeedBounty(
        "key-custody-writeup",
        "aurora-ledger",
        "Document our key custody model for customer security reviews",
        "Draft: a document our customers' security teams can read instead of sending us a 200-row questionnaire.",
        _desc(
            "Still deciding how much detail we are comfortable publishing.",
            [
                "Key generation, storage and rotation, described honestly",
                "What we can and cannot do on a customer's behalf",
                "The recovery path, including the parts that need a human",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.ADVANCED,
        "300",
        ["technical writing", "security", "key management"],
        ["docs", "security"],
        days_to_apply=20,
        days_to_complete=45,
        stage="draft",
    ),
    # --- Fatima El Amrani ---------------------------------------------------------------------------------
    SeedBounty(
        "arabic-rtl-audit",
        "fatima-el-amrani",
        "Audit and fix right-to-left layout across our app",
        "Our Arabic locale is mirrored by a stylesheet and it shows. Audit every screen and fix what is broken.",
        _desc(
            "We flipped the app with a direction attribute and called it done. Users tell us numbers, icons "
            "and progress bars point the wrong way.",
            [
                "Screen-by-screen audit with a screenshot of each defect",
                "Fix the layout issues using logical properties rather than more overrides",
                "Get the numerals right: Arabic-Indic where the locale expects them, Latin in account numbers",
                "Bidirectional text in mixed strings, especially amounts next to currency codes",
                "A regression check a non-Arabic-speaking developer can run",
            ],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "350",
        ["css", "rtl", "i18n", "accessibility"],
        ["rtl", "localization", "frontend"],
        days_to_apply=15,
        days_to_complete=35,
        applicants=[
            SeedApplication(
                "leila-haddadi",
                "The numerals are the part that will embarrass you most and they are barely a CSS problem. "
                "Account numbers and transaction references must stay Latin and left-to-right even inside an "
                "Arabic sentence, and that needs explicit isolation, not a direction flip.",
                "Shipped Arabic and French interfaces for two banking apps in Tunisia.",
            ),
            SeedApplication(
                "zara-iqbal",
                "I would run the audit with a screen reader as well as visually. Mirrored layouts often keep "
                "the reading order of the original, which is invisible in a screenshot and obvious the moment "
                "you listen to it.",
            ),
            SeedApplication(
                "mateo-silva",
                "I would push hard for logical properties rather than another override layer. It is more work "
                "now and it is the only version of this that stays fixed.",
            ),
        ],
        acceptance="Every screen reviewed, with a before and after screenshot for each fix.",
    ),
    SeedBounty(
        "corridor-seasonality",
        "fatima-el-amrani",
        "Research: seasonality in the Morocco to France remittance corridor",
        "Understand when volume spikes in this corridor, and how much of it we can plan for.",
        _desc(
            "We staff support and hold float based on intuition. We would like a model, or at least a "
            "defensible pattern.",
            [
                "Analyse three years of our own transaction data",
                "Cross-reference with public remittance statistics for the corridor",
                "Identify the recurring peaks and how far in advance they are predictable",
                "State clearly where the data does not support a conclusion",
            ],
        ),
        Category.RESEARCH,
        Difficulty.INTERMEDIATE,
        "400",
        ["data analysis", "python", "research"],
        ["research", "payments"],
        days_to_apply=18,
        days_to_complete=45,
        applicants=[
            SeedApplication(
                "sana-qureshi",
                "Three years is enough for annual seasonality and not enough for anything about trend, and I "
                "would say so in the report rather than fitting a line through it. Public corridor statistics "
                "lag by about two quarters, which limits how much they can validate your own data.",
            ),
            SeedApplication(
                "aminata-traore",
                "I would add a qualitative layer — twenty short interviews with senders about when and why "
                "they send. The peaks will be obvious in the data; the reason they move by a week each year "
                "will not be.",
            ),
        ],
    ),
    SeedBounty(
        "kyc-copy-rewrite",
        "fatima-el-amrani",
        "Rewrite the identity verification copy in plain language",
        "Rewrite 30 screens of verification copy so a first-time user understands what we need and why.",
        _desc(
            "Our current copy was written by a compliance consultant and reads like it. Support answers the "
            "same three questions all day.",
            [
                "Rewrite 30 screens and 14 error messages in French and Arabic",
                "Keep every legally required phrase intact — we will flag which ones those are",
                "Explain why each document is needed, in one sentence, where it is asked for",
                "A tone guide so the next 30 screens match",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.BEGINNER,
        "130",
        ["ux writing", "content design", "french"],
        ["copy", "onboarding"],
        days_to_apply=11,
        days_to_complete=26,
        applicants=[
            SeedApplication(
                "daniela-vargas",
                "My French is strong, my Arabic is not, so I would take the French and the tone guide and "
                "would want an Arabic writer alongside me rather than pretending otherwise.",
            ),
            SeedApplication(
                "leila-haddadi",
                "I can take the Arabic. The constraint people miss is that the legally required phrases are "
                "usually long and formal, and the rewritten copy around them has to make room rather than "
                "fight them.",
            ),
        ],
    ),
    # --- Lucas Ferreira -----------------------------------------------------------------------------------
    SeedBounty(
        "pix-offramp-spike",
        "lucas-ferreira",
        "Research: options for a Brazilian real off-ramp for payroll",
        "Compare the realistic routes from an on-ledger balance to a BRL bank account, with fees and settlement times.",
        _desc(
            "We pay contractors in Brazil and currently lose a day and a percentage point at the last step.",
            [
                "Compare at least four routes, including local anchors and licensed partners",
                "Real fee and settlement numbers, not published rate cards",
                "The compliance obligations each route puts on us",
                "A recommendation with the reasoning visible, so we can disagree with it properly",
            ],
        ),
        Category.RESEARCH,
        Difficulty.ADVANCED,
        "600",
        ["payments", "research", "compliance"],
        ["research", "off-ramp"],
        days_to_apply=20,
        days_to_complete=48,
        applicants=[
            SeedApplication(
                "mei-lin-koh",
                "The compliance obligations differ more than the fees do, and that is usually the deciding "
                "factor for a payroll company. I would map each route against what it makes you responsible "
                "for, then let the fees break the tie.",
                "Advised two payroll platforms on local payout licensing in three markets.",
            ),
            SeedApplication(
                "felipe-cardozo",
                "I have integrated two of the likely candidates. Published rate cards are fiction at volume; "
                "I would get quotes under an NDA for your actual monthly number and report the range.",
            ),
            SeedApplication(
                "isabela-rocha",
                "I am in Brazil and can do the local legwork — talking to the partners in Portuguese usually "
                "gets a different answer than the English sales page.",
            ),
        ],
    ),
    SeedBounty(
        "payroll-batch-signer",
        "lucas-ferreira",
        "Build a batch payout signer with a hardware wallet in the loop",
        "Draft: batch 200 payouts into signable transactions without the signer approving 200 things.",
        _desc(
            "Still working out the model. The constraint is that a human must see and approve the total and "
            "the recipient set, not each line.",
            [
                "Batch construction with a deterministic ordering",
                "A summary the signer reads before approving",
                "Partial failure handling that does not double-pay anyone",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.EXPERT,
        "1600",
        ["typescript", "stellar", "payments", "security"],
        ["payouts", "signing"],
        days_to_apply=30,
        days_to_complete=75,
        stage="draft",
    ),
    SeedBounty(
        "pt-br-localization",
        "lucas-ferreira",
        "Translate the contractor-facing app into Brazilian Portuguese",
        "Translate the whole contractor experience, roughly 600 strings, into pt-BR with the payroll terms right.",
        _desc(
            "Our contractors are mostly Brazilian and the app is in English. They manage, but the support "
            "load says they should not have to.",
            [
                "About 600 strings including 40 error messages",
                "Payroll and tax terms checked against what Brazilian contractors actually call them",
                "Plural and currency formatting reviewed, not just the words",
                "A glossary handed back so the next release stays consistent",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.BEGINNER,
        "160",
        ["localization", "portuguese", "i18n"],
        ["localization", "translation"],
        days_to_apply=12,
        days_to_complete=30,
        applicants=[
            SeedApplication(
                "isabela-rocha",
                "Native pt-BR and I have done payroll vocabulary before, which is its own dialect. One thing "
                "to decide early: formal or informal address. Payroll apps usually go formal and then sound "
                "cold, and I would push for informal with careful exceptions.",
                "Localised two HR products into pt-BR, including their tax documentation.",
            ),
        ],
    ),
    SeedBounty(
        "csv-timezone-bug",
        "lucas-ferreira",
        "Payout report CSV shifts dates by one day for some contractors",
        "A contractor in UTC+13 sees payouts dated a day early in the CSV but correct in the app. Fix it.",
        _desc(
            "Reported by two contractors in New Zealand. The dates in the interface are right, so the bug is "
            "in the export path.",
            [
                "Reproduce with a contractor profile set to a positive offset above UTC+12",
                "Fix the formatting, not the stored value",
                "Add a test with at least one timezone either side of the date line",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.BEGINNER,
        "90",
        ["typescript", "node", "timezones"],
        ["bug", "export"],
        days_to_apply=8,
        days_to_complete=18,
        applicants=[
            SeedApplication(
                "jonas-weber",
                "Almost certainly a date formatted in the server's zone instead of the contractor's. I would "
                "fix it at the formatter and add the test for UTC+13 and UTC-11 so the next person cannot "
                "regress it quietly.",
            ),
            SeedApplication(
                "ravi-deshmukh",
                "Happy to take this and I would go slightly beyond the brief: a lint rule or a test helper "
                "that catches any date formatted without an explicit zone. This class of bug always comes "
                "back otherwise.",
            ),
            SeedApplication(
                "daniel-okonkwo",
                "Small and well-specified, which I like. I would want to confirm whether the stored value is "
                "a timestamp or a date, because if it is a bare date the fix is upstream of the export.",
            ),
        ],
    ),
    # --- Anneke Visser ------------------------------------------------------------------------------------
    SeedBounty(
        "grant-reporting-template",
        "anneke-visser",
        "Design a grant reporting template maintainers will actually fill in",
        "A reporting template that takes a maintainer under an hour and still tells us what we need to know.",
        _desc(
            "Our current report is a 14-page document. Half of our grantees file it late and the other half "
            "file something unusable.",
            [
                "A template a maintainer can complete in under an hour",
                "Questions that produce comparable answers across grantees",
                "A version for a three-month grant and one for a twelve-month grant",
                "Guidance notes in the template rather than a separate document",
            ],
        ),
        Category.OTHER,
        Difficulty.BEGINNER,
        "100",
        ["writing", "grants", "documentation"],
        ["grants", "process"],
        days_to_apply=14,
        days_to_complete=30,
    ),
    SeedBounty(
        "oss-contributor-survey",
        "anneke-visser",
        "Run a survey on why first-time contributors do not come back",
        "Design, run and report a survey of people who made exactly one contribution and then stopped.",
        _desc(
            "We fund projects that struggle to retain contributors. We have theories and no evidence.",
            [
                "Survey design, including the questions we should not ask",
                "Distribution to at least 300 one-time contributors across our funded projects",
                "Analysis with the response bias acknowledged honestly",
                "A report of at most eight pages with the raw data attached",
            ],
        ),
        Category.RESEARCH,
        Difficulty.INTERMEDIATE,
        "350",
        ["ux research", "survey design", "data analysis"],
        ["research", "community"],
        days_to_apply=17,
        days_to_complete=50,
        applicants=[
            SeedApplication(
                "hana-suzuki",
                "The people who stopped are the hardest to reach, which means your response set will be "
                "biased towards the ones who still feel warmly about the project. I would supplement the "
                "survey with fifteen interviews recruited some other way and say so plainly in the report.",
                "Ran mixed-method studies for two developer tools, both with the same recruitment problem.",
            ),
            SeedApplication(
                "aminata-traore",
                "I would want to include contributors outside the English-speaking world, who are usually "
                "missing from surveys like this and often have a very specific reason for leaving.",
            ),
            SeedApplication(
                "sana-qureshi",
                "Happy to take the analysis half if you find a researcher for the design. Survey data of this "
                "kind is easy to over-read and I would rather be the person insisting on confidence "
                "intervals.",
            ),
        ],
    ),
    SeedBounty(
        "accessibility-audit-wcag",
        "anneke-visser",
        "WCAG 2.2 AA audit of three funded open-source web apps",
        "Audit three projects against WCAG 2.2 AA and deliver findings their maintainers can act on.",
        _desc(
            "We fund these three projects and accessibility keeps slipping. We want an audit written for "
            "developers, not for a compliance file.",
            [
                "Manual audit with assistive technology, not only an automated scan",
                "Each finding with the failing selector, the criterion and a suggested fix",
                "Findings ranked by user impact rather than by criterion number",
                "A short session with each maintainer to walk through the report",
            ],
        ),
        Category.DESIGN,
        Difficulty.ADVANCED,
        "700",
        ["accessibility", "wcag", "auditing", "html"],
        ["accessibility", "audit"],
        days_to_apply=21,
        days_to_complete=55,
        applicants=[
            SeedApplication(
                "zara-iqbal",
                "Ranking by user impact rather than criterion number is the right instruction and it is rare "
                "to see it written down. I test with NVDA, VoiceOver and keyboard only, and I would deliver "
                "one report per project rather than a combined one so each maintainer can act alone.",
                "Around sixty WCAG audits, most recently for a government service.",
            ),
            SeedApplication(
                "aiko-matsumoto",
                "I would like to take one or two of the three rather than all of them, if you are open to "
                "splitting. A careful audit of one app is worth more than a rushed pass over three.",
            ),
            SeedApplication(
                "ines-moreau",
                "My angle would be the design system underneath each app. Most repeated findings come from "
                "three or four shared components, and fixing those is cheaper than fixing every screen.",
            ),
            SeedApplication(
                "mateo-silva",
                "Interested in the remediation rather than the audit, if that is a separate piece of work "
                "later. Say so and I will hold off applying to the audit itself.",
            ),
        ],
        acceptance="Every finding has a selector, a criterion and a fix a developer can apply without asking.",
    ),
    SeedBounty(
        "meetup-starter-kit",
        "anneke-visser",
        "Put together a starter kit for running a local developer meetup",
        "Everything a first-time organiser needs: agenda templates, a budget sheet, and slides they can adapt.",
        _desc(
            "We give small grants to local meetups and the same questions come back every time.",
            [
                "Agenda templates for a two-hour and a half-day event",
                "A budget sheet with realistic numbers in three regions",
                "An editable slide deck for an introductory session",
                "A checklist for the week before and the day of",
            ],
        ),
        Category.COMMUNITY,
        Difficulty.BEGINNER,
        "150",
        ["community", "events", "writing"],
        ["community", "events"],
        positions=3,
        days_to_apply=20,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "samuel-adeniyi",
                "I have run a meetup for eighteen months and the budget sheet is the thing I wish I had had. "
                "The numbers differ hugely by region, so I would fill in the West African column properly "
                "rather than guessing at all three.",
            ),
            SeedApplication(
                "natalia-sokolova",
                "I would add a short section on recording the session, because organisers always want to and "
                "always underestimate it. Two pages on audio, lighting and consent would save people a lot of "
                "unusable footage.",
            ),
        ],
    ),
    # --- Hiroshi Endō -------------------------------------------------------------------------------------
    SeedBounty(
        "orderbook-stream-client",
        "hiroshi-endo",
        "Build a resilient orderbook streaming client in Go",
        "A streaming client that maintains a correct local orderbook across disconnects and gaps.",
        _desc(
            "Our current client silently diverges from the exchange after a reconnect, and we only notice "
            "when a trade looks wrong.",
            [
                "Snapshot plus delta reconciliation with explicit sequence gap detection",
                "Resynchronise on a gap rather than guessing",
                "Bounded memory for a book with 50,000 levels",
                "A divergence check that can be left running in production",
                "Benchmarks for update throughput and reconnect time",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.EXPERT,
        "1400",
        ["go", "distributed systems", "market data"],
        ["market-data", "streaming"],
        days_to_apply=25,
        days_to_complete=65,
        applicants=[
            SeedApplication(
                "elena-petrova",
                "Silent divergence means the sequence numbers are not being checked, or they are and the gap "
                "handler resumes instead of resyncing. The continuous divergence check you describe is the "
                "right shape: hash the top of book every n updates and compare against a periodic snapshot.",
                "Built market data clients for two venues, including the reconnection logic.",
            ),
            SeedApplication(
                "ahmed-farouk",
                "Bounded memory at 50,000 levels rules out the naive map of price to level. I would use a "
                "sorted structure with pooled allocation and show you the allocation profile as part of the "
                "deliverable, not just the throughput number.",
            ),
            SeedApplication(
                "wei-zhang",
                "I would want to know whether you need the client to be correct or fast first, because at the "
                "margins they conflict. My instinct from your description is correct first, and I would build "
                "the divergence check before anything else.",
            ),
        ],
        acceptance="A forced disconnect under load leaves the local book identical to a fresh snapshot.",
    ),
    SeedBounty(
        "cold-wallet-runbook",
        "hiroshi-endo",
        "Write the cold wallet operations runbook",
        "A runbook an operator can follow at 3am, covering routine sweeps, key ceremonies and the failure cases.",
        _desc(
            "Our procedures live in three people's heads. One of them is leaving.",
            [
                "Routine procedures with every command written out",
                "The key ceremony, including who must be present and what is recorded",
                "Failure cases: a signer unavailable, a device that will not boot, a mismatched checksum",
                "A dry-run checklist so the runbook can be tested without moving funds",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.ADVANCED,
        "420",
        ["technical writing", "security", "operations"],
        ["runbook", "security"],
        days_to_apply=16,
        days_to_complete=38,
        applicants=[
            SeedApplication(
                "ana-melo",
                "I write runbooks by doing the procedure with the operator and writing down what they "
                "actually did, including the step they do from memory and never mention. That takes two "
                "sessions per procedure and it is the only way the document survives contact with 3am.",
                "Wrote the incident runbooks for a payments platform; they are still in use three years on.",
            ),
            SeedApplication(
                "lior-ben-ami",
                "I would take the key ceremony section specifically. Who is present, what is recorded and "
                "what happens when someone is missing are the parts that get skipped, and they are the parts "
                "an auditor will ask about.",
            ),
            SeedApplication(
                "amara-diallo",
                "Available and happy to do the unglamorous version of this properly. I would want to observe "
                "at least one real sweep before writing, even if I am only watching.",
            ),
        ],
    ),
    SeedBounty(
        "withdrawal-replay-bug",
        "hiroshi-endo",
        "A cancelled withdrawal can be replayed from the queue",
        "Cancelling a withdrawal removes the record but a queued job can still process it. Close the window.",
        _desc(
            "Found during an internal review, not in production. The job reads the withdrawal by id, and a "
            "cancel between enqueue and execution is not rechecked.",
            [
                "Reproduce deterministically with a controlled delay",
                "Fix with a state check inside the same transaction as the debit",
                "Audit whether any historical withdrawal hit this path",
                "Regression test that fails without the fix",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.ADVANCED,
        "800",
        ["go", "postgresql", "concurrency", "security"],
        ["bug", "payments"],
        days_to_apply=12,
        days_to_complete=28,
        applicants=[
            SeedApplication(
                "elena-petrova",
                "A state check inside the debit transaction with a row lock is the correct fix, and the "
                "historical audit is the harder half — you need to find withdrawals where the cancel "
                "timestamp is before the execution timestamp, and the clocks may not agree.",
            ),
            SeedApplication(
                "nina-schneider",
                "I would treat this as a security finding rather than a bug, which changes what the "
                "deliverable looks like: a reproduction, a fix, and a written statement of exposure you can "
                "show an auditor.",
            ),
            SeedApplication(
                "arjun-pillai",
                "From the database side this is a SELECT FOR UPDATE away from being fixed, but I would also "
                "check whether the queue can deliver the same job twice, because the same fix has to cover "
                "that.",
            ),
            SeedApplication(
                "ahmed-farouk",
                "Interested. Deterministic reproduction of a race usually needs a test hook in the code, and "
                "I would want agreement that shipping that hook is acceptable before I start.",
            ),
        ],
        acceptance="A cancel issued at any point before the debit commits leaves no debit behind.",
    ),
    SeedBounty(
        "latency-benchmark",
        "hiroshi-endo",
        "Benchmark our order submission path end to end",
        "Draft: measure where the milliseconds go between an API call and an acknowledged order.",
        _desc(
            "Still deciding what we are willing to publish internally versus externally.",
            [
                "Instrument each hop in the submission path",
                "Report percentiles, not averages",
                "Identify the top three contributors to tail latency",
            ],
        ),
        Category.RESEARCH,
        Difficulty.ADVANCED,
        "550",
        ["go", "benchmarking", "observability"],
        ["research", "performance"],
        days_to_apply=22,
        days_to_complete=50,
        stage="draft",
    ),
    # --- Dilnoza Usmanova ---------------------------------------------------------------------------------
    SeedBounty(
        "recipient-picker-ux",
        "dilnoza-usmanova",
        "Redesign the recipient picker for repeat senders",
        "Most of our users send to the same three people. Make that take two taps instead of eleven.",
        _desc(
            "Our picker treats every send as if it were the first. The data says 78% of sends go to a "
            "recipient the user has paid before.",
            [
                "A design that puts recent recipients first without hiding the full list",
                "Handle the awkward cases: a recipient whose details changed, a failed previous send",
                "Work at 360px and with the system font scaled to 200%",
                "Specify the confirmation step — this is the screen where mistakes become expensive",
            ],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "380",
        ["figma", "ui design", "mobile", "ux research"],
        ["design", "mobile"],
        days_to_apply=14,
        days_to_complete=32,
        applicants=[
            SeedApplication(
                "carmen-ortiz",
                "Two taps is achievable but the confirmation screen is where I would spend the design effort. "
                "Speeding up the selection and leaving a vague confirmation just moves the mistake later, "
                "where it costs more.",
                "Designed the send flow for a remittance app in Mexico with a similar repeat rate.",
            ),
            SeedApplication(
                "siti-rahayu",
                "The recipient whose details changed is the interesting case. In my experience people do not "
                "read a banner about it — the changed field has to be visually different in the confirmation "
                "or it gets approved on autopilot.",
            ),
            SeedApplication(
                "mira-kovac",
                "200% font scaling in a picker is a real constraint and it usually kills the card layout "
                "everyone reaches for first. I would design the scaled version first and let the normal one "
                "fall out of it.",
            ),
        ],
    ),
    SeedBounty(
        "number-format-bug",
        "dilnoza-usmanova",
        "Amounts render with the wrong separators in the Russian locale",
        "In ru-RU we show 1,234.56 where users expect 1 234,56. Fix it everywhere, including notifications.",
        _desc(
            "Reported repeatedly. The web app is mostly right; the SMS and push notification templates are "
            "not, and neither is the PDF receipt.",
            [
                "Find every place an amount is formatted, including server-rendered templates",
                "Use the locale's own formatting rather than string replacement",
                "Cover uz-UZ as well, which has the same convention",
                "A test that asserts formatting per locale rather than per screen",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.BEGINNER,
        "85",
        ["i18n", "python", "typescript"],
        ["bug", "localization"],
        days_to_apply=10,
        days_to_complete=21,
    ),
    SeedBounty(
        "agent-onboarding-video",
        "dilnoza-usmanova",
        "Produce a short onboarding video for new cash-out agents",
        "A six to eight minute video in Uzbek and Russian showing an agent their first day end to end.",
        _desc(
            "We onboard agents with a PDF and a phone call. A video would let our field team cover four "
            "times as many.",
            [
                "Script covering setup, a first cash-out, and what to do when it fails",
                "Screen recording of the real app, not a mockup",
                "Uzbek and Russian voiceover, subtitles in both",
                "Under 40MB so it can be shared over a messaging app",
            ],
        ),
        Category.COMMUNITY,
        Difficulty.BEGINNER,
        "200",
        ["video", "scriptwriting", "teaching"],
        ["training", "agents"],
        days_to_apply=18,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "natalia-sokolova",
                "Under 40MB for eight minutes means planning the shots for compression — static screen "
                "recording compresses well, a talking head over a moving background does not. I would build "
                "the whole thing around that constraint rather than shooting and then fighting the encoder.",
                "Produced a 20-part training series for a fintech field team, all delivered over messaging.",
            ),
            SeedApplication(
                "samuel-adeniyi",
                "I would only be useful for the script and structure, not the language work. Happy to "
                "collaborate if you split it, and to bring what we learned teaching agents in person.",
            ),
        ],
    ),
    # --- Noor Rahman --------------------------------------------------------------------------------------
    SeedBounty(
        "offline-first-sync",
        "noor-rahman",
        "Design an offline-first sync layer for our field officer app",
        "Draft: field officers work for hours with no signal. Work out how records reconcile when they return.",
        _desc(
            "Still scoping. The hard part is not the storage, it is what happens when two officers edited the "
            "same household record offline.",
            [
                "A conflict model we can explain to a non-technical field supervisor",
                "Queued writes that survive the app being killed",
                "Bounded local storage on a device with 16GB total",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.EXPERT,
        "1200",
        ["android", "offline sync", "sqlite", "mobile"],
        ["mobile", "sync"],
        days_to_apply=28,
        days_to_complete=70,
        stage="draft",
    ),
    SeedBounty(
        "low-bandwidth-audit",
        "noor-rahman",
        "Audit our app's behaviour on a 2G connection",
        "Measure what our app actually does on a slow, lossy connection and report what we should cut.",
        _desc(
            "Our team tests on office wifi. Our users are on 2G in a rural district with intermittent "
            "coverage.",
            [
                "Measure payload sizes and request counts for the five most used flows",
                "Test on a throttled, lossy connection — not just slow, but dropping packets",
                "Identify what fails silently versus what fails visibly",
                "A ranked list of cuts with the bytes saved for each",
            ],
        ),
        Category.RESEARCH,
        Difficulty.INTERMEDIATE,
        "300",
        ["performance", "mobile", "testing"],
        ["research", "performance"],
        days_to_apply=15,
        days_to_complete=35,
    ),
    SeedBounty(
        "bengali-sms-templates",
        "noor-rahman",
        "Rewrite our SMS templates in Bengali within the segment limit",
        "Rewrite 22 SMS templates in Bengali so each fits one message segment and still makes sense.",
        _desc(
            "Bengali in Unicode gives you 70 characters per segment. Our current templates run to three "
            "segments, which triples the cost and arrives out of order.",
            [
                "22 templates, each within one 70-character segment",
                "Amounts and reference numbers must survive intact",
                "Reviewed by someone who has read these messages on a feature phone",
                "A note on which templates genuinely cannot fit, if any",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.BEGINNER,
        "120",
        ["localization", "bengali", "ux writing"],
        ["sms", "localization"],
        days_to_apply=12,
        days_to_complete=26,
        applicants=[
            SeedApplication(
                "grace-wanjiru",
                "I do not write Bengali, so I would be the wrong person for the copy. What I could add, if "
                "you want it as a separate piece, is the sending side: segment counting before send and an "
                "alert when a template goes over.",
            ),
        ],
    ),
    # --- Théo Lambert -------------------------------------------------------------------------------------
    SeedBounty(
        "wallet-sdk-examples",
        "theo-lambert",
        "Build four runnable example apps for our wallet SDK",
        "Four small apps, each showing one integration path, that a developer can clone and run in five minutes.",
        _desc(
            "Our documentation shows snippets. Developers keep asking for something they can run, and our "
            "one existing example is two major versions behind.",
            [
                "Four examples: browser extension, mobile deep link, server-side signing, read-only explorer",
                "Each one runs with a single command and no account setup",
                "A README per example explaining the one thing it is demonstrating",
                "CI that builds all four against the latest SDK release",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.INTERMEDIATE,
        "260",
        ["typescript", "documentation", "developer experience"],
        ["examples", "sdk"],
        days_to_apply=16,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "sofia-marchetti",
                "The CI that builds all four against the latest release is what stops this rotting like the "
                "last one did, and I would set it up before writing any example. Five minutes to running is "
                "achievable if there is no account setup, which is a real constraint on what the examples can "
                "show.",
                "Maintain the example gallery for an open-source framework, twelve apps kept green in CI.",
            ),
            SeedApplication(
                "kai-tanaka",
                "I would take the browser extension and server-side signing ones. Those are the two where "
                "people get the security model wrong, and an example that models it correctly is worth more "
                "than a paragraph saying so.",
            ),
            SeedApplication(
                "jonas-weber",
                "Happy to take all four or a subset. One suggestion: make the read-only explorer the first "
                "one in the README, because it is the only one that works without a wallet installed and it "
                "is where a curious developer will start.",
            ),
        ],
    ),
    SeedBounty(
        "hackathon-starter-template",
        "theo-lambert",
        "Build a hackathon starter template with wallet auth included",
        "A template a team can clone at 9am and have a working authenticated app by 10am.",
        _desc(
            "We sponsor about eight hackathons a year and watch teams spend the first four hours on the same "
            "setup.",
            [
                "Wallet connect and signature-based sign-in already wired",
                "A minimal backend with one protected route",
                "Deploy to a free tier with one command",
                "A teardown document explaining what to rip out for a real project",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "340",
        ["typescript", "react", "developer experience"],
        ["template", "hackathon"],
        days_to_apply=15,
        days_to_complete=36,
        applicants=[
            SeedApplication(
                "maya-goldberg",
                "The teardown document is the part that makes this honest. Starter templates quietly become "
                "production code, and a page saying which three files are throwaway saves someone a security "
                "incident in six months.",
            ),
            SeedApplication(
                "mateo-silva",
                "I have judged two hackathons and watched this exact four hours disappear. I would keep the "
                "template small enough to read in one sitting — the temptation is to include everything, and "
                "then nobody trusts it.",
            ),
            SeedApplication(
                "kwame-asante",
                "Interested. I would want the deploy step tested from a fresh machine on a slow connection, "
                "because 'one command' often means one command plus a 900MB download.",
            ),
        ],
    ),
    SeedBounty(
        "conference-talk-review",
        "theo-lambert",
        "Review and rehearse two conference talks with our engineers",
        "Two of our engineers are speaking for the first time. Review their talks and rehearse with them.",
        _desc(
            "Both talks are technical and both are currently 45 minutes of slides for a 25 minute slot.",
            [
                "Structural review of each talk with written feedback",
                "Two rehearsal sessions per speaker, recorded",
                "Help cutting to the time limit without losing the argument",
                "Notes on the questions they should expect",
            ],
        ),
        Category.COMMUNITY,
        Difficulty.BEGINNER,
        "110",
        ["public speaking", "teaching", "writing"],
        ["speaking", "coaching"],
        positions=2,
        days_to_apply=9,
        days_to_complete=22,
    ),
    SeedBounty(
        "passkey-explainer-post",
        "theo-lambert",
        "Write an explainer on passkey-based smart wallets",
        "A long-form post explaining how a passkey becomes a wallet, aimed at developers who know neither well.",
        _desc(
            "This comes up at every event we do and our current answer is a whiteboard drawing.",
            [
                "About 2,500 words, technical but readable without a cryptography background",
                "Diagrams for the key flow — creation, signing, recovery",
                "An honest section on the trade-offs, including what happens if a device is lost",
                "Code for the one part readers will want to try",
            ],
        ),
        Category.DOCUMENTATION,
        Difficulty.INTERMEDIATE,
        "220",
        ["technical writing", "cryptography", "documentation"],
        ["docs", "explainer"],
        days_to_apply=14,
        days_to_complete=32,
        applicants=[
            SeedApplication(
                "lior-ben-ami",
                "The honest trade-offs section is the reason to hire someone who works on this rather than a "
                "generalist. Device loss is the question everyone asks and the answer is genuinely "
                "complicated, and a post that glosses it will be picked apart.",
                "Have implemented WebAuthn signing twice and written the internal explainer both times.",
            ),
            SeedApplication(
                "amara-diallo",
                "I would want a technical reviewer lined up before I start. I can write this clearly but I am "
                "not the person who should be the last check on whether the cryptography is stated correctly.",
            ),
        ],
    ),
    # --- Zanele Mthembu -----------------------------------------------------------------------------------
    SeedBounty(
        "ops-alert-triage-playbook",
        "zanele-mthembu",
        "Write a triage playbook for our settlement alerts",
        "Turn 40 alerts into a playbook that says what each one means and what the first three actions are.",
        _desc(
            "My team gets about 40 distinct alerts and treats most of them as noise, which means the real one "
            "gets missed.",
            [
                "One page per alert: what it means, who it affects, first three actions",
                "Identify the alerts that should be deleted rather than documented",
                "Escalation paths with names and hours, not just team labels",
                "A format the on-call person can read on a phone",
            ],
        ),
        Category.OTHER,
        Difficulty.INTERMEDIATE,
        "280",
        ["operations", "technical writing", "observability"],
        ["runbook", "operations"],
        days_to_apply=14,
        days_to_complete=33,
        applicants=[
            SeedApplication(
                "ana-melo",
                "The instruction to identify alerts that should be deleted is the one I would act on first. "
                "Forty alerts for one team is usually twelve real signals and twenty-eight symptoms, and "
                "documenting the symptoms entrenches them.",
                "Cut a payments team's alert set from sixty to nineteen and wrote the playbook for the rest.",
            ),
            SeedApplication(
                "oscar-lindqvist",
                "Agreed on the phone-readable format. I would go further and say each page should fit one "
                "screen, which forces the first three actions to be genuinely the first three.",
            ),
        ],
    ),
    SeedBounty(
        "reconciliation-mismatch",
        "zanele-mthembu",
        "Settlement report disagrees with the ledger by a few cents daily",
        "A small daily variance between our settlement report and the ledger. Find where it is introduced.",
        _desc(
            "Between 2 and 40 cents a day, never in the same direction. My team reconciles it manually and "
            "nobody has found the cause.",
            [
                "Trace a single day's variance to its source",
                "Say whether it is rounding, timing or a genuine miss",
                "Fix it if it is a bug; document it precisely if it is inherent",
                "A check that flags the day it exceeds a threshold",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.INTERMEDIATE,
        "260",
        ["sql", "python", "reconciliation"],
        ["bug", "reconciliation"],
        days_to_apply=13,
        days_to_complete=30,
        applicants=[
            SeedApplication(
                "felipe-cardozo",
                "Variance that changes direction is almost never rounding — rounding drifts one way. My money "
                "is on a timing boundary, where the report and the ledger disagree about which side of "
                "midnight a transaction falls on. That is checkable in an afternoon.",
                "Chased this exact class of variance at three processors.",
            ),
            SeedApplication(
                "sana-qureshi",
                "I would rebuild the report from the raw ledger independently and diff the two, rather than "
                "reading the existing report's code. It is faster and it tells you which side is wrong.",
            ),
            SeedApplication(
                "arjun-pillai",
                "Worth checking whether the report query and the ledger use the same numeric type. A float "
                "somewhere in the middle of a chain of exact values produces exactly this pattern.",
            ),
        ],
    ),
    SeedBounty(
        "settlement-report-redesign",
        "zanele-mthembu",
        "Redesign the daily settlement report for the operations desk",
        "The report my team reads every morning is a wall of numbers. Make the exceptions the point of it.",
        _desc(
            "Eight people open this at 7am and scan for problems. It currently makes them read everything to "
            "find the three lines that matter.",
            [
                "Lead with the exceptions, with the totals still available",
                "A layout that survives printing, because two of the team still print it",
                "Clear treatment for a figure that is unavailable versus one that is zero",
                "Specify the thresholds that make a line an exception, and where they are configured",
            ],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "340",
        ["ui design", "data visualization", "figma"],
        ["design", "operations"],
        days_to_apply=14,
        days_to_complete=31,
        applicants=[
            SeedApplication(
                "marta-kowalska",
                "Unavailable versus zero is the detail that makes an operations report trustworthy, and it is "
                "almost always rendered identically. I would define that treatment first and apply it "
                "everywhere, including the printed version.",
            ),
            SeedApplication(
                "carmen-ortiz",
                "I would sit with two of the eight people for a morning before designing anything. The three "
                "lines that matter are probably not the three lines you would guess, and they will show me by "
                "where their finger goes.",
            ),
        ],
    ),
    # --- Arun Ramaswamy -----------------------------------------------------------------------------------
    SeedBounty(
        "invoice-pdf-renderer",
        "arun-ramaswamy",
        "Build a deterministic invoice PDF renderer",
        "Replace our HTML-to-PDF pipeline with something that renders the same bytes for the same invoice.",
        _desc(
            "Our current renderer produces slightly different output run to run, which breaks the hash we "
            "store for audit purposes.",
            [
                "Deterministic output: same invoice in, identical bytes out",
                "Embedded fonts, including a Tamil and a Devanagari face",
                "Multi-page invoices with repeated headers and correct page totals",
                "Render 500 invoices in under a minute on one core",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "420",
        ["python", "pdf", "typography"],
        ["pdf", "invoicing"],
        days_to_apply=16,
        days_to_complete=40,
        applicants=[
            SeedApplication(
                "jonas-weber",
                "Deterministic PDF means fixing the creation date, the document ID and the font subset "
                "ordering — those three are what change between runs. All are controllable, and I have done "
                "it before for exactly the same audit-hash reason.",
                "Built a deterministic PDF pipeline for a German invoicing product with the same constraint.",
            ),
            SeedApplication(
                "tariq-benali",
                "The Tamil and Devanagari shaping is the part I would want to verify early with real invoice "
                "data. Complex script rendering in PDF libraries ranges from excellent to quietly wrong, and "
                "it is better to find out in week one.",
            ),
        ],
        acceptance="Rendering the same invoice twice produces byte-identical files.",
    ),
    SeedBounty(
        "tax-field-research",
        "arun-ramaswamy",
        "Research: which tax fields our invoices need across five markets",
        "Establish what a compliant invoice must carry in India, Singapore, the UAE, the UK and Germany.",
        _desc(
            "We are expanding and I do not want to discover a mandatory field after issuing 10,000 invoices.",
            [
                "Required fields per market, with the source for each",
                "Where formats conflict, and whether one invoice can satisfy all five",
                "Retention and amendment rules — what happens when an invoice is wrong",
                "A data model recommendation that does not need a rewrite for market six",
            ],
        ),
        Category.RESEARCH,
        Difficulty.INTERMEDIATE,
        "320",
        ["compliance", "research", "tax"],
        ["research", "compliance"],
        days_to_apply=17,
        days_to_complete=42,
        applicants=[
            SeedApplication(
                "mei-lin-koh",
                "Singapore and the UAE I can source directly. India changes often enough that I would date "
                "every claim in the report and say which ones need rechecking before launch rather than "
                "presenting them as settled.",
                "Built the invoice compliance matrix for a regional accounting product covering nine markets.",
            ),
            SeedApplication(
                "emeka-nwosu",
                "My interest is the data model recommendation at the end. Most of these projects produce a "
                "correct matrix and a model that hardcodes the first market, and then market six hurts.",
            ),
        ],
    ),
    SeedBounty(
        "webhook-signature-bug",
        "arun-ramaswamy",
        "Our webhook signature check is vulnerable to a timing attack",
        "The signature comparison is a plain equality check. Fix it and review the rest of the verification path.",
        _desc(
            "Reported through our disclosure address. The comparison short-circuits, and the timestamp "
            "tolerance is also wider than it should be.",
            [
                "Constant-time comparison for the signature",
                "Tighten the timestamp tolerance and reject replays within it",
                "Review the whole verification path, not only the reported line",
                "A test that would catch a regression to a naive comparison",
            ],
        ),
        Category.SECURITY,
        Difficulty.ADVANCED,
        "750",
        ["python", "security", "cryptography"],
        ["security", "webhooks"],
        days_to_apply=11,
        days_to_complete=27,
        applicants=[
            SeedApplication(
                "lior-ben-ami",
                "The constant-time fix is one line; the replay window is the real finding. A wide tolerance "
                "with no nonce store means a captured request is valid for as long as the window, and that is "
                "usually worth more to an attacker than the timing leak.",
            ),
            SeedApplication(
                "nina-schneider",
                "I would review the whole path as you ask, and I would specifically check whether the "
                "signature is verified before or after the body is parsed. Parsing untrusted input first is a "
                "common companion to this bug.",
            ),
            SeedApplication(
                "sol-adeyemi",
                "Happy to take this. I would also want to check how the signing secret is rotated, since a "
                "verification path that cannot accept two secrets at once tends to get bypassed during "
                "rotation.",
            ),
            SeedApplication(
                "gabriel-mensah",
                "From the integrator's side: whatever you tighten, please document the new tolerance clearly. "
                "I have lost days to a provider silently narrowing a replay window.",
            ),
        ],
        acceptance="Signature comparison is constant time and a replayed request inside the window is rejected.",
    ),
    SeedBounty(
        "invoice-empty-states",
        "arun-ramaswamy",
        "Design the empty and error states for the invoice list",
        "Six states, from a brand new account to a failed sync, each with a clear next action.",
        _desc(
            "Our invoice list renders an empty table in every one of these cases, which tells the user "
            "nothing.",
            [
                "New account with no invoices yet",
                "Filters that match nothing, versus no invoices at all",
                "Sync failed, and sync in progress",
                "Permission denied, for a user on a restricted role",
                "Each state with a headline, a sentence and one action",
            ],
        ),
        Category.DESIGN,
        Difficulty.BEGINNER,
        "180",
        ["ui design", "figma", "content design"],
        ["design", "empty-states"],
        days_to_apply=12,
        days_to_complete=26,
        applicants=[
            SeedApplication(
                "carmen-ortiz",
                "Filters matching nothing versus having nothing at all is the distinction most products get "
                "wrong, and it is the difference between a user clearing a filter and a user concluding the "
                "product is broken.",
            ),
            SeedApplication(
                "daniela-vargas",
                "I would take the writing half if you want it split. Six states is six headlines and six "
                "sentences, and getting the sentence right matters more than the illustration.",
            ),
            SeedApplication(
                "siti-rahayu",
                "Permission denied is the one I would spend extra time on. It usually gets a generic message "
                "that leaves the user unsure whether to ask an administrator or give up.",
            ),
        ],
    ),
    # --- Inès Moreau --------------------------------------------------------------------------------------
    SeedBounty(
        "design-token-pipeline",
        "ines-moreau",
        "Build a design token pipeline from Figma to three codebases",
        "Draft: one source of truth for tokens, published to web, iOS and Android without manual copying.",
        _desc(
            "Still deciding on the token format before committing to a pipeline.",
            [
                "Export from Figma variables to a canonical format",
                "Generate platform-specific outputs",
                "A review step so a token change is not silently shipped",
            ],
        ),
        Category.DESIGN,
        Difficulty.ADVANCED,
        "650",
        ["design systems", "figma", "typescript"],
        ["design-system", "tooling"],
        days_to_apply=24,
        days_to_complete=58,
        stage="draft",
    ),
    SeedBounty(
        "motion-guidelines",
        "ines-moreau",
        "Write motion guidelines for our component library",
        "Define durations, easings and the rules for when a component should animate at all.",
        _desc(
            "Three teams animate the same component three ways, and one of them ignores reduced-motion "
            "entirely.",
            [
                "A small set of durations and easings with a stated purpose for each",
                "Rules for when not to animate, which is most of the time",
                "Reduced-motion behaviour specified per pattern, not as a global switch",
                "Implemented as tokens in the library, not only documented",
            ],
        ),
        Category.DESIGN,
        Difficulty.INTERMEDIATE,
        "300",
        ["design systems", "css", "animation"],
        ["design-system", "motion"],
        days_to_apply=14,
        days_to_complete=32,
        applicants=[
            SeedApplication(
                "pablo-navarro",
                "Reduced-motion specified per pattern rather than as a global off switch is the right call "
                "and it is rare to see it asked for. A modal that appears instantly is fine; a loading "
                "indicator that stops moving is a bug.",
                "Wrote the motion layer for two component libraries, both with per-pattern reduced motion.",
            ),
            SeedApplication(
                "maya-goldberg",
                "I would want the tokens to land in the library in the same piece of work. Guidelines that "
                "live only in a document get followed for about one quarter.",
            ),
            SeedApplication(
                "aiko-matsumoto",
                "Interested specifically in the reduced-motion half, including testing it with the setting on "
                "across the real components rather than assuming the media query covers it.",
            ),
        ],
    ),
    SeedBounty(
        "icon-set-audit",
        "ines-moreau",
        "Audit and consolidate our icon set",
        "We have 340 icons and I suspect a third are duplicates. Audit, consolidate and document what is left.",
        _desc(
            "Three teams have added icons independently for two years. There are four distinct download "
            "icons.",
            [
                "Inventory of all 340 with usage counts pulled from the codebases",
                "Identify duplicates and near-duplicates, and propose one survivor for each",
                "Check the survivors are consistent in weight and grid",
                "A short naming convention so this does not recur",
            ],
        ),
        Category.DESIGN,
        Difficulty.BEGINNER,
        "140",
        ["figma", "design systems", "svg"],
        ["design-system", "icons"],
        days_to_apply=12,
        days_to_complete=28,
    ),
    # --- Piotr Kaczmarek ----------------------------------------------------------------------------------
    SeedBounty(
        "k8s-blue-green",
        "piotr-kaczmarek",
        "Implement blue-green deploys for three stateful services",
        "Move three services with database migrations from rolling updates to a blue-green deploy.",
        _desc(
            "Rolling updates leave us with two schema versions live at once, and we have had two incidents "
            "from it this year.",
            [
                "Blue-green cutover including database migration ordering",
                "A rollback that works after the cutover, not only before it",
                "Health gates that check the application, not just the pod",
                "Documented procedure, because I am not the only one who will run this",
            ],
        ),
        Category.OTHER,
        Difficulty.ADVANCED,
        "720",
        ["kubernetes", "postgresql", "devops", "helm"],
        ["deployment", "infrastructure"],
        days_to_apply=18,
        days_to_complete=45,
        applicants=[
            SeedApplication(
                "omar-haddad",
                "Blue-green with a shared database is really a schema compatibility problem wearing a "
                "deployment costume. The pattern that works is expand-migrate-contract across three releases, "
                "and I would make that explicit in the procedure rather than leaving it as tribal knowledge.",
                "Ran the deployment platform for a team of forty, including this exact migration pattern.",
            ),
            SeedApplication(
                "ana-melo",
                "The rollback-after-cutover requirement is the hard one and it usually means keeping the old "
                "schema readable for a release. I would want to agree how long you are willing to carry that "
                "before designing anything.",
            ),
            SeedApplication(
                "oscar-lindqvist",
                "Interested in the health gate half. Pod readiness tells you almost nothing about whether the "
                "new version can serve traffic, and a real gate needs a synthetic transaction.",
            ),
        ],
    ),
    SeedBounty(
        "postgres-index-review",
        "piotr-kaczmarek",
        "Review the index strategy on our two largest tables",
        "Draft: 400GB between two tables, and I suspect we are carrying indexes nobody uses.",
        _desc(
            "Still gathering statistics before I commission this properly.",
            [
                "Identify unused and redundant indexes from production statistics",
                "Propose additions for the slowest queries",
                "Estimate the write amplification we would save",
            ],
        ),
        Category.OTHER,
        Difficulty.EXPERT,
        "950",
        ["postgresql", "performance", "sql"],
        ["database", "performance"],
        days_to_apply=26,
        days_to_complete=60,
        stage="draft",
    ),
    SeedBounty(
        "ci-flake-hunt",
        "piotr-kaczmarek",
        "Find and fix the six flakiest tests in our CI pipeline",
        "Our pipeline fails about one run in five for reasons unrelated to the change. Fix the worst offenders.",
        _desc(
            "People now rerun failed builds without reading them, which defeats the point of having a "
            "pipeline.",
            [
                "Identify the flakiest tests from six months of run history",
                "Diagnose each one properly — a retry wrapper is not a fix",
                "Fix or delete, with a written justification for each choice",
                "A dashboard that keeps the flake rate visible afterwards",
            ],
        ),
        Category.BUG_BOUNTY,
        Difficulty.INTERMEDIATE,
        "290",
        ["testing", "ci", "python", "playwright"],
        ["ci", "testing"],
        days_to_apply=15,
        days_to_complete=38,
        applicants=[
            SeedApplication(
                "ravi-deshmukh",
                "A retry wrapper is not a fix is the line that made me apply. Most flakes are shared state, a "
                "real sleep, or an assertion on something asynchronous, and each has a different correct fix. "
                "I would publish the diagnosis per test alongside the change.",
                "Cut a 300-test suite from a 22% flake rate to under 2% over six weeks.",
            ),
            SeedApplication(
                "ana-melo",
                "The dashboard afterwards is what keeps this from being a one-time cleanup. I would make it "
                "part of the pipeline output so a new flake is visible in the week it appears.",
            ),
            SeedApplication(
                "oscar-lindqvist",
                "Interested if the work includes the infrastructure side. Some flakes are the runner, not the "
                "test, and those are invisible if you only look at the test code.",
            ),
        ],
    ),
    # --- Kwame Asante -------------------------------------------------------------------------------------
    SeedBounty(
        "mobile-money-bridge",
        "kwame-asante",
        "Build a bridge between a mobile money API and on-ledger settlement",
        "Connect one mobile money provider's collection and disbursement APIs to on-ledger settlement records.",
        _desc(
            "I have the provider integration; what I do not have is a clean boundary between their world and "
            "the ledger.",
            [
                "Idempotent handling of the provider's callbacks, which arrive more than once",
                "Reconciliation between provider transaction IDs and ledger records",
                "A clear model for money in flight, which can sit in limbo for hours",
                "Timeouts and the manual intervention path for when one is exceeded",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.ADVANCED,
        "880",
        ["python", "api integration", "payments", "mobile money"],
        ["integration", "payments"],
        days_to_apply=20,
        days_to_complete=50,
        applicants=[
            SeedApplication(
                "gabriel-mensah",
                "Money in flight is the part that sinks these integrations. The provider will tell you a "
                "collection is pending for six hours and then succeed, and anything that assumes a two-state "
                "model breaks. I would model it explicitly with a timeout and an operator queue.",
                "Six mobile money integrations; four of them needed exactly this limbo state added later.",
            ),
            SeedApplication(
                "felipe-cardozo",
                "Duplicate callbacks are guaranteed and the provider will not tell you that in the "
                "documentation. Idempotency keyed on their transaction ID with a uniqueness constraint is the "
                "only thing I have seen hold up under real traffic.",
            ),
            SeedApplication(
                "grace-wanjiru",
                "Interested. I would want to know which provider, because their sandboxes differ enormously "
                "in how faithfully they reproduce the callback behaviour you need to test against.",
            ),
        ],
    ),
    SeedBounty(
        "agent-training-deck",
        "kwame-asante",
        "Build a training deck for agents handling failed disbursements",
        "A deck and facilitator notes for a 90-minute session on what to do when a disbursement fails.",
        _desc(
            "Agents currently escalate every failure to support, including the ones they could resolve in a "
            "minute.",
            [
                "Cover the eight most common failure reasons with a decision tree",
                "Scripts for what to say to the customer in each case",
                "Facilitator notes so someone other than me can run it",
                "A one-page reference card agents keep afterwards",
            ],
        ),
        Category.COMMUNITY,
        Difficulty.INTERMEDIATE,
        "260",
        ["teaching", "community", "writing"],
        ["training", "support"],
        days_to_apply=15,
        days_to_complete=35,
        applicants=[
            SeedApplication(
                "samuel-adeniyi",
                "The one-page reference card is what survives the session; the deck is what gets it into "
                "their hands. I would design the card first and build the ninety minutes around teaching it.",
            ),
            SeedApplication(
                "daniela-vargas",
                "The customer scripts are where I would add the most. Agents default to apologising "
                "vaguely, which makes the customer more anxious, and a concrete sentence about what happens "
                "next changes the whole call.",
            ),
        ],
    ),
    # --- Siti Rahayu, Matías Ovalle, Grace Wanjiru ---------------------------------------------------------
    SeedBounty(
        "id-verification-flow",
        "siti-rahayu",
        "Design a document capture flow that works on a cheap phone",
        "Design the capture, review and retry experience for identity documents on a low-end Android camera.",
        _desc(
            "Half our users are on phones with poor cameras and no flash. Our current flow rejects their "
            "photos without telling them what to change.",
            [
                "Capture guidance that helps before the photo, not after the rejection",
                "Rejection reasons a person can act on: glare, crop, blur, wrong document",
                "A retry path that does not restart the whole flow",
                "Consider the case where the document is genuinely unreadable and we need another route",
            ],
        ),
        Category.DESIGN,
        Difficulty.ADVANCED,
        "600",
        ["figma", "ui design", "mobile", "identity"],
        ["design", "identity"],
        days_to_apply=19,
        days_to_complete=46,
        applicants=[
            SeedApplication(
                "carmen-ortiz",
                "Guidance before the photo is the whole design problem and it is mostly about the overlay and "
                "the timing of the prompt. Telling someone about glare after they have taken four photos is "
                "how you lose them.",
            ),
            SeedApplication(
                "hana-suzuki",
                "I would want to run this with real users on their own phones before it is finished, "
                "including people who are uncomfortable photographing their identity documents at all. That "
                "discomfort shapes the flow more than the camera does.",
            ),
            SeedApplication(
                "linh-nguyen",
                "Coming at it from the implementation side: some of what makes a photo unusable is fixable in "
                "the capture layer rather than the design. I would want to be in the room while the flow is "
                "designed so we do not specify something the camera API cannot support.",
            ),
            SeedApplication(
                "aminata-traore",
                "I test with people who share a phone with their household, which changes the retry path "
                "completely — they may not have the device when the rejection arrives.",
            ),
        ],
    ),
    SeedBounty(
        "soroban-event-indexer",
        "matias-ovalle",
        "Build a Soroban contract event indexer with reorg handling",
        "Draft: index contract events into Postgres with correct handling of ledger reorganisations.",
        _desc(
            "Still deciding how much history the indexer should be able to replay from cold.",
            [
                "Stream events and write them idempotently",
                "Detect and unwind on a reorg rather than accumulating duplicates",
                "Replay from an arbitrary ledger for backfills",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.EXPERT,
        "1500",
        ["rust", "soroban", "postgresql", "indexing"],
        ["indexing", "infrastructure"],
        days_to_apply=30,
        days_to_complete=80,
        stage="draft",
    ),
    SeedBounty(
        "sms-fallback-notifications",
        "grace-wanjiru",
        "Add SMS fallback when a push notification is not delivered",
        "If a push notification is not acknowledged within ten minutes, send the important ones by SMS.",
        _desc(
            "Push is unreliable for our users — old devices, aggressive battery savers, and long periods "
            "offline. The payout notifications matter enough to pay for SMS.",
            [
                "Delivery acknowledgement from the client, with a sensible definition of delivered",
                "A ten-minute fallback window, configurable per notification type",
                "Only the notification types marked important fall back, not all of them",
                "Per-user daily SMS cap so a bug cannot bankrupt us",
                "Cost reporting by notification type",
            ],
        ),
        Category.DEVELOPMENT,
        Difficulty.INTERMEDIATE,
        "400",
        ["python", "celery", "sms", "notifications"],
        ["notifications", "sms"],
        days_to_apply=16,
        days_to_complete=38,
        applicants=[
            SeedApplication(
                "tariq-benali",
                "The daily cap is the requirement I would build first, before the fallback itself. A retry "
                "loop with a billing side effect is the kind of bug that is expensive in a way that ordinary "
                "bugs are not.",
            ),
            SeedApplication(
                "gabriel-mensah",
                "Worth defining delivered carefully — push acknowledgement from the platform means it reached "
                "the device, not that the user saw it. If you fall back on platform acknowledgement you will "
                "under-send, and if you fall back on user interaction you will over-send.",
            ),
            SeedApplication(
                "daniel-okonkwo",
                "Happy to take this. I would put the fallback decision in a scheduled job keyed on the "
                "notification rather than a delayed task per notification, because a delayed task per "
                "notification gets unmanageable at volume.",
            ),
        ],
    ),
]


# --- Bounty Q&A -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedAnswer:
    key: str
    author: str
    body: str
    hours_after: int = 6
    accepted: bool = False
    upvoters: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SeedQuestion:
    key: str
    bounty: str
    author: str
    body: str
    days_ago: int = 5
    pinned: bool = False
    upvoters: list[str] = field(default_factory=list)
    answers: list[SeedAnswer] = field(default_factory=list)


QUESTIONS: list[SeedQuestion] = [
    SeedQuestion(
        "q-wallet-providers",
        "wallet-connect-flow",
        "mateo-silva",
        "Is this Freighter only, or do you want the connect flow abstracted so xBull and Albedo can be added "
        "later? It changes how much of the state I would pull out of the component.",
        days_ago=9,
        upvoters=["kai-tanaka", "maya-goldberg", "linh-nguyen"],
        answers=[
            SeedAnswer(
                "a-wallet-providers",
                "ada-okafor",
                "Freighter only for this piece of work, but please put the provider behind an interface. We "
                "will almost certainly add xBull in the next quarter and I would rather not pay for it twice.",
                hours_after=5,
                accepted=True,
                upvoters=["mateo-silva", "kai-tanaka"],
            )
        ],
    ),
    SeedQuestion(
        "q-wallet-tests",
        "wallet-connect-flow",
        "ravi-deshmukh",
        "Do you want the tests to run against a mocked Freighter object, or is there an existing test harness "
        "in the repository I should use?",
        days_ago=7,
        answers=[
            SeedAnswer(
                "a-wallet-tests",
                "ada-okafor",
                "There is a harness in test/wallet that stubs the injected object. It is undocumented, which "
                "is partly why this bounty exists — a short README for it would be welcome alongside.",
                hours_after=20,
            )
        ],
    ),
    SeedQuestion(
        "q-audit-scope",
        "soroban-audit",
        "yusuf-bello",
        "Is the contract frozen for the duration of the audit? Reviewing a moving target usually means "
        "re-reviewing half of it at the end.",
        days_ago=11,
        pinned=True,
        upvoters=["sol-adeyemi", "karan-mehta", "lior-ben-ami", "nina-schneider"],
        answers=[
            SeedAnswer(
                "a-audit-scope",
                "nova-labs",
                "Yes. We will tag a commit at the start and any change after that goes into a follow-up "
                "review rather than this one.",
                hours_after=3,
                accepted=True,
                upvoters=["yusuf-bello", "sol-adeyemi", "karan-mehta"],
            ),
            SeedAnswer(
                "a-audit-scope-2",
                "karan-mehta",
                "Worth asking whether the tests are in scope too. A contract with a thin test suite takes "
                "longer to review because you cannot lean on the tests to tell you the intent.",
                hours_after=9,
                upvoters=["yusuf-bello"],
            ),
        ],
    ),
    SeedQuestion(
        "q-audit-report-format",
        "soroban-audit",
        "nina-schneider",
        "What severity scale do you want? I normally use CVSS adapted for contracts, but if you have an "
        "internal scale I would rather match it.",
        days_ago=6,
        answers=[
            SeedAnswer(
                "a-audit-report-format",
                "nova-labs",
                "Use whatever you normally use, but please state the scale in the report. We have had two "
                "audits with incompatible severity labels and comparing them was miserable.",
                hours_after=14,
            )
        ],
    ),
    SeedQuestion(
        "q-sep24-wallets",
        "sep24-deposit-ui",
        "kai-tanaka",
        "Which wallets are you testing against? The interactive flow behaves differently in an in-app "
        "browser than in a real one, and that affects how the resume-after-close requirement can work.",
        days_ago=8,
        upvoters=["mateo-silva", "linh-nguyen"],
        answers=[
            SeedAnswer(
                "a-sep24-wallets",
                "helio-collective",
                "Three wallet partners, two of which open us in an in-app browser. That is exactly why the "
                "resume requirement is in the brief — in-app browsers lose state more often than not.",
                hours_after=7,
                accepted=True,
                upvoters=["kai-tanaka", "mateo-silva"],
            )
        ],
    ),
    SeedQuestion(
        "q-sep24-copy",
        "sep24-deposit-ui",
        "leila-haddadi",
        "Who owns the French copy? I can write it, but if it has to be reviewed by a compliance team I would "
        "like to know the turnaround before quoting a timeline.",
        days_ago=5,
        answers=[
            SeedAnswer(
                "a-sep24-copy",
                "helio-collective",
                "We own it and our review is quick, usually a day. The regulated phrases are already agreed "
                "and we will hand them over as fixed strings.",
                hours_after=11,
            )
        ],
    ),
    SeedQuestion(
        "q-multisig-contract-accounts",
        "multisig-policy-editor",
        "matias-ovalle",
        "Following up on my application: do you need contract accounts as signers in this version, or is it "
        "classic ed25519 signers only? I would scope quite differently.",
        days_ago=4,
        upvoters=["kai-tanaka", "lior-ben-ami"],
        answers=[
            SeedAnswer(
                "a-multisig-contract-accounts",
                "aurora-ledger",
                "Classic signers only for this version. Two customers have asked about contract accounts so "
                "we will get there, but not in this piece of work.",
                hours_after=6,
                accepted=True,
                upvoters=["matias-ovalle"],
            )
        ],
    ),
    SeedQuestion(
        "q-multisig-design",
        "multisig-policy-editor",
        "ines-moreau",
        "Is there an existing design system I should work within, or is this a greenfield surface? Your "
        "screenshots look like a system but I do not want to assume.",
        days_ago=3,
        answers=[
            SeedAnswer(
                "a-multisig-design",
                "aurora-ledger",
                "There is a system, though it has no pattern for anything like this. Working within its "
                "tokens and inventing the rest is the right approach.",
                hours_after=16,
            )
        ],
    ),
    SeedQuestion(
        "q-orderbook-venue",
        "orderbook-stream-client",
        "elena-petrova",
        "Is this against one venue's feed or does it need to be generic across several? A generic client "
        "costs maybe forty percent more and is often not worth it.",
        days_ago=10,
        upvoters=["ahmed-farouk", "wei-zhang"],
        answers=[
            SeedAnswer(
                "a-orderbook-venue",
                "hiroshi-endo",
                "One venue. I agree with your instinct — we tried generic once and got something that was "
                "mediocre everywhere.",
                hours_after=4,
                accepted=True,
                upvoters=["elena-petrova", "ahmed-farouk"],
            )
        ],
    ),
    SeedQuestion(
        "q-orderbook-language",
        "orderbook-stream-client",
        "wei-zhang",
        "The brief says Go. Is that a hard requirement or a preference? I would deliver this faster in Rust "
        "but I understand if it has to fit your stack.",
        days_ago=6,
        answers=[
            SeedAnswer(
                "a-orderbook-language",
                "hiroshi-endo",
                "Hard requirement. Everything else on this path is Go and the people who will maintain it "
                "after you are Go engineers.",
                hours_after=8,
                accepted=True,
            )
        ],
    ),
    SeedQuestion(
        "q-webhook-volume",
        "webhook-retry-queue",
        "wei-zhang",
        "What is the peak delivery rate and how long do you want failed deliveries retained? Those two "
        "numbers decide whether this is a Redis-backed queue or needs something durable underneath.",
        days_ago=7,
        upvoters=["tariq-benali", "elena-petrova"],
        answers=[
            SeedAnswer(
                "a-webhook-volume",
                "ada-okafor",
                "Peak is about 900 a minute and we would like 30 days of retention on failures. Storage is "
                "not the constraint; being able to answer a customer asking what happened three weeks ago is.",
                hours_after=5,
                accepted=True,
                upvoters=["wei-zhang", "tariq-benali", "elena-petrova"],
            )
        ],
    ),
    SeedQuestion(
        "q-webhook-ordering",
        "webhook-retry-queue",
        "gabriel-mensah",
        "Will you document the ordering guarantee, or is that out of scope? As an integrator this is the "
        "single thing I most want stated clearly.",
        days_ago=4,
        upvoters=["felipe-cardozo"],
        answers=[
            SeedAnswer(
                "a-webhook-ordering",
                "ada-okafor",
                "In scope. Whatever we end up with, the guarantee goes in the public documentation as part "
                "of this work.",
                hours_after=13,
            )
        ],
    ),
    SeedQuestion(
        "q-a11y-split",
        "accessibility-audit-wcag",
        "aiko-matsumoto",
        "Would you consider splitting this across two auditors, one project each for two of us and the third "
        "shared? Three careful audits is a lot for one person in the window you have set.",
        days_ago=8,
        upvoters=["zara-iqbal", "ines-moreau"],
        answers=[
            SeedAnswer(
                "a-a11y-split",
                "anneke-visser",
                "I would consider it. Send me a note on how you would divide the reporting so the three do "
                "not come back in three different formats, and I will look at raising the positions to two.",
                hours_after=22,
                upvoters=["aiko-matsumoto", "zara-iqbal"],
            )
        ],
    ),
    SeedQuestion(
        "q-a11y-automated",
        "accessibility-audit-wcag",
        "zara-iqbal",
        "Have the projects already run an automated scan? If not I would run one first so the manual time "
        "goes on what a scanner cannot see.",
        days_ago=5,
        answers=[
            SeedAnswer(
                "a-a11y-automated",
                "anneke-visser",
                "Two of the three have axe in CI. The third has nothing, so plan for a scan there.",
                hours_after=9,
                accepted=True,
            )
        ],
    ),
    SeedQuestion(
        "q-rtl-scope",
        "arabic-rtl-audit",
        "zara-iqbal",
        "How many screens is this in total? The brief says every screen and I would like to size it honestly "
        "before applying properly.",
        days_ago=6,
        answers=[
            SeedAnswer(
                "a-rtl-scope",
                "fatima-el-amrani",
                "Sixty-two screens, of which about forty are simple. I can send the inventory to anyone who "
                "asks — it is a spreadsheet with a screenshot per screen.",
                hours_after=4,
                accepted=True,
                upvoters=["zara-iqbal", "leila-haddadi"],
            )
        ],
    ),
    SeedQuestion(
        "q-ussd-aggregator",
        "ussd-balance-check",
        "gabriel-mensah",
        "Which aggregator are you on? I asked in my application but it is probably useful publicly — the "
        "session model differs enough that it changes what is possible.",
        days_ago=7,
        upvoters=["kwame-asante", "grace-wanjiru"],
        answers=[
            SeedAnswer(
                "a-ussd-aggregator",
                "helio-collective",
                "Two, unfortunately, depending on the market. We would want the handler abstracted over both "
                "rather than two separate services.",
                hours_after=10,
                accepted=True,
                upvoters=["gabriel-mensah", "kwame-asante"],
            )
        ],
    ),
    SeedQuestion(
        "q-pagination-repro",
        "fix-pagination-bug",
        "daniel-okonkwo",
        "Is there a reproduction case attached anywhere, or do I start from the report? Knowing the page size "
        "the users hit it at would save me a day.",
        days_ago=5,
        answers=[
            SeedAnswer(
                "a-pagination-repro",
                "ada-okafor",
                "It shows up at page size 50 on accounts with more than about 10,000 transactions. I have "
                "attached the two account IDs to the bounty links.",
                hours_after=6,
                accepted=True,
                upvoters=["daniel-okonkwo", "river-chen"],
            )
        ],
    ),
    SeedQuestion(
        "q-import-banks",
        "csv-import-reconciler",
        "jonas-weber",
        "How many distinct bank formats do you need on day one? Saved mappings are easy; guessing the "
        "mapping automatically is a much bigger job.",
        days_ago=4,
        answers=[
            SeedAnswer(
                "a-import-banks",
                "aurora-ledger",
                "Six on day one and no automatic guessing. A human mapping the columns once per bank is "
                "completely acceptable.",
                hours_after=7,
                accepted=True,
                upvoters=["jonas-weber", "felipe-cardozo"],
            )
        ],
    ),
    SeedQuestion(
        "q-flake-history",
        "ci-flake-hunt",
        "ravi-deshmukh",
        "Do you have six months of structured run history, or would the first job be building the data set to "
        "find the flakiest tests from?",
        days_ago=3,
        upvoters=["ana-melo"],
        answers=[
            SeedAnswer(
                "a-flake-history",
                "piotr-kaczmarek",
                "We have the raw JUnit XML for six months but nothing that aggregates it. Building that is "
                "part of the work and honestly may be the most valuable part.",
                hours_after=5,
                accepted=True,
                upvoters=["ravi-deshmukh", "ana-melo", "oscar-lindqvist"],
            )
        ],
    ),
    SeedQuestion(
        "q-video-length",
        "agent-onboarding-video",
        "natalia-sokolova",
        "Is the 40MB limit per video or for the whole set? If it is for the set I would plan this as three "
        "shorter videos instead of one.",
        days_ago=6,
        answers=[
            SeedAnswer(
                "a-video-length",
                "dilnoza-usmanova",
                "Per video. Three shorter ones is an interesting idea though — agents share these one at a "
                "time and a three-minute clip travels further than an eight-minute one.",
                hours_after=18,
                upvoters=["natalia-sokolova"],
            )
        ],
    ),
    SeedQuestion(
        "q-sms-provider",
        "sms-fallback-notifications",
        "gabriel-mensah",
        "Which SMS provider, and is the per-user cap meant to be a hard block or a soft alert? A hard block "
        "means someone can miss a payout notification entirely.",
        days_ago=3,
        upvoters=["tariq-benali"],
        answers=[
            SeedAnswer(
                "a-sms-provider",
                "grace-wanjiru",
                "Africa's Talking in Kenya, Twilio elsewhere. Hard block, and I accept the trade-off — an "
                "account hitting the cap is already a bug and I would rather find out than pay for it.",
                hours_after=4,
                accepted=True,
                upvoters=["gabriel-mensah", "tariq-benali", "daniel-okonkwo"],
            )
        ],
    ),
    SeedQuestion(
        "q-invoice-fonts",
        "invoice-pdf-renderer",
        "tariq-benali",
        "Are the Tamil and Devanagari faces already licensed for embedding? That is usually a procurement "
        "question rather than an engineering one and it can take weeks.",
        days_ago=5,
        upvoters=["jonas-weber"],
        answers=[
            SeedAnswer(
                "a-invoice-fonts",
                "arun-ramaswamy",
                "Both are Noto, so embedding is fine. Good question though — we got caught by exactly this "
                "with a commercial face last year.",
                hours_after=3,
                accepted=True,
                upvoters=["tariq-benali", "jonas-weber"],
            )
        ],
    ),
    SeedQuestion(
        "q-bluegreen-services",
        "k8s-blue-green",
        "omar-haddad",
        "Do the three services share a database or have one each? Blue-green is a completely different "
        "problem if they share.",
        days_ago=4,
        upvoters=["ana-melo"],
        answers=[
            SeedAnswer(
                "a-bluegreen-services",
                "piotr-kaczmarek",
                "Two share one database, the third has its own. I know that is the awkward answer.",
                hours_after=6,
                accepted=True,
                upvoters=["omar-haddad", "ana-melo"],
            )
        ],
    ),
    SeedQuestion(
        "q-survey-recruitment",
        "oss-contributor-survey",
        "hana-suzuki",
        "Can you share how you plan to reach the 300? If it is through the projects' own channels the sample "
        "is already selected for people who stayed engaged.",
        days_ago=7,
        upvoters=["aminata-traore"],
        answers=[
            SeedAnswer(
                "a-survey-recruitment",
                "anneke-visser",
                "Through commit history and a direct email, not the project channels. Your point stands "
                "though — the email addresses we have are the ones people used to contribute, and some will "
                "be dead.",
                hours_after=12,
                accepted=True,
                upvoters=["hana-suzuki"],
            )
        ],
    ),
]


# --- Bookmarks --------------------------------------------------------------------------------------------

# Who has saved what. Only published bounties: a draft is not visible to anyone but its requester.
BOOKMARKS: dict[str, list[str]] = {
    "kai-tanaka": ["soroban-audit", "multisig-policy-editor", "sep24-deposit-ui", "wallet-sdk-examples"],
    "river-chen": ["webhook-retry-queue", "kafka-consumer-docs", "ledger-export-csv"],
    "mira-kovac": ["onboarding-redesign", "recipient-picker-ux", "settlement-report-redesign"],
    "sol-adeyemi": ["soroban-audit", "faucet-abuse-review", "webhook-signature-bug", "topup-threat-model"],
    "yusuf-bello": ["soroban-audit", "fee-research"],
    "elena-petrova": ["orderbook-stream-client", "webhook-retry-queue", "withdrawal-replay-bug"],
    "mateo-silva": ["sep24-deposit-ui", "arabic-rtl-audit", "hackathon-starter-template"],
    "aiko-matsumoto": ["accessibility-audit-wcag", "motion-guidelines"],
    "daniel-okonkwo": ["ledger-export-csv", "fix-pagination-bug", "sms-fallback-notifications"],
    "sana-qureshi": ["agent-liquidity-report", "corridor-seasonality", "reconciliation-mismatch"],
    "linh-nguyen": ["low-bandwidth-audit", "id-verification-flow", "recipient-picker-ux"],
    "oscar-lindqvist": ["grafana-dashboards", "ops-alert-triage-playbook", "ci-flake-hunt"],
    "amara-diallo": ["sdk-v3-migration-guide", "cold-wallet-runbook", "passkey-explainer-post"],
    "ravi-deshmukh": ["ci-flake-hunt", "csv-timezone-bug"],
    "nina-schneider": ["topup-threat-model", "faucet-abuse-review", "webhook-signature-bug"],
    "tobias-berg": ["fee-research", "cli-shell-completions", "horizon-backoff-client"],
    "carmen-ortiz": ["onboarding-redesign", "invoice-empty-states", "id-verification-flow"],
    "wei-zhang": ["orderbook-stream-client", "kafka-consumer-docs"],
    "gabriel-mensah": ["ussd-balance-check", "mobile-money-bridge", "sms-fallback-notifications"],
    "isabela-rocha": ["i18n-support", "pt-br-localization", "number-format-bug"],
    "omar-haddad": ["k8s-blue-green"],
    "freya-nilsen": ["low-bandwidth-audit"],
    "karan-mehta": ["soroban-audit", "fee-research"],
    "hana-suzuki": ["oss-contributor-survey", "id-verification-flow"],
    "emeka-nwosu": ["sdk-v3-migration-guide", "tax-field-research"],
    "lior-ben-ami": ["soroban-audit", "webhook-signature-bug", "passkey-explainer-post"],
    "marta-kowalska": ["treasury-dashboard-charts", "settlement-report-redesign", "icon-set-audit"],
    "ahmed-farouk": ["orderbook-stream-client", "horizon-backoff-client"],
    "sofia-marchetti": ["sdk-v3-migration-guide", "wallet-sdk-examples", "cli-shell-completions"],
    "tariq-benali": ["webhook-retry-queue", "invoice-pdf-renderer", "sms-fallback-notifications"],
    "mei-lin-koh": ["tax-field-research", "pix-offramp-spike"],
    "pablo-navarro": ["motion-guidelines"],
    "zara-iqbal": ["accessibility-audit-wcag", "arabic-rtl-audit"],
    "ana-melo": ["cold-wallet-runbook", "ops-alert-triage-playbook", "ci-flake-hunt"],
    "jonas-weber": ["invoice-pdf-renderer", "csv-import-reconciler", "csv-timezone-bug"],
    "leila-haddadi": ["arabic-rtl-audit", "kyc-copy-rewrite"],
    "daniela-vargas": ["kyc-copy-rewrite", "invoice-empty-states"],
    "samuel-adeniyi": ["community-workshop", "meetup-starter-kit", "agent-training-deck"],
    "natalia-sokolova": ["agent-onboarding-video", "conference-talk-review"],
    "arjun-pillai": ["refund-duplicate-rows", "reconciliation-mismatch"],
    "maya-goldberg": ["multisig-policy-editor", "motion-guidelines", "hackathon-starter-template"],
    "felipe-cardozo": ["csv-import-reconciler", "reconciliation-mismatch", "mobile-money-bridge"],
    "aminata-traore": ["low-bandwidth-audit", "oss-contributor-survey", "agent-liquidity-report"],
    "grace-wanjiru": ["ussd-balance-check", "mobile-money-bridge"],
    "kwame-asante": ["ussd-balance-check", "hackathon-starter-template"],
    "siti-rahayu": ["recipient-picker-ux", "invoice-empty-states"],
    "matias-ovalle": ["multisig-policy-editor", "fee-research"],
    "ines-moreau": ["accessibility-audit-wcag", "icon-set-audit"],
}


# --- Saved searches ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedSearch:
    key: str
    user: str
    name: str
    filters: dict[str, object]
    frequency: AlertFrequency = AlertFrequency.DAILY
    notify_in_app: bool = True
    notify_email: bool = False
    paused: bool = False


SAVED_SEARCHES: list[SeedSearch] = [
    SeedSearch(
        "rust-expert",
        "yusuf-bello",
        "Rust and Soroban, 500+",
        {"skills": ["rust", "soroban"], "min_reward": "500", "sort": "reward_high"},
        frequency=AlertFrequency.INSTANT,
        notify_email=True,
    ),
    SeedSearch(
        "audit-work",
        "sol-adeyemi",
        "Security audits",
        {"category": ["SECURITY", "BUG_BOUNTY"], "difficulty": ["ADVANCED", "EXPERT"]},
        frequency=AlertFrequency.INSTANT,
        notify_email=True,
    ),
    SeedSearch(
        "design-systems",
        "ines-moreau",
        "Design system work",
        {"category": ["DESIGN"], "tags": ["design-system"]},
        frequency=AlertFrequency.WEEKLY,
    ),
    SeedSearch(
        "a11y-anywhere",
        "zara-iqbal",
        "Anything accessibility",
        {"q": "accessibility", "sort": "newest"},
        frequency=AlertFrequency.DAILY,
        notify_email=True,
    ),
    SeedSearch(
        "quick-frontend",
        "mateo-silva",
        "Frontend, under three weeks",
        {"skills": ["react", "typescript"], "deadline_within_days": 21},
    ),
    SeedSearch(
        "writing-gigs",
        "amara-diallo",
        "Documentation and writing",
        {"category": ["DOCUMENTATION"], "sort": "newest"},
        frequency=AlertFrequency.DAILY,
    ),
    SeedSearch(
        "beginner-friendly",
        "samuel-adeniyi",
        "Good first bounties",
        {"difficulty": ["BEGINNER"], "sort": "newest"},
        frequency=AlertFrequency.WEEKLY,
    ),
    SeedSearch(
        "payments-integration",
        "felipe-cardozo",
        "Payments and reconciliation",
        {"tags": ["payments", "reconciliation"], "min_reward": "200"},
        frequency=AlertFrequency.INSTANT,
    ),
    SeedSearch(
        "infra-deep",
        "omar-haddad",
        "Infrastructure, advanced",
        {"category": ["OTHER"], "difficulty": ["ADVANCED", "EXPERT"], "min_reward": "400"},
    ),
    SeedSearch(
        "data-and-research",
        "sana-qureshi",
        "Research with real data",
        {"category": ["RESEARCH"], "sort": "reward_high"},
        frequency=AlertFrequency.WEEKLY,
        notify_email=True,
    ),
    SeedSearch(
        "localization",
        "isabela-rocha",
        "Localization and i18n",
        {"q": "localization", "tags": ["localization", "i18n"]},
        frequency=AlertFrequency.DAILY,
    ),
    SeedSearch(
        "mobile-only",
        "linh-nguyen",
        "Mobile work",
        {"tags": ["mobile"], "sort": "newest"},
    ),
    SeedSearch(
        "big-contracts",
        "matias-ovalle",
        "Over 1000, expert",
        {"min_reward": "1000", "difficulty": ["EXPERT"], "sort": "reward_high"},
        frequency=AlertFrequency.INSTANT,
        notify_email=True,
    ),
    SeedSearch(
        "community-events",
        "natalia-sokolova",
        "Community and training",
        {"category": ["COMMUNITY"]},
        frequency=AlertFrequency.WEEKLY,
    ),
    SeedSearch(
        "paused-for-now",
        "ravi-deshmukh",
        "Testing and CI",
        {"tags": ["ci", "testing"]},
        frequency=AlertFrequency.DAILY,
        paused=True,
    ),
    SeedSearch(
        "kafka-streams",
        "wei-zhang",
        "Streaming and event systems",
        {"q": "streaming", "skills": ["kafka", "go"]},
        frequency=AlertFrequency.WEEKLY,
    ),
    SeedSearch(
        "postgres-work",
        "arjun-pillai",
        "Postgres and query performance",
        {"skills": ["postgresql"], "sort": "reward_high"},
        frequency=AlertFrequency.DAILY,
    ),
    SeedSearch(
        "everything-new",
        "morgan-reyes",
        "Everything new this week",
        {"sort": "newest"},
        frequency=AlertFrequency.DAILY,
        notify_email=True,
    ),
]


# --- Product feedback -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Device:
    """A plausible sender context. The user agent is what the server reads from the request header; the
    viewport is what the form reports. No IP address is stored anywhere — see the feedback model."""

    user_agent: str
    width: int
    height: int


DEVICES: dict[str, Device] = {
    "chrome-win": Device(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36",
        1920,
        947,
    ),
    "chrome-win-small": Device(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36",
        1366,
        625,
    ),
    "edge-win": Device(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
        1536,
        730,
    ),
    "safari-mac": Device(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.6 Safari/605.1.15",
        1512,
        857,
    ),
    "chrome-mac": Device(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36",
        1728,
        962,
    ),
    "firefox-linux": Device(
        "Mozilla/5.0 (X11; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0",
        2560,
        1329,
    ),
    "firefox-win": Device(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0",
        1440,
        768,
    ),
    "safari-iphone": Device(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.6 Mobile/15E148 Safari/604.1",
        390,
        664,
    ),
    "chrome-android": Device(
        "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Mobile Safari/537.36",
        412,
        823,
    ),
    "chrome-android-low": Device(
        "Mozilla/5.0 (Linux; Android 13; TECNO BF6) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Mobile Safari/537.36",
        360,
        720,
    ),
    "safari-ipad": Device(
        "Mozilla/5.0 (iPad; CPU OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.6 Safari/604.1",
        1024,
        1292,
    ),
}


@dataclass(frozen=True)
class SeedFeedback:
    key: str
    kind: FeedbackKind
    message: str
    path: str
    device: str
    hours_ago: int
    sender: str | None = None  # a signed-in account
    email: str | None = None  # a signed-out sender's reply address
    handled_by: str | None = None
    handled_note: str = ""
    handled_after_hours: int = 6
    # Sent from a bounty page: the slug is generated when the bounty is created, so the route is resolved at
    # seed time rather than written here. `path` above is the fallback if that bounty is missing.
    bounty: str = ""


FEEDBACK: list[SeedFeedback] = [
    SeedFeedback(
        "fb-filter-reset",
        FeedbackKind.BUG,
        "If I filter the marketplace by category and then open a bounty and press back, every filter is "
        "gone and I am at the top of the list again. I lose my place every single time.",
        "/bounties",
        "chrome-win",
        3,
        sender="mateo-silva",
    ),
    SeedFeedback(
        "fb-reward-sort",
        FeedbackKind.BUG,
        "Sorting by reward puts a 90 XLM bounty above a 1200 one. Looks like it is sorting the amount as "
        "text rather than as a number.",
        "/bounties",
        "firefox-linux",
        9,
        sender="arjun-pillai",
        handled_by="morgan-reyes",
        handled_note="Confirmed — the sort was comparing the formatted string. Fixed in this week's release "
        "and I replied to Arjun directly.",
        handled_after_hours=4,
    ),
    SeedFeedback(
        "fb-deadline-timezone",
        FeedbackKind.BUG,
        "The application deadline on a bounty shows a date with no timezone. I applied on what I thought was "
        "the last day and it had already closed. Please show the time and the zone.",
        "/bounties",
        "safari-mac",
        26,
        sender="karan-mehta",
        handled_by="priya-nair",
        handled_note="Real problem. Logged for the next UI pass; deadlines will render with the local time "
        "and an explicit UTC offset.",
        handled_after_hours=11,
        bounty="soroban-audit",
    ),
    SeedFeedback(
        "fb-draft-lost",
        FeedbackKind.BUG,
        "I spent forty minutes writing a bounty description, the session expired while I was reading "
        "something else, and hitting save took me to the login page and threw the whole thing away.",
        "/app/bounties/create",
        "chrome-mac",
        51,
        sender="lucas-ferreira",
        handled_by="morgan-reyes",
        handled_note="Worst kind of bug. The create form now keeps a local draft and restores it after "
        "sign-in. Apologised and asked him to try again.",
        handled_after_hours=7,
    ),
    SeedFeedback(
        "fb-mobile-table",
        FeedbackKind.BUG,
        "The applications table scrolls sideways on my phone and the status column is off screen, so I "
        "cannot tell which ones are still pending without rotating.",
        "/app/applications",
        "safari-iphone",
        14,
        sender="linh-nguyen",
    ),
    SeedFeedback(
        "fb-qa-markdown",
        FeedbackKind.BUG,
        "A code block in a question renders as a single long line on mobile instead of scrolling inside its "
        "own box. It pushes the whole page sideways.",
        "/bounties",
        "chrome-android",
        30,
        sender="ahmed-farouk",
        bounty="orderbook-stream-client",
    ),
    SeedFeedback(
        "fb-skill-autocomplete",
        FeedbackKind.BUG,
        "The skills field on my profile has no autocomplete, so I typed react.js and the marketplace filter "
        "for react does not match me. Two spellings of the same skill should not split the list.",
        "/app/profile",
        "chrome-win",
        44,
        email="d.bakker.dev@example.test",
        handled_by="priya-nair",
        handled_note="Merged the duplicate spellings in the skill graph and opened a ticket for an "
        "autocomplete on the field. Wrote back to say so.",
        handled_after_hours=19,
    ),
    SeedFeedback(
        "fb-notification-link",
        FeedbackKind.BUG,
        "A notification about a reply on my question links to the bounty but not to the question itself, so "
        "on a long thread I have to hunt for what changed.",
        "/app/notifications",
        "firefox-win",
        7,
        sender="gabriel-mensah",
    ),
    SeedFeedback(
        "fb-saved-search-count",
        FeedbackKind.BUG,
        "My saved search says three new matches but opening it shows nothing new. I think the count is not "
        "being cleared when I view it from the sidebar rather than the saved page.",
        "/app/saved",
        "chrome-win-small",
        20,
        sender="ravi-deshmukh",
        handled_by="morgan-reyes",
        handled_note="Reproduced. The sidebar link was not marking the search viewed. Fix is in review.",
        handled_after_hours=9,
    ),
    SeedFeedback(
        "fb-verify-email-loop",
        FeedbackKind.BUG,
        "Clicking the verification link in my email logs me out and sends me to sign in, and after signing "
        "in the banner still says my address is unverified. Took me three tries to get through.",
        "/verify-email",
        "safari-iphone",
        62,
        email="tanvir.h.mail@example.test",
        handled_by="morgan-reyes",
        handled_note="Caused by the token being consumed before the session was established on mobile "
        "Safari. Fixed and verified on a real device.",
        handled_after_hours=5,
    ),
    SeedFeedback(
        "fb-long-title-overflow",
        FeedbackKind.BUG,
        "A bounty with a very long title overflows its card on the marketplace grid and covers the reward "
        "amount underneath it.",
        "/bounties",
        "safari-ipad",
        38,
        sender="carmen-ortiz",
    ),
    SeedFeedback(
        "fb-back-button-admin",
        FeedbackKind.BUG,
        "In the admin feedback queue, changing the status filter and then pressing back does not restore the "
        "previous filter, it leaves the admin section entirely.",
        "/admin/feedback",
        "chrome-win",
        16,
        sender="priya-nair",
        handled_by="morgan-reyes",
        handled_note="The filter is not in the URL. Agreed it should be — queued behind the reports queue "
        "work.",
        handled_after_hours=27,
    ),
    SeedFeedback(
        "fb-cover-letter-limit",
        FeedbackKind.BUG,
        "The cover letter box does not tell you the character limit until you exceed it, and then it just "
        "refuses to submit without saying by how much.",
        "/bounties",
        "chrome-android",
        11,
        sender="tariq-benali",
        bounty="webhook-retry-queue",
    ),
    SeedFeedback(
        "fb-currency-rounding",
        FeedbackKind.BUG,
        "A reward of 1234.5678901 shows as 1234.57 on the card and 1234.5678901 on the detail page. One of "
        "those is wrong and for money I would rather see the full value everywhere.",
        "/bounties",
        "firefox-linux",
        33,
        sender="felipe-cardozo",
        handled_by="priya-nair",
        handled_note="Deliberate on the card for space, but he is right that it should be obvious it is "
        "truncated. Passed to design.",
        handled_after_hours=14,
    ),
    SeedFeedback(
        "fb-dark-contrast",
        FeedbackKind.BUG,
        "In dark mode the secondary text on the bounty detail page fails contrast against the background. "
        "Measured it at about 3.1:1 where it needs 4.5:1.",
        "/bounties",
        "chrome-mac",
        48,
        sender="zara-iqbal",
        handled_by="morgan-reyes",
        handled_note="Confirmed with the same measurement. Token adjusted and the whole dark palette "
        "rechecked while we were in there.",
        handled_after_hours=8,
        bounty="accessibility-audit-wcag",
    ),
    SeedFeedback(
        "fb-slow-analytics",
        FeedbackKind.BUG,
        "The analytics page takes about eleven seconds to load for me and shows an empty chart area the whole "
        "time, so it looks broken rather than slow.",
        "/app/analytics",
        "chrome-win",
        23,
        sender="zanele-mthembu",
    ),
    SeedFeedback(
        "fb-duplicate-notification",
        FeedbackKind.BUG,
        "I got the same application-received notification twice, about four seconds apart, for one "
        "application.",
        "/app/notifications",
        "edge-win",
        55,
        sender="arun-ramaswamy",
        handled_by="morgan-reyes",
        handled_note="Traced to a redelivered event with a null source id, which skipped the uniqueness "
        "check. Fixed at the consumer.",
        handled_after_hours=6,
    ),
    # --- Ideas ------------------------------------------------------------------------------------------
    SeedFeedback(
        "fb-idea-saved-filters",
        FeedbackKind.IDEA,
        "Let me save a search from the marketplace in one click instead of going to the saved page and "
        "rebuilding the filters by hand. The filters are already on screen.",
        "/bounties",
        "chrome-win",
        5,
        sender="isabela-rocha",
    ),
    SeedFeedback(
        "fb-idea-rate-card",
        FeedbackKind.IDEA,
        "It would help enormously to see the reward converted to a local currency estimate next to the XLM "
        "amount. I am doing the conversion in another tab every time.",
        "/bounties",
        "chrome-android-low",
        18,
        sender="kwame-asante",
        bounty="mobile-money-bridge",
    ),
    SeedFeedback(
        "fb-idea-application-template",
        FeedbackKind.IDEA,
        "A saved cover letter template would save me ten minutes per application. Not a generic one — my own "
        "text that I edit each time.",
        "/app/applications",
        "safari-mac",
        29,
        sender="amara-diallo",
        handled_by="priya-nair",
        handled_note="Good idea and cheap. Added to the applications backlog with her wording attached.",
        handled_after_hours=21,
    ),
    SeedFeedback(
        "fb-idea-rss",
        FeedbackKind.IDEA,
        "An RSS or Atom feed per saved search would let me read new bounties where I already read everything "
        "else, without another email subscription.",
        "/app/saved",
        "firefox-linux",
        41,
        sender="tobias-berg",
    ),
    SeedFeedback(
        "fb-idea-difficulty-explainer",
        FeedbackKind.IDEA,
        "The difficulty labels mean different things to different requesters. A one-line definition on hover "
        "would help people apply to the right things.",
        "/how-it-works",
        "chrome-win-small",
        13,
        email="p.okoye.writes@example.test",
    ),
    SeedFeedback(
        "fb-idea-timezone-profile",
        FeedbackKind.IDEA,
        "Let contributors show a timezone on their profile. As a requester I care a lot whether someone "
        "overlaps with my working day and there is no way to tell.",
        "/u/kai-tanaka",
        "chrome-mac",
        36,
        sender="hiroshi-endo",
        handled_by="morgan-reyes",
        handled_note="Agreed, and it pairs well with the availability field already sketched. On the profile "
        "roadmap for next quarter.",
        handled_after_hours=30,
    ),
    SeedFeedback(
        "fb-idea-withdraw-application",
        FeedbackKind.IDEA,
        "I would like to withdraw an application with a short note to the requester rather than silently. It "
        "feels rude to just disappear when my availability changes.",
        "/app/applications",
        "chrome-android",
        58,
        sender="hana-suzuki",
    ),
    SeedFeedback(
        "fb-idea-qa-subscribe",
        FeedbackKind.IDEA,
        "Let me follow a bounty's questions without bookmarking it. I want the answers but I am not saving it "
        "to apply later.",
        "/bounties",
        "safari-mac",
        22,
        sender="maya-goldberg",
        bounty="multisig-policy-editor",
    ),
    SeedFeedback(
        "fb-idea-markdown-preview",
        FeedbackKind.IDEA,
        "A preview tab on the bounty description editor. I write Markdown fine but I would still like to see "
        "it before publishing to sixty people.",
        "/app/bounties/create",
        "chrome-win",
        46,
        sender="anneke-visser",
        handled_by="priya-nair",
        handled_note="Already half built behind a flag. Told her roughly when it lands.",
        handled_after_hours=16,
    ),
    SeedFeedback(
        "fb-idea-bulk-reject",
        FeedbackKind.IDEA,
        "When I have picked someone, let me decline the other applicants in one action with one shared "
        "message. Doing it one at a time makes me put it off, which is worse for them.",
        "/app/bounties",
        "edge-win",
        27,
        sender="aurora-ledger",
    ),
    SeedFeedback(
        "fb-idea-email-digest-time",
        FeedbackKind.IDEA,
        "Let me choose what time the daily digest arrives. Mine turns up at 2am and is buried by morning.",
        "/app/settings",
        "chrome-android-low",
        34,
        sender="dilnoza-usmanova",
    ),
    SeedFeedback(
        "fb-idea-print-bounty",
        FeedbackKind.IDEA,
        "A print stylesheet for a bounty page. Two of my colleagues review these on paper and the current "
        "print output includes the whole navigation.",
        "/bounties",
        "firefox-win",
        66,
        email="ops.review.desk@example.test",
        handled_by="priya-nair",
        handled_note="Small and worth doing. Added to the design-polish list.",
        handled_after_hours=25,
        bounty="settlement-report-redesign",
    ),
    SeedFeedback(
        "fb-idea-keyboard-shortcuts",
        FeedbackKind.IDEA,
        "Keyboard shortcuts for the marketplace — j and k to move between results, enter to open. I browse "
        "this list a lot.",
        "/bounties",
        "firefox-linux",
        12,
        sender="elena-petrova",
    ),
    SeedFeedback(
        "fb-idea-contributor-badges",
        FeedbackKind.IDEA,
        "Some signal of who has actually completed work would help me decide between five similar "
        "applications. Not a score, just something verifiable.",
        "/app/bounties",
        "chrome-mac",
        70,
        sender="helio-collective",
        handled_by="morgan-reyes",
        handled_note="This is what the attestation work is for. Explained the plan and pointed at the public "
        "attestation page.",
        handled_after_hours=12,
    ),
    # --- Praise -----------------------------------------------------------------------------------------
    SeedFeedback(
        "fb-praise-questions",
        FeedbackKind.PRAISE,
        "The questions section on a bounty is the best thing here. I got a clear answer about scope in three "
        "hours and it stopped me writing an application for the wrong job.",
        "/bounties",
        "safari-mac",
        8,
        sender="yusuf-bello",
        bounty="soroban-audit",
    ),
    SeedFeedback(
        "fb-praise-no-wallet-required",
        FeedbackKind.PRAISE,
        "Being able to read everything and apply without connecting a wallet first is a relief. Most sites "
        "like this put the wallet in front of the door.",
        "/",
        "chrome-android",
        19,
        email="first.look.2026@example.test",
    ),
    SeedFeedback(
        "fb-praise-escrow-explainer",
        FeedbackKind.PRAISE,
        "The page explaining what happens to the money is unusually honest. It says what the platform cannot "
        "do, which is the part everyone else leaves out.",
        "/how-it-works",
        "chrome-win",
        31,
        sender="mei-lin-koh",
        handled_by="morgan-reyes",
        handled_note="Passed to the person who wrote it. Nothing to action, worth reading.",
        handled_after_hours=10,
    ),
    SeedFeedback(
        "fb-praise-keyboard",
        FeedbackKind.PRAISE,
        "I navigated the whole application flow with a keyboard and a screen reader without getting stuck "
        "once. That is rare enough that I wanted to say so.",
        "/app/applications",
        "firefox-win",
        43,
        sender="aiko-matsumoto",
    ),
    SeedFeedback(
        "fb-praise-fast",
        FeedbackKind.PRAISE,
        "The marketplace is fast on a bad connection, which is not something I get to say often. Filters "
        "apply without a full page reload and nothing jumps around while it loads.",
        "/bounties",
        "chrome-android-low",
        24,
        sender="aminata-traore",
    ),
    SeedFeedback(
        "fb-praise-copy",
        FeedbackKind.PRAISE,
        "Whoever wrote the empty state on the saved page — thank you. It told me what to do next instead of "
        "just telling me the list was empty.",
        "/app/saved",
        "safari-iphone",
        52,
        sender="daniela-vargas",
        handled_by="priya-nair",
        handled_note="Forwarded to content design. No action needed.",
        handled_after_hours=18,
    ),
    SeedFeedback(
        "fb-praise-admin-audit",
        FeedbackKind.PRAISE,
        "The audit log actually records who did what and when, in a format I can read. I have used admin "
        "tools where that was a wishlist item.",
        "/admin/audit-logs",
        "chrome-win",
        60,
        sender="priya-nair",
    ),
    SeedFeedback(
        "fb-praise-onboarding",
        FeedbackKind.PRAISE,
        "Signed up and posted my first bounty in under fifteen minutes with no support contact. The step "
        "that asks what you are here for made the rest of it make sense.",
        "/app/onboarding",
        "chrome-mac",
        15,
        sender="piotr-kaczmarek",
    ),
    SeedFeedback(
        "fb-praise-mobile",
        FeedbackKind.PRAISE,
        "Reviewed six applications on my phone on a train and did not once wish I had a laptop. The review "
        "screens hold up at this size.",
        "/app/bounties",
        "safari-iphone",
        37,
        sender="theo-lambert",
        handled_by="morgan-reyes",
        handled_note="Shared with the team that did the mobile pass. Closing.",
        handled_after_hours=20,
    ),
    SeedFeedback(
        "fb-praise-privacy-page",
        FeedbackKind.PRAISE,
        "The privacy page tells me exactly what is stored and lets me export it without emailing anyone. "
        "Genuinely the first time I have seen that work in one click.",
        "/app/privacy",
        "firefox-linux",
        68,
        sender="nina-schneider",
    ),
    # --- Other ------------------------------------------------------------------------------------------
    SeedFeedback(
        "fb-other-invoice",
        FeedbackKind.OTHER,
        "Question rather than feedback: if I complete a bounty, do you produce anything I can give my "
        "accountant, or do I invoice the requester myself?",
        "/app/payments",
        "chrome-win",
        21,
        sender="sofia-marchetti",
        handled_by="priya-nair",
        handled_note="Answered by email: the requester pays directly on-chain, the platform is not a party, "
        "and the transaction record is exportable. Suggested we add this to the FAQ.",
        handled_after_hours=13,
    ),
    SeedFeedback(
        "fb-other-tax",
        FeedbackKind.OTHER,
        "Is there any guidance on the tax treatment of a bounty reward in the EU? Not asking for advice, just "
        "whether anything exists that I could read.",
        "/guide",
        "chrome-win-small",
        47,
        email="questions.eu.2026@example.test",
        handled_by="morgan-reyes",
        handled_note="Replied that we do not publish tax guidance and cannot advise. Pointed at the "
        "transaction export as the record their accountant will want.",
        handled_after_hours=17,
    ),
    SeedFeedback(
        "fb-other-account-delete",
        FeedbackKind.OTHER,
        "I want to close my account but I have one open application. Does closing withdraw it, and does the "
        "requester see that I left?",
        "/app/privacy",
        "safari-mac",
        56,
        sender="pablo-navarro",
        handled_by="priya-nair",
        handled_note="Explained the deletion flow: open applications are withdrawn and the requester sees a "
        "withdrawal, not a name. He decided to keep the account for now.",
        handled_after_hours=9,
    ),
    SeedFeedback(
        "fb-other-partnership",
        FeedbackKind.OTHER,
        "We run a developer community of about 4,000 people in South East Asia and would like to talk about "
        "putting bounties in front of them. Who should I write to?",
        "/about",
        "chrome-win",
        72,
        email="programs.sea.network@example.test",
        handled_by="morgan-reyes",
        handled_note="Not a support request. Forwarded to partnerships and replied with an introduction.",
        handled_after_hours=23,
    ),
    SeedFeedback(
        "fb-other-wrong-category",
        FeedbackKind.OTHER,
        "There is a bounty in the design category that is clearly a development task. Not sure whether to "
        "report it or whether miscategorising is just something that happens.",
        "/bounties",
        "edge-win",
        28,
        sender="ines-moreau",
        handled_by="priya-nair",
        handled_note="Checked it, agreed, and asked the requester to recategorise rather than acting "
        "unilaterally. They did.",
        handled_after_hours=7,
    ),
    SeedFeedback(
        "fb-other-duplicate-account",
        FeedbackKind.OTHER,
        "I appear to have signed up twice with two addresses and I cannot merge them. The one with my "
        "applications is the one I want to keep.",
        "/app/settings",
        "chrome-android",
        64,
        email="m.lindgren.two@example.test",
    ),
    SeedFeedback(
        "fb-other-screenreader-question",
        FeedbackKind.OTHER,
        "Do you test with screen readers as part of your release process, or is accessibility handled by "
        "audits after the fact? Asking before I recommend this to a client.",
        "/about",
        "firefox-win",
        39,
        sender="zara-iqbal",
    ),
    SeedFeedback(
        "fb-other-api-access",
        FeedbackKind.OTHER,
        "Is there a public API for the marketplace listings? I would like to mirror open bounties into our "
        "internal board rather than asking people to check two places.",
        "/guide",
        "chrome-mac",
        50,
        sender="nova-labs",
        handled_by="morgan-reyes",
        handled_note="Pointed at the public listing endpoints and the rate limits. Asked them to tell us if "
        "the limits are too tight for a mirror.",
        handled_after_hours=11,
    ),
]


# --- Announcements ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedAnnouncement:
    """A platform notice. Nothing here implies chain activity: no funding, payout or assignment."""

    key: str
    recipients: tuple[str, ...]
    title: str
    message: str
    link: str
    days_ago: int
    read: bool = False


ANNOUNCEMENTS: list[SeedAnnouncement] = [
    SeedAnnouncement(
        "ann-feedback-form",
        PRIMARY_USERNAMES,
        "You can now send feedback from any page",
        "The button in the corner sends a note straight to the people who build this, with the page you were "
        "on. It works signed out too.",
        "/app/notifications",
        days_ago=6,
    ),
    SeedAnnouncement(
        "ann-saved-search-digests",
        ("yusuf-bello", "sol-adeyemi", "zara-iqbal", "sana-qureshi", "matias-ovalle", "isabela-rocha"),
        "Saved search digests are now configurable",
        "Choose instant, daily or weekly per search, and pause one without deleting it. Existing searches "
        "were left on daily.",
        "/app/saved",
        days_ago=11,
        read=True,
    ),
    SeedAnnouncement(
        "ann-qa-threads",
        ("ada-okafor", "nova-labs", "helio-collective", "aurora-ledger", "hiroshi-endo", "arun-ramaswamy"),
        "Questions on your bounties",
        "Anyone can ask a public question on an open bounty, and you can pin the answer that matters. "
        "Questions close automatically when the bounty does.",
        "/app/bounties",
        days_ago=15,
        read=True,
    ),
    SeedAnnouncement(
        "ann-accessibility-pass",
        ("aiko-matsumoto", "zara-iqbal", "ines-moreau", "mira-kovac", "carmen-ortiz"),
        "Contrast and focus fixes across the workspace",
        "Secondary text now meets AA in both themes, and every interactive element has a visible focus ring. "
        "Tell us what we missed.",
        "/app/notifications",
        days_ago=4,
    ),
    SeedAnnouncement(
        "ann-export-your-data",
        PRIMARY_USERNAMES,
        "Export everything we hold about you",
        "One click on the privacy page produces a complete export, including your bounties, applications, "
        "questions and saved searches.",
        "/app/privacy",
        days_ago=20,
        read=True,
    ),
]


# --- Seeding ----------------------------------------------------------------------------------------------


def _uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


async def _load_users(session: AsyncSession, usernames: list[str]) -> dict[str, User]:
    """Every account the seed cares about in one query, keyed by username (no lookup per user)."""
    rows = await session.scalars(select(User).where(User.username.in_(usernames)))
    return {u.username: u for u in rows.unique().all()}


async def _ensure_user(
    session: AsyncSession,
    spec: SeedUser,
    password_hash: str,
    existing: dict[str, User],
    summary: dict[str, int],
) -> User:
    user = existing.get(spec.username)
    if user is None and (legacy := LEGACY_USERNAMES.get(spec.username)):
        user = existing.get(legacy)
    if user is not None:
        if user.username == spec.username and not user.normalized_email.endswith(LEGACY_EMAIL_DOMAIN):
            return user
        # Upgrade an account created by an older seed into a normal account with a real sign-in.
        user.username = spec.username
        user.email = spec.email
        user.normalized_email = spec.email
        user.display_name = spec.display_name
        user.bio = spec.bio
        user.role = spec.role
        user.password_hash = password_hash
        await session.commit()
        summary["users_updated"] += 1
        return user
    now = utcnow()
    user = User(
        id=_uuid(f"user:{spec.username}"),
        email=spec.email,
        normalized_email=spec.email,
        password_hash=password_hash,
        email_verified_at=now,
        display_name=spec.display_name,
        username=spec.username,
        bio=spec.bio,
        github_url=spec.github,
        interests=spec.interests,
        role=spec.role,
        wants_to_request=spec.requester,
        wants_to_contribute=spec.contributor,
        onboarding_completed_at=now,
        skills=[UserSkill(skill_name=s) for s in spec.skills],
    )
    session.add(user)
    await session.flush()  # dependent rows reference users.id without an ORM relationship
    session.add(NotificationPreference(user_id=user.id, email_enabled=False, types={}))
    session.add(
        Notification(
            user_id=user.id,
            notification_type=NotificationType.SYSTEM,
            title="Welcome to BountyFlow",
            message="Connect a Stellar wallet from your profile to fund bounties or receive rewards.",
            link="/app/profile",
            payload={"seed": True},
        )
    )
    await session.commit()
    summary["users"] += 1
    return user


async def _seeded_keys(session: AsyncSession) -> set[str]:
    """The seed keys already in the database, in one query rather than one lookup per bounty."""
    keys = [b.key for b in BOUNTIES]
    rows: ScalarResult[str | None] = await session.scalars(
        select(Bounty.metadata_["seed_key"].astext).where(Bounty.metadata_["seed_key"].astext.in_(keys))
    )
    return {key for key in rows.all() if key}


async def _bounties_by_key(session: AsyncSession) -> dict[str, Bounty]:
    keys = [b.key for b in BOUNTIES]
    rows = await session.scalars(select(Bounty).where(Bounty.metadata_["seed_key"].astext.in_(keys)))
    return {str(b.metadata_["seed_key"]): b for b in rows.unique().all()}


async def _ensure_bounty(
    session: AsyncSession,
    spec: SeedBounty,
    users: dict[str, User],
    known: set[str],
    summary: dict[str, int],
) -> None:
    if spec.key in known:
        summary["bounties_existing"] += 1
        return
    requester = users[spec.requester]
    now = datetime.now(UTC)
    detail = await bounty_service.create_bounty(
        session,
        requester,
        BountyCreate(
            title=spec.title,
            short_description=spec.short,
            description=spec.description,
            category=spec.category,
            difficulty=spec.difficulty,
            tags=spec.tags,
            required_skills=spec.skills,
            reward_amount=spec.reward,
            positions_available=spec.positions,
            application_deadline=now + timedelta(days=spec.days_to_apply),
            completion_deadline=now + timedelta(days=spec.days_to_complete),
            acceptance_criteria=spec.acceptance or "Meets the scope above and passes review.",
            submission_requirements="Link to a pull request, document, or file with a short summary.",
            eligibility_criteria="Open to everyone.",
        ),
    )
    bounty = await session.get(Bounty, detail.id)
    assert bounty is not None
    bounty.is_featured = spec.key in FEATURED_KEYS
    bounty.metadata_ = {**(bounty.metadata_ or {}), "seed_key": spec.key}
    await session.commit()
    known.add(spec.key)
    summary["bounties_created"] += 1
    if spec.stage == "draft":
        return
    await bounty_service.publish(session, requester, bounty.id)

    for application in spec.applicants:
        await application_service.apply(
            session,
            users[application.username],
            bounty.id,
            ApplicationCreate(
                cover_message=application.cover,
                relevant_experience=application.experience or None,
            ),
        )
        summary["applications"] += 1


async def _ensure_questions(
    session: AsyncSession,
    bounties: dict[str, Bounty],
    users: dict[str, User],
    summary: dict[str, int],
) -> None:
    """Questions and answers, written straight to the table with deterministic ids.

    Only published bounties get a thread: on a draft the Q&A is closed, and seeding around that rule would
    produce a thread the product itself would refuse to create.
    """
    ids = [_uuid(f"qa:{q.key}") for q in QUESTIONS]
    ids += [_uuid(f"qa:{a.key}") for q in QUESTIONS for a in q.answers]
    existing = set((await session.scalars(select(BountyQAPost.id).where(BountyQAPost.id.in_(ids)))).all())
    now = datetime.now(UTC)
    pending: list[tuple[SeedQuestion, Bounty, datetime]] = []
    for spec in QUESTIONS:
        bounty = bounties.get(spec.bounty)
        if bounty is None or bounty.published_at is None:
            continue
        asked_at = now - timedelta(days=spec.days_ago)
        if _uuid(f"qa:{spec.key}") not in existing:
            session.add(
                BountyQAPost(
                    id=_uuid(f"qa:{spec.key}"),
                    bounty_id=bounty.id,
                    author_id=users[spec.author].id,
                    parent_id=None,
                    body=spec.body,
                    is_pinned=spec.pinned,
                    upvotes_count=len(spec.upvoters),
                    created_at=asked_at,
                    updated_at=asked_at,
                )
            )
            summary["questions"] += 1
        pending.append((spec, bounty, asked_at))
    await session.flush()  # the replies below reference the question rows by id

    for spec, bounty, asked_at in pending:
        for answer in spec.answers:
            if _uuid(f"qa:{answer.key}") in existing:
                continue
            written_at = asked_at + timedelta(hours=answer.hours_after)
            session.add(
                BountyQAPost(
                    id=_uuid(f"qa:{answer.key}"),
                    bounty_id=bounty.id,
                    author_id=users[answer.author].id,
                    parent_id=_uuid(f"qa:{spec.key}"),
                    body=answer.body,
                    is_accepted=answer.accepted,
                    upvotes_count=len(answer.upvoters),
                    created_at=written_at,
                    updated_at=written_at,
                )
            )
            summary["answers"] += 1
    await session.flush()

    votes = [
        {"post_id": _uuid(f"qa:{key}"), "user_id": users[voter].id}
        for key, voters in (
            [(q.key, q.upvoters) for q in QUESTIONS]
            + [(a.key, a.upvoters) for q in QUESTIONS for a in q.answers]
        )
        for voter in voters
        if _uuid(f"qa:{key}") not in existing and voter in users
    ]
    if votes:
        await session.execute(
            pg_insert(BountyQAVote)
            .values(votes)
            .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
        )
    await session.commit()


async def _ensure_bookmarks(
    session: AsyncSession,
    bounties: dict[str, Bounty],
    users: dict[str, User],
    summary: dict[str, int],
) -> None:
    rows = [
        {
            "id": _uuid(f"bookmark:{username}:{key}"),
            "user_id": users[username].id,
            "bounty_id": bounties[key].id,
        }
        for username, keys in BOOKMARKS.items()
        if username in users
        for key in keys
        if key in bounties and bounties[key].published_at is not None
    ]
    if not rows:
        return
    inserted = await session.scalars(
        pg_insert(BountyBookmark)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["user_id", "bounty_id"])
        .returning(BountyBookmark.id)
    )
    summary["bookmarks"] += len(inserted.all())
    # One statement re-derives the denormalised counter for the affected bounties; no per-bounty update.
    touched = list({row["bounty_id"] for row in rows})
    tally = (
        select(BountyBookmark.bounty_id.label("bounty_id"), func.count().label("total"))
        .where(BountyBookmark.bounty_id.in_(touched))
        .group_by(BountyBookmark.bounty_id)
        .subquery()
    )
    await session.execute(
        update(Bounty)
        .where(Bounty.id == tally.c.bounty_id, Bounty.bookmarks_count != tally.c.total)
        .values(bookmarks_count=tally.c.total, version_id=Bounty.version_id + 1)
        .execution_options(synchronize_session=False)
    )
    await session.commit()


async def _ensure_saved_searches(
    session: AsyncSession, users: dict[str, User], summary: dict[str, int]
) -> None:
    ids = [_uuid(f"search:{s.key}") for s in SAVED_SEARCHES]
    existing = set((await session.scalars(select(SavedSearch.id).where(SavedSearch.id.in_(ids)))).all())
    now = utcnow()
    for spec in SAVED_SEARCHES:
        search_id = _uuid(f"search:{spec.key}")
        if search_id in existing or spec.user not in users:
            continue
        session.add(
            SavedSearch(
                id=search_id,
                user_id=users[spec.user].id,
                name=spec.name,
                filters=SavedSearchFilters.model_validate(spec.filters).stored(),
                alert_frequency=spec.frequency,
                notify_in_app=spec.notify_in_app,
                notify_email=spec.notify_email,
                is_paused=spec.paused,
                last_viewed_at=now - timedelta(days=2),
                next_digest_at=None if spec.paused else next_digest_time(spec.frequency, now),
            )
        )
        summary["saved_searches"] += 1
    await session.commit()


async def _ensure_feedback(
    session: AsyncSession,
    bounties: dict[str, Bounty],
    users: dict[str, User],
    summary: dict[str, int],
) -> None:
    ids = [_uuid(f"feedback:{f.key}") for f in FEEDBACK]
    existing = set((await session.scalars(select(Feedback.id).where(Feedback.id.in_(ids)))).all())
    now = datetime.now(UTC)
    for spec in FEEDBACK:
        feedback_id = _uuid(f"feedback:{spec.key}")
        if feedback_id in existing:
            continue
        sender = users.get(spec.sender) if spec.sender else None
        handler = users.get(spec.handled_by) if spec.handled_by else None
        sent_at = now - timedelta(hours=spec.hours_ago)
        device = DEVICES[spec.device]
        from_bounty = bounties.get(spec.bounty) if spec.bounty else None
        path = f"/bounties/{from_bounty.slug}" if from_bounty else spec.path
        session.add(
            Feedback(
                id=feedback_id,
                user_id=sender.id if sender else None,
                # A signed-in sender is reachable through their account, so no address is stored beside it.
                email=None if sender else spec.email,
                kind=spec.kind,
                status=FeedbackStatus.HANDLED if handler else FeedbackStatus.NEW,
                message=spec.message,
                path=path,
                viewport_width=device.width,
                viewport_height=device.height,
                user_agent=device.user_agent,
                created_at=sent_at,
                handled_at=sent_at + timedelta(hours=spec.handled_after_hours) if handler else None,
                handled_by_id=handler.id if handler else None,
                handled_note=spec.handled_note or None if handler else None,
            )
        )
        summary["feedback"] += 1
    await session.commit()


async def _ensure_announcements(
    session: AsyncSession, users: dict[str, User], summary: dict[str, int]
) -> None:
    ids = [_uuid(f"notification:{a.key}:{username}") for a in ANNOUNCEMENTS for username in a.recipients]
    existing = set((await session.scalars(select(Notification.id).where(Notification.id.in_(ids)))).all())
    now = datetime.now(UTC)
    for spec in ANNOUNCEMENTS:
        sent_at = now - timedelta(days=spec.days_ago)
        for username in spec.recipients:
            notification_id = _uuid(f"notification:{spec.key}:{username}")
            if notification_id in existing or username not in users:
                continue
            session.add(
                Notification(
                    id=notification_id,
                    user_id=users[username].id,
                    notification_type=NotificationType.SYSTEM,
                    title=spec.title,
                    message=spec.message,
                    link=spec.link,
                    payload={"seed": True, "announcement": spec.key},
                    created_at=sent_at,
                    read_at=sent_at + timedelta(hours=9) if spec.read else None,
                )
            )
            summary["announcements"] += 1
    await session.commit()


async def seed() -> dict[str, int]:
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("Refusing to seed data outside development/test.")
    summary = {
        "users": 0,
        "users_updated": 0,
        "bounties_created": 0,
        "bounties_existing": 0,
        "applications": 0,
        "questions": 0,
        "answers": 0,
        "bookmarks": 0,
        "saved_searches": 0,
        "feedback": 0,
        "announcements": 0,
    }
    password_hash = hash_password(settings.seed_user_password)
    usernames = [spec.username for spec in USERS] + list(LEGACY_USERNAMES.values())
    async with get_sessionmaker()() as session:
        known_users = await _load_users(session, usernames)
        users: dict[str, User] = {}
        for spec in USERS:
            users[spec.username] = await _ensure_user(session, spec, password_hash, known_users, summary)
        known = await _seeded_keys(session)
        for bounty_spec in BOUNTIES:
            try:
                await _ensure_bounty(session, bounty_spec, users, known, summary)
            except Exception:
                await session.rollback()
                logger.exception("seed_bounty_failed", key=bounty_spec.key)
                # The rollback expired every ORM object in the session, including the cached users; touching
                # them in the next iteration would lazy-load outside the async context. Reload them.
                users = await _load_users(session, [spec.username for spec in USERS])
                known = await _seeded_keys(session)
        # Everything below hangs off the bounties above, so they are re-read once, together.
        bounties = await _bounties_by_key(session)
        await _ensure_questions(session, bounties, users, summary)
        await _ensure_bookmarks(session, bounties, users, summary)
        await _ensure_saved_searches(session, users, summary)
        await _ensure_feedback(session, bounties, users, summary)
        await _ensure_announcements(session, users, summary)
    return summary


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json, service="seed")

    async def _main() -> dict[str, int]:
        try:
            return await seed()
        finally:
            await close_redis()
            await dispose_engine()

    result = run_async(_main())
    logger.info("seed_complete", network=settings.network_label, **result)
    print_accounts(settings.seed_user_password)


def print_accounts(password: str) -> None:
    """Sign-in details for the seeded accounts (development only).

    Only the primary accounts are listed: one of each role plus both sides of the marketplace. The rest exist
    to populate the listings and share the same password, and printing sixty rows helps nobody.
    """
    primary = {spec.username: spec for spec in USERS}
    rows = [
        (spec.display_name, spec.email, spec.role.value.title())
        for username in PRIMARY_USERNAMES
        if (spec := primary.get(username)) is not None
    ]
    width = max(len(email) for _, email, _ in rows)
    lines = ["", "Seeded accounts (sign in at /login):", ""]
    lines += [f"  {email.ljust(width)}  {role.ljust(9)}  {name}" for name, email, role in rows]
    others = len(USERS) - len(rows)
    lines += ["", f"  and {others} more accounts, same password: name.surname@bountyflow.test"]
    lines += ["", f"  Password for every account: {password}", ""]
    text = chr(10).join(lines)
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")  # names like "Kovač" on a cp1252 console
    stream.write(text + chr(10))
    stream.flush()


if __name__ == "__main__":
    run()
