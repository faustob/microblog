"""OpenTelemetry bootstrap and browser Core Web Vitals (RUM) instruments.

``init_telemetry()`` builds the TracerProvider/MeterProvider with an OTLP
exporter exactly once per process and registers them as the global providers.
It is called from ``app/auth/routes.py``, which ``create_app()`` imports when it
registers the auth blueprint, so the setup really executes at startup and the
meters below are backed by the SDK instead of being no-ops.

The OTLP endpoint and service name come from the environment
(``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_SERVICE_NAME``) and are never
hardcoded.
"""

import logging
import os

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

logger = logging.getLogger(__name__)

_initialised = False


def init_telemetry():
    """Register the global OpenTelemetry providers (idempotent)."""
    global _initialised
    if _initialised:
        return
    _initialised = True

    if os.environ.get('OTEL_SDK_DISABLED', '').strip().lower() == 'true':
        logger.info('OpenTelemetry SDK disabled via OTEL_SDK_DISABLED')
        return

    resource = Resource.create({
        'service.name': os.environ.get('OTEL_SERVICE_NAME', 'microblog'),
    })

    try:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)

        metrics.set_meter_provider(MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(OTLPMetricExporter()),
            ],
        ))
    except Exception:  # pragma: no cover - tolerate an attached OTel agent
        logger.warning(
            'OpenTelemetry providers already configured; keeping the existing '
            'global providers', exc_info=True)


# Module level meter/instruments: the API returns proxy objects that re-bind to
# the real provider once init_telemetry() registers it.
_meter = metrics.get_meter('microblog.web_vitals')

LCP_DURATION = _meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by real user browsers',
)

INP_DURATION = _meter.create_histogram(
    'web.vital.inp',
    unit='ms',
    description='Interaction to Next Paint reported by real user browsers',
)

CLS_SCORE = _meter.create_histogram(
    'web.vital.cls',
    unit='1',
    description='Cumulative Layout Shift reported by real user browsers',
)

# vital name -> (instrument, factor applied to the browser value)
_VITALS = {
    'LCP': (LCP_DURATION, 0.001),  # browser reports milliseconds -> seconds
    'INP': (INP_DURATION, 1.0),
    'CLS': (CLS_SCORE, 1.0),
}


def record_web_vital(name, value, route, device_type='unknown'):
    """Record one Core Web Vital measurement with low-cardinality attributes.

    ``route`` must be the matched route TEMPLATE (e.g. ``/user/<username>``),
    never a raw path.
    """
    entry = _VITALS.get((name or '').strip().upper())
    if entry is None:
        return
    instrument, factor = entry
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return
    if numeric < 0:
        return
    instrument.record(numeric * factor, {
        'http.route': route or 'unmatched',
        'device.type': device_type or 'unknown',
    })
