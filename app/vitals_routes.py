"""Server-side endpoint to receive Web Vitals (LCP, INP) beacons from the
browser and record them via the OTel meter as histograms, per OTel Web
Vitals RUM practice. The client half (static/js/vitals.js) holds zero
OTel imports; it only POSTs JSON here.
"""
from flask import Blueprint, request, jsonify
from opentelemetry import metrics

bp = Blueprint('vitals', __name__)

meter = metrics.get_meter(__name__)

_lcp_histogram = meter.create_histogram(
    name='web.vital.lcp.duration',
    description='Largest Contentful Paint reported from the browser',
    unit='s',
)

_inp_histogram = meter.create_histogram(
    name='web.vital.inp.duration',
    description='Interaction to Next Paint reported from the browser',
    unit='s',
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
    route = payload.get('route', 'unknown')

    histogram = _ALLOWED_METRICS.get(name)
    if histogram is None or not isinstance(value, (int, float)):
        return jsonify({'status': 'ignored'}), 202

    histogram.record(float(value) / 1000.0, attributes={'http.route': route})
    return jsonify({'status': 'ok'}), 202
