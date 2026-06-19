# backend/app/db/base.py
# This file exists solely for Alembic autogenerate model discovery.
# It re-exports Base and imports all models so Alembic can see them.
# Application code should import Base from backend.app.db.declarative_base directly.

from backend.app.db.declarative_base import Base  # noqa: F401

# All model imports must come AFTER Base is imported above.
from backend.app.models.component import (  # noqa: F401
    ComponentType,
    Component,
    ComponentConstraint,
)
from backend.app.models.story import (  # noqa: F401
    Story,
    StoryChapter,
    StoryScene,
    StoryComponentLink,
)
from backend.app.models.agent import AgentRun  # noqa: F401