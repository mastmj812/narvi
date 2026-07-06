"""FastAPI dependencies — the warehouse connection.

Connections come from the shared pool (app/db.py), opened by the lifespan in
main.py. `pool.connection()` commits on clean exit and rolls back on error;
persist.py's explicit commits are unaffected. Endpoints that touch the
warehouse depend on `get_conn`; pure generation (no DB) doesn't.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg

from . import db


def get_conn() -> Iterator[psycopg.Connection]:
    pool = db.pool if db.pool is not None else db.open_pool()
    with pool.connection() as conn:
        yield conn
