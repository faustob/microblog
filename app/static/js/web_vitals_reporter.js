/*
 * Core Web Vitals reporter for Microblog.
 *
 * Injected into every HTML page (see inject_web_vitals_reporter in
 * app/auth/routes.py). It collects LCP and INP with the web-vitals library and
 * POSTs them to the server endpoint, which records them on the server-side
 * OpenTelemetry meter. This file intentionally contains no OTel imports.
 */
(function () {
  'use strict';

  var el = document.currentScript ||
    document.querySelector('script[data-endpoint][data-route]');
  if (!el) {
    return;
  }

  var endpoint = el.getAttribute('data-endpoint');
  var route = el.getAttribute('data-route') || 'unknown';
  if (!endpoint) {
    return;
  }

  var mobile = !!(navigator.userAgentData && navigator.userAgentData.mobile);

  function send(metric) {
    var payload = JSON.stringify({
      route: route,
      mobile: mobile,
      metrics: [{ name: metric.name, value: metric.value }]
    });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(
          endpoint, new Blob([payload], { type: 'application/json' }));
        return;
      }
    } catch (e) {
      /* fall through to fetch */
    }
    try {
      fetch(endpoint, {
        method: 'POST',
        body: payload,
        headers: { 'Content-Type': 'application/json' },
        keepalive: true
      }).catch(function () {});
    } catch (e) {
      /* reporting is best effort */
    }
  }

  import('https://unpkg.com/web-vitals@4?module').then(function (webVitals) {
    if (webVitals.onLCP) {
      webVitals.onLCP(send);
    }
    if (webVitals.onINP) {
      webVitals.onINP(send);
    }
  }).catch(function () {});
})();
