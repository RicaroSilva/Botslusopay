from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, bots, credentials, dashboard, flows, hooks, runs, worker
from .config import get_settings
from .db import session_factory
from .registry.loader import sync_registry
from .services.bootstrap import bootstrap
from .services.runs import RunError
from .states import InvalidTransition

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(sync_on_start: bool = True) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if sync_on_start:
            with session_factory()() as db:
                sync_registry(db, settings.registry_dirs)
                bootstrap(db)
        yield

    app = FastAPI(
        title="LUSOPAY Bot Manager",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                           allow_headers=["Content-Type", "X-Requested-With"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RunError)
    async def run_error_handler(_: Request, exc: RunError):
        return JSONResponse(status_code=exc.http_status,
                            content={"detail": str(exc), "code": exc.code, "details": exc.details})

    @app.exception_handler(InvalidTransition)
    async def transition_handler(_: Request, exc: InvalidTransition):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "invalid_transition"})

    for r in (auth.router, dashboard.router, bots.router, runs.router, admin.router, credentials.router, flows.router,
              worker.router, hooks.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            return FileResponse(FRONTEND_DIST / "index.html")

    return app

