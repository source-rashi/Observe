# Project Phases

- **Phase 1: Infra** - Local observability stack via Docker Compose (OpenTelemetry Collector, Prometheus, Grafana).
- **Phase 2: Demo App + Failure Injection** - Demo application with synthetic failure injection emitting traces and metrics.
- **Phase 3: FastAPI + Anomaly Detection** - Ingestion service with automated statistical and metric anomaly detection.
- **Phase 4: TimescaleDB Incidents** - Persistent incident storage and time-series metadata management with TimescaleDB.
- **Phase 5: LLM Root-Cause** - LLM-driven root-cause analysis agent evaluating incidents, traces, and metrics.
- **Phase 6: UI + Docs + Demo** - Observability dashboard UI, end-to-end documentation, and interactive demonstration.
