"""Application startup and shutdown lifecycle hooks.

# TODO Phase 8: Implement orchestrator pipeline initialization
"""

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def on_startup() -> None:
    """Execute on application startup.

    # TODO Phase 8: Initialize orchestrator pipeline
    # TODO Phase 5: Initialize agent registry
    """
    logger.info("StoryForge startup hooks executing")
    logger.info("Config: LLM_BASE_URL=%s, DEFAULT_MODEL=%s", settings.llm_base_url, settings.default_model)


async def on_shutdown() -> None:
    """Execute on application shutdown.

    # TODO Phase 8: Cleanup orchestrator pipeline resources
    """
    logger.info("StoryForge shutdown hooks executing")