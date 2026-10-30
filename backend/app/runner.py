import asyncio
import logging
import time
from typing import List
from app.config import Settings
from app.detector import detect
from app.prometheus_client import PrometheusClient
from app.signals import SIGNALS
from app.store import Anomaly, AnomalyStore

logger = logging.getLogger("analyzer.runner")

async def run_detection_cycle(
    client: PrometheusClient, store: AnomalyStore, cfg: Settings
) -> List[Anomaly]:
    now = time.time()
    start = now - (cfg.BASELINE_MINUTES * 60)
    step = cfg.STEP_SECONDS

    for signal in SIGNALS:
        try:
            series_dict = await client.query_range(signal.promql, start, now, step)
            if not series_dict:
                # If per_endpoint is False, default endpoint is 'all'
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
        except Exception as e:
            logger.error(f"Error evaluating signal {signal.name}: {e}", exc_info=True)

    return store.list("active")

async def detection_loop(
    client: PrometheusClient, store: AnomalyStore, cfg: Settings
) -> None:
    logger.info("Starting background anomaly detection loop...")
    while True:
        try:
            await run_detection_cycle(client, store, cfg)
        except asyncio.CancelledError:
            logger.info("Detection loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in detection loop cycle: {e}", exc_info=True)

        try:
            await asyncio.sleep(cfg.DETECTION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
