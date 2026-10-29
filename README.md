# AI Observability

End-to-end observability and root-cause analysis stack for AI systems.

Status: Phase 2 (demo app + failure injection)

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
