"""Warehouse connection pool — one pool for every endpoint (incl. per-tile
requests), opened/closed by the app lifespan in main.py. A fresh Supabase TLS
handshake per request is the latency floor otherwise; max_size stays small so
narvi never crowds the warehouse's direct-connection budget.

Constructed lazily: db_conninfo() requires the DB_* env keys, and DB-free use
(pure /generate, backend tests without a warehouse) must still import the app.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from narvi.warehouse import db_conninfo

pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    """Create (first call) and open the shared pool. Raises RuntimeError if the
    DB_* env keys are missing — callers decide whether that is fatal.

    Sized for the Supavisor transaction pooler (DB_PORT=6543): prepared statements
    are disabled (transaction mode can't reuse them across the multiplexed server
    connection) and session GUCs ride the conninfo startup `options` (see
    warehouse._db_kwargs), so no per-session `configure` hook is needed. min_size=0
    plus max_idle/max_lifetime keep narvi from stranding idle server sessions — the
    failure mode that exhausted the 15-client session-mode cap on repeated reloads."""
    global pool
    if pool is None:
        pool = ConnectionPool(
            conninfo=db_conninfo(),
            kwargs={"prepare_threshold": None},
            min_size=0,
            max_size=6,
            max_idle=120.0,
            max_lifetime=600.0,
            open=False,
            name="narvi-warehouse",
        )
    pool.open()
    return pool


def close_pool() -> None:
    if pool is not None:
        pool.close()
