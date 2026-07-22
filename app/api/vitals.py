"""Server-side endpoint that receives browser-reported Web Vitals (LCP, INP)
and records them via the OTel meter using semantic-convention-style naming.

The browser never touches the OTel API directly (client-side OTel would be
a no-op); it POSTs JSON here and this module records real histograms
against the process-global MeterProvider registered in app/telemetry.py.
"""
from flask import Blueprint, jsonify, request

from opentelemetry import metrics

bp = Blueprint('vitals', __name__)

meter = metrics.get_meter(__name__)

_lcp_histogram = meter.create_histogram(
    name="web.vital.lcp",
    description="Largest Contentful Paint as reported by the browser",
    unit="ms",
)

_inp_histogram = meter.create_histogram(
    name="web.vital.inp",
    description="Interaction to Next Paint as reported by the browser",
    unit="ms",
)

_ALLOWED_METRICS = {
    'LCP': _lcp_histogram,
    'INP': _inp_histogram,
}


@bp.route('/api/vitals', methods=['POST'])
def report_vital():
    payload = request.get_json(silent=True) or {}
    name = payload.get('name')
    value = payload.get('value')
    route = payload.get('route') or 'unknown'

    histogram = _ALLOWED_METRICS.get(name)
    if histogram is not None and isinstance(value, (int, float)):
        histogram.record(
            float(value),
            attributes={
                'http.route': route,
            },
        )

    return jsonify({'status': 'ok'})
