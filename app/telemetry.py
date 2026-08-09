"""OpenTelemetry wiring for Microblog.

``init_otel()`` builds and registers the global tracer/meter providers exactly
once at process startup (it is called from the first lines of ``create_app()``).
The OTLP endpoint comes from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT``
environment variable -- it is never hardcoded.

This module also owns the Core Web Vitals instruments (LCP / INP) that back the
``microblog-web-lcp-p75`` and ``microblog-web-inp-p75`` SLIs. The browser
reporter in ``app/templates/base.html`` POSTs measurements to the ``/vitals``
route, which calls :func:`record_web_vital` here.
"""

import os
import threading

from opentelemetry import metrics, trace

_init_lock = threading.Lock()
_initialized = False


def init_otel():
    """Build and register the global OTel providers. Safe to call repeatedly.

    If an OTel agent / auto-instrumentation has already registered providers,
    the SDK's ``set_*_provider`` calls log a warning and keep the existing
    provider, so the app starts correctly either way.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import \
                OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import \
                OTLPSpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import \
                PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:  # SDK not installed -- API stays a no-op.
            return

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


# The API returns proxy instruments that re-bind to the real provider once
# init_otel() registers it, so module-level creation is safe.
_meter = metrics.get_meter(__name__)

web_vital_lcp = _meter.create_histogram(
    'web.vital.lcp',
    unit='s',
    description='Largest Contentful Paint reported by the browser, in seconds',
)

web_vital_inp = _meter.create_histogram(
    'web.vital.inp',
    unit='s',
    description='Interaction to Next Paint reported by the browser, in seconds',
)

web_vital_cls = _meter.create_histogram(
    'web.vital.cls',
    unit='1',
    description='Cumulative Layout Shift reported by the browser (unitless)',
)

_HISTOGRAMS = {
    'LCP': web_vital_lcp,
    'INP': web_vital_inp,
    'CLS': web_vital_cls,
}

# Ratings emitted by the web-vitals library; anything else is dropped to keep
# the dimension low cardinality.
_RATINGS = ('good', 'needs-improvement', 'poor')
_NAV_TYPES = ('navigate', 'reload', 'back-forward', 'back-forward-cache',
              'prerender', 'restore')


def record_web_vital(name, value, route=None, rating=None,
                     navigation_type=None):
    """Record one browser Core Web Vital measurement.

    ``value`` arrives from the browser in milliseconds for the time-based
    vitals (LCP, INP) and is converted to seconds; CLS is unitless.
    Attributes are kept low cardinality: the matched Flask route TEMPLATE
    (e.g. ``/user/<username>``), never the raw path.
    """
    if not isinstance(name, str):
        return
    histogram = _HISTOGRAMS.get(name.upper())
    if histogram is None:
        return
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    if value < 0:
        return
    if name.upper() != 'CLS':
        value = value / 1000.0

    attributes = {
        'http.route': route if isinstance(route, str) and route else 'unknown',
    }
    if rating in _RATINGS:
        attributes['web.vital.rating'] = rating
    if navigation_type in _NAV_TYPES:
        attributes['web.vital.navigation_type'] = navigation_type

    histogram.record(value, attributes)
