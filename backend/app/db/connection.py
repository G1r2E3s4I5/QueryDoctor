# backend/app/db/connection.py
"""Database connection utilities for QueryDoctor.

Provides two helper functions:
- ``get_project_connection()`` – connects to the QueryDoctor project database.
- ``get_target_connection()`` – connects to the target e‑commerce database used for
  query ingestion and execution‑plan collection.

Both functions read the connection strings from environment variables via
``backend.app.config``. They raise a clear ``RuntimeError`` when the required URL
is missing. Connections are created using the ``psycopg`` driver (the same driver
used by the sample‑db generator). All callers must close the connection (or use
 a context manager) – the helpers do **not** manage connection pooling.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

# Optional import – keep safe for dry‑run environments.
try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

# Load configuration (env vars).
from .. import config

def _create_connection(db_url: str) -> "psycopg.Connection":
    """Create a new psycopg connection.

    Args:
        db_url: PostgreSQL connection string.
    Returns:
        psycopg.Connection object.
    Raises:
        RuntimeError: If the psycopg driver is unavailable.
    """
    if psycopg is None:
        raise RuntimeError("psycopg is required for database operations but is not installed.")
    return psycopg.connect(db_url, autocommit=False)

@contextmanager
def get_project_connection() -> Generator["psycopg.Connection", None, None]:
    """Yield a connection to the QueryDoctor project database.

    Raises ``RuntimeError`` if ``PROJECT_DATABASE_URL`` is missing.
    """
    db_url = config.PROJECT_DATABASE_URL
    if not db_url:
        raise RuntimeError("PROJECT_DATABASE_URL environment variable is not set.")
    conn = _create_connection(db_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@contextmanager
def get_target_connection() -> Generator["psycopg.Connection", None, None]:
    """Yield a connection to the target e‑commerce database.

    Validates that the target URL differs from the project URL.
    """
    target_url = config.TARGET_DATABASE_URL
    project_url = config.PROJECT_DATABASE_URL
    if not target_url:
        raise RuntimeError("TARGET_DATABASE_URL environment variable is not set.")
    # Normalized comparison to avoid equivalent URLs passing the guard.
    from urllib.parse import urlparse
    def _norm(u: str) -> str:
        p = urlparse(u)
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{host}{port}{p.path}".rstrip('/')
    if _norm(target_url) == _norm(project_url):
        raise RuntimeError(
            "TARGET_DATABASE_URL must not refer to the same database as PROJECT_DATABASE_URL."
        )
    conn = _create_connection(target_url)
    try:
        # Enforce read‑only transaction and a safe statement timeout (30 s).
        cur = conn.cursor()
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.execute("SET statement_timeout = 30000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
