"""API v1 router.

Aggregates all v1 sub-routers and exposes a single `v1_router`
that the FastAPI application mounts at `/api/v1`.
"""

from fastapi import APIRouter

from backend.app.api.v1 import chapters, stories

v1_router = APIRouter()

# Phase 5/7: Stories API (create, get, list, reroll, status)
v1_router.include_router(stories.router)

# Phase 7: Chapters API (list chapters, get chapter, get scene)
v1_router.include_router(chapters.router)