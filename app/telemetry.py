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
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def init_telemetry():
    """Build and register the global OTel SDK providers exactly once.

    Guards against a second registration (e.g. if an agent already set
    global providers) so app startup never crashes.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    endpoint = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
    service_name = os.environ.get('OTEL_SERVICE_NAME', 'microblog')
    resource = Resource.create({SERVICE_NAME: service_name})

    try:
        trace_exporter_kwargs = {}
        metric_exporter_kwargs = {}
        if endpoint:
            trace_exporter_kwargs['endpoint'] = endpoint.rstrip('/') + '/v1/traces'
            metric_exporter_kwargs['endpoint'] = endpoint.rstrip('/') + '/v1/metrics'

        tracer_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(**trace_exporter_kwargs)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        metric_exporter = OTLPMetricExporter(**metric_exporter_kwargs)
        metric_reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
    except Exception:
        # Providers may already be registered by an external agent; tolerate
        # and continue using whatever global provider is in place.
        pass


_meter = metrics.get_meter('app.web_vitals')

web_vital_lcp_histogram = _meter.create_histogram(
    name='web.vital.lcp',
    description='Largest Contentful Paint reported from the browser',
    unit='ms',
)

web_vital_inp_histogram = _meter.create_histogram(
    name='web.vital.inp',
    description='Interaction to Next Paint reported from the browser',
    unit='ms',
)
