"""
Truth Versioning Service - FastAPI Application
================================================

The Truth Versioning Service is responsible for:
1. Promoting evaluations to immutable TruthVersion records
2. Managing version history per claim class
3. Generating deterministic diffs between versions
4. Analyzing impact of evidence/entity updates
5. Queueing recomputation tasks for impacted claim classes

All promotions are gated on replay verification.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.schemas import HealthCheck, HealthStatus

from .routes import router
from .schemas import TRUTH_VERSION_SERVICE_VERSION


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()
    configure_logging(
        service_name="truth-versioning-service",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger.info(
        "Starting Truth Versioning Service",
        version=TRUTH_VERSION_SERVICE_VERSION,
    )
    yield
    logger.info("Shutting down Truth Versioning Service")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Truth Versioning Service",
        description="Immutable truth state versioning for the Financial Solvency Truth Engine",
        version=TRUTH_VERSION_SERVICE_VERSION,
        docs_url=settings.docs_url if settings.debug else None,
        lifespan=lifespan,
    )

    # Include versioned API routes
    app.include_router(router, prefix="/v1")

    @app.get("/health", response_model=HealthCheck, tags=["Health"])
    async def health_check() -> HealthCheck:
        return HealthCheck(
            status=HealthStatus.HEALTHY,
            service="truth-versioning-service",
            version=TRUTH_VERSION_SERVICE_VERSION,
        )

    return app


app = create_app()
