"""FastAPI application factory.

Wiring only. Every behaviour lives in a module; this file decides which modules
are mounted and in what order the cross-cutting concerns wrap them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.config import settings
from app.core.db import healthcheck
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware

# Registers every mapper before any request touches the ORM.
import app.db.models  # noqa: F401

from app.modules.admin.router import admin_router, router as operator_router
from app.modules.booking.router import router as booking_router
from app.modules.catalog.router import router as catalog_router
from app.modules.identity.router import profile_router, router as auth_router
from app.modules.inventory.router import router as inventory_router
from app.modules.payments.router import router as payments_router, webhook_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.venues.router import router as venues_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(json_logs=not settings.is_local, level="DEBUG" if settings.debug else "INFO")
    info = healthcheck()
    logger.info(
        "startup",
        environment=settings.environment,
        postgres=info["server_version"],
        extensions=info["extensions"],
        gateway=settings.payment_gateway,
        llm_provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
    )

    scheduler = None
    if settings.enable_scheduler:
        from app.workers.scheduler import start_scheduler

        scheduler = start_scheduler()

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=(
            "A movie ticket booking platform built as an AI-engineering sandbox. "
            "Seat inventory is transactional; AI features are pluggable."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    register_middleware(app)
    register_exception_handlers(app)

    v1 = APIRouter(prefix=settings.api_v1_prefix)
    v1.include_router(auth_router)
    v1.include_router(profile_router)
    v1.include_router(venues_router)
    v1.include_router(catalog_router)
    v1.include_router(scheduling_router)
    v1.include_router(inventory_router)
    v1.include_router(booking_router)
    v1.include_router(operator_router)
    v1.include_router(admin_router)
    v1.include_router(payments_router)
    v1.include_router(webhook_router)
    app.include_router(v1)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        """Liveness plus the facts you need when a deployment looks wrong.

        `host` and `tls` are here deliberately: the single most confusing
        failure when moving to a managed database is an app that starts
        perfectly while still talking to the old local server. Reporting which
        host answered makes that impossible to miss. The password is never part
        of `host`.
        """
        info = healthcheck()
        return {
            "status": "ok",
            "environment": settings.environment,
            "database": info["server_version"],
            "host": info["host"],
            "tls": info["ssl"],
            "uuidv7": "native" if info["server_version_num"] >= 180_000 else "shim",
            "extensions": info["extensions"],
        }

    return app


app = create_app()
