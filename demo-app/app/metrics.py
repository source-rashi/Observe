import os
import psutil
from typing import Iterable
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

resource = Resource.create({"service.name": "demo-app"})

exporter = OTLPMetricExporter(
    endpoint=OTEL_ENDPOINT,
    insecure=True,
)

reader = PeriodicExportingMetricReader(
    exporter,
    export_interval_millis=5000,
)

duration_view = View(
    instrument_name="app_request_duration_ms",
    aggregation=ExplicitBucketHistogramAggregation(
        boundaries=[5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0]
    ),
)

provider = MeterProvider(
    resource=resource,
    metric_readers=[reader],
    views=[duration_view],
)
metrics.set_meter_provider(provider)
meter = metrics.get_meter("demo-app")

app_requests_counter = meter.create_counter(
    name="app_requests",
    description="Total application HTTP requests",
    unit="",
)

app_errors_counter = meter.create_counter(
    name="app_errors",
    description="Total application HTTP errors",
    unit="",
)

app_request_duration_histogram = meter.create_histogram(
    name="app_request_duration_ms",
    description="Application HTTP request duration in milliseconds",
    unit="",
)

_process = psutil.Process()

def _observe_memory(options: CallbackOptions) -> Iterable[Observation]:
    rss_mb = _process.memory_info().rss / (1024 * 1024)
    yield Observation(rss_mb)

meter.create_observable_gauge(
    name="app_memory_mb",
    callbacks=[_observe_memory],
    description="Application process RSS memory in megabytes",
    unit="",
)

def _observe_chaos(options: CallbackOptions) -> Iterable[Observation]:
    try:
        from app.chaos import is_chaos_active
        active = 1 if is_chaos_active() else 0
    except Exception:
        active = 0
    yield Observation(active)

meter.create_observable_gauge(
    name="app_chaos_active",
    callbacks=[_observe_chaos],
    description="Chaos mode active indicator (1 if active, 0 otherwise)",
    unit="",
)

def record_request_metrics(endpoint: str, method: str, status_code: int, duration_ms: float) -> None:
    attributes = {
        "endpoint": endpoint,
        "method": method,
        "status_code": str(status_code),
    }
    app_requests_counter.add(1, attributes)
    app_request_duration_histogram.record(duration_ms, {"endpoint": endpoint})
    if status_code >= 500:
        app_errors_counter.add(1, {"endpoint": endpoint})
