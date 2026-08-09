"""OpenTelemetry bootstrap and application instruments for Microblog.

Importing this module registers the global TracerProvider / MeterProvider
exactly once, using the OTLP endpoint from the environment
(``OTEL_EXPORTER_OTLP_ENDPOINT``) -- never hardcoded. It is imported for its
side effect by ``app/auth/routes.py``, which Flask imports while building the
application, so the providers are in place before any request is served.

It also owns the Real User Monitoring (Core Web Vitals) instruments that back
the LCP / INP SLIs. These are recorded by the ``auth.report_web_vitals``
endpoint in ``app/auth/routes.py``.
"""
import logging
import os
import threading

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_logger = logging.getLogger(__name__)
_setup_lock = threading.Lock()
_configured = False


def setup_telemetry():
    """Build and register the global OTel providers (idempotent).

    Safe to call when an OTel agent/distro has already registered providers:
    ``set_tracer_provider`` / ``set_meter_provider`` only log a warning and keep
    the existing provider, and any exporter construction problem is logged
    instead of preventing the application from starting.
    """
    global _configured
    with _setup_lock:
        if _configured:
            return
        _configured = True
        try:
            resource = Resource.create({
                'service.name': os.environ.get('OTEL_SERVICE_NAME',
                                               'microblog'),
            })
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[reader]))
        except Exception:  # pragma: no cover - never block app startup
            _logger.warning('OpenTelemetry SDK setup skipped', exc_info=True)


setup_telemetry()

meter = metrics.get_meter('microblog.web')

web_vital_lcp = meter.create_histogram(
    'web.vital.lcp',
    unit='ms',
    description='Largest Contentful Paint reported by real user sessions',
)

web_vital_inp = meter.create_histogram(
    'web.vital.inp',
    unit='ms',
    description='Interaction to Next Paint reported by real user sessions',
)
