# AI Observability

End-to-end observability and root-cause analysis stack for AI systems.

Status: Phase 3 (analyzer + anomaly detection)

## Demo App

A FastAPI application instrumented with OpenTelemetry metrics and failure injection capabilities.

### Endpoints
- `GET /health`: Health check (bypasses chaos)
- `GET /products`: Product listing (5-20ms simulated latency)
- `GET /orders`: Orders query (30-80ms simulated latency)
- `POST /checkout`: Order placement (50-150ms simulated latency)

### Chaos Endpoints
- `POST /chaos/latency?ms=<int>`: Injects extra latency (0-5000ms)
- `POST /chaos/errors?rate=<float>`: Injects HTTP 500 error probability (0.0-1.0)
- `POST /chaos/memory-leak?enabled=<bool>`: Toggles background memory leak (+5MB/sec up to 150MB)
- `POST /chaos/reset`: Clears all chaos parameters and frees leaked memory
- `GET /chaos/status`: Returns current chaos state

### Exported Metrics
- `app_requests`: Total HTTP request count (labels: `endpoint`, `method`, `status_code`)
- `app_errors`: Total HTTP 500 error count (labels: `endpoint`)
- `app_request_duration_ms`: Request duration histogram (labels: `endpoint`)
- `app_memory_mb`: Process RSS memory usage in megabytes
- `app_chaos_active`: Gauge indicator (1 if chaos active, 0 otherwise)

## Analyzer API

The analyzer service operates on port 8001:
- `GET /health`: Service health status, Prometheus readiness, and active anomaly count
- `GET /signals`: Inspection endpoint showing current baseline mean, std, latest value, and z-score for each signal/endpoint
- `GET /anomalies?status=active|resolved|all`: Filter anomalies by status (defaults to active)
- `GET /anomalies/{id}`: Retrieve a specific anomaly by short ID (404 if unknown)
- `POST /detect/run`: Manually trigger one detection cycle immediately and return active anomalies

## How Detection Works

1. **Sliding Windows**: Points older than `now - RECENT_SECONDS` (default: 60s) up to `now - BASELINE_MINUTES` (default: 15m) form the baseline. The remainder forms the recent window.
2. **Z-Score Calculation**: Calculates mean and population standard deviation of baseline. A floor (`min_std`) prevents division by zero on flat baselines. For each recent point, `z = (v - mean) / std`.
3. **Consecutive Points Rule**: An anomaly triggers only when the last `CONSECUTIVE_POINTS` (default: 3) consecutive points are all anomalous (`z >= Z_THRESHOLD` for upward signals, `|z| >= Z_THRESHOLD` for bidirectional signals).
4. **Severity & Direction**: Severity is `critical` if `|z| >= Z_CRITICAL` (default: 5.0), else `warning`. Direction is labeled `spike` (z > 0) or `drop` (z < 0).
5. **Resolution**: An active anomaly transitions to `resolved` after `RESOLVE_AFTER_CYCLES` (default: 3) consecutive detection cycles with normal metrics.

## Known Limitations

- **Baseline Contamination**: A sustained, long-running incident will gradually incorporate into the rolling 15-minute window and become the new baseline.
- **Stationarity Assumption**: Z-score detection assumes roughly stable normal behavior and can generate false positives during legitimate step-function traffic changes.
