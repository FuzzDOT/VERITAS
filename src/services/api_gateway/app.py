"""
API Gateway - FastAPI Application (A1 Production-Grade)
========================================================

The main application factory for the API Gateway service.
This is the single entry point for all external API traffic.

Design Principles:
- Single external endpoint for solvency evaluation
- Health and readiness endpoints for orchestration
- Comprehensive error handling with structured responses
- Full trace correlation throughout request lifecycle
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shared.config import get_settings
from shared.errors import RefusalError, RefusalCategory
from shared.logging import bind_trace_context, configure_logging, get_logger
from shared.schemas import ErrorResponse

from services.api_gateway.routes import router as legacy_router
from services.api_gateway.solvency import solvency_router
from services.api_gateway.schemas import HealthResponse, ReadinessResponse


logger = get_logger(__name__)


# =============================================================================
# Application Lifespan
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown."""
    settings = get_settings()

    # Configure structured logging
    configure_logging(
        service_name="api-gateway",
        log_level=settings.log_level,
        json_output=not settings.debug,
    )

    logger.info(
        "Starting API Gateway",
        version=settings.service_version,
        environment="development" if settings.debug else "production",
    )

    # Initialize dependencies
    # EXTENSION_POINT: Add database connection, cache initialization, etc.
    app.state.startup_time = datetime.now(timezone.utc)
    app.state.ready = True

    yield

    # Cleanup
    logger.info("Shutting down API Gateway")
    app.state.ready = False


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns a fully configured FastAPI instance with:
    - Solvency evaluation endpoint
    - Health and readiness endpoints
    - Error handlers
    - Middleware
    """
    settings = get_settings()

    app = FastAPI(
        title="Financial Solvency Truth Engine - API Gateway",
        description="""
        Production-grade API Gateway for the Financial Solvency Truth Engine.
        
        ## Overview
        
        This API provides institutional-grade solvency evaluation for financial entities.
        All requests are validated exhaustively, normalized deterministically, and 
        routed to the Truth Orchestrator for processing.
        
        ## Authentication
        
        Authentication is required for all endpoints except health checks.
        (EXTENSION_POINT: Implement in A2)
        
        ## Rate Limiting
        
        Rate limits apply based on client tier.
        (EXTENSION_POINT: Implement in A2)
        
        ## Versioning
        
        This API uses URI versioning. The current version is v1.
        """,
        version=settings.service_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # =========================================================================
    # Middleware
    # =========================================================================

    # CORS - restrictive in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next: Callable) -> Response:
        """
        Add trace ID to all requests for correlation.
        
        The trace ID is:
        1. Taken from X-Trace-ID header if provided
        2. Generated as a new UUID if not provided
        3. Included in the response headers
        4. Bound to the logging context
        """
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        bind_trace_context(trace_id)
        
        # Add timing
        start_time = datetime.now(timezone.utc)
        
        response = await call_next(request)
        
        # Add headers
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-Time-Ms"] = str(
            int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        )
        
        return response

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next: Callable) -> Response:
        """Log all incoming requests and their outcomes."""
        trace_id = request.headers.get("X-Trace-ID", "unknown")
        
        logger.info(
            "Request received",
            method=request.method,
            path=request.url.path,
            trace_id=trace_id,
            client_ip=request.client.host if request.client else "unknown",
        )
        
        response = await call_next(request)
        
        logger.info(
            "Request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            trace_id=trace_id,
        )
        
        return response

    # =========================================================================
    # Exception Handlers
    # =========================================================================

    @app.exception_handler(RefusalError)
    async def refusal_error_handler(request: Request, exc: RefusalError) -> JSONResponse:
        """
        Handle refusal errors with structured error responses.
        
        Refusals are first-class responses that indicate the system
        explicitly declined to process a request.
        """
        trace_id = request.headers.get("X-Trace-ID", "unknown")
        
        logger.warning(
            "Request refused",
            operation=exc.operation,
            reason=exc.reason,
            category=exc.category.value,
            trace_id=trace_id,
        )
        
        return JSONResponse(
            status_code=_category_to_status(exc.category),
            content=ErrorResponse(
                error=exc.reason,
                category=exc.category.value,
                operation=exc.operation,
                details=exc.details,
                trace_id=trace_id,
            ).model_dump(mode="json"),
            headers={"X-Trace-ID": trace_id},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
        """Handle Pydantic validation errors."""
        trace_id = request.headers.get("X-Trace-ID", "unknown")
        
        errors = [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err.get("type"),
            }
            for err in exc.errors()
        ]
        
        logger.warning(
            "Validation error",
            trace_id=trace_id,
            error_count=len(errors),
        )
        
        return JSONResponse(
            status_code=422,
            content={
                "refused": True,
                "reason": "Request validation failed",
                "category": "validation_failed",
                "field_errors": errors,
                "trace_id": trace_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Trace-ID": trace_id},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        trace_id = request.headers.get("X-Trace-ID", "unknown")
        
        logger.exception(
            "Unexpected error",
            trace_id=trace_id,
            error=str(exc),
        )
        
        return JSONResponse(
            status_code=500,
            content={
                "refused": True,
                "reason": "Internal server error",
                "category": "internal_error",
                "trace_id": trace_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Trace-ID": trace_id},
        )

    # =========================================================================
    # Health & Readiness Endpoints
    # =========================================================================

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="Health Check",
        description="Returns the health status of the API Gateway.",
    )
    async def health_check() -> HealthResponse:
        """
        Health check endpoint.
        
        Returns healthy if the service is running.
        This endpoint does not check downstream dependencies.
        """
        return HealthResponse(
            status="healthy",
            service="api-gateway",
            version=settings.service_version,
            checks={
                "api": "healthy",
            },
        )

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["Health"],
        summary="Readiness Check",
        description="Returns whether the service is ready to accept traffic.",
    )
    async def readiness_check(request: Request) -> ReadinessResponse:
        """
        Readiness check endpoint.
        
        Returns ready=true if all dependencies are available.
        Kubernetes uses this to determine if the pod should receive traffic.
        """
        checks = {
            "api": True,
            # EXTENSION_POINT: Add dependency checks
            # "database": await check_database(),
            # "orchestrator": await check_orchestrator(),
            # "cache": await check_cache(),
        }
        
        all_ready = all(checks.values())
        
        return ReadinessResponse(
            ready=all_ready,
            checks=checks,
        )

    @app.get(
        "/",
        tags=["Health"],
        summary="Root",
        description="Root endpoint returning service information.",
    )
    async def root() -> dict:
        """Root endpoint with service information."""
        return {
            "service": "Financial Solvency Truth Engine - API Gateway",
            "version": settings.service_version,
            "status": "operational",
            "documentation": "/docs" if settings.debug else None,
        }

    # =========================================================================
    # API Routes
    # =========================================================================

    # Main solvency evaluation endpoint
    app.include_router(
        solvency_router,
        prefix="/v1",
        tags=["Solvency"],
    )

    # Legacy routes (for backward compatibility during transition)
    # These will be deprecated in A2
    if settings.debug:
        app.include_router(
            legacy_router,
            prefix="/api/v1",
            tags=["Legacy"],
            deprecated=True,
        )

    return app


# =============================================================================
# Helper Functions
# =============================================================================


def _category_to_status(category: RefusalCategory) -> int:
    """Map refusal category to HTTP status code."""
    mapping = {
        RefusalCategory.PRECONDITION_NOT_MET: 412,
        RefusalCategory.VALIDATION_FAILED: 422,
        RefusalCategory.INVARIANT_VIOLATED: 500,
        RefusalCategory.AUTHORIZATION_DENIED: 403,
        RefusalCategory.RESOURCE_NOT_FOUND: 404,
        RefusalCategory.CONFLICT: 409,
        RefusalCategory.RATE_LIMITED: 429,
        RefusalCategory.SERVICE_UNAVAILABLE: 503,
        RefusalCategory.INTERNAL_ERROR: 500,
    }
    return mapping.get(category, 500)


# =============================================================================
# Application Instance
# =============================================================================

# Create the application instance
# This is imported by uvicorn or gunicorn
app = create_app()
app = create_app()
