"""OpenTelemetry bootstrap and shared instruments for Microblog.

``init_telemetry(app)`` is called from ``create_app()`` (app/__init__.py) so the
global TracerProvider/MeterProvider are registered exactly once at process
startup, before any request is served.  The OTLP endpoint comes from the
standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable — never hardcoded.

The instruments below are created at import time against the API's proxy meter,
which re-binds to the real MeterProvider once it is registered.
"""
import os
import threading

from opentelemetry import metrics, trace

_init_lock = threading.Lock()
_initialized = False

meter = metrics.get_meter(__name__)

# Core Web Vitals reported by the browser (web-vitals library) and forwarded to
# the server by the /vitals route in app/main/routes.py.
web_vital_lcp = meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by real user sessions.',
)
web_vital_inp = meter.create_histogram(
    'web.vital.inp',
    unit='ms',
    description='Interaction to Next Paint reported by real user sessions.',
)
web_vitals_reported = meter.create_counter(
    'web.vital.reports',
    description='Number of Core Web Vitals measurements received from browsers.',
)

WEB_VITAL_HISTOGRAMS = {
    'lcp': web_vital_lcp,
    'inp': web_vital_inp,
}

WEB_VITAL_UNITS = {
    'lcp': 's',
    'inp': 'ms',
}


def init_telemetry(app):
    """Register the global OTel providers once and instrument the Flask app.

    Safe to call more than once, and safe when an OTel agent/auto-instrumentation
    has already registered providers (set_*_provider logs and keeps the existing
    provider rather than raising).
    """
    global _initialized

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

    with _init_lock:
        if not _initialized:
            _initialized = True
            resource = Resource.create({
                'service.name': os.environ.get(
                    'OTEL_SERVICE_NAME', 'microblog'),
            })
            try:
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
            except Exception:  # pragma: no cover - telemetry must never break app
                app.logger.exception('OpenTelemetry SDK setup failed')

    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        FlaskInstrumentor().instrument_app(app)
    except Exception:  # pragma: no cover - agent may already have instrumented
        app.logger.exception('Flask OpenTelemetry instrumentation failed')
