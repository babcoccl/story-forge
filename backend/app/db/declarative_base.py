"""Isolated SQLAlchemy declarative base.

This file imports nothing from the application to prevent circular imports.
All model files MUST import Base from here, not from backend.app.db.base.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass