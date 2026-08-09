"""OpenTelemetry wiring for Microblog.

This module owns the global SDK registration (tracer + meter providers with an
OTLP exporter whose endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT) and the
instruments used by the application. ``init_telemetry()`` is called from the
first lines of ``create_app()`` in ``app/__init__.py`` so the providers are
registered exactly once at process startup.
"""
import os
import threading

from opentelemetry import metrics, trace

_init_lock = threading.Lock()
_initialized = False

# Module-level meter/instruments are safe: the API returns proxy objects that
# re-bind to the real MeterProvider once it is registered.
meter = metrics.get_meter(__name__)

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

_VITALS = {
    'LCP': web_vital_lcp,
    'INP': web_vital_inp,
}


def init_telemetry():
    """Build and register the global OTel providers once.

    Registering is tolerant of an already-configured global provider (e.g. when
    an auto-instrumentation agent is attached in the deployment): the OTel
    Python API logs and keeps the existing provider instead of raising.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

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
        except Exception:  # pragma: no cover - never break app startup
            import logging
            logging.getLogger(__name__).warning(
                'OpenTelemetry SDK setup skipped', exc_info=True)


def instrument_flask_app(app):
    """Attach the official Flask instrumentation to this app instance.

    Emits http.server.request.duration with the standard semconv attributes
    (http.request.method, http.route, http.response.status_code).
    """
    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        FlaskInstrumentor().instrument_app(app)
    except Exception:  # pragma: no cover - never break app startup
        import logging
        logging.getLogger(__name__).warning(
            'Flask OpenTelemetry instrumentation not enabled', exc_info=True)


def record_web_vital(name, value, route=None):
    """Record a browser-reported Core Web Vital measurement.

    ``route`` must be the matched Flask route TEMPLATE (e.g. /user/<username>)
    to keep the metric attributes low cardinality.
    """
    histogram = _VITALS.get(name)
    if histogram is None:
        return
    try:
        measurement = float(value)
    except (TypeError, ValueError):
        return
    if measurement < 0:
        return
    histogram.record(measurement, {'http.route': route or 'unmatched'})
