"""OpenTelemetry SDK bootstrap for Microblog.

Builds and registers the global TracerProvider and MeterProvider exactly
once at process startup, exporting via OTLP to the endpoint configured by
the OTEL_EXPORTER_OTLP_ENDPOINT environment variable. Safe to call multiple
times (e.g. under the Flask reloader) and safe if an OTel agent/SDK has
already registered a global provider elsewhere.
"""
import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

_initialized = False


def init_telemetry(app_name: str = "microblog") -> None:
    """Idempotently create and register the global OTel providers."""
    global _initialized
    if _initialized:
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", app_name)
    resource = Resource.create({"service.name": service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter())
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[metric_reader]
    )
    metrics.set_meter_provider(meter_provider)

    _initialized = True


init_telemetry()
