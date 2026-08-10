"""OpenTelemetry bootstrap and shared instruments for Microblog.

This module builds and registers the global TracerProvider / MeterProvider
exactly once at process startup (called from ``create_app()`` in
``app/__init__.py``) and owns the Core Web Vitals instruments recorded by the
``/vitals`` route in ``app/main/routes.py``.

The OTLP endpoint is taken from the standard environment variables
(``OTEL_EXPORTER_OTLP_ENDPOINT``) and is never hardcoded.
"""
import logging
import os

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)

# Module-level meter: the API returns a proxy that re-binds to the real
# MeterProvider once it is registered below, so instruments created here are
# safe to define at import time.
meter = metrics.get_meter('microblog')
tracer = trace.get_tracer('microblog')

# --- Core Web Vitals (RUM) instruments -------------------------------------
web_vital_lcp_duration = meter.create_histogram(
    name='web.vital.lcp.duration',
    unit='s',
    description='Largest Contentful Paint reported by the browser, in seconds',
)

web_vital_inp_duration = meter.create_histogram(
    name='web.vital.inp.duration',
    unit='s',
    description='Interaction to Next Paint reported by the browser, in seconds',
)

web_vital_reports = meter.create_counter(
    name='web.vital.reports',
    description='Number of Core Web Vitals measurements received from browsers',
)

# Map of the web-vitals metric name (lowercased) to its histogram.
WEB_VITAL_HISTOGRAMS = {
    'lcp': web_vital_lcp_duration,
    'inp': web_vital_inp_duration,
}

_initialized = False


def init_telemetry(app=None):
    """Build and register the global OTel SDK, and instrument the Flask app.

    Safe to call more than once and safe when an OTel agent/auto-instrumentation
    already registered the global providers (set_*_provider logs and keeps the
    existing provider rather than raising).
    """
    global _initialized

    if not _initialized:
        _initialized = True
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

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
            logger.warning('OpenTelemetry SDK setup skipped', exc_info=True)

    if app is not None:
        try:
            from opentelemetry.instrumentation.flask import FlaskInstrumentor

            FlaskInstrumentor().instrument_app(app)
        except Exception:  # pragma: no cover
            logger.warning('Flask OpenTelemetry instrumentation skipped',
                           exc_info=True)
