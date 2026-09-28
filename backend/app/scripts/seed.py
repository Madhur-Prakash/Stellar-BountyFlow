"""Deterministic, idempotent development seed.

    uv run python -m app.scripts.seed          # or: make seed
    SEED_ON_STARTUP=true                       # run automatically on every API start

Every record has a stable key (username, or `metadata.seed_key` for bounties). Existing records are left untouched and
only missing ones are created, so running the seed repeatedly is safe.

Data is created through the real domain services, so it always obeys the bounty state machine: users and profiles,
open and draft bounties, and pending applications. No chain history is ever fabricated — funding, assignment and
payouts only happen when a real wallet signs a real Stellar transaction.

Seeded users are ordinary accounts: each has a real email address and a password (`SEED_USER_PASSWORD`, default
`BountyFlow!2026`) and signs in through the normal login form. The emails use the reserved `.test` domain, so no message
can ever reach a real inbox by accident. `make seed` prints the sign-in details. Seeding is refused outside
development/test.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
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
from app.modules.bounties.models import Bounty, Category, Difficulty
from app.modules.bounties.schemas import BountyCreate
from app.modules.notifications.models import Notification, NotificationPreference, NotificationType
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


# Usernames used by earlier versions of the seed. An existing account under one of these is renamed in place, so its
# bounties, applications and history are kept.
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
]


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
    applicants: list[str] = field(default_factory=list)
    acceptance: str = ""


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
        applicants=["kai-tanaka"],
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
        applicants=["sol-adeyemi", "kai-tanaka"],
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
        applicants=["river-chen"],
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
        applicants=["mira-kovac"],
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
        applicants=["river-chen"],
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
        applicants=["kai-tanaka", "sol-adeyemi"],
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
        applicants=["priya-nair"],
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
        applicants=["kai-tanaka"],
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
]


def _uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


async def _ensure_user(
    session: AsyncSession, spec: SeedUser, password_hash: str, summary: dict[str, int]
) -> User:
    user = await session.scalar(select(User).where(User.username == spec.username))
    if user is None and (legacy := LEGACY_USERNAMES.get(spec.username)):
        user = await session.scalar(select(User).where(User.username == legacy))
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


async def _find_bounty(session: AsyncSession, key: str) -> Bounty | None:
    return await session.scalar(select(Bounty).where(Bounty.metadata_["seed_key"].astext == key))


async def _ensure_bounty(
    session: AsyncSession, spec: SeedBounty, users: dict[str, User], summary: dict[str, int]
) -> None:
    if await _find_bounty(session, spec.key) is not None:
        summary["bounties_existing"] += 1
        return
    stage = spec.stage
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
    bounty.is_featured = spec.key in {"soroban-audit", "wallet-connect-flow", "fee-research"}
    bounty.metadata_ = {**(bounty.metadata_ or {}), "seed_key": spec.key}
    await session.commit()
    summary["bounties_created"] += 1
    if stage == "draft":
        return
    await bounty_service.publish(session, requester, bounty.id)

    for username in spec.applicants:
        await application_service.apply(
            session,
            users[username],
            bounty.id,
            ApplicationCreate(
                cover_message=f"Hi! I'm {users[username].display_name}. I've shipped similar work and can "
                "start this week.",
                relevant_experience="Relevant portfolio and open-source contributions linked on my profile.",
            ),
        )


async def seed() -> dict[str, int]:
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("Refusing to seed data outside development/test.")
    summary = {"users": 0, "users_updated": 0, "bounties_created": 0, "bounties_existing": 0}
    password_hash = hash_password(settings.seed_user_password)
    async with get_sessionmaker()() as session:
        users: dict[str, User] = {}
        for spec in USERS:
            users[spec.username] = await _ensure_user(session, spec, password_hash, summary)
        for bounty_spec in BOUNTIES:
            try:
                await _ensure_bounty(session, bounty_spec, users, summary)
            except Exception:
                await session.rollback()
                logger.exception("seed_bounty_failed", key=bounty_spec.key)
                # The rollback expired every ORM object in the session, including the cached users; touching
                # them in the next iteration would lazy-load outside the async context. Reload them.
                loaded = await session.scalars(select(User).where(User.username.in_(list(users))))
                users = {u.username: u for u in loaded.all()}
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
    """Sign-in details for the seeded accounts (development only)."""
    rows = [(u.display_name, u.email, u.role.value.title()) for u in USERS]
    width = max(len(email) for _, email, _ in rows)
    lines = ["", "Seeded accounts (sign in at /login):", ""]
    lines += [f"  {email.ljust(width)}  {role.ljust(9)}  {name}" for name, email, role in rows]
    lines += ["", f"  Password for every account: {password}", ""]
    text = chr(10).join(lines)
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")  # names like "Kovač" on a cp1252 console
    stream.write(text + chr(10))
    stream.flush()


if __name__ == "__main__":
    run()
