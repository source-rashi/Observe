"""Async repository layer — all DB I/O is here.

Functions accept an asyncpg.Pool (may be None when the DB is down; callers
must guard accordingly).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from app.incidents import Incident
from app.store import Anomaly

logger = logging.getLogger("analyzer.repository")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO-8601 string (UTC, Z suffix)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _epoch_to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _row_to_anomaly_dict(row: asyncpg.Record) -> Dict[str, Any]:
    d = dict(row)
    for col in ("started_at", "last_seen_at", "resolved_at"):
        if isinstance(d.get(col), datetime):
            d[col] = _ts(d[col])
    if isinstance(d.get("points"), str):
        d["points"] = json.loads(d["points"])
    return d


def _row_to_incident_dict(row: asyncpg.Record) -> Dict[str, Any]:
    d = dict(row)
    for col in ("started_at", "last_seen_at", "resolved_at"):
        if isinstance(d.get(col), datetime):
            d[col] = _ts(d[col])
    return d


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def upsert_incident(pool: asyncpg.Pool, incident: Incident) -> None:
    sql = """
        INSERT INTO incidents (id, status, severity, title, started_at, resolved_at, last_seen_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO UPDATE SET
            status       = EXCLUDED.status,
            severity     = EXCLUDED.severity,
            title        = EXCLUDED.title,
            resolved_at  = EXCLUDED.resolved_at,
            last_seen_at = EXCLUDED.last_seen_at
    """
    started = incident.started_at
    resolved = incident.resolved_at
    last_seen = incident.last_seen_at
    async with pool.acquire() as conn:
        await conn.execute(
            sql,
            incident.id,
            incident.status,
            incident.severity,
            incident.title,
            started,
            resolved,
            last_seen,
        )


async def upsert_anomaly(pool: asyncpg.Pool, anomaly: Anomaly) -> None:
    sql = """
        INSERT INTO anomalies
            (id, incident_id, signal, endpoint, severity, direction, unit, value,
             baseline_mean, baseline_std, z_score, status, started_at, last_seen_at,
             resolved_at, points)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
        ON CONFLICT (id) DO UPDATE SET
            incident_id   = EXCLUDED.incident_id,
            severity      = EXCLUDED.severity,
            direction     = EXCLUDED.direction,
            value         = EXCLUDED.value,
            baseline_mean = EXCLUDED.baseline_mean,
            baseline_std  = EXCLUDED.baseline_std,
            z_score       = EXCLUDED.z_score,
            status        = EXCLUDED.status,
            last_seen_at  = EXCLUDED.last_seen_at,
            resolved_at   = EXCLUDED.resolved_at,
            points        = EXCLUDED.points
    """
    started_dt = _epoch_to_dt(anomaly.started_at)
    last_seen_dt = _epoch_to_dt(anomaly.last_seen_at)
    resolved_dt = _epoch_to_dt(anomaly.resolved_at) if anomaly.resolved_at else None
    points_json = json.dumps(anomaly.points)
    async with pool.acquire() as conn:
        await conn.execute(
            sql,
            anomaly.id,
            anomaly.incident_id,
            anomaly.signal,
            anomaly.endpoint,
            anomaly.severity,
            anomaly.direction,
            anomaly.unit,
            anomaly.value,
            anomaly.baseline_mean,
            anomaly.baseline_std,
            anomaly.z_score,
            anomaly.status,
            started_dt,
            last_seen_dt,
            resolved_dt,
            points_json,
        )


async def insert_samples(
    pool: asyncpg.Pool,
    rows: List[Tuple[datetime, str, str, float]],
) -> None:
    """Bulk-insert (time, signal, endpoint, value) tuples, ignoring duplicates."""
    if not rows:
        return
    sql = """
        INSERT INTO signal_samples (time, signal, endpoint, value)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
    """
    async with pool.acquire() as conn:
        await conn.executemany(sql, rows)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

async def load_active_state(
    pool: asyncpg.Pool,
) -> Tuple[List[Anomaly], List[Incident]]:
    """Load active anomalies and open incidents for in-memory restore."""
    anomalies: List[Anomaly] = []
    incidents: List[Incident] = []

    async with pool.acquire() as conn:
        a_rows = await conn.fetch(
            "SELECT * FROM anomalies WHERE status = 'active' ORDER BY started_at"
        )
        for row in a_rows:
            points = json.loads(row["points"]) if isinstance(row["points"], str) else row["points"]
            anomaly = Anomaly(
                id=row["id"],
                incident_id=row["incident_id"],
                signal=row["signal"],
                endpoint=row["endpoint"],
                severity=row["severity"],
                direction=row["direction"],
                unit=row["unit"],
                value=row["value"],
                baseline_mean=row["baseline_mean"],
                baseline_std=row["baseline_std"],
                z_score=row["z_score"],
                status=row["status"],
                started_at=row["started_at"].timestamp(),
                last_seen_at=row["last_seen_at"].timestamp(),
                resolved_at=row["resolved_at"].timestamp() if row["resolved_at"] else None,
                points=points,
            )
            anomalies.append(anomaly)

        i_rows = await conn.fetch(
            """
            SELECT i.*, array_agg(a.id) FILTER (WHERE a.id IS NOT NULL) AS anomaly_ids
            FROM incidents i
            LEFT JOIN anomalies a ON a.incident_id = i.id
            WHERE i.status = 'open'
            GROUP BY i.id
            ORDER BY i.started_at
            """
        )
        for row in i_rows:
            incident = Incident(
                id=row["id"],
                status=row["status"],
                severity=row["severity"],
                title=row["title"],
                started_at=row["started_at"].replace(tzinfo=timezone.utc)
                if row["started_at"].tzinfo is None
                else row["started_at"],
                resolved_at=row["resolved_at"],
                last_seen_at=row["last_seen_at"].replace(tzinfo=timezone.utc)
                if row["last_seen_at"].tzinfo is None
                else row["last_seen_at"],
                anomaly_ids=list(row["anomaly_ids"]) if row["anomaly_ids"] else [],
            )
            incidents.append(incident)

    return anomalies, incidents


async def list_incidents(
    pool: asyncpg.Pool,
    status: str = "open",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if status == "all":
        where = ""
    else:
        where = f"WHERE status = '{status}'"
    sql = f"SELECT * FROM incidents {where} ORDER BY started_at DESC LIMIT {limit}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [_row_to_incident_dict(r) for r in rows]


async def get_incident(
    pool: asyncpg.Pool, inc_id: str
) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM incidents WHERE id = $1", inc_id)
        if row is None:
            return None
        result = _row_to_incident_dict(row)
        a_rows = await conn.fetch(
            "SELECT * FROM anomalies WHERE incident_id = $1 ORDER BY started_at", inc_id
        )
        result["anomalies"] = [_row_to_anomaly_dict(r) for r in a_rows]
    return result


async def get_samples(
    pool: asyncpg.Pool,
    signal: str,
    endpoint: str,
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    where_ep = "" if endpoint == "all" else "AND endpoint = $4"
    params: List[Any] = [signal, start, end]
    if endpoint != "all":
        params.append(endpoint)
    sql = f"""
        SELECT time, signal, endpoint, value
        FROM signal_samples
        WHERE signal = $1 AND time >= $2 AND time <= $3
        {where_ep}
        ORDER BY time
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [
        {
            "time": _ts(r["time"]),
            "signal": r["signal"],
            "endpoint": r["endpoint"],
            "value": r["value"],
        }
        for r in rows
    ]
