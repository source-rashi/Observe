"""asyncpg pool helpers for Phase 4 persistence."""

import asyncio
import logging
import pathlib
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


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Execute schema.sql idempotently against *pool*."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
    logger.info("Schema ensured.")


async def close_pool(pool: Optional[asyncpg.Pool]) -> None:
    if pool is not None:
        await pool.close()
        logger.info("DB pool closed.")
