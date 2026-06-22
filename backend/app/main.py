"""StoryForge API — FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.v1.router import v1_router
from backend.app.config import settings
from backend.app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

app = FastAPI(title="StoryForge", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS — allow the Next.js frontend to call the API
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    """Log server startup."""
    setup_logging()
    logger.info("StoryForge API starting up")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Log server shutdown."""
    logger.info("StoryForge API shutting down")


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}