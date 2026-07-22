from flask import request, jsonify, Response

from app.api import bp
from app.telemetry import web_vital_lcp_histogram, web_vital_inp_histogram


@bp.route('/vitals', methods=['POST'])
def vitals():
    """Receive Core Web Vitals beacons (LCP, INP) from the browser client
    and record them into the corresponding OTel histograms.

    Low-cardinality attributes only: route template, not raw path/ids.
    """
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    value = data.get('value')
    route = data.get('route') or 'unknown'

    if not isinstance(value, (int, float)):
        return jsonify({'status': 'ignored'}), 400

    attributes = {'http.route': str(route)[:128]}

    if name == 'LCP':
        web_vital_lcp_histogram.record(float(value), attributes=attributes)
    elif name == 'INP':
        web_vital_inp_histogram.record(float(value), attributes=attributes)
    else:
        return jsonify({'status': 'ignored'}), 400

    return Response(status=204)
