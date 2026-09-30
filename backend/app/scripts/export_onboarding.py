"""Builds the onboarding workbook: who is on the platform, and what they have said about it.

    uv run python -m app.scripts.export_onboarding
    uv run python -m app.scripts.export_onboarding --form-csv ~/Downloads/responses.csv

Two sources feed it, and they are kept on separate sheets because they are not the same evidence:

* **In-product feedback** — rows people submitted through the feedback button, read straight from the
  `feedback` table. This is first-party and always present.
* **Google Form responses** — only when ``--form-csv`` points at a CSV exported from the form. Without
  that flag the sheet is written with its headers and a note saying no export was supplied. Nothing is
  ever invented to fill it: a workbook that implies responses nobody sent is worse than an empty one.

The participant sheet lists accounts with their verified Stellar address where one exists. It contains
personal data, so treat the output the way you would treat the database it came from.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.runtime import run_async
from app.db.session import dispose_engine, get_sessionmaker
from app.modules.feedback.models import Feedback
from app.modules.users.models import User, Wallet

logger = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1B1A17")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)

# The columns a Google Form built to the spec in docs/user-onboarding.md exports.
FORM_COLUMNS = [
    "Timestamp",
    "Full name",
    "Email address",
    "Stellar wallet address (public key)",
    "How did you use BountyFlow?",
    "Overall rating",
    "Ease of connecting a wallet and moving money",
    "Likelihood to recommend",
    "Kind of feedback",
    "What worked, and what did not?",
    "If you could change one thing, what would it be?",
]


@dataclass(frozen=True)
class Sheet:
    title: str
    headers: list[str]
    rows: list[list[Any]]
    widths: list[int]
    note: str = ""


def _write(wb: Workbook, sheet: Sheet, first: bool) -> None:
    ws: Worksheet = wb.active if first else wb.create_sheet()
    ws.title = sheet.title
    row = 1
    if sheet.note:
        ws.cell(row=1, column=1, value=sheet.note).font = Font(italic=True, color="6B6A75")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(sheet.headers)))
        row = 3
    for col, name in enumerate(sheet.headers, start=1):
        cell = ws.cell(row=row, column=col, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for r, values in enumerate(sheet.rows, start=row + 1):
        for c, value in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=value).alignment = Alignment(vertical="top", wrap_text=c > 2)
    for i, width in enumerate(sheet.widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    ws.auto_filter.ref = f"A{row}:{get_column_letter(max(1, len(sheet.headers)))}{row + len(sheet.rows)}"


def _naive(value: datetime | None) -> datetime | None:
    """Excel cannot store a timezone, so timestamps are written as UTC without one."""
    return value.astimezone(UTC).replace(tzinfo=None) if value else None


async def _collect(form_csv: Path | None) -> tuple[list[Sheet], dict[str, int]]:
    async with get_sessionmaker()() as session:
        # One statement per sheet, each with its joins, rather than a query per row.
        wallet_col = (
            select(Wallet.public_address)
            .where(Wallet.user_id == User.id, Wallet.revoked_at.is_(None))
            .order_by(Wallet.is_primary.desc(), Wallet.verified_at.asc())
            .limit(1)
            .scalar_subquery()
        )
        people = (
            await session.execute(
                select(
                    User.display_name,
                    User.username,
                    User.email,
                    User.role,
                    wallet_col.label("wallet"),
                    User.wants_to_request,
                    User.wants_to_contribute,
                    User.email_verified_at,
                    User.created_at,
                )
                .where(User.is_active.is_(True))
                .order_by(User.created_at.asc())
            )
        ).all()

        handler = User.__table__.alias("handler")
        notes = (
            await session.execute(
                select(
                    Feedback.created_at,
                    Feedback.kind,
                    Feedback.status,
                    Feedback.message,
                    User.display_name.label("sender"),
                    Feedback.email,
                    Feedback.path,
                    Feedback.viewport_width,
                    Feedback.viewport_height,
                    Feedback.handled_at,
                    handler.c.display_name.label("handled_by"),
                    Feedback.handled_note,
                )
                .select_from(Feedback)
                .outerjoin(User, User.id == Feedback.user_id)
                .outerjoin(handler, handler.c.id == Feedback.handled_by_id)
                .order_by(Feedback.created_at.desc())
            )
        ).all()

        wallets = await session.scalar(select(func.count(Wallet.id)).where(Wallet.revoked_at.is_(None)))

    participants = Sheet(
        "Participants",
        ["Name", "Username", "Email", "Role", "Stellar wallet", "Posts", "Contributes", "Verified", "Joined"],
        [
            [
                p.display_name,
                p.username,
                p.email,
                p.role.value.title() if hasattr(p.role, "value") else str(p.role),
                p.wallet or "",
                "yes" if p.wants_to_request else "",
                "yes" if p.wants_to_contribute else "",
                "yes" if p.email_verified_at else "",
                _naive(p.created_at),
            ]
            for p in people
        ],
        [24, 18, 32, 11, 58, 9, 12, 10, 20],
    )

    feedback = Sheet(
        "In-product feedback",
        [
            "Received",
            "Type",
            "Status",
            "Message",
            "From",
            "Reply-to email",
            "Page",
            "Viewport",
            "Handled",
            "Handled by",
            "Resolution",
        ],
        [
            [
                _naive(n.created_at),
                str(getattr(n.kind, "value", n.kind)).title(),
                str(getattr(n.status, "value", n.status)).title(),
                n.message,
                n.sender or "Anonymous",
                n.email or "",
                n.path or "",
                f"{n.viewport_width} x {n.viewport_height}" if n.viewport_width else "",
                _naive(n.handled_at),
                n.handled_by or "",
                n.handled_note or "",
            ]
            for n in notes
        ],
        [20, 10, 10, 70, 22, 30, 28, 14, 20, 20, 50],
    )

    form_rows: list[list[Any]] = []
    form_note = (
        "No Google Form export was supplied. Run this again with --form-csv <file> once responses exist. "
        "Nothing here is generated: an empty sheet is the honest state until real responses are collected."
    )
    if form_csv:
        with form_csv.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            headers = next(reader, [])
            form_rows = [list(row) for row in reader]
        form_note = (
            f"Exported from {form_csv.name}, {len(form_rows)} response(s), columns as the form wrote them."
        )
        form = Sheet(
            "Form responses", headers or FORM_COLUMNS, form_rows, [22] * max(1, len(headers)), form_note
        )
    else:
        form = Sheet("Form responses", FORM_COLUMNS, [], [22] * len(FORM_COLUMNS), form_note)

    kinds = Counter(str(getattr(n.kind, "value", n.kind)).title() for n in notes)
    handled = sum(1 for n in notes if n.handled_at)
    summary_rows: list[list[Any]] = [
        ["Accounts on the platform", len(people)],
        ["…with a verified Stellar wallet", wallets or 0],
        ["…who post bounties", sum(1 for p in people if p.wants_to_request)],
        ["…who take on work", sum(1 for p in people if p.wants_to_contribute)],
        ["In-product feedback notes", len(notes)],
        ["…handled", handled],
        ["…still waiting", len(notes) - handled],
        ["Google Form responses", len(form_rows)],
        ["Exported (UTC)", _naive(datetime.now(UTC))],
    ]
    summary_rows += [[f"Feedback — {k}", v] for k, v in sorted(kinds.items())]
    summary = Sheet("Summary", ["Measure", "Value"], summary_rows, [38, 26])

    counts = {
        "participants": len(people),
        "wallets": wallets or 0,
        "feedback": len(notes),
        "form_responses": len(form_rows),
    }
    return [summary, participants, feedback, form], counts


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--form-csv", type=Path, default=None, help="CSV exported from the Google Form")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("../docs/onboarding/bountyflow-onboarding.xlsx"),
        help="where to write the workbook",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json, service="export-onboarding")
    if args.form_csv and not args.form_csv.exists():
        raise SystemExit(f"No such CSV: {args.form_csv}")

    async def _main() -> tuple[list[Sheet], dict[str, int]]:
        try:
            return await _collect(args.form_csv)
        finally:
            await dispose_engine()

    sheets, counts = run_async(_main())

    wb = Workbook()
    for i, sheet in enumerate(sheets):
        _write(wb, sheet, first=i == 0)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    logger.info("onboarding_export_written", path=str(out), **counts)
    sys.stdout.write(
        f"\n  {out.resolve()}\n"
        f"  {counts['participants']} accounts ({counts['wallets']} with a verified wallet), "
        f"{counts['feedback']} feedback notes, {counts['form_responses']} form responses\n\n"
    )


if __name__ == "__main__":
    run()
