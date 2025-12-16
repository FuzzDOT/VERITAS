"""
Trace & Audit Service - FastAPI Application
=============================================
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus


logger = get_logger(__name__)


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
        description="Audit logging for the Truth Engine",
        version=settings.service_version,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="trace-audit-service",
            version=settings.service_version,
        )

    return app


app = create_app()
