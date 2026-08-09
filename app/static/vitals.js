// Core Web Vitals (LCP, INP) reporter.  Collects measurements in the browser
// with the web-vitals library and POSTs them to the server, which records them
// with the server-side OpenTelemetry meter.  No OTel APIs run in the browser.
import {onLCP, onINP} from 'https://cdn.jsdelivr.net/npm/web-vitals@4/dist/web-vitals.attribution.js';

const script = document.currentScript ||
    document.querySelector('script[data-endpoint]');
const endpoint = script ? script.dataset.endpoint : '/vitals';
// Matched Flask route TEMPLATE (e.g. /user/<username>), never the raw path.
const route = script ? (script.dataset.route || 'unknown') : 'unknown';
const mobile = window.matchMedia('(max-width: 767px)').matches;

function report(metric) {
  const body = JSON.stringify({
    name: metric.name,
    value: metric.value,
    route: route,
    mobile: mobile
  });
  if (navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, new Blob([body],
        {type: 'application/json'}));
  } else {
    fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: body,
      keepalive: true
    });
  }
}

onLCP(report);
onINP(report);
