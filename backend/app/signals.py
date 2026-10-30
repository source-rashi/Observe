from dataclasses import dataclass
from typing import List

# NOTE: Metric names used in PromQL queries must match what
# `curl localhost:8889/metrics | grep app_` exports from the collector:
# app_requests_total, app_errors_total, app_request_duration_ms_bucket, app_memory_mb, app_chaos_active.

@dataclass(frozen=True)
class Signal:
    name: str
    promql: str
    unit: str
    direction: str  # "up" | "both"
    min_std: float
    per_endpoint: bool

SIGNALS: List[Signal] = [
    Signal(
        name="latency_p95",
        promql="histogram_quantile(0.95, sum by (le, endpoint) (rate(app_request_duration_ms_bucket[1m])))",
        unit="ms",
        direction="up",
        min_std=5.0,
        per_endpoint=True,
    ),
    Signal(
        name="request_rate",
        promql="sum by (endpoint) (rate(app_requests_total[1m]))",
        unit="req/s",
        direction="both",
        min_std=0.5,
        per_endpoint=True,
    ),
    Signal(
        name="error_rate",
        promql="100 * (sum(rate(app_errors_total[1m])) or vector(0)) / clamp_min(sum(rate(app_requests_total[1m])), 1e-9)",
        unit="%",
        direction="up",
        min_std=1.0,
        per_endpoint=False,
    ),
    Signal(
        name="memory_mb",
        promql="app_memory_mb",
        unit="MB",
        direction="up",
        min_std=5.0,
        per_endpoint=False,
    ),
]
