"""Warehouse connection pool — one pool for every endpoint (incl. per-tile
requests), opened/closed by the app lifespan in main.py. A fresh Supabase TLS
handshake per request is the latency floor otherwise; max_size stays small so
narvi never crowds the warehouse's direct-connection budget.

Constructed lazily: db_conninfo() requires the DB_* env keys, and DB-free use
(pure /generate, backend tests without a warehouse) must still import the app.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from narvi.warehouse import apply_session_settings, db_conninfo

pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    """Create (first call) and open the shared pool. Raises RuntimeError if the
    DB_* env keys are missing — callers decide whether that is fatal."""
    global pool
    if pool is None:
        pool = ConnectionPool(
            conninfo=db_conninfo(),
            min_size=1,
            max_size=6,
            configure=apply_session_settings,
            open=False,
            name="narvi-warehouse",
        )
    pool.open()
    return pool


def close_pool() -> None:
    if pool is not None:
        pool.close()
