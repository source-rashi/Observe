"""asyncpg pool helpers for Phase 4 persistence."""

import asyncio
import logging
import pathlib
import re
from typing import Optional

import asyncpg

logger = logging.getLogger("analyzer.database")

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


async def create_pool(
    database_url: str,
    retries: int = 15,
    delay: float = 2.0,
) -> Optional[asyncpg.Pool]:
    """Create an asyncpg pool, retrying up to *retries* times.

    Returns None (instead of raising) if all attempts fail so the caller
    can degrade gracefully.
    """
    for attempt in range(1, retries + 1):
        try:
            pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
            logger.info("Connected to TimescaleDB (attempt %d).", attempt)
            return pool
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DB connection attempt %d/%d failed: %s", attempt, retries, exc
            )
            if attempt < retries:
                await asyncio.sleep(delay)
    logger.error(
        "Could not connect to TimescaleDB after %d attempts. Running without persistence.",
        retries,
    )
    return None


def _split_sql(sql: str):
    """Split a SQL file into individual statements, skipping empty ones.

    asyncpg's execute() rejects multi-statement strings that contain
    SELECT-returning calls (e.g. create_hypertable, add_retention_policy).
    We execute statements one by one instead.
    """
    # Strip single-line comments before splitting
    sql_no_comments = re.sub(r'--[^\n]*', '', sql)
    raw_stmts = sql_no_comments.split(';')
    return [s.strip() for s in raw_stmts if s.strip()]


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Execute schema.sql idempotently against *pool*, statement by statement."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    statements = _split_sql(sql)
    async with pool.acquire() as conn:
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except asyncpg.exceptions.DuplicateObjectError:
                pass  # IF NOT EXISTS guard missed something — safe to ignore
    logger.info("Schema ensured (%d statements).", len(statements))


async def ping(pool: asyncpg.Pool) -> bool:
    """Return True if the pool can execute a trivial query."""
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False


async def close_pool(pool: Optional[asyncpg.Pool]) -> None:
    if pool is not None:
        await pool.close()
        logger.info("DB pool closed.")
