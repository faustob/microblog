"""OpenTelemetry wiring for Microblog.

This module owns the global provider setup (called once from ``create_app()``
in ``app/__init__.py``) and the shared instruments used by the application.
The OTLP endpoint comes from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT``
environment variable -- it is never hardcoded.
"""
import logging
import os
import threading

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False

SERVICE_NAME = os.environ.get('OTEL_SERVICE_NAME', 'microblog')


def init_telemetry():
    """Build and register the global TracerProvider/MeterProvider once.

    Safe to call more than once and safe when an OpenTelemetry auto-
    instrumentation agent has already registered the global providers: the
    OTel Python API logs and keeps the existing provider rather than raising.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter)
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter)
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader)
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({'service.name': SERVICE_NAME})

            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[
                    PeriodicExportingMetricReader(OTLPMetricExporter())])
            metrics.set_meter_provider(meter_provider)
        except Exception:  # pragma: no cover - telemetry must never break boot
            logger.warning('OpenTelemetry setup skipped', exc_info=True)


def instrument_flask_app(app):
    """Attach the official Flask instrumentation (http.server.request.duration
    with semconv method/route/status attributes) to this application."""
    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        FlaskInstrumentor().instrument_app(app)
    except Exception:  # pragma: no cover
        logger.warning('Flask OpenTelemetry instrumentation skipped',
                       exc_info=True)


# Meter/instruments are created at import time; the OTel Python API returns
# proxy objects that re-bind to the real provider once it is registered.
meter = metrics.get_meter(__name__)

web_vital_lcp = meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by real user browsers')

web_vital_inp = meter.create_histogram(
    'web.vital.inp',
    unit='s',
    description='Interaction to Next Paint reported by real user browsers')

web_vital_cls = meter.create_histogram(
    'web.vital.cls',
    unit='1',
    description='Cumulative Layout Shift reported by real user browsers')

web_vital_reports_total = meter.create_counter(
    'web.vital.reports',
    description='Number of Core Web Vitals measurements reported by browsers')

WEB_VITAL_HISTOGRAMS = {
    'lcp': web_vital_lcp,
    'inp': web_vital_inp,
    'cls': web_vital_cls,
}

WEB_VITAL_UNITS = {
    'lcp': 's',
    'inp': 's',
    'cls': '1',
}
