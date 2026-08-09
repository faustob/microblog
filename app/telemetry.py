"""OpenTelemetry bootstrap and shared instruments for Microblog.

``init_telemetry()`` is called from ``create_app()`` (app/__init__.py) so the
global TracerProvider/MeterProvider are registered exactly once at startup,
before any request is served.  The OTLP endpoint comes from the environment
(``OTEL_EXPORTER_OTLP_ENDPOINT``) and is never hardcoded.
"""
import os
import threading

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import \
    OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import \
    OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_init_lock = threading.Lock()
_initialized = False

# The API returns proxy meters/instruments at import time and rebinds them to
# the real provider once init_telemetry() registers it.
meter = metrics.get_meter('microblog')

# Core Web Vitals reported by the browser (LCP/INP p75 SLIs).  Durations are
# recorded in seconds; the vital name is a low-cardinality attribute.
web_vital_duration = meter.create_histogram(
    'web.vital.duration',
    unit='s',
    description='Core Web Vitals durations (LCP, INP, ...) reported by real '
                'user sessions, in seconds',
)

web_vital_reports = meter.create_counter(
    'web.vital.reports',
    description='Number of Core Web Vitals measurements reported by browsers',
)


def init_telemetry():
    """Build and register the global OTel providers exactly once.

    Safe to call repeatedly and safe when an OTel agent already registered
    providers: ``set_*_provider`` logs and keeps the existing provider instead
    of raising.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        resource = Resource.create({
            'service.name': os.environ.get('OTEL_SERVICE_NAME', 'microblog'),
        })

        try:
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[reader]))
        except Exception:  # pragma: no cover - never break app startup
            # An agent may already own the global providers; keep serving.
            pass
