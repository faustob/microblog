"""OpenTelemetry SDK bootstrap for Microblog.

Builds and registers the global TracerProvider and MeterProvider exactly
once at application startup, using an OTLP exporter whose endpoint comes
from the OTEL_EXPORTER_OTLP_ENDPOINT environment variable (never
hardcoded). Safe to call multiple times (e.g. under the reloader or if an
agent already registered providers) — registration errors are caught and
logged rather than raised.
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


def init_telemetry(app=None):
    """Idempotently build and register the global OTel SDK.

    Call this from the Flask application factory before the app starts
    serving requests.
    """
    global _initialized
    if _initialized:
        return

    service_name = os.environ.get('OTEL_SERVICE_NAME', 'microblog')
    resource = Resource.create({'service.name': service_name})

    try:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)
    except Exception:
        logger.exception('Failed to initialize OTel tracer provider; '
                          'continuing with existing/no-op provider')

    try:
        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
    except Exception:
        logger.exception('Failed to initialize OTel meter provider; '
                          'continuing with existing/no-op provider')

    if app is not None:
        try:
            from opentelemetry.instrumentation.flask import FlaskInstrumentor
            FlaskInstrumentor().instrument_app(app)
        except Exception:
            logger.exception('Failed to instrument Flask app with OTel')

        try:
            from app import vitals_routes
            app.register_blueprint(vitals_routes.bp)
        except Exception:
            logger.exception('Failed to register vitals blueprint')

    _initialized = True
