"""Aggregated daily product metrics maintained by the analytics worker."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MONEY, Base, Timestamps


class DailyMetric(Timestamps, Base):
    """One row per (day, metric). Values are recomputed idempotently from source tables, never incremented
    blindly, so event redelivery cannot double-count."""

    __tablename__ = "daily_metrics"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
