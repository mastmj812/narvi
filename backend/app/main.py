"""narvi API — a thin FastAPI service over the narvi inventory-planning engine.

Mirrors the erebor/anduin layout: routers under app/api/*, registered with an
`/api` prefix, CORS open to the Vite dev server. The heavy lifting lives in the
narvi library; these endpoints are adapters.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from narvi import persist

from app import __version__, db
from app.api import basemap, generate, health, parcels, scenarios, tiles, warehouse

logger = logging.getLogger("narvi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        pool = db.open_pool()
        with pool.connection() as conn:
            persist.apply_schema(conn)  # once at boot, not per /scenarios request
    except Exception:
        # DB-free start still serves /generate, basemap, parcels/upload
        logger.exception("warehouse pool/apply_schema at startup failed")
    yield
    db.close_pool()


app = FastAPI(title="narvi API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5176", "http://127.0.0.1:5176",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # bad parcels / params raise ValueError deep in the engine; that's client input
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(health.router, prefix="/api")
app.include_router(basemap.router, prefix="/api")
app.include_router(parcels.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
app.include_router(warehouse.router, prefix="/api")
app.include_router(scenarios.router, prefix="/api")
app.include_router(tiles.router, prefix="/api")
