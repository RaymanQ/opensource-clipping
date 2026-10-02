"""
web.api.app — FastAPI Application Entry Point

OpenSource Clipping Studio — Web GUI Backend

Run with:
    uvicorn web.api.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import hmac
import os
import signal
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from clipping import __version__
from .routes import jobs, files, settings


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
    "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175",
    "http://localhost:5500", "http://127.0.0.1:5500",
]


def _parse_allowed_origins(raw: str | None) -> list[str]:
    """Parse comma-separated exact origins, ignoring invalid/path-bearing values."""
    origins = list(DEFAULT_ALLOWED_ORIGINS)
    for value in (raw or "").split(","):
        origin = value.strip().rstrip("/")
        parsed = urlparse(origin)
        if origin and parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.path:
            origins.append(origin)
    return list(dict.fromkeys(origins))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    print("🚀 OpenSource Clipping Studio — Backend starting...")
    yield
    print("👋 Backend shutting down...")


app = FastAPI(
    title="OpenSource Clipping Studio",
    description="AI Auto-Clipper & Teaser Generator — Web GUI API",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(os.environ.get("OSC_ALLOWED_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_bearer_auth(request: Request, call_next):
    """Protect API routes when OSC_API_TOKEN is configured."""
    expected = os.environ.get("OSC_API_TOKEN", "")
    public_paths = {"/", "/api/health", "/api/capabilities", "/docs", "/openapi.json", "/redoc"}
    if (
        expected
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path not in public_paths
    ):
        supplied = request.headers.get("Authorization", "")
        token = supplied[7:] if supplied.startswith("Bearer ") else ""
        if not token or not hmac.compare_digest(token, expected):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid backend access token"})
    return await call_next(request)

# Routes
app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings.router)


@app.get("/")
async def root():
    return {
        "name": "OpenSource Clipping Studio",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }

@app.post("/api/shutdown")
async def shutdown_server():
    """Trigger graceful shutdown of the FastAPI server."""
    # Send SIGINT to own process to trigger uvicorn graceful shutdown
    async def _shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)
    
    asyncio.create_task(_shutdown())
    return {"status": "shutting down", "message": "Server is stopping..."}
