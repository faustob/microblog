"""OpenTelemetry bootstrap and shared instruments for Microblog.

Importing this module registers the global ``TracerProvider`` and
``MeterProvider`` exactly once, exporting over OTLP/HTTP to the endpoint taken
from the environment (``OTEL_EXPORTER_OTLP_ENDPOINT``) -- never hardcoded.

The registration is defensive: if an OpenTelemetry agent (or a previous import)
already installed real SDK providers, we leave them alone, so the application
starts correctly with or without an agent attached.

This module is imported for its side effect from ``app/vitals.py``, which in
turn is imported by ``app/auth/routes.py`` while Flask builds the application,
so the setup really executes at startup.
"""
import atexit
import logging
import os

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

logger = logging.getLogger(__name__)

_INITIALIZED = False


def _shutdown_provider(provider):
    """Flush and shut down an SDK provider at interpreter exit."""
    try:
        provider.shutdown()
    except Exception:  # pragma: no cover - shutdown must never raise at exit
        logger.exception('OpenTelemetry provider shutdown failed')


def init_telemetry():
    """Build and globally register the OTel SDK providers (idempotent)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    resource = Resource.create({
        'service.name': os.environ.get('OTEL_SERVICE_NAME', 'microblog'),
    })

    try:
        # Only install providers if no real SDK provider is present already
        # (e.g. an auto-instrumentation agent got there first).
        if not isinstance(trace.get_tracer_provider(), TracerProvider):
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)
            # Flush buffered spans on interpreter exit.
            atexit.register(_shutdown_provider, tracer_provider)

        if not isinstance(metrics.get_meter_provider(), MeterProvider):
            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            meter_provider = MeterProvider(
                resource=resource, metric_readers=[reader])
            metrics.set_meter_provider(meter_provider)
            # Flush buffered measurements on interpreter exit.
            atexit.register(_shutdown_provider, meter_provider)
    except Exception:  # pragma: no cover - telemetry must never break boot
        logger.exception('OpenTelemetry setup failed; continuing without it')


init_telemetry()

meter = metrics.get_meter('microblog.web')

# Core Web Vitals, reported by real browsers (values arrive in milliseconds,
# which is the unit the web-vitals library uses for LCP and INP).
WEB_VITAL_HISTOGRAMS = {
    'LCP': meter.create_histogram(
        'web.vital.lcp',
        unit='ms',
        description='Largest Contentful Paint reported by real user sessions',
    ),
    'INP': meter.create_histogram(
        'web.vital.inp',
        unit='ms',
        description='Interaction to Next Paint reported by real user sessions',
    ),
}
