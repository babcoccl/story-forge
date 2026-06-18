"""SQLAlchemy DeclarativeBase.

All models are imported here so Alembic can discover them for autogenerate.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass

# Import all models so Alembic can discover them
from backend.app.models.component import ComponentType, Component, ComponentConstraint  # noqa: F401
from backend.app.models.story import Story, StoryComponentLink, StoryChapter, StoryScene  # noqa: F401
from backend.app.models.agent import AgentRun  # noqa: F401
