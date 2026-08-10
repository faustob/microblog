"""OpenTelemetry bootstrap and instruments for Microblog.

This module owns the global provider registration (called from ``create_app``
in ``app/__init__.py``) and the Core Web Vitals instruments recorded by the
``/api/vitals`` collector route in ``app/main/routes.py``.

The OTLP endpoint comes from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT``
environment variable — it is never hardcoded here.
"""
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

_init_lock = threading.Lock()
_initialized = False


def init_telemetry():
    """Build and register the global tracer/meter providers exactly once.

    Safe to call repeatedly and safe when an OTel auto-instrumentation agent
    has already registered providers: ``set_tracer_provider`` /
    ``set_meter_provider`` log and keep the existing provider instead of
    raising, and any failure here must never prevent the app from starting.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True
        try:
            resource = Resource.create({
                'service.name': os.environ.get('OTEL_SERVICE_NAME',
                                               'microblog'),
            })

            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[
                    PeriodicExportingMetricReader(OTLPMetricExporter()),
                ],
            )
            metrics.set_meter_provider(meter_provider)
        except Exception:  # pragma: no cover - telemetry must never break boot
            pass


def instrument_flask_app(app):
    """Attach the official Flask instrumentation to this app instance.

    Emits ``http.server.request.duration`` with the semantic-convention
    attributes (http.request.method, http.route, http.response.status_code).
    """
    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        FlaskInstrumentor().instrument_app(app)
    except Exception:  # pragma: no cover - optional package / already done
        pass


# The API returns proxy instruments that re-bind to the real provider once
# ``init_telemetry`` registers it, so module-scope creation is correct here.
meter = metrics.get_meter(__name__)

web_vital_lcp_duration = meter.create_histogram(
    'web.vital.lcp.duration',
    unit='s',
    description='Largest Contentful Paint reported by real user sessions.',
)

web_vital_inp_duration = meter.create_histogram(
    'web.vital.inp.duration',
    unit='ms',
    description='Interaction to Next Paint reported by real user sessions.',
)

web_vital_reports_total = meter.create_counter(
    'web.vital.reports',
    description='Count of Core Web Vitals measurements reported by browsers.',
)

WEB_VITAL_HISTOGRAMS = {
    'lcp': web_vital_lcp_duration,
    'inp': web_vital_inp_duration,
}

_VALID_RATINGS = ('good', 'needs-improvement', 'poor')


def normalize_vital_rating(rating):
    """Clamp the client-supplied rating to the low-cardinality Vitals set."""
    rating = str(rating or '').lower()
    return rating if rating in _VALID_RATINGS else 'unknown'
