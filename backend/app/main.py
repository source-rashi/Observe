import asyncio
import math
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.detector import zscore
from app.prometheus_client import PrometheusClient
from app.runner import detection_loop, run_detection_cycle
from app.signals import SIGNALS
from app.store import AnomalyStore

client = PrometheusClient(settings.PROMETHEUS_URL)
store = AnomalyStore(settings)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(detection_loop(client, store, settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="AI Observability Analyzer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    prom_up = await client.is_up()
    active_count = len(store.list("active"))
    return {
        "status": "ok",
        "prometheus": prom_up,
        "active_anomalies": active_count,
    }

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

@app.get("/anomalies")
async def get_anomalies(status: str = Query("active", regex="^(active|resolved|all)$")):
    return store.list(status=status)

@app.get("/anomalies/{anomaly_id}")
async def get_anomaly(anomaly_id: str):
    item = store.get(anomaly_id)
    if not item:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return item

@app.post("/detect/run")
async def trigger_detect_run():
    active = await run_detection_cycle(client, store, settings)
    return active
