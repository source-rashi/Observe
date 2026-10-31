import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_pool, create_pool, ensure_schema
from app.detector import zscore
from app.incidents import IncidentManager
from app.prometheus_client import PrometheusClient
from app.runner import detection_loop, run_detection_cycle
from app.signals import SIGNALS
from app.store import AnomalyStore

logger = logging.getLogger("analyzer.main")

client = PrometheusClient(settings.PROMETHEUS_URL)
store = AnomalyStore(settings)
incident_manager = IncidentManager(settings.INCIDENT_WINDOW_SECONDS)

_pool = None  # set during lifespan
_db_ok = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _db_ok

    pool = await create_pool(settings.DATABASE_URL)
    _pool = pool
    _db_ok = pool is not None

    if pool is not None:
        try:
            await ensure_schema(pool)
        except Exception as e:
            logger.warning("Schema application failed: %s — running without persistence.", e)
            _db_ok = False

        if _db_ok:
            try:
                from app.repository import load_active_state
                anomalies, incidents = await load_active_state(pool)
                store.restore(anomalies)
                incident_manager.restore(incidents)
                logger.info(
                    "Restored %d anomalies and %d incidents from DB.",
                    len(anomalies),
                    len(incidents),
                )
            except Exception as e:
                logger.warning("State restore failed: %s", e)

    task = asyncio.create_task(
        detection_loop(client, store, settings, pool=_pool, incident_manager=incident_manager)
    )
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await close_pool(_pool)


app = FastAPI(title="AI Observability Analyzer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    prom_up = await client.is_up()
    active_count = len(store.list("active"))
    open_incidents = len(incident_manager.list("open"))
    return {
        "status": "ok",
        "prometheus": prom_up,
        "active_anomalies": active_count,
        "db": _db_ok,
        "open_incidents": open_incidents,
    }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@app.get("/signals")
async def get_signals() -> List[Dict[str, Any]]:
    now = time.time()
    start = now - (settings.BASELINE_MINUTES * 60)
    cutoff = now - settings.RECENT_SECONDS
    results: List[Dict[str, Any]] = []

    for sig in SIGNALS:
        try:
            series_dict = await client.query_range(sig.promql, start, now, settings.STEP_SECONDS)
        except Exception:
            series_dict = {}

        if not series_dict:
            results.append({
                "signal": sig.name,
                "endpoint": "all" if not sig.per_endpoint else "none",
                "unit": sig.unit,
                "direction": sig.direction,
                "latest_value": None,
                "baseline_mean": None,
                "baseline_std": None,
                "z_score": None,
                "points_count": 0,
            })
            continue

        for key, points in series_dict.items():
            endpoint = key if sig.per_endpoint else "all"
            baseline = [p[1] for p in points if p[0] < cutoff]
            latest_val = points[-1][1] if points else None

            if len(baseline) >= settings.MIN_BASELINE_POINTS:
                mean = sum(baseline) / len(baseline)
                variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
                raw_std = math.sqrt(variance)
                std = max(raw_std, sig.min_std)
                z = zscore(latest_val, mean, std) if latest_val is not None else None
            else:
                mean, std, z = None, None, None

            results.append({
                "signal": sig.name,
                "endpoint": endpoint,
                "unit": sig.unit,
                "direction": sig.direction,
                "latest_value": latest_val,
                "baseline_mean": mean,
                "baseline_std": std,
                "z_score": z,
                "points_count": len(points),
            })

    return results


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------

@app.get("/anomalies")
async def get_anomalies(status: str = Query("active", pattern="^(active|resolved|all)$")):
    return store.list(status=status)


@app.get("/anomalies/{anomaly_id}")
async def get_anomaly(anomaly_id: str):
    item = store.get(anomaly_id)
    if not item:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return item


@app.post("/detect/run")
async def trigger_detect_run():
    active = await run_detection_cycle(
        client, store, settings, pool=_pool, incident_manager=incident_manager
    )
    return active


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@app.get("/incidents")
async def get_incidents(status: str = Query("open", pattern="^(open|resolved|all)$")):
    if _db_ok and _pool is not None:
        try:
            from app.repository import list_incidents
            return await list_incidents(_pool, status)
        except Exception as e:
            logger.warning("DB list_incidents failed, falling back to memory: %s", e)
    # In-memory fallback
    incs = incident_manager.list(status)
    return [
        {
            "id": i.id,
            "status": i.status,
            "severity": i.severity,
            "title": i.title,
            "started_at": i.started_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "last_seen_at": i.last_seen_at.isoformat(),
            "anomaly_ids": i.anomaly_ids,
        }
        for i in incs
    ]


@app.get("/incidents/{inc_id}")
async def get_incident(inc_id: str):
    if _db_ok and _pool is not None:
        try:
            from app.repository import get_incident as repo_get_incident
            result = await repo_get_incident(_pool, inc_id)
            if result is None:
                raise HTTPException(status_code=404, detail="Incident not found")
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("DB get_incident failed: %s", e)
    # In-memory fallback
    inc = incident_manager.get(inc_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {
        "id": inc.id,
        "status": inc.status,
        "severity": inc.severity,
        "title": inc.title,
        "started_at": inc.started_at.isoformat(),
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "last_seen_at": inc.last_seen_at.isoformat(),
        "anomaly_ids": inc.anomaly_ids,
        "anomalies": [
            {
                "id": a.id,
                "signal": a.signal,
                "endpoint": a.endpoint,
                "severity": a.severity,
                "status": a.status,
                "incident_id": a.incident_id,
            }
            for a in store.list("all")
            if a.id in inc.anomaly_ids
        ],
    }


# ---------------------------------------------------------------------------
# Signal history
# ---------------------------------------------------------------------------

@app.get("/history/signals")
async def history_signals(
    signal: str = Query(...),
    endpoint: str = Query("all"),
    minutes: int = Query(60, ge=1, le=1440),
):
    if not _db_ok or _pool is None:
        raise HTTPException(
            status_code=503,
            detail="Signal history requires the database (TimescaleDB is unavailable).",
        )
    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(minutes=minutes)
    try:
        from app.repository import get_samples
        rows = await get_samples(_pool, signal, endpoint, start, now)
    except Exception as e:
        logger.warning("get_samples failed: %s", e)
        raise HTTPException(status_code=503, detail=f"DB error: {e}")
    return {"signal": signal, "endpoint": endpoint, "minutes": minutes, "points": rows}
