"""
Trace & Audit Service - FastAPI Application
=============================================

REST API for the Trace & Audit Service (A7).

Endpoints:
- POST /v1/trace/build - Build and store trace for evaluation
- GET /v1/trace/{trace_id} - Get trace by ID
- GET /v1/trace/by-evaluation/{evaluation_id} - Get trace by evaluation ID
- GET /v1/audit/{evaluation_id} - Get audit record
- GET /v1/audit/manifest/{date} - Get daily manifest
- POST /v1/audit/manifest/{date}/generate - Generate daily manifest
- GET /v1/replay/{evaluation_id} - Replay verification
- POST /v1/audit/verify-chain - Verify audit chain integrity
"""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Annotated, Any, AsyncGenerator, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, ConfigDict, Field

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus
from shared.errors import RefusalError

from infrastructure.postgres.session import get_session
from infrastructure.object_store import NullObjectStore, ObjectStoreInterface

from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import (
    TRACE_SERVICE_VERSION,
    TraceGraph,
    AuditRecord,
    AuditManifest,
    ReplayResult,
    ReplayStatus,
    BuildTraceRequest,
    BuildTraceResponse,
    GetTraceResponse,
    GetAuditResponse,
    GetManifestResponse,
    ReplayVerificationRequest,
    ReplayVerificationResponse,
)
from .stores import (
    TraceStore,
    AuditStore,
    ManifestService,
    ReplayService,
    TraceAuditServiceV2,
)
from .builder import build_trace_graph, build_refusal_trace_graph


logger = get_logger(__name__)


# =============================================================================
# Application Setup
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()
    configure_logging(
        service_name="trace-audit-service",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger.info("Starting Trace & Audit Service", version=settings.service_version)
    yield
    logger.info("Shutting down Trace & Audit Service")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Trace & Audit Service",
        description="Audit logging and trace graph management for the Truth Engine",
        version=settings.service_version,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )

    # Register routes
    from .routes import router
    app.include_router(router, prefix="/v1")

    @app.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="trace-audit-service",
            version=settings.service_version,
        )

    return app


app = create_app()
