"""Browser Core Web Vitals (RUM) collection for the Microblog frontend.

The client half (a tiny module script using the ``web-vitals`` library) holds no
OpenTelemetry code at all: it beacons LCP/INP/CLS to ``POST /api/vitals``, and
this server module records them with the server-side meter defined in
``app/telemetry.py``.

``register_web_vitals(bp)`` is called from ``app/auth/routes.py`` and uses the
blueprint's deferred-registration hook to install the endpoint and the snippet
injection on the real Flask application built by ``create_app()``.
"""

import re

from flask import current_app, request

from app.telemetry import record_web_vital

_MOBILE_RE = re.compile(
    r'(android|iphone|ipad|ipod|mobile|windows phone)', re.IGNORECASE)

_SNIPPET = """<script type="module">
(function () {
  if (window.__microblogWebVitals) { return; }
  window.__microblogWebVitals = true;
  var path = window.location.pathname;
  function send(metric) {
    var body = JSON.stringify({
      path: path,
      metrics: [{ name: metric.name, value: metric.value }]
    });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/vitals',
          new Blob([body], { type: 'application/json' }));
      } else {
        fetch('/api/vitals', {
          method: 'POST',
          body: body,
          headers: { 'Content-Type': 'application/json' },
          keepalive: true
        });
      }
    } catch (e) { /* never break the page for telemetry */ }
  }
  import('https://unpkg.com/web-vitals@4?module').then(function (wv) {
    wv.onLCP(send);
    wv.onINP(send);
    wv.onCLS(send);
  }).catch(function () { /* ignore */ });
})();
</script>
"""


def _device_type(user_agent):
    if not user_agent:
        return 'unknown'
    return 'mobile' if _MOBILE_RE.search(user_agent) else 'desktop'


def _route_template(path):
    """Map a raw browser path to its matched Werkzeug route template."""
    if not path:
        return 'unmatched'
    try:
        adapter = current_app.url_map.bind('localhost')
        rule, _args = adapter.match(path, method='GET', return_rule=True)
        return rule.rule
    except Exception:
        return 'unmatched'


def web_vitals_endpoint():
    """Receive browser Core Web Vitals and record them as OTel histograms."""
    payload = request.get_json(silent=True) or {}
    measurements = payload.get('metrics')
    if not isinstance(measurements, list):
        measurements = [payload]
    route = _route_template(payload.get('path'))
    device = _device_type(request.headers.get('User-Agent', ''))
    for measurement in measurements:
        if isinstance(measurement, dict):
            record_web_vital(measurement.get('name'),
                             measurement.get('value'), route, device)
    return '', 204


def _inject_snippet(response):
    """Append the reporter snippet to HTML pages so the client half runs."""
    try:
        content_type = response.content_type or ''
        if (not response.direct_passthrough
                and content_type.startswith('text/html')):
            body = response.get_data(as_text=True)
            if '</body>' in body and 'web-vitals' not in body:
                response.set_data(
                    body.replace('</body>', _SNIPPET + '</body>', 1))
    except Exception:  # pragma: no cover - telemetry must never break a page
        current_app.logger.debug('web vitals snippet injection skipped',
                                 exc_info=True)
    return response


def _install(app):
    if 'web_vitals' in app.view_functions:
        return
    app.add_url_rule('/api/vitals', 'web_vitals', web_vitals_endpoint,
                     methods=['POST'])
    app.after_request(_inject_snippet)


def register_web_vitals(bp):
    """Install the RUM endpoint + reporter when ``bp`` is registered on an app."""
    bp.record_once(lambda state: _install(state.app))
