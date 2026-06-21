"""API v1 router.

Aggregates all v1 sub-routers and exposes a single `v1_router`
that the FastAPI application mounts at `/api/v1`.
"""

from fastapi import APIRouter

from backend.app.api.v1 import stories

v1_router = APIRouter()

# Phase 5: Stories API
v1_router.include_router(stories.router)

# TODO Phase 9: include component_router
# TODO Phase 9: include run_router
