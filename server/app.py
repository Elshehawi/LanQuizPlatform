"""FastAPI application factory with lifespan hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.database import init_db
from server.auth import get_or_create_tutor_access_code
from server.routers import auth_routes, quiz_routes, attempt_routes, grading_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and tutor access code on startup."""
    init_db()
    code = get_or_create_tutor_access_code()
    app.state.tutor_access_code = code
    print(f"\n{'='*50}")
    print(f"  Tutor Access Code: {code}")
    print(f"{'='*50}\n")
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="LAN Quiz Platform",
        description="Offline LAN University Quiz Platform API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Include routers
    app.include_router(auth_routes.router)
    app.include_router(quiz_routes.router)
    app.include_router(attempt_routes.router)
    app.include_router(grading_routes.router)

    @app.get("/health")
    def health_check():
        return {"status": "ok", "service": "LAN Quiz Platform"}

    return app
