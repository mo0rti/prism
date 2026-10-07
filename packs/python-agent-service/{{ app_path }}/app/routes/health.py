"""`GET /api/health`: open, reports that the process is up. It reports nothing about identity or providers."""

from __future__ import annotations

from fastapi import APIRouter

from app.models import HealthResponse

router = APIRouter()


@router.get("/api/health", operation_id="getHealth", tags=["health"], response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="UP")
