"""Real User Monitoring (Core Web Vitals) collection for Microblog.

The browser half (``VITALS_JS``) contains **no** OpenTelemetry code: it uses the
``web-vitals`` library to measure LCP and INP and POSTs the measurements to the
server, which records them with the server-side meter defined in
``app/telemetry.py``.

``register_vitals_routes(bp)`` is called from ``app/auth/routes.py`` so the
endpoints and the snippet injection are actually installed on the running app.
"""
import logging
from urllib.parse import urlsplit

from flask import Response, current_app, request, url_for

from app.telemetry import WEB_VITAL_HISTOGRAMS

logger = logging.getLogger(__name__)

VITALS_JS = """
import {onLCP, onINP} from 'https://unpkg.com/web-vitals@4?module';

const ENDPOINT = '__VITALS_ENDPOINT__';
const queue = [];

function flush(isFinal) {
  if (!queue.length) {
    return;
  }
  const body = JSON.stringify({
    url: location.pathname,
    metrics: queue.splice(0, queue.length)
  });
  if (isFinal && navigator.sendBeacon) {
    navigator.sendBeacon(ENDPOINT, new Blob([body],
                         {type: 'application/json'}));
  } else {
    fetch(ENDPOINT, {
      method: 'POST',
      body: body,
      headers: {'Content-Type': 'application/json'},
      keepalive: true
    }).catch(function () {});
  }
}

function report(metric) {
  queue.push({name: metric.name, value: metric.value, rating: metric.rating});
  flush(false);
}

onLCP(report);
onINP(report);

addEventListener('visibilitychange', function () {
  if (document.visibilityState === 'hidden') {
    flush(true);
  }
});
"""


def _route_template(url):
    """Resolve a page URL/path to its low-cardinality Flask route template."""
    if not url:
        return 'unknown'
    path = urlsplit(url).path or '/'
    try:
        adapter = current_app.url_map.bind('localhost')
        rule, _args = adapter.match(path, method='GET', return_rule=True)
        return rule.rule
    except Exception:
        return 'unknown'


def _device_class(user_agent):
    """Coarse, low-cardinality device segment for the RUM measurements."""
    ua = (user_agent or '').lower()
    if 'ipad' in ua or 'tablet' in ua:
        return 'tablet'
    if 'mobi' in ua or 'android' in ua or 'iphone' in ua:
        return 'mobile'
    return 'desktop'


def vitals_js():
    """Serve the browser Web Vitals reporter."""
    js = VITALS_JS.replace('__VITALS_ENDPOINT__', url_for('auth.web_vitals'))
    return Response(js, mimetype='application/javascript')


def web_vitals():
    """Record LCP / INP measurements reported by the browser."""
    payload = request.get_json(silent=True) or {}
    entries = payload.get('metrics')
    if not isinstance(entries, list):
        entries = [payload]
    attributes = {
        'http.route': _route_template(payload.get('url') or request.referrer),
        'device.class': _device_class(request.headers.get('User-Agent')),
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        histogram = WEB_VITAL_HISTOGRAMS.get(
            str(entry.get('name', '')).upper())
        value = entry.get('value')
        if histogram is None or not isinstance(value, (int, float)):
            continue
        rating = entry.get('rating')
        histogram.record(float(value), dict(
            attributes,
            **{'web.vital.rating': str(rating) if rating else 'unknown'}))
    return '', 204


def inject_vitals_snippet(response):
    """Add the reporter <script> to HTML pages so the RUM half actually runs."""
    try:
        if response.direct_passthrough or response.status_code != 200:
            return response
        if 'text/html' not in (response.content_type or ''):
            return response
        body = response.get_data(as_text=True)
        if '</body>' not in body or 'auth/vitals.js' in body:
            return response
        snippet = '<script type="module" src="%s"></script>' % url_for(
            'auth.vitals_js')
        response.set_data(body.replace('</body>', snippet + '</body>', 1))
    except Exception:  # pragma: no cover - never break a real response
        logger.exception('Web Vitals snippet injection skipped')
    return response


def register_vitals_routes(bp):
    """Install the RUM endpoints and snippet injection on ``bp``."""
    bp.add_url_rule('/vitals.js', 'vitals_js', vitals_js, methods=['GET'])
    bp.add_url_rule('/vitals', 'web_vitals', web_vitals, methods=['POST'])
    bp.after_app_request(inject_vitals_snippet)
