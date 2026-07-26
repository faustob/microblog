// Reports Core Web Vitals (LCP, INP) from the browser to the server's
// /api/vitals endpoint for OTel-backed RUM SLIs. Holds zero OTel imports —
// all OTel recording happens server-side in app/vitals_routes.py.
import {onLCP, onINP} from 'https://unpkg.com/web-vitals@4?module';

function sendToServer(metric) {
  const body = JSON.stringify({
    name: metric.name,
    value: metric.value,
    route: (document.body && document.body.dataset && document.body.dataset.routeTemplate) || window.location.pathname,
  });
  const url = '/api/vitals';
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([body], {type: 'application/json'}));
  } else {
    fetch(url, {
      body,
      method: 'POST',
      keepalive: true,
      headers: {'Content-Type': 'application/json'},
    });
  }
}

onLCP(sendToServer);
onINP(sendToServer);
