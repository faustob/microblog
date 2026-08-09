"""OpenTelemetry bootstrap and instruments for Microblog.

The provider setup runs exactly once, from ``create_app()`` (see
``app/__init__.py``), before any request is served. The OTLP endpoint comes
from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable and is
never hardcoded.
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

# The API returns proxy meters/instruments that re-bind to the real provider
# once it is registered, so module-level creation here is safe.
meter = metrics.get_meter(__name__)

# Core Web Vitals reported by the browser. LCP is recorded in seconds
# (semconv duration style); INP is an interaction latency in milliseconds.
web_vital_lcp = meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by real user sessions',
)
web_vital_inp = meter.create_histogram(
    'web.vital.inp',
    unit='ms',
    description='Interaction to Next Paint reported by real user sessions',
)

_VITALS = {
    'LCP': (web_vital_lcp, 0.001),  # browser reports LCP in ms -> seconds
    'INP': (web_vital_inp, 1.0),    # browser reports INP in ms
}


def init_telemetry():
    """Build and register the global tracer/meter providers exactly once.

    Tolerates an already-registered provider (e.g. an auto-instrumentation
    agent attached at runtime): the OTel Python API logs a warning and keeps
    the existing provider instead of raising.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        resource = Resource.create({
            'service.name': os.environ.get('OTEL_SERVICE_NAME', 'microblog'),
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


def instrument_flask_app(app):
    """Install Flask auto-instrumentation (http.server.request.duration)."""
    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
    except ImportError:  # instrumentation package not installed
        return
    FlaskInstrumentor().instrument_app(app)


def record_web_vital(name, value, route=None, rating=None,
                     navigation_type=None):
    """Record a Core Web Vital reported by the browser.

    Attributes are kept low-cardinality: the matched route TEMPLATE, the
    vital's rating bucket and the navigation type only.
    """
    if name is None or value is None:
        return
    instrument_and_scale = _VITALS.get(str(name).upper())
    if instrument_and_scale is None:
        return
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return
    instrument, scale = instrument_and_scale
    attributes = {'http.route': route or 'unknown'}
    if rating:
        attributes['web.vital.rating'] = str(rating)
    if navigation_type:
        attributes['web.vital.navigation_type'] = str(navigation_type)
    instrument.record(numeric_value * scale, attributes)
