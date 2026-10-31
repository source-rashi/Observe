import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import asyncpg

from app.config import Settings
from app.detector import detect
from app.incidents import IncidentManager
from app.prometheus_client import PrometheusClient
from app.signals import SIGNALS
from app.store import Anomaly, AnomalyStore

logger = logging.getLogger("analyzer.runner")


async def run_detection_cycle(
    client: PrometheusClient,
    store: AnomalyStore,
    cfg: Settings,
    pool: Optional[asyncpg.Pool] = None,
    incident_manager: Optional[IncidentManager] = None,
) -> List[Anomaly]:
    now = time.time()
    start = now - (cfg.BASELINE_MINUTES * 60)
    step = cfg.STEP_SECONDS

    # Collect latest data point per (signal, endpoint) for sample insertion
    sample_rows = []

    for signal in SIGNALS:
        try:
            series_dict = await client.query_range(signal.promql, start, now, step)
            if not series_dict:
                endpoint = "all" if not signal.per_endpoint else ""
                if endpoint:
                    store.mark_clear(signal.name, endpoint)
                continue

            for key, points in series_dict.items():
                endpoint = key if signal.per_endpoint else "all"
                detection = detect(signal, endpoint, points, now, cfg)
                if detection:
                    store.update(detection)
                else:
                    store.mark_clear(signal.name, endpoint)

                # Collect latest sample point for persistence
                if pool is not None and points:
                    last_ts, last_val = points[-1]
                    sample_rows.append(
                        (
                            datetime.fromtimestamp(last_ts, tz=timezone.utc),
                            signal.name,
                            endpoint,
                            float(last_val),
                        )
                    )
        except Exception as e:
            logger.error(f"Error evaluating signal {signal.name}: {e}", exc_info=True)

    # Persist samples
    if pool is not None and sample_rows:
        try:
            from app.repository import insert_samples
            await insert_samples(pool, sample_rows)
        except Exception as e:
            logger.warning("Failed to insert samples: %s", e)

    # Process lifecycle events
    if pool is not None or incident_manager is not None:
        events = store.pop_events()
        all_by_id = {a.id: a for a in store.list("all")}

        for event_type, anomaly in events:
            try:
                if incident_manager is not None:
                    if event_type == "created":
                        incident = incident_manager.assign(anomaly)
                        if pool is not None:
                            from app.repository import upsert_incident, upsert_anomaly
                            await upsert_incident(pool, incident)
                            await upsert_anomaly(pool, anomaly)
                    elif event_type == "updated":
                        incident = incident_manager.refresh(anomaly, all_by_id)
                        if pool is not None:
                            from app.repository import upsert_anomaly
                            await upsert_anomaly(pool, anomaly)
                            if incident:
                                from app.repository import upsert_incident
                                await upsert_incident(pool, incident)
                    elif event_type == "resolved":
                        if pool is not None:
                            from app.repository import upsert_anomaly
                            await upsert_anomaly(pool, anomaly)
                        incident = incident_manager.on_resolved(anomaly, all_by_id)
                        if incident is not None and pool is not None:
                            from app.repository import upsert_incident
                            await upsert_incident(pool, incident)
                else:
                    # No incident manager; still persist anomaly changes
                    if pool is not None:
                        from app.repository import upsert_anomaly
                        await upsert_anomaly(pool, anomaly)
            except Exception as e:
                logger.warning("DB error processing event %s for %s: %s", event_type, anomaly.id, e)

    return store.list("active")


async def detection_loop(
    client: PrometheusClient,
    store: AnomalyStore,
    cfg: Settings,
    pool: Optional[asyncpg.Pool] = None,
    incident_manager: Optional[IncidentManager] = None,
) -> None:
    logger.info("Starting background anomaly detection loop...")
    while True:
        try:
            await run_detection_cycle(client, store, cfg, pool=pool, incident_manager=incident_manager)
        except asyncio.CancelledError:
            logger.info("Detection loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in detection loop cycle: {e}", exc_info=True)

        try:
            await asyncio.sleep(cfg.DETECTION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
