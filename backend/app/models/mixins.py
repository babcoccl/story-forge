"""Shared model mixins.

Provides common columns used across all StoryForge models.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns.

    Both columns are UTC-aware timestamptz. `created_at` is set once
    on insert via a server-side default. `updated_at` is set on insert
    and automatically refreshed on every update.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )