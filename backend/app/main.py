"""narvi API — a thin FastAPI service over the narvi inventory-planning engine.

Mirrors the erebor/anduin layout: routers under app/api/*, registered with an
`/api` prefix, CORS open to the Vite dev server. The heavy lifting lives in the
narvi library; these endpoints are adapters.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import generate, health, parcels, scenarios, warehouse

app = FastAPI(title="narvi API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5176", "http://127.0.0.1:5176",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(parcels.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
app.include_router(warehouse.router, prefix="/api")
app.include_router(scenarios.router, prefix="/api")
