"""FastAPI dependencies — the warehouse connection.

narvi.warehouse.get_connection() reads the gitignored .env (DB_* keys) and applies
the Supabase session settings; the backend reuses it rather than standing up a
second DB mechanism. Endpoints that touch the warehouse depend on `get_conn`;
pure generation (no DB) doesn't.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
from narvi.warehouse import get_connection


def get_conn() -> Iterator[psycopg.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
