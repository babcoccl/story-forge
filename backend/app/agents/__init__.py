"""StoryForge agent modules."""


class AgentError(Exception):
    """Base exception for agent failures."""
    pass


from backend.app.agents.base_agent import BaseAgent  # noqa: E402

__all__ = ["AgentError", "BaseAgent"]
