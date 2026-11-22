"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers


class HealthResponse(BaseModel):
    """Service health check payload."""

    status: str
    service: str
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = settings or get_settings()

    application = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description=(
            "REST API for the Integrated Scholarly Journal Publishing and "
            "Peer-Review Management System."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["System"],
        summary="Service health check",
    )
    def health_check() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="scholarly-journal-backend",
            version=cfg.app_version,
        )

    application.include_router(api_router)
    return application


app = create_app()
