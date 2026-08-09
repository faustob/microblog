"""OpenTelemetry bootstrap and instruments for Microblog.

This module owns the process-wide OpenTelemetry setup (tracer + meter
providers exporting via OTLP) and the Core Web Vitals instruments used to
measure the frontend RUM SLIs (LCP p75, INP p75).

``init_telemetry(app)`` is called from ``create_app()`` in ``app/__init__.py``
(the app factory used by both ``microblog.py`` and the WSGI entrypoint), so the
global providers are registered exactly once at startup.
"""

import logging
import os
import threading

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False

# The API returns proxy meters that re-bind to the real provider once it is
# registered, so creating these at import time is safe.
meter = metrics.get_meter(__name__)

# Core Web Vitals. The web-vitals library reports LCP and INP in
# milliseconds; both are normalized to SECONDS here so every duration in this
# metric family shares one unit, per OTel semantic-convention style.
web_vital_lcp = meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by the browser',
)
web_vital_inp = meter.create_histogram(
    'web.vital.inp',
    unit='s',
    description='Interaction to Next Paint reported by the browser',
)


def init_telemetry(app=None):
    """Build and globally register the OpenTelemetry SDK once per process.

    Registration is guarded so that running under an auto-instrumentation
    agent (which already registers global providers) does not crash or
    double-register the app.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
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

            # Endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT (never hardcoded).
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(tracer_provider)

            reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[reader]))
        except Exception:  # pragma: no cover - telemetry must never break boot
            logger.warning('OpenTelemetry SDK setup skipped', exc_info=True)


def record_web_vital(name, value, route=None, rating=None):
    """Record a browser-reported Core Web Vital as an OTel histogram value.

    Only the duration-valued vitals in scope for the SLIs (LCP, INP) are
    recorded; their values arrive in milliseconds and are converted to
    seconds. Unitless vitals such as CLS are ignored rather than mixed into a
    duration histogram.
    """
    if not name or value is None:
        return
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    if value < 0:
        return

    name = str(name).upper()
    attributes = {
        'http.route': route if route else 'unmatched',
    }
    if rating in ('good', 'needs-improvement', 'poor'):
        attributes['web.vital.rating'] = rating

    seconds = value / 1000.0
    if name == 'LCP':
        web_vital_lcp.record(seconds, attributes)
    elif name == 'INP':
        web_vital_inp.record(seconds, attributes)
