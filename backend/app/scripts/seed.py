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
